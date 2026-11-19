"""
Data step between the schema change (0006) and the new constraints (0008):
- create the initial FareRule rows (prices editable in /admin afterwards),
- give old rides their earning split (no commission was charged then),
- leave at most one active ride per customer / driver so 0008 can add the
  unique constraints.
"""
from decimal import Decimal

from django.db import migrations
from django.db.models import F
from django.utils import timezone

DEFAULT_RULES = [
    ('bike', 'GoBike', 1, 12_000, 2, 4_500, 12_000, 20),
    ('car4', 'GoCar 4 chỗ', 4, 25_000, 2, 9_000, 25_000, 20),
    ('car7', 'GoCar 7 chỗ', 7, 30_000, 2, 11_000, 30_000, 20),
]
CUSTOMER_ACTIVE = ('PENDING', 'ACCEPTED', 'ARRIVED', 'IN_PROGRESS')
DRIVER_ACTIVE = ('ACCEPTED', 'ARRIVED', 'IN_PROGRESS')


def forwards(apps, schema_editor):
    FareRule = apps.get_model('core', 'FareRule')
    Ride = apps.get_model('core', 'Ride')

    for vt, name, seats, base, base_km, per_km, minimum, pct in DEFAULT_RULES:
        FareRule.objects.get_or_create(vehicle_type=vt, defaults={
            'display_name': name, 'seats': seats, 'base_fare': base, 'base_km': Decimal(base_km),
            'per_km': per_km, 'minimum_fare': minimum, 'commission_percent': Decimal(pct),
        })

    Ride.objects.filter(driver_earning=0).update(driver_earning=F('fare'))
    Ride.objects.filter(status='PENDING', dispatched_at__isnull=True).update(dispatched_at=F('created_at'))

    now = timezone.now()

    def cancel_extras(field, statuses):
        seen = set()
        for ride in Ride.objects.filter(status__in=statuses, **{f'{field}__isnull': False}).order_by('-created_at'):
            key = getattr(ride, f'{field}_id')
            if key in seen:
                ride.status = 'CANCELLED'
                ride.cancelled_by = 'system'
                ride.cancel_reason = 'Đóng tự động khi nâng cấp hệ thống.'
                ride.cancelled_at = now
                ride.save(update_fields=['status', 'cancelled_by', 'cancel_reason', 'cancelled_at'])
            seen.add(key)

    cancel_extras('customer', CUSTOMER_ACTIVE)
    cancel_extras('driver', DRIVER_ACTIVE)


class Migration(migrations.Migration):
    dependencies = [('core', '0006_fare_rules_and_offers')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
