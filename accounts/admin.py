from django.contrib import admin, messages

from core.models import DriverProfile
from .models import Customer


class CustomerAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'phone', 'created_at')
    search_fields = ('full_name', 'phone', 'user__username')


class DriverProfileAdmin(admin.ModelAdmin):
    list_display = (
        'full_name',
        'phone',
        'vehicle_plate',
        'vehicle_type',
        'is_approved',
        'status',
        'rating',
    )
    list_filter = ('is_approved', 'status', 'vehicle_type')
    search_fields = ('full_name', 'phone', 'vehicle_plate', 'license_number')
    readonly_fields = ('rating',)
    actions = ['approve_selected_drivers']

    @admin.action(description="✓ Phê duyệt các Tài xế đã chọn")
    def approve_selected_drivers(self, request, queryset):
        pending_drivers = queryset.filter(is_approved=False)
        count = pending_drivers.count()

        if count > 0:
            pending_drivers.update(is_approved=True, status='OFFLINE')
            self.message_user(
                request,
                f"Thành công: Đã phê duyệt {count} tài xế. Họ đã có thể bắt đầu nhận cuốc.",
                messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                "Không có tài xế nào được duyệt. Các tài xế bạn chọn có thể đã được duyệt từ trước.",
                messages.WARNING,
            )


if not admin.site.is_registered(Customer):
    admin.site.register(Customer, CustomerAdmin)

if not admin.site.is_registered(DriverProfile):
    admin.site.register(DriverProfile, DriverProfileAdmin)
