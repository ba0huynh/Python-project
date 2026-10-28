from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from accounts.models import Customer
from .models import DriverProfile, Ride, Route, VehicleType


# ==============================================================================
# 1. BẢNG KHÁCH HÀNG (Customer / User Profile)
# ==============================================================================
if admin.site.is_registered(Customer):
    admin.site.unregister(Customer)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """
    Quản trị thông tin Khách hàng (User Profile)
    """
    list_display = ('id', 'full_name', 'phone', 'user', 'created_at')
    search_fields = ('full_name', 'phone', 'user__username', 'user__email')
    list_filter = ('created_at',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    list_per_page = 20
    ordering = ('-created_at',)

    fieldsets = (
        (_("Tài khoản liên kết"), {
            'fields': ('user', 'id'),
        }),
        (_("Thông tin cá nhân"), {
            'fields': ('full_name', 'phone'),
        }),
        (_("Thời gian ghi nhận"), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


# ==============================================================================
# 2. BẢNG TÀI XẾ (DriverProfile)
# ==============================================================================
@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    """
    Quản trị thông tin Tài xế, phương tiện và duyệt hồ sơ
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
    list_filter = ('is_approved', 'status', 'vehicle_type', 'created_at')
    search_fields = (
        'full_name',
        'phone',
        'vehicle_plate',
        'license_number',
        'vehicle_name',
        'user__username',
    )
    readonly_fields = ('id', 'created_at', 'updated_at', 'location_updated_at')
    list_per_page = 20
    ordering = ('-created_at',)
    actions = ['approve_drivers', 'unapprove_drivers']

    # --- Actions Duyệt Hàng Loạt ---
    @admin.action(description="✓ Duyệt hàng loạt tài xế đã chọn")
    def approve_drivers(self, request, queryset):
        updated_count = queryset.update(is_approved=True)
        self.message_user(
            request,
            f"Đã duyệt thành công {updated_count} hồ sơ tài xế.",
            messages.SUCCESS,
        )

    @admin.action(description="✗ Hủy duyệt hàng loạt tài xế đã chọn")
    def unapprove_drivers(self, request, queryset):
        updated_count = queryset.update(is_approved=False)
        self.message_user(
            request,
            f"Đã hủy duyệt {updated_count} tài xế đã chọn.",
            messages.WARNING,
        )

    # --- Badges / Displays ---
    @admin.display(description="Loại xe", ordering="vehicle_type")
    def vehicle_type_badge(self, obj):
        colors = {
            VehicleType.BIKE: "#28a745",
            VehicleType.CAR4: "#17a2b8",
            VehicleType.CAR7: "#007bff",
        }
        color = colors.get(obj.vehicle_type, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px;">{}</span>',
            color,
            obj.get_vehicle_type_display(),
        )

    @admin.display(description="Trạng thái duyệt", boolean=True, ordering="is_approved")
    def is_approved_badge(self, obj):
        return obj.is_approved

    @admin.display(description="Trạng thái", ordering="status")
    def status_badge(self, obj):
        colors = {
            'ONLINE': 'background: #28a745; color: #fff;',
            'BUSY': 'background: #e0a800; color: #fff;',
            'OFFLINE': 'background: #6c757d; color: #fff;',
        }
        style = colors.get(obj.status, 'background: #6c757d; color: #fff;')
        return format_html(
            '<span style="{}; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px;">{}</span>',
            style,
            obj.get_status_display(),
        )

    @admin.display(description="Đánh giá", ordering="rating")
    def rating_display(self, obj):
        return format_html('⭐ <strong>{:.1f}</strong>', obj.rating)

    fieldsets = (
        (_("Tài khoản & Hồ sơ cá nhân"), {
            'fields': ('user', 'full_name', 'phone', 'license_number'),
        }),
        (_("Phương tiện di chuyển"), {
            'fields': ('vehicle_plate', 'vehicle_type', 'vehicle_name'),
        }),
        (_("Trạng thái hoạt động & Xét duyệt"), {
            'fields': ('is_approved', 'status', 'rating'),
        }),
        (_("Vị trí GPS thời gian thực"), {
            'fields': (('current_latitude', 'current_longitude'), 'location_updated_at'),
            'classes': ('collapse',),
        }),
        (_("Thông tin hệ thống"), {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


# ==============================================================================
# 3. BẢNG CUỐC XE (Booking / Ride)
# ==============================================================================
@admin.register(Ride)
class RideAdmin(admin.ModelAdmin):
    """
    Quản trị chuyến đi: khóa chặt các trường nhạy cảm để chống gian lận
    """
    list_display = (
        'id',
        'customer_display',
        'driver_display',
        'pickup_address',
        'dropoff_address',
        'fare_display',
        'status_badge',
        'created_at',
    )
    list_filter = (
        'status',
        'created_at',
        'vehicle_type',
        'payment_method',
    )
    search_fields = (
        'id',
        'customer__username',
        'customer__first_name',
        'customer__last_name',
        'customer__customer__full_name',
        'customer__customer__phone',
        'driver__full_name',
        'driver__phone',
        'driver__vehicle_plate',
        'pickup_address',
        'dropoff_address',
    )
    date_hierarchy = 'created_at'
    list_per_page = 20
    ordering = ('-created_at',)

    # Khóa toàn bộ các trường nhạy cảm: giá tiền, thời gian đặt, thông tin khách/tài xế, v.v.
    readonly_fields = (
        'id',
        'customer',
        'driver',
        'fare',
        'created_at',
        'updated_at',
        'accepted_at',
        'arrived_at',
        'started_at',
        'completed_at',
        'cancelled_at',
        'cancelled_by',
        'cancel_reason',
        'distance_m',
        'duration_s',
        'route',
        'approach_route',
    )

    # --- Custom Displays ---
    @admin.display(description="Khách hàng", ordering="customer__username")
    def customer_display(self, obj):
        customer_profile = getattr(obj.customer, 'customer', None)
        if customer_profile and customer_profile.full_name:
            return f"{customer_profile.full_name} ({customer_profile.phone})"
        return obj.customer.username

    @admin.display(description="Tài xế", ordering="driver__full_name")
    def driver_display(self, obj):
        if obj.driver:
            return f"{obj.driver.full_name} ({obj.driver.phone})"
        return format_html('<span style="color: #999;">— Chưa gán —</span>')

    @admin.display(description="Giá tiền", ordering="fare")
    def fare_display(self, obj):
        formatted = f"{obj.fare:,.0f} đ".replace(",", ".")
        return format_html('<strong>{}</strong>', formatted)

    @admin.display(description="Trạng thái", ordering="status")
    def status_badge(self, obj):
        color_map = {
            'PENDING': 'background: #e0a800; color: #fff;',
            'ACCEPTED': 'background: #17a2b8; color: #fff;',
            'ARRIVED': 'background: #007bff; color: #fff;',
            'IN_PROGRESS': 'background: #6f42c1; color: #fff;',
            'COMPLETED': 'background: #28a745; color: #fff;',
            'CANCELLED': 'background: #dc3545; color: #fff;',
        }
        style = color_map.get(obj.status, 'background: #6c757d; color: #fff;')
        return format_html(
            '<span style="{}; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; display: inline-block;">{}</span>',
            style,
            obj.get_status_display(),
        )

    fieldsets = (
        (_("Thông tin chung & Trạng thái"), {
            'fields': ('id', 'status', 'vehicle_type', 'payment_method'),
        }),
        (_("Đối tượng tham gia (Khóa bảo vệ chống gian lận)"), {
            'fields': ('customer', 'driver'),
            'description': "Thông tin khách hàng và tài xế được khóa để tránh can thiệp trái phép.",
        }),
        (_("Cước phí & Thanh toán (Khóa bảo vệ chống gian lận)"), {
            'fields': ('fare',),
            'description': "Giá cước gốc của chuyến đi được bảo vệ toàn vẹn dữ liệu.",
        }),
        (_("Địa điểm đón & trả khách"), {
            'fields': (
                ('pickup_address', 'pickup_lat', 'pickup_lng'),
                ('dropoff_address', 'dropoff_lat', 'dropoff_lng'),
            ),
        }),
        (_("Lộ trình & Khoảng cách"), {
            'fields': (
                ('distance_m', 'duration_s'),
                ('route', 'approach_route'),
            ),
            'classes': ('collapse',),
        }),
        (_("Mốc thời gian tiến trình cuốc xe"), {
            'fields': (
                ('created_at', 'accepted_at'),
                ('arrived_at', 'started_at'),
                ('completed_at', 'cancelled_at'),
                ('cancelled_by', 'cancel_reason'),
            ),
            'classes': ('collapse',),
        }),
        (_("Đánh giá từ khách hàng"), {
            'fields': ('rating', 'rating_comment'),
            'classes': ('collapse',),
        }),
    )


# ==============================================================================
# 4. BẢNG TUYẾN ĐƯỜNG (Route Cache)
# ==============================================================================
@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    """
    Quản trị cache lộ trình Geoapify
    """
    list_display = ('id', 'mode', 'distance_m', 'duration_s', 'provider', 'created_at')
    list_filter = ('mode', 'provider', 'created_at')
    search_fields = ('mode', 'provider')
    readonly_fields = ('id', 'created_at', 'updated_at', 'geometry')
    list_per_page = 20
    ordering = ('-created_at',)

