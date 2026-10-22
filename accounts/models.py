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
