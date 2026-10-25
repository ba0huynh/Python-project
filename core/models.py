import uuid

from django.contrib.auth.models import User
from django.db import models


class BaseModel(models.Model):
    """
    Abstract base model providing UUID primary key and timestamp tracking.
    All application entities can inherit from this.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']


class VehicleType(models.TextChoices):
    # Must match VEHICLES in mobile/src/lib/mock.ts and core/pricing.py
    BIKE = 'bike', 'GoBike (xe máy)'
    CAR4 = 'car4', 'GoCar 4 chỗ'
    CAR7 = 'car7', 'GoCar 7 chỗ'


class DriverProfile(BaseModel):
    """
    Model quản lý thông tin chi tiết của Tài xế.
    """
    STATUS_CHOICES = [
        ('OFFLINE', 'Offline'),
        ('ONLINE', 'Online'),
        ('BUSY', 'Busy'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='driver_profile')
    phone = models.CharField(max_length=12, unique=True, help_text="Số điện thoại (+84...)")
    full_name = models.CharField(max_length=150, default='')
    license_number = models.CharField(max_length=50, unique=True, help_text="Số bằng lái xe")
    vehicle_plate = models.CharField(max_length=20, help_text="Biển số xe")
    vehicle_type = models.CharField(
        max_length=10, choices=VehicleType.choices, default=VehicleType.BIKE, db_index=True
    )
    vehicle_name = models.CharField(max_length=100, blank=True, default='', help_text="VD: Honda Vision · Đỏ")
    is_approved = models.BooleanField(default=False, help_text="Trạng thái duyệt của Admin")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OFFLINE', db_index=True)
    current_latitude = models.FloatField(null=True, blank=True, help_text="Vĩ độ GPS hiện tại")
    current_longitude = models.FloatField(null=True, blank=True, help_text="Kinh độ GPS hiện tại")
    location_updated_at = models.DateTimeField(null=True, blank=True)
    rating = models.FloatField(default=5.0)

    class Meta:
        verbose_name = "Driver Profile"
        verbose_name_plural = "Driver Profiles"

    def __str__(self):
        return f"Tài xế {self.full_name or self.user.username} - {self.status}"


class Route(BaseModel):
    """
    A road route between two points, fetched from Geoapify and cached.

    Endpoints are rounded (see core/routing.py) so the same trip reuses one row
    instead of calling the API again. `geometry` is a GeoJSON LineString with
    [lng, lat] coordinates, ready to draw with MapLibre.
    """
    PROVIDER_CHOICES = [
        ('geoapify', 'Geoapify'),
        ('straight_line', 'Đường thẳng (dự phòng)'),
    ]

    mode = models.CharField(max_length=20, help_text="Geoapify mode: motorcycle / drive")
    from_lat = models.FloatField()
    from_lng = models.FloatField()
    to_lat = models.FloatField()
    to_lng = models.FloatField()
    distance_m = models.PositiveIntegerField()
    duration_s = models.PositiveIntegerField()
    geometry = models.JSONField(help_text="GeoJSON LineString, toạ độ [lng, lat]")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='geoapify')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['mode', 'from_lat', 'from_lng', 'to_lat', 'to_lng'], name='unique_route_endpoints'
            ),
        ]

    def __str__(self):
        return f"{self.mode} {self.distance_m}m ({self.provider})"


class Ride(BaseModel):
    """
    Model quản lý thông tin chuyến đi đặt xe.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Chờ tài xế'),
        ('ACCEPTED', 'Đã nhận cuốc'),
        ('ARRIVED', 'Tài xế đã đến điểm đón'),
        ('IN_PROGRESS', 'Đang chở khách'),
        ('COMPLETED', 'Hoàn thành'),
        ('CANCELLED', 'Đã hủy'),
    ]
    ACTIVE_STATUSES = ('PENDING', 'ACCEPTED', 'ARRIVED', 'IN_PROGRESS')
    CANCELLED_BY_CHOICES = [('customer', 'Khách hàng'), ('driver', 'Tài xế'), ('system', 'Hệ thống')]

    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='customer_rides')
    driver = models.ForeignKey(DriverProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='driver_rides')
    vehicle_type = models.CharField(max_length=10, choices=VehicleType.choices, default=VehicleType.BIKE)

    pickup_address = models.CharField(max_length=255, help_text="Điểm đón")
    pickup_lat = models.FloatField()
    pickup_lng = models.FloatField()
    dropoff_address = models.CharField(max_length=255, help_text="Điểm trả")
    dropoff_lat = models.FloatField()
    dropoff_lng = models.FloatField()

    # Pickup -> dropoff route (what the customer pays for)
    route = models.ForeignKey(Route, on_delete=models.SET_NULL, null=True, blank=True, related_name='rides')
    # Driver position at accept time -> pickup
    approach_route = models.ForeignKey(
        Route, on_delete=models.SET_NULL, null=True, blank=True, related_name='approach_rides'
    )
    distance_m = models.PositiveIntegerField(default=0)
    duration_s = models.PositiveIntegerField(default=0)
    fare = models.PositiveIntegerField(help_text="Cước phí chuyến đi (VND)")
    payment_method = models.CharField(max_length=20, default='cash')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.CharField(max_length=10, choices=CANCELLED_BY_CHOICES, blank=True, default='')
    cancel_reason = models.CharField(max_length=255, blank=True, default='')

    rating = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Khách đánh giá tài xế (1-5)")
    rating_comment = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        verbose_name = "Ride"
        verbose_name_plural = "Rides"
        ordering = ['-created_at']

    def __str__(self):
        return f"Cuốc #{self.id} - {self.status}"
