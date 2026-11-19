from django.db import connection
from django.db.models import Q
from rest_framework import permissions, status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import geocoding, services
from .models import Ride
from .serializers import (
    CancelSerializer, CreateRideSerializer, DriverProfileSerializer, DriverStatusSerializer,
    EstimateOptionSerializer, EstimateRequestSerializer, GeoPointSerializer, GeoSearchSerializer,
    LocationSerializer, OfferSerializer, RateSerializer, RideSerializer, RideStatusSerializer,
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


def validated(serializer_class, data):
    s = serializer_class(data=data)
    s.is_valid(raise_exception=True)
    return s.validated_data


def ride_response(request, ride, code=status.HTTP_200_OK):
    return Response(services.ride_payload(ride, services.viewer_for(request.user, ride)), status=code)


def my_rides(user):
    driver = services.get_driver(user)
    return Ride.objects.filter(Q(driver=driver) if driver else Q(customer=user))


class HealthView(APIView):
    """GET /api/health/ for load balancers / uptime checks."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        connection.ensure_connection()
        return Response({'status': 'ok'})


# --- Customer -----------------------------------------------------------------

class RideEstimateView(APIView):
    """POST /api/rides/estimate/ -> road route + fare for each vehicle type."""
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    throttle_scope = 'estimate'

    def post(self, request):
        data = validated(EstimateRequestSerializer, request.data)
        options = services.estimate(data['pickup'], data['dropoff'])
        return Response({'options': EstimateOptionSerializer(options, many=True).data})


class RidePagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100


class RideListCreateView(APIView):
    """GET: my rides, newest first (customer: booked, driver: driven). POST (customer): book a ride."""

    def get_throttles(self):
        self.throttle_scope = 'booking' if self.request.method == 'POST' else None
        return super().get_throttles()

    def get(self, request):
        paginator = RidePagination()
        rides = my_rides(request.user).select_related(*RIDE_RELATED).order_by('-created_at')
        page = paginator.paginate_queryset(rides, request, view=self)
        viewer = 'driver' if services.get_driver(request.user) else 'customer'
        return paginator.get_paginated_response(
            [services.ride_payload(r, viewer) for r in page]
        )

    def post(self, request):
        if not services.is_customer(request.user):
            return Response({'detail': IsCustomer.message}, status=status.HTTP_403_FORBIDDEN)
        data = validated(CreateRideSerializer, request.data)
        ride = services.create_ride(request.user, data['vehicle_type'], data['pickup'], data['dropoff'])
        return ride_response(request, ride, status.HTTP_201_CREATED)


class CurrentRideView(APIView):
    """GET /api/rides/current/ -> the active ride of this user, or null."""

    def get(self, request):
        driver = services.get_driver(request.user)
        if driver:
            qs = Ride.objects.filter(driver=driver, status__in=services.DRIVER_ACTIVE_STATUSES)
        else:
            qs = Ride.objects.filter(customer=request.user, status__in=Ride.ACTIVE_STATUSES)
        ride = qs.first()
        # Without the worker running, a search must still end for the customer.
        if ride and ride.status == 'PENDING' and services.expire_ride_if_stale(ride.id):
            ride = None
        if ride is None:
            return Response({'ride': None})
        ride = Ride.objects.select_related(*RIDE_RELATED).get(pk=ride.pk)
        return Response({'ride': services.ride_payload(ride, services.viewer_for(request.user, ride))})


class RideDetailView(APIView):
    def get(self, request, ride_id):
        ride = my_rides(request.user).select_related(*RIDE_RELATED).filter(pk=ride_id).first()
        if ride is None:
            return Response({'detail': 'Không tìm thấy chuyến đi.'}, status=status.HTTP_404_NOT_FOUND)
        return ride_response(request, ride)


class CancelRideView(APIView):
    def post(self, request, ride_id):
        data = validated(CancelSerializer, request.data)
        ride = services.cancel_ride(request.user, ride_id, data['reason'])
        return ride_response(request, ride)


class RateRideView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]

    def post(self, request, ride_id):
        data = validated(RateSerializer, request.data)
        ride = services.rate_ride(request.user, ride_id, data['rating'], data['comment'])
        return ride_response(request, ride)


# --- Driver -------------------------------------------------------------------

class DriverOnlyView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsDriver]

    @property
    def driver(self):
        return services.get_driver(self.request.user)


class UpdateDriverStatusView(DriverOnlyView):
    """PATCH /api/driver/status/ {status: ONLINE|OFFLINE, lat, lng}"""

    def patch(self, request):
        data = validated(DriverStatusSerializer, request.data)
        driver = services.set_driver_status(
            self.driver, data['status'] == 'ONLINE', data.get('lat'), data.get('lng')
        )
        return Response(DriverProfileSerializer(driver).data)


class DriverLocationView(DriverOnlyView):
    """POST /api/driver/location/ {lat, lng, heading?}. Fallback for the WebSocket message."""
    throttle_scope = 'location'

    def post(self, request):
        data = validated(LocationSerializer, request.data)
        services.update_driver_location(self.driver, data['lat'], data['lng'], data['heading'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class DriverOffersView(DriverOnlyView):
    """GET /api/driver/offers/ -> my open ride offer(s), e.g. after reconnecting."""

    def get(self, request):
        return Response({'offers': OfferSerializer(services.open_offers_for(self.driver), many=True).data})


class AcceptRideView(DriverOnlyView):
    def post(self, request, ride_id):
        ride = services.accept_ride(self.driver, ride_id)
        return ride_response(request, ride)


class DeclineRideView(DriverOnlyView):
    def post(self, request, ride_id):
        services.decline_ride(self.driver, ride_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UpdateRideStatusView(DriverOnlyView):
    """PATCH /api/driver/rides/<id>/update-status/ {status: ARRIVED|IN_PROGRESS|COMPLETED}"""

    def patch(self, request, ride_id):
        data = validated(RideStatusSerializer, request.data)
        ride = services.advance_ride(self.driver, ride_id, data['status'])
        return ride_response(request, ride)


class DriverEarningsView(DriverOnlyView):
    """GET /api/driver/earnings/ -> today / week / month totals + recent completed rides."""

    def get(self, request):
        data = services.driver_earnings(self.driver)
        data['recent'] = [services.ride_payload(r, 'driver') for r in data['recent']]
        return Response(data)


# --- Places -------------------------------------------------------------------

class GeoSearchView(APIView):
    """GET /api/geo/search/?q=&lat=&lng= -> {results: [{name, address, lat, lng}]}"""
    throttle_scope = 'geo'

    def get(self, request):
        data = validated(GeoSearchSerializer, request.query_params)
        return Response({'results': geocoding.search(data['q'], data.get('lat'), data.get('lng'))})


class GeoReverseView(APIView):
    """GET /api/geo/reverse/?lat=&lng= -> {name, address, lat, lng}"""
    throttle_scope = 'geo'

    def get(self, request):
        data = validated(GeoPointSerializer, request.query_params)
        return Response(geocoding.reverse(data['lat'], data['lng']))
