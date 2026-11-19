from django.contrib import admin

from .models import DriverProfile, FareRule, Ride, RideOffer, Route


@admin.register(FareRule)
class FareRuleAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'vehicle_type', 'base_fare', 'base_km', 'per_km', 'minimum_fare',
                    'commission_percent', 'is_active')
    list_editable = ('base_fare', 'base_km', 'per_km', 'minimum_fare', 'commission_percent', 'is_active')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'vehicle_plate', 'vehicle_type', 'status', 'is_approved', 'rating',
                    'location_updated_at')
    list_filter = ('status', 'is_approved', 'vehicle_type')
    list_editable = ('is_approved',)
    search_fields = ('full_name', 'phone', 'user__username', 'license_number', 'vehicle_plate')
    readonly_fields = ('id', 'created_at', 'updated_at', 'location_updated_at', 'current_latitude',
                       'current_longitude', 'current_heading', 'rating')
    actions = ['approve']

    @admin.action(description='Duyệt các tài xế đã chọn')
    def approve(self, request, queryset):
        queryset.update(is_approved=True)


class RideOfferInline(admin.TabularInline):
    model = RideOffer
    extra = 0
    can_delete = False
    fields = ('driver', 'status', 'distance_m', 'created_at', 'expires_at', 'responded_at')
    readonly_fields = fields


@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'driver', 'vehicle_type', 'fare', 'commission', 'status', 'cancelled_by',
                    'created_at')
    list_filter = ('status', 'vehicle_type', 'cancelled_by')
    search_fields = ('id', 'customer__username', 'driver__phone', 'pickup_address', 'dropoff_address')
    raw_id_fields = ('customer', 'driver', 'route', 'approach_route')
    readonly_fields = ('id', 'created_at', 'updated_at', 'fare', 'commission_percent', 'commission',
                       'driver_earning', 'distance_m', 'duration_s', 'dispatched_at')
    inlines = [RideOfferInline]
    date_hierarchy = 'created_at'


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('id', 'mode', 'distance_m', 'duration_s', 'provider', 'created_at')
    list_filter = ('mode', 'provider')
    readonly_fields = ('id', 'created_at', 'updated_at')
