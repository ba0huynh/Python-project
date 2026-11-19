"""
Ride business logic shared by REST views, the WebSocket consumer and the
dispatcher worker (`manage.py ride_worker`). Put new rules here, not in views.

Ride status flow:
    PENDING -> ACCEPTED -> ARRIVED -> IN_PROGRESS -> COMPLETED
    PENDING / ACCEPTED / ARRIVED -> CANCELLED (by customer)
    PENDING -> CANCELLED (by system, no driver found in RIDE_SEARCH_SECONDS)
    ACCEPTED / ARRIVED -> PENDING (driver cancels; the ride is offered to other drivers)

Matching: a PENDING ride is offered (RideOffer) to the DISPATCH_BATCH_SIZE nearest
free drivers. Each offer lasts DRIVER_OFFER_SECONDS. When every open offer was
declined or timed out, the next batch is offered. A driver holds at most one
open offer and is never re-offered a ride they declined, let expire or cancelled.
The first driver to accept wins.

Realtime events (core/realtime.py):
    ride.offer           -> driver, a ride they can accept (Offer payload)
    ride.offer_cancelled -> driver, {ride_id, offer_id, reason: taken|cancelled|expired}
    ride.updated         -> customer + driver, the ride changed
    driver.location      -> customer, the assigned driver moved
"""
import logging
import math
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from . import pricing
from .models import DriverProfile, Ride, RideOffer
from .realtime import notify_user
from .routing import get_route, haversine_m

logger = logging.getLogger(__name__)

# Driver-driven transitions and the timestamp each one sets.
DRIVER_TRANSITIONS = {
    'ACCEPTED': ('ARRIVED', 'arrived_at'),
    'ARRIVED': ('IN_PROGRESS', 'started_at'),
    'IN_PROGRESS': ('COMPLETED', 'completed_at'),
}
DRIVER_ACTIVE_STATUSES = ('ACCEPTED', 'ARRIVED', 'IN_PROGRESS')
CUSTOMER_CANCELLABLE = ('PENDING', 'ACCEPTED', 'ARRIVED')
NO_DRIVER_REASON = 'Không tìm thấy tài xế phù hợp.'
# Accept requests that arrive a moment after the offer expired (network latency).
ACCEPT_GRACE = timedelta(seconds=2)


def get_driver(user) -> DriverProfile | None:
    return getattr(user, 'driver_profile', None) if user.is_authenticated else None


def is_customer(user) -> bool:
    return user.is_authenticated and hasattr(user, 'customer')


# --- Payloads ---------------------------------------------------------------------

def ride_payload(ride, viewer='customer'):
    """viewer: 'customer', 'driver' (the assigned driver) or 'offer' (a driver being offered it)."""
    from .serializers import RideSerializer  # local import: serializers -> services would be circular
    return RideSerializer(ride, context={'viewer': viewer}).data


def offer_payload(offer):
    from .serializers import OfferSerializer
    return OfferSerializer(offer).data


def viewer_for(user, ride) -> str:
    driver = get_driver(user)
    return 'driver' if driver and ride.driver_id == driver.id else 'customer'


def notify_ride(ride):
    """Send ride.updated to the customer and the assigned driver (each gets their own view)."""
    notify_user(ride.customer_id, 'ride.updated', ride_payload(ride, 'customer'))
    if ride.driver_id:
        notify_user(ride.driver.user_id, 'ride.updated', ride_payload(ride, 'driver'))


def withdraw_offers(ride, reason, exclude_offer_id=None):
    """Close the ride's open offers and tell those drivers to drop it."""
    open_offers = ride.offers.filter(status='PENDING').select_related('driver')
    if exclude_offer_id:
        open_offers = open_offers.exclude(pk=exclude_offer_id)
    for offer in open_offers:
        notify_user(offer.driver.user_id, 'ride.offer_cancelled',
                    {'ride_id': str(ride.id), 'offer_id': str(offer.id), 'reason': reason})
    open_offers.update(status='WITHDRAWN', responded_at=timezone.now())


# --- Estimates & booking ------------------------------------------------------------

def validate_trip(pickup, dropoff):
    straight = haversine_m(pickup['lat'], pickup['lng'], dropoff['lat'], dropoff['lng'])
    if straight < settings.MIN_TRIP_METERS:
        raise ValidationError('Điểm đến quá gần điểm đón.')
    if straight > settings.MAX_TRIP_KM * 1000:
        raise ValidationError(f'Chuyến đi tối đa {settings.MAX_TRIP_KM:g} km.')


