from django.conf import settings
from django.db import models

from core.models import BaseModel


class Customer(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer'
    )
    phone = models.CharField(max_length=12, unique=True)
    full_name = models.CharField(max_length=150)

    def __str__(self):
        return f'{self.full_name} ({self.phone})'


class PhoneOTP(BaseModel):
    """
    One-time code sent by SMS to prove a phone number (sign-up, password reset).

    Only a keyed hash of the code is stored. See accounts/otp.py for the rules
    (expiry, resend cooldown, attempt limit).
    """
    PURPOSE_CHOICES = [('register', 'Đăng ký'), ('reset_password', 'Đặt lại mật khẩu')]
    ROLE_CHOICES = [('customer', 'Khách hàng'), ('driver', 'Tài xế')]

    phone = models.CharField(max_length=12, db_index=True)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['phone', 'purpose', 'role', '-created_at'])]

    def __str__(self):
        return f'OTP {self.purpose}/{self.role} {self.phone}'
