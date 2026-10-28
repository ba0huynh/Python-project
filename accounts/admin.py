from django.contrib import admin

from .models import Customer


if not admin.site.is_registered(Customer):
    @admin.register(Customer)
    class CustomerAdmin(admin.ModelAdmin):
        list_display = ('id', 'full_name', 'phone', 'user', 'created_at')
        search_fields = ('full_name', 'phone', 'user__username', 'user__email')
        list_filter = ('created_at',)
        readonly_fields = ('id', 'created_at', 'updated_at')
        list_per_page = 20
        ordering = ('-created_at',)

