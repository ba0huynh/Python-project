from django.db import migrations


def fill_driver_fields(apps, schema_editor):
    """Old rows stored free-text vehicle types and had no phone/name."""
    DriverProfile = apps.get_model('core', 'DriverProfile')
    for driver in DriverProfile.objects.select_related('user'):
        text = (driver.vehicle_type or '').lower()
        driver.vehicle_type = 'car7' if '7' in text else 'car4' if ('ô tô' in text or 'car' in text) else 'bike'
        driver.phone = driver.user.username.removeprefix('driver:')[:12] or f'legacy{str(driver.pk)[:6]}'
        driver.full_name = driver.user.get_full_name() or driver.user.username
        driver.save(update_fields=['vehicle_type', 'phone', 'full_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_driver_contact_fields'),
    ]

    operations = [
        migrations.RunPython(fill_driver_fields, migrations.RunPython.noop),
    ]
