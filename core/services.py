"""
Ride business logic shared by REST views and the WebSocket consumer.

Ride status flow:
    PENDING -> ACCEPTED -> ARRIVED -> IN_PROGRESS -> COMPLETED
    PENDING / ACCEPTED / ARRIVED -> CANCELLED (by customer)
    ACCEPTED / ARRIVED -> PENDING (driver cancels; ride is offered to other drivers again)

Realtime events sent (see core/realtime.py):
    ride.requested   -> nearby online drivers, a new ride they can accept
    ride.unavailable -> drivers, a ride was taken or cancelled (drop it from the list)
    ride.updated     -> customer + driver, ride changed (status, driver assigned, ...)
    driver.location  -> customer, the assigned driver moved
"""
import math

from django.conf import settings
from django.db import transaction
from django.db.models import Avg
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import DriverProfile, Ride
from .pricing import PRICING, estimate_fare
from .realtime import notify_ride_parties, notify_user
from .routing import get_route, haversine_m

# Driver-driven transitions and the timestamp each one sets.
DRIVER_TRANSITIONS = {
    'ACCEPTED': ('ARRIVED', 'arrived_at'),
    'ARRIVED': ('IN_PROGRESS', 'started_at'),
    'IN_PROGRESS': ('COMPLETED', 'completed_at'),
}
DRIVER_ACTIVE_STATUSES = ('ACCEPTED', 'ARRIVED', 'IN_PROGRESS')


def get_driver(user) -> DriverProfile | None:
    return getattr(user, 'driver_profile', None) if user.is_authenticated else None


def is_customer(user) -> bool:
    return user.is_authenticated and hasattr(user, 'customer')


def ride_payload(ride):
    from .serializers import RideSerializer  # local import: serializers -> services would be circular
    return RideSerializer(ride).data


# --- Estimates & creation ---------------------------------------------------

def estimate(pickup, dropoff):
    """Route + fare for every vehicle type. pickup/dropoff: {'lat', 'lng'}."""
    options, routes = [], {}
    for vehicle_type, pricing in PRICING.items():
        mode = pricing.routing_mode
        if mode not in routes:
            routes[mode] = get_route(pickup['lat'], pickup['lng'], dropoff['lat'], dropoff['lng'], mode)
        route = routes[mode]
        options.append({
            'vehicle_type': vehicle_type.value,
            'name': pricing.name,
            'seats': pricing.seats,
            'fare': estimate_fare(vehicle_type, route.distance_m),
            'route': route,
        })
    return options


def create_ride(user, vehicle_type, pickup, dropoff) -> Ride:
    if Ride.objects.filter(customer=user, status__in=Ride.ACTIVE_STATUSES).exists():
        raise ValidationError('Bạn đang có một chuyến đi chưa hoàn thành.')
    route = get_route(pickup['lat'], pickup['lng'], dropoff['lat'], dropoff['lng'],
                      PRICING[vehicle_type].routing_mode)
    with transaction.atomic():
        ride = Ride.objects.create(
            customer=user,
            vehicle_type=vehicle_type,
            pickup_address=pickup.get('address') or 'Điểm đón',
            pickup_lat=pickup['lat'],
            pickup_lng=pickup['lng'],
            dropoff_address=dropoff.get('address') or 'Điểm đến',
            dropoff_lat=dropoff['lat'],
            dropoff_lng=dropoff['lng'],
            route=route,
            distance_m=route.distance_m,
            duration_s=route.duration_s,
            fare=estimate_fare(vehicle_type, route.distance_m),
        )
        dispatch(ride)
    return ride


# --- Matching -----------------------------------------------------------------