def estimate(pickup, dropoff):
    """Route + fare for every bookable vehicle type. pickup/dropoff: {'lat', 'lng'}."""
    validate_trip(pickup, dropoff)
    options, routes = [], {}
    for rule in pricing.active_rules():
        mode = pricing.routing_mode(rule.vehicle_type)
        if mode not in routes:
            routes[mode] = get_route(pickup['lat'], pickup['lng'], dropoff['lat'], dropoff['lng'], mode)
        route = routes[mode]
        options.append({
            'vehicle_type': rule.vehicle_type,
            'name': rule.display_name,
            'seats': rule.seats,
            'fare': pricing.quote(rule, route.distance_m).fare,
            'distance_m': route.distance_m,
            'duration_s': route.duration_s,
            'route': route,
            'drivers_nearby': len(available_drivers(pickup['lat'], pickup['lng'], rule.vehicle_type,
                                                    include_offered=True)),
        })
    return options


def create_ride(user, vehicle_type, pickup, dropoff) -> Ride:
    validate_trip(pickup, dropoff)
    rule = pricing.get_rule(vehicle_type)
    if rule is None:
        raise ValidationError('Loại xe này hiện chưa phục vụ.')
    if Ride.objects.filter(customer=user, status__in=Ride.ACTIVE_STATUSES).exists():
        raise ValidationError('Bạn đang có một chuyến đi chưa hoàn thành.')
    # External HTTP call: keep it outside the transaction.
    route = get_route(pickup['lat'], pickup['lng'], dropoff['lat'], dropoff['lng'],
                      pricing.routing_mode(vehicle_type))
    quote = pricing.quote(rule, route.distance_m)
    try:
        with transaction.atomic():
            ride = Ride.objects.create(
                customer=user,
                vehicle_type=vehicle_type,
                pickup_address=(pickup.get('address') or 'Điểm đón')[:255],
                pickup_lat=pickup['lat'],
                pickup_lng=pickup['lng'],
                dropoff_address=(dropoff.get('address') or 'Điểm đến')[:255],
                dropoff_lat=dropoff['lat'],
                dropoff_lng=dropoff['lng'],
                route=route,
                distance_m=route.distance_m,
                duration_s=route.duration_s,
                fare=quote.fare,
                commission_percent=quote.commission_percent,
                commission=quote.commission,
                driver_earning=quote.driver_earning,
                dispatched_at=timezone.now(),
            )
    except IntegrityError:  # one_active_ride_per_customer: a parallel request won
        raise ValidationError('Bạn đang có một chuyến đi chưa hoàn thành.')
    dispatch_ride(ride.id)
    return ride


# --- Matching -------------------------------------------------------------------------

def available_drivers(lat, lng, vehicle_type, exclude_ids=(), include_offered=False, limit=50):
    """
    Online, approved drivers of this vehicle type with a fresh GPS position inside
    the search radius, closest first. Drivers holding an open offer are skipped
    unless include_offered (used to count supply for estimates).
    """
    now = timezone.now()
    radius_km = settings.DRIVER_SEARCH_RADIUS_KM
    dlat = radius_km / 111
    dlng = radius_km / (111 * max(math.cos(math.radians(lat)), 0.01))
    qs = DriverProfile.objects.filter(
        status='ONLINE', is_approved=True, vehicle_type=vehicle_type,
        location_updated_at__gte=now - timedelta(seconds=settings.DRIVER_LOCATION_MAX_AGE_SECONDS),
        current_latitude__range=(lat - dlat, lat + dlat),
        current_longitude__range=(lng - dlng, lng + dlng),
    ).exclude(id__in=list(exclude_ids))
    if not include_offered:
        busy = RideOffer.objects.filter(status='PENDING', expires_at__gt=now).values('driver_id')
        qs = qs.exclude(id__in=busy)
    scored = []
    for d in qs.select_related('user'):
        dist = haversine_m(lat, lng, d.current_latitude, d.current_longitude)
        if dist <= radius_km * 1000:
            scored.append((dist, d))
    scored.sort(key=lambda x: x[0])
    return scored[:limit]


