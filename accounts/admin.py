from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'user', 'created_at')
    search_fields = ('full_name', 'phone')
    readonly_fields = ('id', 'created_at', 'updated_at')
