import uuid
from django.db import models
from django.contrib.auth.models import User


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
    license_number = models.CharField(max_length=50, unique=True, help_text="Số bằng lái xe")
    vehicle_plate = models.CharField(max_length=20, help_text="Biển số xe")
    vehicle_type = models.CharField(max_length=50, default='Xe máy công nghệ')
    is_approved = models.BooleanField(default=False, help_text="Trạng thái duyệt của Admin")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OFFLINE', db_index=True)
    current_latitude = models.FloatField(null=True, blank=True, help_text="Vĩ độ GPS hiện tại")
    current_longitude = models.FloatField(null=True, blank=True, help_text="Kinh độ GPS hiện tại")

    class Meta:
        verbose_name = "Driver Profile"
        verbose_name_plural = "Driver Profiles"

    def __str__(self):
        return f"Tài xế {self.user.username} - {self.status}"


class Ride(BaseModel):
    """
    Model quản lý thông tin chuyến đi đặt xe.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Chờ tài xế'),
        ('ACCEPTED', 'Đã nhận cuốc'),
        ('IN_PROGRESS', 'Đang chở khách'),
        ('COMPLETED', 'Hoàn thành'),
        ('CANCELLED', 'Đã hủy'),
    ]

    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='customer_rides')
    driver = models.ForeignKey(DriverProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='driver_rides')
    pickup_location = models.CharField(max_length=255, help_text="Điểm đón")
    dropoff_location = models.CharField(max_length=255, help_text="Điểm trả")
    fare = models.DecimalField(max_digits=12, decimal_places=2, help_text="Cước phí chuyến đi")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)

    class Meta:
        verbose_name = "Ride"
        verbose_name_plural = "Rides"

    def __str__(self):
        return f"Cuốc #{self.id} - {self.status}"