def dispatch_ride(ride_id) -> int:
    """
    Offer a PENDING ride to the next batch of drivers, unless someone still holds
    an open offer for it. Returns how many offers were sent.
    """
    now = timezone.now()
    with transaction.atomic():
        ride = Ride.objects.select_for_update(of=('self',)).filter(pk=ride_id).first()
        if ride is None or ride.status != 'PENDING':
            return 0
        if ride.offers.filter(status='PENDING', expires_at__gt=now).exists():
            return 0
        expired = ride.offers.filter(status='PENDING', expires_at__lte=now).select_related('driver')
        for offer in expired:
            notify_user(offer.driver.user_id, 'ride.offer_cancelled',
                        {'ride_id': str(ride.id), 'offer_id': str(offer.id), 'reason': 'expired'})
        expired.update(status='EXPIRED')

        # Skip drivers who declined, let it expire or gave it up. Drivers who only lost
        # the race to someone else (WITHDRAWN) may get it again if it comes back.
        excluded = list(ride.offers.exclude(status='WITHDRAWN').values_list('driver_id', flat=True))
        candidates = available_drivers(ride.pickup_lat, ride.pickup_lng, ride.vehicle_type,
                                       exclude_ids=excluded)
        sent = 0
        for dist, driver in candidates:
            if sent >= settings.DISPATCH_BATCH_SIZE:
                break
            # Lock the driver and re-check, so a parallel dispatch can't give them two offers.
            locked = DriverProfile.objects.select_for_update().filter(pk=driver.pk, status='ONLINE').first()
            if locked is None or RideOffer.objects.filter(
                driver=locked, status='PENDING', expires_at__gt=now
            ).exists():
                continue
            offer, _ = RideOffer.objects.update_or_create(ride=ride, driver=locked, defaults={
                'status': 'PENDING', 'distance_m': int(dist), 'responded_at': None,
                'expires_at': now + timedelta(seconds=settings.DRIVER_OFFER_SECONDS),
            })
            notify_user(driver.user_id, 'ride.offer', offer_payload(offer))
            sent += 1
        return sent


def open_offers_for(driver):
    return (
        RideOffer.objects.filter(driver=driver, status='PENDING', expires_at__gt=timezone.now(),
                                 ride__status='PENDING')
        .select_related('ride', 'ride__route', 'ride__customer__customer')
        .order_by('-created_at')
    )


def expire_ride_if_stale(ride_id) -> bool:
    """Cancel a PENDING ride nobody accepted within RIDE_SEARCH_SECONDS."""
    deadline = timezone.now() - timedelta(seconds=settings.RIDE_SEARCH_SECONDS)
    with transaction.atomic():
        ride = Ride.objects.select_for_update(of=('self',)).filter(pk=ride_id).first()
        if ride is None or ride.status != 'PENDING' or not ride.dispatched_at or ride.dispatched_at > deadline:
            return False
        ride.status = 'CANCELLED'
        ride.cancelled_by = 'system'
        ride.cancel_reason = NO_DRIVER_REASON
        ride.cancelled_at = timezone.now()
        ride.save()
        withdraw_offers(ride, 'cancelled')
        notify_ride(ride)
    return True


def run_dispatch_cycle():
    """One pass of the dispatcher worker: time out searches and offers, send next batches."""
    deadline = timezone.now() - timedelta(seconds=settings.RIDE_SEARCH_SECONDS)
    for ride_id in Ride.objects.filter(status='PENDING', dispatched_at__lte=deadline).values_list('id', flat=True):
        expire_ride_if_stale(ride_id)
    for ride_id in Ride.objects.filter(status='PENDING').values_list('id', flat=True):
        dispatch_ride(ride_id)
    # Offers left open on rides that are no longer pending.
    RideOffer.objects.filter(status='PENDING', expires_at__lte=timezone.now()).update(status='EXPIRED')


# --- Driver actions -------------------------------------------------------------------

