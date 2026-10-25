from django.contrib import admin

from .models import DriverProfile, Ride, Route


@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'vehicle_plate', 'vehicle_type', 'status', 'is_approved', 'rating')
    list_filter = ('status', 'is_approved', 'vehicle_type')
    list_editable = ('is_approved',)
    search_fields = ('full_name', 'phone', 'user__username', 'license_number', 'vehicle_plate')
    readonly_fields = ('id', 'created_at', 'updated_at', 'location_updated_at')


@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'driver', 'vehicle_type', 'pickup_address', 'dropoff_address', 'fare', 'status', 'created_at')
    list_filter = ('status', 'vehicle_type')
    search_fields = ('customer__username', 'pickup_address', 'dropoff_address')
    raw_id_fields = ('customer', 'driver', 'route', 'approach_route')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('id', 'mode', 'distance_m', 'duration_s', 'provider', 'created_at')
    list_filter = ('mode', 'provider')
    readonly_fields = ('id', 'created_at', 'updated_at')