def nearby_drivers(lat, lng, vehicle_type, radius_km=None, limit=10):
    """Online, approved, idle drivers of this vehicle type, closest first."""
    radius_km = radius_km or settings.DRIVER_SEARCH_RADIUS_KM
    dlat = radius_km / 111
    dlng = radius_km / (111 * max(math.cos(math.radians(lat)), 0.01))
    candidates = DriverProfile.objects.filter(
        status='ONLINE', is_approved=True, vehicle_type=vehicle_type,
        current_latitude__range=(lat - dlat, lat + dlat),
        current_longitude__range=(lng - dlng, lng + dlng),
    )
    scored = []
    for d in candidates:
        dist = haversine_m(lat, lng, d.current_latitude, d.current_longitude)
        if dist <= radius_km * 1000:
            scored.append((dist, d))
    scored.sort(key=lambda x: x[0])
    return scored[:limit]


def dispatch(ride):
    """Offer a PENDING ride to nearby drivers."""
    data = ride_payload(ride)
    for dist, driver in nearby_drivers(ride.pickup_lat, ride.pickup_lng, ride.vehicle_type):
        notify_user(driver.user_id, 'ride.requested', {**data, 'distance_to_pickup_m': int(dist)})


def withdraw(ride, exclude_driver_id=None):
    """Tell drivers who may have seen this ride that it is gone."""
    for _, driver in nearby_drivers(ride.pickup_lat, ride.pickup_lng, ride.vehicle_type, limit=50):
        if driver.id != exclude_driver_id:
            notify_user(driver.user_id, 'ride.unavailable', {'id': str(ride.id)})


def available_rides_for(driver):
    if driver.current_latitude is None:
        return []
    radius_m = settings.DRIVER_SEARCH_RADIUS_KM * 1000
    rides = Ride.objects.filter(status='PENDING', vehicle_type=driver.vehicle_type).select_related('route')
    result = []
    for ride in rides:
        dist = haversine_m(driver.current_latitude, driver.current_longitude, ride.pickup_lat, ride.pickup_lng)
        if dist <= radius_m:
            result.append((dist, ride))
    result.sort(key=lambda x: x[0])
    return result


# --- Driver actions -------------------------------------------------------------

def set_driver_status(driver, online: bool, lat=None, lng=None):
    if online and not driver.is_approved:
        raise PermissionDenied('Tài khoản tài xế chưa được duyệt.')
    if driver.status == 'BUSY':
        raise ValidationError('Bạn đang có chuyến, không thể đổi trạng thái.')
    driver.status = 'ONLINE' if online else 'OFFLINE'
    fields = ['status', 'updated_at']
    if lat is not None and lng is not None:
        driver.current_latitude, driver.current_longitude = lat, lng
        driver.location_updated_at = timezone.now()
        fields += ['current_latitude', 'current_longitude', 'location_updated_at']
    driver.save(update_fields=fields)
    return driver


def update_driver_location(driver, lat, lng):
    driver.current_latitude, driver.current_longitude = lat, lng
    driver.location_updated_at = timezone.now()
    driver.save(update_fields=['current_latitude', 'current_longitude', 'location_updated_at', 'updated_at'])
    ride = Ride.objects.filter(driver=driver, status__in=DRIVER_ACTIVE_STATUSES).first()
    if ride:
        notify_user(ride.customer_id, 'driver.location', {'ride_id': str(ride.id), 'lat': lat, 'lng': lng})
    return ride


def accept_ride(driver, ride_id) -> Ride:
    if not driver.is_approved:
        raise PermissionDenied('Tài khoản tài xế chưa được duyệt.')
    with transaction.atomic():
        # Lock both rows so two drivers can't take the same ride.
        driver = DriverProfile.objects.select_for_update().get(pk=driver.pk)
        if driver.status != 'ONLINE':
            raise ValidationError('Bạn cần trực tuyến và không có chuyến khác để nhận cuốc.')
        ride = Ride.objects.select_for_update().filter(pk=ride_id).first()
        if ride is None or ride.status != 'PENDING':
            raise ValidationError('Cuốc xe không hợp lệ hoặc đã có người nhận.')
        if ride.vehicle_type != driver.vehicle_type:
            raise ValidationError('Loại xe không phù hợp với cuốc này.')

        if driver.current_latitude is not None:
            ride.approach_route = get_route(
                driver.current_latitude, driver.current_longitude,
                ride.pickup_lat, ride.pickup_lng, PRICING[ride.vehicle_type].routing_mode,
            )
        ride.driver = driver
        ride.status = 'ACCEPTED'
        ride.accepted_at = timezone.now()
        ride.save()
        driver.status = 'BUSY'
        driver.save(update_fields=['status', 'updated_at'])

        notify_ride_parties(ride, 'ride.updated', ride_payload(ride))
        withdraw(ride, exclude_driver_id=driver.id)
    return ride