def set_driver_status(driver, online: bool, lat=None, lng=None):
    if online and not driver.is_approved:
        raise PermissionDenied('Tài khoản tài xế đang chờ duyệt.')
    if online and (lat is None or lng is None):
        raise ValidationError('Cần vị trí GPS để bật nhận chuyến.')
    with transaction.atomic():
        driver = DriverProfile.objects.select_for_update().get(pk=driver.pk)
        if driver.status == 'BUSY':
            raise ValidationError('Bạn đang có chuyến, không thể đổi trạng thái.')
        driver.status = 'ONLINE' if online else 'OFFLINE'
        fields = ['status', 'updated_at']
        if lat is not None and lng is not None:
            driver.current_latitude, driver.current_longitude = lat, lng
            driver.location_updated_at = timezone.now()
            fields += ['current_latitude', 'current_longitude', 'location_updated_at']
        driver.save(update_fields=fields)
        declined = []
        if not online:
            declined = list(RideOffer.objects.filter(driver=driver, status='PENDING').values_list('ride_id', flat=True))
            RideOffer.objects.filter(driver=driver, status='PENDING').update(
                status='DECLINED', responded_at=timezone.now()
            )
    for ride_id in declined:
        dispatch_ride(ride_id)
    return driver


def update_driver_location(driver, lat, lng, heading=None):
    """Save the driver's GPS position and forward it to the customer of their active ride."""
    if heading is not None and not 0 <= heading <= 360:
        heading = None  # unknown (phones send -1)
    DriverProfile.objects.filter(pk=driver.pk).update(
        current_latitude=lat, current_longitude=lng, current_heading=heading,
        location_updated_at=timezone.now(),
    )
    driver.current_latitude, driver.current_longitude, driver.current_heading = lat, lng, heading
    ride = (
        Ride.objects.filter(driver_id=driver.pk, status__in=DRIVER_ACTIVE_STATUSES)
        .only('id', 'customer_id').first()
    )
    if ride:
        notify_user(ride.customer_id, 'driver.location',
                    {'ride_id': str(ride.id), 'lat': lat, 'lng': lng, 'heading': heading})
    return ride


def accept_ride(driver, ride_id) -> Ride:
    if not driver.is_approved:
        raise PermissionDenied('Tài khoản tài xế đang chờ duyệt.')
    ride = Ride.objects.filter(pk=ride_id).first()
    if ride is None:
        raise NotFound('Không tìm thấy cuốc xe.')
    approach = None
    if driver.current_latitude is not None and ride.status == 'PENDING':
        # External HTTP call: fetch before taking row locks.
        approach = get_route(driver.current_latitude, driver.current_longitude,
                             ride.pickup_lat, ride.pickup_lng, pricing.routing_mode(ride.vehicle_type))

    now = timezone.now()
    with transaction.atomic():
        # Lock driver, ride and offer so two drivers can't take the same ride.
        driver = DriverProfile.objects.select_for_update().get(pk=driver.pk)
        if driver.status != 'ONLINE':
            raise ValidationError('Bạn cần bật nhận chuyến và không có chuyến khác.')
        ride = Ride.objects.select_for_update(of=('self',)).get(pk=ride_id)
        if ride.status != 'PENDING':
            raise ValidationError('Cuốc xe đã có tài xế khác nhận hoặc đã bị hủy.')
        offer = RideOffer.objects.select_for_update().filter(ride=ride, driver=driver).first()
        if offer is None or offer.status != 'PENDING' or offer.expires_at + ACCEPT_GRACE < now:
            raise ValidationError('Lời mời nhận cuốc đã hết hạn.')

        offer.status, offer.responded_at = 'ACCEPTED', now
        offer.save(update_fields=['status', 'responded_at', 'updated_at'])
        ride.approach_route = approach
        ride.driver = driver
        ride.status = 'ACCEPTED'
        ride.accepted_at = now
        ride.save()
        driver.status = 'BUSY'
        driver.save(update_fields=['status', 'updated_at'])
        withdraw_offers(ride, 'taken', exclude_offer_id=offer.pk)
        notify_ride(ride)
    return ride


def decline_ride(driver, ride_id):
    with transaction.atomic():
        updated = RideOffer.objects.filter(ride_id=ride_id, driver=driver, status='PENDING').update(
            status='DECLINED', responded_at=timezone.now()
        )
    if not updated:
        raise ValidationError('Không có lời mời nào để từ chối.')
    dispatch_ride(ride_id)


def advance_ride(driver, ride_id, new_status) -> Ride:
    with transaction.atomic():
        ride = Ride.objects.select_for_update(of=('self',)).select_related('driver').filter(
            pk=ride_id, driver=driver
        ).first()
        if ride is None:
            raise NotFound('Không tìm thấy chuyến đi của bạn.')
        expected = DRIVER_TRANSITIONS.get(ride.status)
        if expected is None or expected[0] != new_status:
            raise ValidationError(f'Không thể chuyển từ {ride.status} sang {new_status}.')
        if new_status == 'ARRIVED':
            check_near_pickup(ride.driver, ride)
        ride.status = new_status
        setattr(ride, expected[1], timezone.now())
        ride.save()
        if new_status == 'COMPLETED':
            DriverProfile.objects.filter(pk=ride.driver_id).update(status='ONLINE')
        notify_ride(ride)
    return ride


