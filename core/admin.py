import csv
from django.contrib import admin, messages
from django.contrib.admin.views.main import ChangeList
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from accounts.models import Customer
from .models import DriverProfile, Ride, RideSummary, Route, VehicleType


# ==============================================================================
# CUSTOM ENGLISH FILTERS (Matches Django standard)
# ==============================================================================
class RideStatusFilter(admin.SimpleListFilter):
    title = 'status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return [
            ('PENDING', 'Pending'),
            ('ACCEPTED', 'Accepted'),
            ('ARRIVED', 'Arrived'),
            ('IN_PROGRESS', 'In Progress'),
            ('COMPLETED', 'Completed'),
            ('CANCELLED', 'Cancelled'),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(status=self.value())
        return queryset


class VehicleTypeFilter(admin.SimpleListFilter):
    title = 'vehicle type'
    parameter_name = 'vehicle_type'

    def lookups(self, request, model_admin):
        return [
            ('bike', 'GoBike'),
            ('car4', 'GoCar 4 Seats'),
            ('car7', 'GoCar 7 Seats'),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(vehicle_type=self.value())
        return queryset


class FareRangeFilter(admin.SimpleListFilter):
    title = 'fare range'
    parameter_name = 'fare_range'

    def lookups(self, request, model_admin):
        return [
            ('low', 'Under 50,000 ₫'),
            ('medium', '50,000 ₫ – 100,000 ₫'),
            ('high', 'Over 100,000 ₫'),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val == 'low':
            return queryset.filter(fare__lt=50000)
        elif val == 'medium':
            return queryset.filter(fare__gte=50000, fare__lte=100000)
        elif val == 'high':
            return queryset.filter(fare__gt=100000)
        return queryset


class DistanceFilter(admin.SimpleListFilter):
    title = 'distance'
    parameter_name = 'distance'

    def lookups(self, request, model_admin):
        return [
            ('short', 'Short (< 5 km)'),
            ('long', 'Long (≥ 5 km)'),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val == 'short':
            return queryset.filter(distance_m__lt=5000)
        elif val == 'long':
            return queryset.filter(distance_m__gte=5000)
        return queryset


class PaymentMethodFilter(admin.SimpleListFilter):
    title = 'payment method'
    parameter_name = 'payment_method'

    def lookups(self, request, model_admin):
        return [
            ('cash', 'Cash'),
            ('wallet', 'Wallet'),
            ('card', 'Credit/Debit Card'),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(payment_method=self.value())
        return queryset


class RatingFilter(admin.SimpleListFilter):
    title = 'rating'
    parameter_name = 'rating'

    def lookups(self, request, model_admin):
        return [
            ('5', '5 Stars'),
            ('4', '4 Stars'),
            ('3', '3 Stars'),
            ('2', '2 Stars'),
            ('1', '1 Star'),
            ('unrated', 'Unrated'),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val in ('1', '2', '3', '4', '5'):
            return queryset.filter(rating=int(val))
        elif val == 'unrated':
            return queryset.filter(rating__isnull=True)
        return queryset


# Alias for backward compatibility
BadRatingFilter = RatingFilter


# ==============================================================================
# 1. CUSTOMER TABLE (Customer / User Profile)
# ==============================================================================
if admin.site.is_registered(Customer):
    admin.site.unregister(Customer)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """
    Admin management for Customer profile
    """
    list_display = ('id', 'full_name', 'phone', 'user', 'created_at')
    search_fields = ('full_name', 'phone', 'user__username', 'user__email')
    list_filter = ('created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    list_per_page = 20
    ordering = ('-created_at',)

    fieldsets = (
        (_("Linked Account"), {
            'fields': ('user', 'id'),
        }),
        (_("Personal Information"), {
            'fields': ('full_name', 'phone'),
        }),
        (_("Timestamps"), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


# ==============================================================================
# 2. DRIVER PROFILE TABLE (DriverProfile)
# ==============================================================================
if admin.site.is_registered(DriverProfile):
    admin.site.unregister(DriverProfile)


@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    """
    Admin management for Driver profiles, vehicles and approvals
    """
    list_display = (
        'id',
        'full_name',
        'phone',
        'vehicle_plate',
        'vehicle_type_badge',
        'is_approved_badge',
        'status_badge',
        'rating_display',
    )
    list_filter = ('is_approved', 'status', VehicleTypeFilter, 'created_at')
    search_fields = (
        'full_name',
        'phone',
        'vehicle_plate',
        'license_number',
        'vehicle_name',
        'user__username',
    )
    readonly_fields = ('id', 'created_at', 'updated_at', 'location_updated_at', 'rating')
    list_per_page = 20
    ordering = ('-created_at',)
    actions = ['approve_selected_drivers', 'unapprove_drivers']

    # --- Actions ---
    @admin.action(description="Approve selected drivers")
    def approve_selected_drivers(self, request, queryset):
        """Phase 1 Driver approval: only approve unapproved drivers and set status to OFFLINE."""
        pending_drivers = queryset.filter(is_approved=False)
        count = pending_drivers.count()

        if count > 0:
            pending_drivers.update(is_approved=True, status='OFFLINE')
            self.message_user(
                request,
                f"Successfully approved {count} driver(s). They can now go ONLINE.",
                messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                "No drivers were approved. Selected driver(s) may already be approved.",
                messages.WARNING,
            )

    @admin.action(description="Unapprove selected drivers")
    def unapprove_drivers(self, request, queryset):
        """Revoke approval for selected drivers."""
        updated_count = queryset.update(is_approved=False)
        self.message_user(
            request,
            f"Successfully unapproved {updated_count} driver(s).",
            messages.WARNING,
        )

    # --- Column Displays (100% English following Django) ---
    @admin.display(description="Vehicle Type", ordering="vehicle_type")
    def vehicle_type_badge(self, obj):
        return obj.get_vehicle_type_display()

    @admin.display(description="Approval Status", boolean=True, ordering="is_approved")
    def is_approved_badge(self, obj):
        return obj.is_approved

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        colors = {
            'ONLINE': 'background: #28a745; color: #fff;',
            'BUSY': 'background: #e0a800; color: #fff;',
            'OFFLINE': 'background: #6c757d; color: #fff;',
        }
        status_labels = {
            'ONLINE': 'Online',
            'BUSY': 'Busy',
            'OFFLINE': 'Offline',
        }
        style = colors.get(obj.status, 'background: #6c757d; color: #fff;')
        label = status_labels.get(obj.status, obj.get_status_display())
        return format_html(
            '<span style="{}; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px;">{}</span>',
            style,
            label,
        )

    @admin.display(description="Rating", ordering="rating")
    def rating_display(self, obj):
        rating_str = f"{obj.rating:.1f}" if obj.rating is not None else "—"
        return format_html('⭐ <strong>{}</strong>', rating_str)

    fieldsets = (
        (_("Account & Personal Profile"), {
            'fields': ('user', 'full_name', 'phone', 'license_number'),
        }),
        (_("Vehicle Details"), {
            'fields': ('vehicle_plate', 'vehicle_type', 'vehicle_name'),
        }),
        (_("Operating Status & Verification"), {
            'fields': ('is_approved', 'status', 'rating'),
        }),
        (_("Real-time GPS Location"), {
            'fields': (('current_latitude', 'current_longitude'), 'location_updated_at'),
            'classes': ('collapse',),
        }),
        (_("System Information"), {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


# ==============================================================================
# 3. RIDE TABLE (Booking / Ride) - PHASE 2
# ==============================================================================
@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    """
    Admin management for Rides: Dashboard and protected financial data
    """
    list_display = (
        'short_id',
        'customer',
        'driver',
        'get_vehicle_type_display',
        'status',
        'fare_display',
        'rating_display',
        'created_at',
    )
    list_filter = (
        RideStatusFilter,
        VehicleTypeFilter,
        FareRangeFilter,
        DistanceFilter,
        RatingFilter,
        PaymentMethodFilter,
    )
    search_fields = (
        'customer__username',
        'customer__customer__full_name',
        'driver__full_name',
        'id',
    )
    date_hierarchy = 'created_at'
    list_per_page = 20
    ordering = ('-created_at',)
    actions = ['export_selected_rides_to_csv']

    # Lock sensitive financial, route, and customer review data
    readonly_fields = (
        'fare',
        'distance_m',
        'duration_s',
        'route',
        'approach_route',
        'rating',
        'rating_comment',
    )

    fieldsets = (
        (_("General Overview"), {
            'fields': ('customer', 'driver', 'vehicle_type', 'status', 'payment_method'),
        }),
        (_("Coordinates & Locations"), {
            'fields': (
                ('pickup_address', 'pickup_lat', 'pickup_lng'),
                ('dropoff_address', 'dropoff_lat', 'dropoff_lng'),
            ),
        }),
        (_("Route & Financials"), {
            'fields': ('distance_m', 'duration_s', 'fare', 'route', 'approach_route'),
        }),
        (_("Timeline & Incidents"), {
            'classes': ('collapse',),
            'fields': (
                'accepted_at',
                'arrived_at',
                'started_at',
                'completed_at',
                'cancelled_at',
                'cancelled_by',
                'cancel_reason',
            ),
        }),
        (_("Customer Feedback"), {
            'classes': ('collapse',),
            'fields': ('rating', 'rating_comment'),
        }),
    )

    # --- Custom Displays (100% English following Django) ---
    @admin.display(description="Ride ID")
    def short_id(self, obj):
        """Return the first part of UUID in uppercase."""
        if not obj.id:
            return ""
        return str(obj.id).split('-')[0].upper()
    short_id.short_description = 'Ride ID'

    @admin.display(description="Driver", ordering="driver__full_name")
    def driver(self, obj):
        """Display driver name and status in English."""
        if obj.driver:
            return f"{obj.driver.full_name} ({obj.driver.status})"
        return "—"

    @admin.display(description="Status", ordering="status")
    def status(self, obj):
        """Display status in clean English."""
        status_labels = {
            'PENDING': 'Pending',
            'ACCEPTED': 'Accepted',
            'ARRIVED': 'Arrived',
            'IN_PROGRESS': 'In Progress',
            'COMPLETED': 'Completed',
            'CANCELLED': 'Cancelled',
        }
        return status_labels.get(obj.status, obj.status)

    @admin.display(description="Fare")
    def fare_display(self, obj):
        """Format fare with commas and ₫ currency symbol."""
        if obj.fare is None:
            return "0 ₫"
        return f"{obj.fare:,.0f} ₫"
    fare_display.short_description = 'Fare'

    @admin.display(description="Service")
    def get_vehicle_type_display(self, obj):
        """Human-readable service / vehicle type label."""
        labels = {
            VehicleType.BIKE: "GoBike",
            VehicleType.CAR4: "GoCar 4 Seats",
            VehicleType.CAR7: "GoCar 7 Seats",
        }
        return labels.get(obj.vehicle_type, obj.get_vehicle_type_display())
    get_vehicle_type_display.short_description = 'Service'

    @admin.display(description="Rating", ordering="rating")
    def rating_display(self, obj):
        """Format rating with star icon or dash if unrated."""
        if obj.rating:
            return format_html('⭐ <strong>{}</strong>', obj.rating)
        return "—"

    @admin.action(description="Export selected rides to CSV")
    def export_selected_rides_to_csv(self, request, queryset):
        """
        Export selected rides to a CSV file formatted with UTF-8 BOM
        so that Excel opens Vietnamese characters cleanly.
        100% pure Python using the standard library csv module.
        """
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="goxe_rides_{timestamp}.csv"'

        # Write UTF-8 BOM to ensure Excel properly displays UTF-8 (Vietnamese characters)
        response.write('\ufeff'.encode('utf-8'))

        writer = csv.writer(response)
        writer.writerow([
            "Ride ID",
            "Created At",
            "Completed At",
            "Customer Name",
            "Customer Phone",
            "Driver Name",
            "Driver Phone",
            "Vehicle Plate",
            "Vehicle Type",
            "Pickup Address",
            "Dropoff Address",
            "Distance (km)",
            "Fare (VND)",
            "Payment Method",
            "Status",
            "Rating",
            "Customer Feedback",
        ])

        # Optimize database query
        rides = queryset.select_related('customer', 'driver')
        for ride in rides:
            customer_name = ""
            customer_phone = ""
            if ride.customer:
                customer_profile = getattr(ride.customer, 'customer', None)
                if customer_profile:
                    customer_name = customer_profile.full_name
                    customer_phone = customer_profile.phone
                else:
                    customer_name = ride.customer.get_full_name() or ride.customer.username

            driver_name = ride.driver.full_name if ride.driver else ""
            driver_phone = ride.driver.phone if ride.driver else ""
            driver_plate = ride.driver.vehicle_plate if ride.driver else ""

            distance_km = f"{ride.distance_m / 1000:.2f}" if ride.distance_m else "0"
            created_str = ride.created_at.strftime("%Y-%m-%d %H:%M:%S") if ride.created_at else ""
            completed_str = ride.completed_at.strftime("%Y-%m-%d %H:%M:%S") if ride.completed_at else ""

            vehicle_labels = {
                VehicleType.BIKE: "GoBike",
                VehicleType.CAR4: "GoCar 4 Seats",
                VehicleType.CAR7: "GoCar 7 Seats",
            }
            vehicle_type_str = vehicle_labels.get(ride.vehicle_type, ride.get_vehicle_type_display())

            status_labels = {
                'PENDING': 'Pending',
                'ACCEPTED': 'Accepted',
                'ARRIVED': 'Arrived',
                'IN_PROGRESS': 'In Progress',
                'COMPLETED': 'Completed',
                'CANCELLED': 'Cancelled',
            }
            status_str = status_labels.get(ride.status, ride.status)

            writer.writerow([
                str(ride.id),
                created_str,
                completed_str,
                customer_name,
                customer_phone,
                driver_name,
                driver_phone,
                driver_plate,
                vehicle_type_str,
                ride.pickup_address,
                ride.dropoff_address,
                distance_km,
                ride.fare,
                ride.payment_method.capitalize() if ride.payment_method else "",
                status_str,
                ride.rating if ride.rating is not None else "",
                ride.rating_comment or "",
            ])

        return response


# ==============================================================================
# 4. ROUTE TABLE (Route Cache) - PHASE 2
# ==============================================================================
@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    """
    Admin management for Geoapify cached routes
    """
    list_display = ('mode', 'distance_m', 'duration_s', 'provider', 'created_at')
    list_filter = ('mode', 'provider')
    readonly_fields = ('geometry', 'id', 'created_at', 'updated_at')
    list_per_page = 20
    ordering = ('-created_at',)


# ==============================================================================
# 5. RIDES SUMMARY & ANALYTICS DASHBOARD (100% PURE PYTHON)
# ==============================================================================
class RideSummaryChangeList(ChangeList):
    """
    Custom ChangeList grouping rides by vehicle/service type and aggregating
    live performance indicators and gross revenue via Django ORM.
    """
    def get_results(self, request):
        super().get_results(request)
        grouped = self.queryset.values('vehicle_type').annotate(
            total_rides=Count('id'),
            completed_rides=Count('id', filter=Q(status='COMPLETED')),
            cancelled_rides=Count('id', filter=Q(status='CANCELLED')),
            active_rides=Count('id', filter=Q(status__in=['ACCEPTED', 'ARRIVED', 'IN_PROGRESS'])),
            total_revenue=Coalesce(Sum('fare', filter=Q(status='COMPLETED')), Value(0)),
        ).order_by('vehicle_type')

        results = []
        for row in grouped:
            obj = RideSummary(
                id=row['vehicle_type'],
                vehicle_type=row['vehicle_type'],
            )
            obj.total_rides = row['total_rides']
            obj.completed_rides = row['completed_rides']
            obj.cancelled_rides = row['cancelled_rides']
            obj.active_rides = row['active_rides']
            obj.total_revenue = row['total_revenue']
            results.append(obj)

        self.result_list = results
        self.result_count = len(results)
        self.can_show_all = False
        self.multi_page = False
        self.paginator = self.model_admin.get_paginator(request, results, 100)


@admin.register(RideSummary)
class RideSummaryAdmin(admin.ModelAdmin):
    """
    Operations Analytics & Revenue Dashboard (100% pure Python, no HTML files required).
    Aggregates trips, completion rates, and total revenue by service type and date.
    """
    list_display = (
        'service_badge',
        'total_rides_count',
        'completed_rides_count',
        'active_rides_count',
        'cancelled_rides_count',
        'revenue_display',
    )
    list_display_links = None
    list_filter = ('vehicle_type', 'created_at')
    date_hierarchy = 'created_at'

    def get_changelist(self, request, **kwargs):
        return RideSummaryChangeList

    @admin.display(description="Service", ordering="vehicle_type")
    def service_badge(self, obj):
        label = obj.get_vehicle_type_display()
        from django.urls import reverse
        url = reverse('admin:core_ride_changelist') + f'?vehicle_type={obj.vehicle_type}'
        return format_html(
            '<a href="{}" style="font-weight: 600; text-decoration: none;" title="Filter detailed rides for {}">'
            '{} &rarr;'
            '</a>',
            url,
            label,
            label,
        )

    @admin.display(description="Total Trips")
    def total_rides_count(self, obj):
        return obj.total_rides

    @admin.display(description="Completed Trips")
    def completed_rides_count(self, obj):
        return format_html('<span style="color: #28a745; font-weight: bold;">{}</span>', obj.completed_rides)

    @admin.display(description="Active Trips")
    def active_rides_count(self, obj):
        return format_html('<span style="color: #007bff; font-weight: bold;">{}</span>', obj.active_rides)

    @admin.display(description="Cancelled Trips")
    def cancelled_rides_count(self, obj):
        return format_html('<span style="color: #dc3545; font-weight: bold;">{}</span>', obj.cancelled_rides)

    @admin.display(description="Total Revenue")
    def revenue_display(self, obj):
        revenue_val = obj.total_revenue or 0
        revenue_str = f"{revenue_val:,.0f} ₫"
        return format_html('<strong style="font-size: 13px; color: #28a745;">{}</strong>', revenue_str)

    # Disable mutating actions since this is a pure analytics reporting view
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def change_view(self, request, object_id, form_url='', extra_context=None):
        from django.shortcuts import redirect
        from django.urls import reverse
        return redirect(reverse('admin:core_ridesummary_changelist'))

