from django.db.models import Q
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Ride
from .serializers import (
    CancelSerializer, CreateRideSerializer, DriverProfileSerializer, DriverStatusSerializer,
    EstimateOptionSerializer, EstimateRequestSerializer, LocationSerializer, RateSerializer,
    RideSerializer, RideStatusSerializer,
)

RIDE_RELATED = ('customer__customer', 'driver', 'route', 'approach_route')


class IsCustomer(permissions.BasePermission):
    message = 'Chỉ khách hàng mới dùng được chức năng này.'

    def has_permission(self, request, view):
        return services.is_customer(request.user)


class IsDriver(permissions.BasePermission):
    message = 'Chỉ tài xế mới dùng được chức năng này.'

    def has_permission(self, request, view):
        return services.get_driver(request.user) is not None


def validated(serializer_class, request):
    s = serializer_class(data=request.data)
    s.is_valid(raise_exception=True)
    return s.validated_data


# --- Customer -----------------------------------------------------------------

class RideEstimateView(APIView):
    """POST /api/rides/estimate/ -> road route + fare for each vehicle type."""

    def post(self, request):
        data = validated(EstimateRequestSerializer, request)
        options = services.estimate(data['pickup'], data['dropoff'])
        return Response({'options': EstimateOptionSerializer(options, many=True).data})


class RideListCreateView(APIView):
    """GET: my rides (customer or driver). POST (customer): book a ride."""

    def get(self, request):
        driver = services.get_driver(request.user)
        q = Q(customer=request.user)
        if driver:
            q |= Q(driver=driver)
        rides = Ride.objects.filter(q).select_related(*RIDE_RELATED)[:50]
        return Response(RideSerializer(rides, many=True).data)

    def post(self, request):
        if not services.is_customer(request.user):
            return Response({'detail': IsCustomer.message}, status=status.HTTP_403_FORBIDDEN)
        data = validated(CreateRideSerializer, request)
        ride = services.create_ride(request.user, data['vehicle_type'], data['pickup'], data['dropoff'])
        return Response(RideSerializer(ride).data, status=status.HTTP_201_CREATED)


class CurrentRideView(APIView):
    """GET /api/rides/current/ -> the active ride of this user, or null."""

    def get(self, request):
        driver = services.get_driver(request.user)
        q = Q(customer=request.user, status__in=Ride.ACTIVE_STATUSES)
        if driver:
            q |= Q(driver=driver, status__in=services.DRIVER_ACTIVE_STATUSES)
        ride = Ride.objects.filter(q).select_related(*RIDE_RELATED).first()
        return Response({'ride': RideSerializer(ride).data if ride else None})


class RideDetailView(APIView):
    def get(self, request, ride_id):
        driver = services.get_driver(request.user)
        q = Q(customer=request.user)
        if driver:
            # Drivers may also look at pending rides they are being offered.
            q |= Q(driver=driver) | Q(status='PENDING', vehicle_type=driver.vehicle_type)
        ride = Ride.objects.filter(q, pk=ride_id).select_related(*RIDE_RELATED).first()
        if ride is None:
            return Response({'detail': 'Không tìm thấy chuyến đi.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(RideSerializer(ride).data)


class CancelRideView(APIView):
    def post(self, request, ride_id):
        data = validated(CancelSerializer, request)
        ride = services.cancel_ride(request.user, ride_id, data['reason'])
        return Response(RideSerializer(ride).data)


class RateRideView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]

    def post(self, request, ride_id):
        data = validated(RateSerializer, request)
        ride = services.rate_ride(request.user, ride_id, data['rating'], data['comment'])
        return Response(RideSerializer(ride).data)


# --- Driver -------------------------------------------------------------------

class DriverOnlyView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsDriver]

    @property
    def driver(self):
        return services.get_driver(self.request.user)


class UpdateDriverStatusView(DriverOnlyView):
    """PATCH /api/driver/status/ {status: ONLINE|OFFLINE, lat?, lng?}"""

    def patch(self, request):
        data = validated(DriverStatusSerializer, request)
        driver = services.set_driver_status(
            self.driver, data['status'] == 'ONLINE', data.get('lat'), data.get('lng')
        )
        return Response(DriverProfileSerializer(driver).data)


class DriverLocationView(DriverOnlyView):
    """POST /api/driver/location/ {lat, lng}. The WebSocket does the same, prefer it."""

    def post(self, request):
        data = validated(LocationSerializer, request)
        services.update_driver_location(self.driver, data['lat'], data['lng'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class AvailableRidesView(DriverOnlyView):
    """GET /api/driver/rides/available/ -> pending rides near me, closest first."""

    def get(self, request):
        rides = services.available_rides_for(self.driver)
        data = [{**RideSerializer(r).data, 'distance_to_pickup_m': int(d)} for d, r in rides]
        return Response({'total': len(data), 'rides': data})


class AcceptRideView(DriverOnlyView):
    def post(self, request, ride_id):
        ride = services.accept_ride(self.driver, ride_id)
        return Response(RideSerializer(ride).data)


class UpdateRideStatusView(DriverOnlyView):
    """PATCH /api/driver/rides/<id>/update-status/ {status: ARRIVED|IN_PROGRESS|COMPLETED}"""

    def patch(self, request, ride_id):
        data = validated(RideStatusSerializer, request)
        ride = services.advance_ride(self.driver, ride_id, data['status'])
        return Response(RideSerializer(ride).data)
