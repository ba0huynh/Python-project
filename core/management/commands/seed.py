from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Customer
from core.models import DriverProfile, Ride

User = get_user_model()

PASSWORD = 'GoXe!2026'

CUSTOMERS = [
    {'phone': '+84912345678', 'full_name': 'Nguyễn Văn An'},
    {'phone': '+84987654321', 'full_name': 'Nguyễn Thị Mai'},
]

# Online drivers around Quận 1, HCMC, so a booking near Bến Thành finds them.
DRIVERS = [
    {'phone': '+84901234567', 'full_name': 'Trần Văn Bình', 'license_number': 'B1-000001', 'vehicle_plate': '59X2-123.45',
     'vehicle_type': 'bike', 'vehicle_name': 'Honda Vision · Đỏ', 'lat': 10.7752, 'lng': 106.7010},
    {'phone': '+84902345678', 'full_name': 'Lê Minh Châu', 'license_number': 'B1-000002', 'vehicle_plate': '59T1-678.90',
     'vehicle_type': 'bike', 'vehicle_name': 'Yamaha Sirius · Xanh', 'lat': 10.7701, 'lng': 106.6952},
    {'phone': '+84903456789', 'full_name': 'Phạm Quốc Dũng', 'license_number': 'B2-000003', 'vehicle_plate': '51G-246.80',
     'vehicle_type': 'car4', 'vehicle_name': 'Toyota Vios · Trắng', 'lat': 10.7768, 'lng': 106.7031},
    {'phone': '+84904567890', 'full_name': 'Võ Thị Hạnh', 'license_number': 'B2-000004', 'vehicle_plate': '51H-135.79',
     'vehicle_type': 'car7', 'vehicle_name': 'Mitsubishi Xpander · Bạc', 'lat': 10.7731, 'lng': 106.6990},
]


class Command(BaseCommand):
    help = 'Seed demo customers and online drivers (password for all: GoXe!2026)'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Delete seeded accounts and their rides first')

    @transaction.atomic
    def handle(self, *args, **options):
        usernames = [c['phone'] for c in CUSTOMERS] + [f"driver:{d['phone']}" for d in DRIVERS]
        if options['clear']:
            Ride.objects.filter(customer__username__in=usernames).delete()
            deleted, _ = User.objects.filter(username__in=usernames).delete()
            self.stdout.write(self.style.WARNING(f'Deleted {deleted} seeded objects.'))

        for c in CUSTOMERS:
            user, created = User.objects.get_or_create(username=c['phone'])
            if created:
                user.set_password(PASSWORD)
                user.save()
            Customer.objects.update_or_create(user=user, defaults={'phone': c['phone'], 'full_name': c['full_name']})
            self.stdout.write(f" - customer {c['phone']} ({'created' if created else 'exists'})")

        for d in DRIVERS:
            user, created = User.objects.get_or_create(username=f"driver:{d['phone']}", defaults={'first_name': d['full_name']})
            if created:
                user.set_password(PASSWORD)
                user.save()
            DriverProfile.objects.update_or_create(user=user, defaults={
                'phone': d['phone'], 'full_name': d['full_name'], 'license_number': d['license_number'],
                'vehicle_plate': d['vehicle_plate'], 'vehicle_type': d['vehicle_type'], 'vehicle_name': d['vehicle_name'],
                'is_approved': True, 'status': 'ONLINE', 'current_latitude': d['lat'], 'current_longitude': d['lng'],
                'location_updated_at': timezone.now(),
            })
            self.stdout.write(f" - driver {d['phone']} {d['vehicle_type']} ({'created' if created else 'exists'})")

        self.stdout.write(self.style.SUCCESS(f'Done. Password for every seeded account: {PASSWORD}'))