def check_near_pickup(driver, ride):
    limit = settings.DRIVER_ARRIVAL_RADIUS_M
    if not limit or driver.current_latitude is None:
        return
    dist = haversine_m(driver.current_latitude, driver.current_longitude, ride.pickup_lat, ride.pickup_lng)
    if dist > limit:
        raise ValidationError(f'Bạn còn cách điểm đón khoảng {int(round(dist, -1))} m. Hãy đến gần hơn.')


# --- Cancel & rate ------------------------------------------------------------------

def cancel_ride(user, ride_id, reason='') -> Ride:
    driver = get_driver(user)
    redispatch = False
    with transaction.atomic():
        # Postgres can't FOR UPDATE through the nullable driver join, so lock only the ride row.
        ride = Ride.objects.select_for_update(of=('self',)).select_related('driver').filter(pk=ride_id).first()
        if ride is None:
            raise NotFound('Không tìm thấy chuyến đi.')

        if ride.customer_id == user.id:
            if ride.status not in CUSTOMER_CANCELLABLE:
                raise ValidationError('Không thể hủy chuyến ở trạng thái này.')
            ride.status = 'CANCELLED'
            ride.cancelled_by = 'customer'
            ride.cancel_reason = reason or 'Khách hàng hủy chuyến'
            ride.cancelled_at = timezone.now()
            ride.save()
            if ride.driver_id:
                DriverProfile.objects.filter(pk=ride.driver_id).update(status='ONLINE')
            withdraw_offers(ride, 'cancelled')
            notify_ride(ride)
        elif driver and ride.driver_id == driver.id:
            if ride.status not in ('ACCEPTED', 'ARRIVED'):
                raise ValidationError('Không thể hủy chuyến ở trạng thái này.')
            # Driver gives up: the ride goes back to searching (this driver won't get it again).
            DriverProfile.objects.filter(pk=driver.pk).update(status='ONLINE')
            ride.driver = None
            ride.approach_route = None
            ride.status = 'PENDING'
            ride.accepted_at = ride.arrived_at = None
            ride.dispatched_at = timezone.now()
            ride.save()
            notify_ride(ride)
            redispatch = True
        else:
            raise PermissionDenied('Bạn không có quyền với chuyến đi này.')
    if redispatch:
        dispatch_ride(ride.id)
    return ride


def rate_ride(user, ride_id, rating, comment='') -> Ride:
    ride = Ride.objects.filter(pk=ride_id, customer=user).first()
    if ride is None:
        raise NotFound('Không tìm thấy chuyến đi.')
    if ride.status != 'COMPLETED':
        raise ValidationError('Chỉ đánh giá được chuyến đã hoàn thành.')
    with transaction.atomic():
        updated = Ride.objects.filter(pk=ride.pk, rating__isnull=True).update(
            rating=rating, rating_comment=comment, updated_at=timezone.now()
        )
        if not updated:
            raise ValidationError('Bạn đã đánh giá chuyến này.')
        if ride.driver_id:
            avg = Ride.objects.filter(driver_id=ride.driver_id, rating__isnull=False).aggregate(a=Avg('rating'))['a']
            DriverProfile.objects.filter(pk=ride.driver_id).update(rating=round(avg, 2))
    ride.refresh_from_db()
    return ride


# --- Earnings ---------------------------------------------------------------------------

def driver_earnings(driver):
    now = timezone.localtime()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    periods = {
        'today': today,
        'week': today - timedelta(days=today.weekday()),
        'month': today.replace(day=1),
    }
    done = Ride.objects.filter(driver=driver, status='COMPLETED')
    result = {}
    for name, since in periods.items():
        agg = done.filter(completed_at__gte=since).aggregate(
            trips=Count('id'), gross=Sum('fare'), commission=Sum('commission'), net=Sum('driver_earning'),
        )
        result[name] = {k: v or 0 for k, v in agg.items()}
    result['recent'] = done.order_by('-completed_at').select_related(
        'customer__customer', 'driver', 'route', 'approach_route'
    )[:20]
    return result
