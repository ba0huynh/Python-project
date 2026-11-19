from django.urls import path

from . import views

# Mounted at /api/ in config/urls.py
urlpatterns = [
    path('health/', views.HealthView.as_view(), name='health'),
    # Customer (and shared)
    path('rides/estimate/', views.RideEstimateView.as_view(), name='ride-estimate'),
    path('rides/', views.RideListCreateView.as_view(), name='rides'),
    path('rides/current/', views.CurrentRideView.as_view(), name='ride-current'),
    path('rides/<uuid:ride_id>/', views.RideDetailView.as_view(), name='ride-detail'),
    path('rides/<uuid:ride_id>/cancel/', views.CancelRideView.as_view(), name='ride-cancel'),
    path('rides/<uuid:ride_id>/rate/', views.RateRideView.as_view(), name='ride-rate'),
    # Driver
    path('driver/status/', views.UpdateDriverStatusView.as_view(), name='update-driver-status'),
    path('driver/location/', views.DriverLocationView.as_view(), name='driver-location'),
    path('driver/offers/', views.DriverOffersView.as_view(), name='driver-offers'),
    path('driver/earnings/', views.DriverEarningsView.as_view(), name='driver-earnings'),
    path('driver/rides/<uuid:ride_id>/accept/', views.AcceptRideView.as_view(), name='accept-ride'),
    path('driver/rides/<uuid:ride_id>/decline/', views.DeclineRideView.as_view(), name='decline-ride'),
    path('driver/rides/<uuid:ride_id>/update-status/', views.UpdateRideStatusView.as_view(),
         name='update-ride-status'),
    # Places
    path('geo/search/', views.GeoSearchView.as_view(), name='geo-search'),
    path('geo/reverse/', views.GeoReverseView.as_view(), name='geo-reverse'),
]
