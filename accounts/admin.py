from django.contrib import admin

from .models import Customer, PhoneOTP


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'user', 'created_at')
    search_fields = ('full_name', 'phone')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    list_display = ('phone', 'purpose', 'role', 'created_at', 'expires_at', 'attempts', 'consumed_at')
    list_filter = ('purpose', 'role')
    search_fields = ('phone',)
    exclude = ('code_hash',)
    readonly_fields = ('id', 'phone', 'purpose', 'role', 'expires_at', 'attempts', 'consumed_at', 'created_at',
                       'updated_at')
