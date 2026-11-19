import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


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
    # Must match mobile/src/lib/vehicles.ts. Prices live in FareRule (editable in /admin).
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
    current_heading = models.FloatField(null=True, blank=True, help_text="Hướng di chuyển (độ, 0 = Bắc)")
    location_updated_at = models.DateTimeField(null=True, blank=True)
    rating = models.FloatField(default=5.0)

    class Meta:
        verbose_name = "Driver Profile"
        verbose_name_plural = "Driver Profiles"

    def __str__(self):
        return f"Tài xế {self.full_name or self.user.username} - {self.status}"


class FareRule(BaseModel):
    """
    Price list for one vehicle type, editable in /admin without a deploy.

    fare = base_fare (covers the first base_km) + per_km * (km - base_km), at least
    minimum_fare, rounded to 1.000đ. The platform keeps commission_percent of the
    fare; the rest is the driver's earning. See core/pricing.py.
    """
    vehicle_type = models.CharField(max_length=10, choices=VehicleType.choices, unique=True)
    display_name = models.CharField(max_length=50)
    seats = models.PositiveSmallIntegerField(default=1)
    base_fare = models.PositiveIntegerField(help_text="VND, covers the first base_km")
    base_km = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('2'))
    per_km = models.PositiveIntegerField(help_text="VND per km after base_km")
    minimum_fare = models.PositiveIntegerField(default=0, help_text="VND")
    commission_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('20'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Platform fee taken from the fare (%)",
    )
    is_active = models.BooleanField(default=True, help_text="Inactive types can't be booked")

    class Meta:
        ordering = ['base_fare']

    def __str__(self):
        return f"{self.display_name} ({self.vehicle_type})"


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
    fare = models.PositiveIntegerField(help_text="Cước phí khách trả (VND), chốt khi đặt xe")
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0'))
    commission = models.PositiveIntegerField(default=0, help_text="Phí nền tảng thu từ tài xế (VND)")
    driver_earning = models.PositiveIntegerField(default=0, help_text="Tài xế nhận = fare - commission (VND)")
    payment_method = models.CharField(max_length=20, default='cash')
    # When the current search for a driver started (reset when a driver cancels).
    dispatched_at = models.DateTimeField(null=True, blank=True)

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
        constraints = [
            # Enforced by the DB so two concurrent requests can't both succeed.
            models.UniqueConstraint(
                fields=['customer'], condition=Q(status__in=('PENDING', 'ACCEPTED', 'ARRIVED', 'IN_PROGRESS')),
                name='one_active_ride_per_customer',
            ),
            models.UniqueConstraint(
                fields=['driver'], condition=Q(status__in=('ACCEPTED', 'ARRIVED', 'IN_PROGRESS')),
                name='one_active_ride_per_driver',
            ),
        ]
        indexes = [models.Index(fields=['status', 'vehicle_type'])]

    def __str__(self):
        return f"Cuốc #{self.id} - {self.status}"


class RideOffer(BaseModel):
    """
    A ride offered to one driver, who has a few seconds to accept or decline.

    The dispatcher (core/dispatch.py) offers a PENDING ride to the nearest free
    drivers in small batches. A driver gets at most one open offer at a time and
    is never offered the same ride twice.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Đang chờ'),
        ('ACCEPTED', 'Đã nhận'),
        ('DECLINED', 'Từ chối'),
        ('EXPIRED', 'Hết hạn'),
        ('WITHDRAWN', 'Đã rút'),  # ride taken by someone else or cancelled
    ]

    ride = models.ForeignKey(Ride, on_delete=models.CASCADE, related_name='offers')
    driver = models.ForeignKey(DriverProfile, on_delete=models.CASCADE, related_name='offers')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    distance_m = models.PositiveIntegerField(default=0, help_text="Driver -> pickup at offer time")
    expires_at = models.DateTimeField(db_index=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['ride', 'driver'], name='one_offer_per_ride_driver'),
        ]

    def __str__(self):
        return f"Offer {self.ride_id} -> {self.driver_id} ({self.status})"