def advance_ride(driver, ride_id, new_status) -> Ride:
    with transaction.atomic():
        ride = Ride.objects.select_for_update().filter(pk=ride_id, driver=driver).first()
        if ride is None:
            raise ValidationError('Không tìm thấy chuyến đi của bạn.')
        expected = DRIVER_TRANSITIONS.get(ride.status)
        if expected is None or expected[0] != new_status:
            raise ValidationError(f'Không thể chuyển từ {ride.status} sang {new_status}.')
        ride.status = new_status
        setattr(ride, expected[1], timezone.now())
        ride.save()
        if new_status == 'COMPLETED':
            DriverProfile.objects.filter(pk=driver.pk).update(status='ONLINE')
        notify_ride_parties(ride, 'ride.updated', ride_payload(ride))
    return ride


# --- Cancel & rate ----------------------------------------------------------

def cancel_ride(user, ride_id, reason='') -> Ride:
    driver = get_driver(user)
    with transaction.atomic():
        # Postgres can't FOR UPDATE through the nullable driver join, so lock only the ride row.
        ride = Ride.objects.select_for_update(of=('self',)).select_related('driver').filter(pk=ride_id).first()
        if ride is None:
            raise ValidationError('Không tìm thấy chuyến đi.')

        if ride.customer_id == user.id:
            if ride.status not in ('PENDING', 'ACCEPTED', 'ARRIVED'):
                raise ValidationError('Không thể hủy chuyến ở trạng thái này.')
            was_pending = ride.status == 'PENDING'
            ride.status = 'CANCELLED'
            ride.cancelled_by = 'customer'
            ride.cancel_reason = reason
            ride.cancelled_at = timezone.now()
            ride.save()
            if ride.driver_id:
                DriverProfile.objects.filter(pk=ride.driver_id).update(status='ONLINE')
            notify_ride_parties(ride, 'ride.updated', ride_payload(ride))
            if was_pending:
                withdraw(ride)
            return ride

        if driver and ride.driver_id == driver.id:
            if ride.status not in ('ACCEPTED', 'ARRIVED'):
                raise ValidationError('Không thể hủy chuyến ở trạng thái này.')
            # Driver gives up: ride goes back to searching.
            DriverProfile.objects.filter(pk=driver.pk).update(status='ONLINE')
            ride.driver = None
            ride.approach_route = None
            ride.status = 'PENDING'
            ride.accepted_at = ride.arrived_at = None
            ride.save()
            notify_user(ride.customer_id, 'ride.updated', ride_payload(ride))
            notify_user(driver.user_id, 'ride.unavailable', {'id': str(ride.id)})
            dispatch(ride)
            return ride

    raise PermissionDenied('Bạn không có quyền với chuyến đi này.')


def rate_ride(user, ride_id, rating, comment='') -> Ride:
    ride = Ride.objects.filter(pk=ride_id, customer=user).select_related('driver').first()
    if ride is None:
        raise ValidationError('Không tìm thấy chuyến đi.')
    if ride.status != 'COMPLETED':
        raise ValidationError('Chỉ đánh giá được chuyến đã hoàn thành.')
    if ride.rating is not None:
        raise ValidationError('Bạn đã đánh giá chuyến này.')
    ride.rating, ride.rating_comment = rating, comment
    ride.save(update_fields=['rating', 'rating_comment', 'updated_at'])
    if ride.driver_id:
        avg = Ride.objects.filter(driver_id=ride.driver_id, rating__isnull=False).aggregate(a=Avg('rating'))['a']
        DriverProfile.objects.filter(pk=ride.driver_id).update(rating=round(avg, 2))
    return ride
