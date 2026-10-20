import uuid
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


class SampleEntity(BaseModel):
    """
    Starter entity model demonstrating Django ORM models with migrations and seeding.
    This can be easily renamed, customized, or replaced once project requirements are defined.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived'),
    ]

    title = models.CharField(max_length=255, help_text="Title or name of the entity")
    description = models.TextField(blank=True, default="", help_text="Detailed description")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', db_index=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True, help_text="Flexible key-value payload")

    class Meta:
        verbose_name = "Sample Entity"
        verbose_name_plural = "Sample Entities"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.status})"
