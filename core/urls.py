from django.urls import path
from .views import (
    UpdateDriverStatusView, 
    AvailableRidesView, 
    AcceptRideView, 
    UpdateRideStatusView
)

urlpatterns = [
    path('driver/<uuid:driver_id>/status/', UpdateDriverStatusView.as_view(), name='update-driver-status'),
    path('driver/rides/available/', AvailableRidesView.as_view(), name='available-rides'),
    path('driver/rides/<uuid:ride_id>/accept/', AcceptRideView.as_view(), name='accept-ride'),
    path('driver/rides/<uuid:ride_id>/update-status/', UpdateRideStatusView.as_view(), name='update-ride-status'),
]