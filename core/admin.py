from django.contrib import admin
from .models import DriverProfile, Ride

# Đăng ký các model mới lên trang quản trị Admin của Django
@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'vehicle_plate', 'vehicle_type', 'status', 'is_approved')
    list_filter = ('status', 'is_approved', 'vehicle_type')
    search_fields = ('user__username', 'license_number', 'vehicle_plate')

@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'driver', 'pickup_location', 'dropoff_location', 'fare', 'status')
    list_filter = ('status',)
    search_fields = ('customer__username', 'pickup_location', 'dropoff_location')