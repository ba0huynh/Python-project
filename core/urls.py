from django.urls import path

from .views import (
    AcceptRideView, AvailableRidesView, CancelRideView, CurrentRideView, DriverLocationView,
    RateRideView, RideDetailView, RideEstimateView, RideListCreateView, UpdateDriverStatusView,
    UpdateRideStatusView,
)

# Mounted at /api/ in config/urls.py
urlpatterns = [
    # Customer (and shared)
    path('rides/estimate/', RideEstimateView.as_view(), name='ride-estimate'),
    path('rides/', RideListCreateView.as_view(), name='rides'),
    path('rides/current/', CurrentRideView.as_view(), name='ride-current'),
    path('rides/<uuid:ride_id>/', RideDetailView.as_view(), name='ride-detail'),
    path('rides/<uuid:ride_id>/cancel/', CancelRideView.as_view(), name='ride-cancel'),
    path('rides/<uuid:ride_id>/rate/', RateRideView.as_view(), name='ride-rate'),
    # Driver
    path('driver/status/', UpdateDriverStatusView.as_view(), name='update-driver-status'),
    path('driver/location/', DriverLocationView.as_view(), name='driver-location'),
    path('driver/rides/available/', AvailableRidesView.as_view(), name='available-rides'),
    path('driver/rides/<uuid:ride_id>/accept/', AcceptRideView.as_view(), name='accept-ride'),
    path('driver/rides/<uuid:ride_id>/update-status/', UpdateRideStatusView.as_view(), name='update-ride-status'),
]
