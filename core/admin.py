from django.contrib import admin
from .models import SampleEntity


@admin.register(SampleEntity)
class SampleEntityAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'is_active', 'created_at', 'updated_at')
    list_filter = ('status', 'is_active', 'created_at')
    search_fields = ('title', 'description')
    readonly_fields = ('id', 'created_at', 'updated_at')
