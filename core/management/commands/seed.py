import random
from datetime import timedelta

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Customer
from core.models import DriverProfile, Ride

User = get_user_model()
PASSWORD = 'GoXe!2026'

CUSTOMERS_DATA = [
    {'phone': '+84912345678', 'full_name': 'Nguyễn Văn An'},
    {'phone': '+84987654321', 'full_name': 'Nguyễn Thị Mai'},
    {'phone': '+84903112233', 'full_name': 'Trần Minh Đức'},
    {'phone': '+84908223344', 'full_name': 'Lê Thị Thu Trang'},
    {'phone': '+84915334455', 'full_name': 'Phạm Hoàng Nam'},
    {'phone': '+84918445566', 'full_name': 'Võ Quốc Bảo'},
    {'phone': '+84922556677', 'full_name': 'Đặng Thúy Hằng'},
    {'phone': '+84933667788', 'full_name': 'Bùi Anh Tuấn'},
    {'phone': '+84944778899', 'full_name': 'Đỗ Phương Linh'},
    {'phone': '+84966889900', 'full_name': 'Hồ Ngọc Hải'},
    {'phone': '+84977990011', 'full_name': 'Ngô Kim Chi'},
    {'phone': '+84988001122', 'full_name': 'Dương Gia Huy'},
    {'phone': '+84999112233', 'full_name': 'Phan Khánh Ly'},
    {'phone': '+84901234888', 'full_name': 'Vũ Thanh Tùng'},
    {'phone': '+84902345999', 'full_name': 'Trịnh Cẩm Tú'},
]

DRIVERS_DATA = [
    # GoBike (6 drivers)
    {'phone': '+84901234567', 'full_name': 'Trần Văn Bình', 'license_number': 'B1-000001',
     'vehicle_plate': '59X2-123.45', 'vehicle_type': 'bike', 'vehicle_name': 'Honda Vision · Đỏ',
     'is_approved': True, 'status': 'ONLINE', 'lat': 10.7752, 'lng': 106.7010, 'rating': 4.9},
    {'phone': '+84902345678', 'full_name': 'Lê Minh Châu', 'license_number': 'B1-000002',
     'vehicle_plate': '59T1-678.90', 'vehicle_type': 'bike', 'vehicle_name': 'Yamaha Sirius · Xanh',
     'is_approved': True, 'status': 'ONLINE', 'lat': 10.7701, 'lng': 106.6952, 'rating': 4.8},
    {'phone': '+84903344556', 'full_name': 'Nguyễn Hữu Đạt', 'license_number': 'B1-000003',
     'vehicle_plate': '59K3-345.67', 'vehicle_type': 'bike', 'vehicle_name': 'Honda AirBlade · Đen nhám',
     'is_approved': True, 'status': 'BUSY', 'lat': 10.7780, 'lng': 106.6920, 'rating': 4.7},
    {'phone': '+84904455667', 'full_name': 'Phan Trọng Khang', 'license_number': 'B1-000004',
     'vehicle_plate': '59M2-567.89', 'vehicle_type': 'bike', 'vehicle_name': 'Honda Wave Alpha · Trắng',
     'is_approved': True, 'status': 'ONLINE', 'lat': 10.7650, 'lng': 106.6890, 'rating': 4.6},
    {'phone': '+84905566778', 'full_name': 'Đinh Văn Lâm', 'license_number': 'B1-000005',
     'vehicle_plate': '59P1-890.12', 'vehicle_type': 'bike', 'vehicle_name': 'Yamaha Exciter · Xanh GP',
     'is_approved': True, 'status': 'OFFLINE', 'lat': 10.7820, 'lng': 106.7050, 'rating': 4.5},
    {'phone': '+84906677889', 'full_name': 'Hoàng Văn Phúc (Pending)', 'license_number': 'B1-000006',
     'vehicle_plate': '59S2-234.56', 'vehicle_type': 'bike', 'vehicle_name': 'Honda Future · Xám',
     'is_approved': False, 'status': 'OFFLINE', 'lat': None, 'lng': None, 'rating': 5.0},

    # GoCar 4 Seats (5 drivers)
    {'phone': '+84907788990', 'full_name': 'Phạm Quốc Dũng', 'license_number': 'B2-000010',
     'vehicle_plate': '51G-246.80', 'vehicle_type': 'car4', 'vehicle_name': 'Toyota Vios · Trắng',
     'is_approved': True, 'status': 'ONLINE', 'lat': 10.7768, 'lng': 106.7031, 'rating': 4.9},
    {'phone': '+84908899001', 'full_name': 'Bùi Thế Hiển', 'license_number': 'B2-000011',
     'vehicle_plate': '51H-357.91', 'vehicle_type': 'car4', 'vehicle_name': 'Hyundai Accent · Đen',
     'is_approved': True, 'status': 'ONLINE', 'lat': 10.7845, 'lng': 106.7110, 'rating': 4.8},
    {'phone': '+84909900112', 'full_name': 'Lý Tuấn Kiệt', 'license_number': 'B2-000012',
     'vehicle_plate': '51K-468.02', 'vehicle_type': 'car4', 'vehicle_name': 'VinFast VF5 · Xanh dương',
     'is_approved': True, 'status': 'BUSY', 'lat': 10.7712, 'lng': 106.6985, 'rating': 4.7},
    {'phone': '+84910011223', 'full_name': 'Đỗ Thành Long', 'license_number': 'B2-000013',
     'vehicle_plate': '51F-579.13', 'vehicle_type': 'car4', 'vehicle_name': 'Honda City · Bạc',
     'is_approved': True, 'status': 'OFFLINE', 'lat': 10.7680, 'lng': 106.6940, 'rating': 4.6},
    {'phone': '+84911122334', 'full_name': 'Mai Văn Nghĩa (Pending)', 'license_number': 'B2-000014',
     'vehicle_plate': '51E-680.24', 'vehicle_type': 'car4', 'vehicle_name': 'Kia Morning · Đỏ',
     'is_approved': False, 'status': 'OFFLINE', 'lat': None, 'lng': None, 'rating': 5.0},

    # GoCar 7 Seats (4 drivers)
    {'phone': '+84912233445', 'full_name': 'Võ Thị Hạnh', 'license_number': 'B2-000020',
     'vehicle_plate': '51H-135.79', 'vehicle_type': 'car7', 'vehicle_name': 'Mitsubishi Xpander · Bạc',
     'is_approved': True, 'status': 'ONLINE', 'lat': 10.7731, 'lng': 106.6990, 'rating': 4.9},
    {'phone': '+84913344556', 'full_name': 'Trương Công Phước', 'license_number': 'B2-000021',
     'vehicle_plate': '51G-864.20', 'vehicle_type': 'car7', 'vehicle_name': 'Toyota Innova Cross · Trắng',
     'is_approved': True, 'status': 'ONLINE', 'lat': 10.7810, 'lng': 106.7025, 'rating': 4.8},
    {'phone': '+84914455667', 'full_name': 'Cao Văn Sang', 'license_number': 'B2-000022',
     'vehicle_plate': '51K-975.31', 'vehicle_type': 'car7', 'vehicle_name': 'Toyota Veloz Cross · Đen',
     'is_approved': True, 'status': 'BUSY', 'lat': 10.7695, 'lng': 106.7040, 'rating': 4.6},
    {'phone': '+84915566778', 'full_name': 'Nguyễn Tấn Tài', 'license_number': 'B2-000023',
     'vehicle_plate': '51F-086.42', 'vehicle_type': 'car7', 'vehicle_name': 'Ford Everest · Xám titan',
     'is_approved': True, 'status': 'ONLINE', 'lat': 10.7760, 'lng': 106.6965, 'rating': 4.7},
]

LOCATIONS = [
    ('Chợ Bến Thành, Quận 1', 10.7725, 106.6981),
    ('Landmark 81, Bình Thạnh', 10.7950, 106.7219),
    ('Phố đi bộ Nguyễn Huệ, Quận 1', 10.7740, 106.7035),
    ('Sân bay Tân Sơn Nhất, Tân Bình', 10.8185, 106.6588),
    ('Nhà thờ Đức Bà, Quận 1', 10.7798, 106.6990),
    ('Đại học Bách Khoa TP.HCM, Quận 10', 10.7726, 106.6578),
    ('Bitexco Financial Tower, Quận 1', 10.7716, 106.7044),
    ('Thảo Cầm Viên, Quận 1', 10.7875, 106.7053),
    ('Crescent Mall, Quận 7', 10.7296, 106.7196),
    ('Vạn Hạnh Mall, Quận 10', 10.7705, 106.6710),
]

FEEDBACK_SAMPLES = {
    5: [
        'Tài xế lái xe cẩn thận, rất nhiệt tình và chu đáo.',
        'Xe sạch sẽ thơm tho, tài xế chào hỏi lịch sự.',
        'Đến đón đúng giờ, phong cách phục vụ 5 sao!',
        'Chuyến đi êm ái, an toàn, tài xế vui vẻ.',
    ],
    4: [
        'Dịch vụ tốt, chạy đúng tuyến đường quy định.',
        'Bác tài thân thiện, lái xe an toàn.',
        'Xe tương đối sạch sẽ, hài lòng.',
    ],
    3: [
        'Tài xế đi hơi gấp, có phanh gấp vài lần.',
        'Đến điểm đón trễ khoảng 5 phút.',
    ],
    2: [
        'Tài xế nói chuyện cộc cằn, thái độ không nhiệt tình.',
        'Xe có mùi thuốc lá hơi khó chịu.',
    ],
    1: [
        'Tài xế đi lòng vòng cố tình kéo dài quãng đường tính tiền.',
        'Thái độ phục vụ rất tệ, cáu gắt với hành khách.',
    ],
}

CANCEL_REASONS = [
    ('customer', 'Khách đổi kế hoạch, không còn nhu cầu di chuyển'),
    ('customer', 'Thời gian chờ tài xế quá lâu (>10 phút)'),
    ('driver', 'Xe bị sự cố thủng lốp đột xuất'),
    ('driver', 'Khu vực đón kẹt xe nghiêm trọng không tiếp cận được'),
    ('system', 'Hết thời gian tìm kiếm tài xế phù hợp'),
]


class Command(BaseCommand):
    help = 'Seeds a comprehensive, realistic demo database for GoXe Admin (password: GoXe!2026)'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Clean existing customers, drivers, and rides first')

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('=== Starting GoXe Database Seeding ==='))

        seeded_customer_phones = [c['phone'] for c in CUSTOMERS_DATA]
        seeded_driver_phones = [d['phone'] for d in DRIVERS_DATA]
        driver_usernames = [f"driver:{p}" for p in seeded_driver_phones]

        if options['clear']:
            self.stdout.write('Clearing existing demo data...')
            # Delete rides
            Ride.objects.all().delete()
            # Clear old admin log entries for a fresh start
            LogEntry.objects.all().delete()
            # Delete seeded users
            User.objects.filter(username__in=seeded_customer_phones + driver_usernames).delete()
            self.stdout.write(self.style.WARNING('Cleared existing rides, logs, and demo users.'))

        # 1. Create Customers
        created_customers = []
        for c in CUSTOMERS_DATA:
            user, created = User.objects.get_or_create(username=c['phone'])
            if created:
                user.set_password(PASSWORD)
                user.first_name = c['full_name']
                user.save()
            customer, _ = Customer.objects.update_or_create(
                user=user,
                defaults={'phone': c['phone'], 'full_name': c['full_name']}
            )
            created_customers.append((user, customer))
        self.stdout.write(self.style.SUCCESS(f'Created {len(created_customers)} Customers.'))

        # 2. Create Drivers
        created_drivers = []
        for d in DRIVERS_DATA:
            user, created = User.objects.get_or_create(
                username=f"driver:{d['phone']}",
                defaults={'first_name': d['full_name']}
            )
            if created:
                user.set_password(PASSWORD)
                user.save()
            driver, _ = DriverProfile.objects.update_or_create(
                user=user,
                defaults={
                    'phone': d['phone'],
                    'full_name': d['full_name'],
                    'license_number': d['license_number'],
                    'vehicle_plate': d['vehicle_plate'],
                    'vehicle_type': d['vehicle_type'],
                    'vehicle_name': d['vehicle_name'],
                    'is_approved': d['is_approved'],
                    'status': d['status'],
                    'current_latitude': d['lat'],
                    'current_longitude': d['lng'],
                    'location_updated_at': timezone.now() if d['lat'] else None,
                    'rating': d['rating'],
                }
            )
            created_drivers.append(driver)
        self.stdout.write(self.style.SUCCESS(f'Created {len(created_drivers)} Drivers (including pending reviews).'))

        # 3. Create 40 Realistic Rides
        self.stdout.write('Generating 40 realistic rides across services and date ranges...')
        approved_drivers = [d for d in created_drivers if d.is_approved]
        now = timezone.now()

        # Generate timestamps spread over the last 10 days
        base_days = [
            now - timedelta(days=9, hours=random.randint(1, 8)),
            now - timedelta(days=8, hours=random.randint(1, 8)),
            now - timedelta(days=7, hours=random.randint(1, 8)),
            now - timedelta(days=6, hours=random.randint(1, 8)),
            now - timedelta(days=5, hours=random.randint(1, 8)),
            now - timedelta(days=4, hours=random.randint(1, 8)),
            now - timedelta(days=3, hours=random.randint(1, 8)),
            now - timedelta(days=2, hours=random.randint(1, 8)),
            now - timedelta(days=1, hours=random.randint(1, 8)),
            now - timedelta(hours=random.randint(2, 6)),
            now - timedelta(minutes=random.randint(10, 45)),
        ]

        rides_to_create = []

        # 26 Completed rides with varied fares, ratings, and vehicle types
        for i in range(26):
            c_user, _ = random.choice(created_customers)
            driver = random.choice(approved_drivers)
            v_type = driver.vehicle_type

            if v_type == 'bike':
                dist_m = random.choice([1500, 2300, 3400, 4200, 5800, 7200, 8900])
                fare = random.choice([18000, 22000, 28000, 35000, 42000, 52000, 68000])
            elif v_type == 'car4':
                dist_m = random.choice([3200, 4800, 6500, 8400, 11200, 14500])
                fare = random.choice([55000, 68000, 85000, 110000, 145000, 185000])
            else:  # car7
                dist_m = random.choice([4500, 7800, 12000, 16500, 21000])
                fare = random.choice([85000, 125000, 175000, 220000, 290000])

            p_loc, d_loc = random.sample(LOCATIONS, 2)
            ride_time = random.choice(base_days)

            # Rating distribution
            if i < 14:
                star = 5
                comment = random.choice(FEEDBACK_SAMPLES[5])
            elif i < 19:
                star = 4
                comment = random.choice(FEEDBACK_SAMPLES[4])
            elif i < 21:
                star = 3
                comment = random.choice(FEEDBACK_SAMPLES[3])
            elif i < 23:
                star = 2
                comment = random.choice(FEEDBACK_SAMPLES[2])
            elif i < 24:
                star = 1
                comment = random.choice(FEEDBACK_SAMPLES[1])
            else:
                star = None
                comment = ''

            pm = random.choice(['cash', 'cash', 'card', 'wallet'])

            ride = Ride(
                customer=c_user,
                driver=driver,
                vehicle_type=v_type,
                pickup_address=p_loc[0],
                pickup_lat=p_loc[1],
                pickup_lng=p_loc[2],
                dropoff_address=d_loc[0],
                dropoff_lat=d_loc[1],
                dropoff_lng=d_loc[2],
                distance_m=dist_m,
                duration_s=int(dist_m / 6),
                fare=fare,
                payment_method=pm,
                status='COMPLETED',
                rating=star,
                rating_comment=comment,
                created_at=ride_time,
                accepted_at=ride_time + timedelta(seconds=25),
                arrived_at=ride_time + timedelta(minutes=4),
                started_at=ride_time + timedelta(minutes=5),
                completed_at=ride_time + timedelta(minutes=20),
            )
            rides_to_create.append(ride)

        # 6 Cancelled rides
        for i in range(6):
            c_user, _ = random.choice(created_customers)
            driver = random.choice(approved_drivers)
            v_type = driver.vehicle_type
            p_loc, d_loc = random.sample(LOCATIONS, 2)
            c_by, reason = random.choice(CANCEL_REASONS)
            ride_time = random.choice(base_days)
            fare = 25000 if v_type == 'bike' else (65000 if v_type == 'car4' else 95000)

            ride = Ride(
                customer=c_user,
                driver=driver,
                vehicle_type=v_type,
                pickup_address=p_loc[0],
                pickup_lat=p_loc[1],
                pickup_lng=p_loc[2],
                dropoff_address=d_loc[0],
                dropoff_lat=d_loc[1],
                dropoff_lng=d_loc[2],
                distance_m=random.choice([2500, 5000, 7500]),
                duration_s=600,
                fare=fare,
                payment_method='cash',
                status='CANCELLED',
                cancelled_by=c_by,
                cancel_reason=reason,
                created_at=ride_time,
                cancelled_at=ride_time + timedelta(minutes=3),
            )
            rides_to_create.append(ride)

        # 3 In-progress rides
        for i in range(3):
            c_user, _ = random.choice(created_customers)
            driver = random.choice(approved_drivers)
            p_loc, d_loc = random.sample(LOCATIONS, 2)
            ride_time = now - timedelta(minutes=random.randint(5, 15))
            v_type = driver.vehicle_type
            fare = 32000 if v_type == 'bike' else (75000 if v_type == 'car4' else 110000)

            ride = Ride(
                customer=c_user,
                driver=driver,
                vehicle_type=v_type,
                pickup_address=p_loc[0],
                pickup_lat=p_loc[1],
                pickup_lng=p_loc[2],
                dropoff_address=d_loc[0],
                dropoff_lat=d_loc[1],
                dropoff_lng=d_loc[2],
                distance_m=4200,
                duration_s=720,
                fare=fare,
                payment_method='cash',
                status='IN_PROGRESS',
                created_at=ride_time,
                accepted_at=ride_time + timedelta(seconds=20),
                arrived_at=ride_time + timedelta(minutes=3),
                started_at=ride_time + timedelta(minutes=4),
            )
            rides_to_create.append(ride)

        # 2 Accepted rides
        for i in range(2):
            c_user, _ = random.choice(created_customers)
            driver = random.choice(approved_drivers)
            p_loc, d_loc = random.sample(LOCATIONS, 2)
            ride_time = now - timedelta(minutes=random.randint(2, 5))
            v_type = driver.vehicle_type
            fare = 28000 if v_type == 'bike' else 60000

            ride = Ride(
                customer=c_user,
                driver=driver,
                vehicle_type=v_type,
                pickup_address=p_loc[0],
                pickup_lat=p_loc[1],
                pickup_lng=p_loc[2],
                dropoff_address=d_loc[0],
                dropoff_lat=d_loc[1],
                dropoff_lng=d_loc[2],
                distance_m=3500,
                duration_s=600,
                fare=fare,
                payment_method='cash',
                status='ACCEPTED',
                created_at=ride_time,
                accepted_at=ride_time + timedelta(seconds=15),
            )
            rides_to_create.append(ride)

        # 2 Arrived rides (driver arrived at pickup point and waiting for customer)
        for i in range(2):
            c_user, _ = random.choice(created_customers)
            driver = random.choice(approved_drivers)
            p_loc, d_loc = random.sample(LOCATIONS, 2)
            ride_time = now - timedelta(minutes=random.randint(3, 7))
            v_type = driver.vehicle_type
            fare = 26000 if v_type == 'bike' else 58000

            ride = Ride(
                customer=c_user,
                driver=driver,
                vehicle_type=v_type,
                pickup_address=p_loc[0],
                pickup_lat=p_loc[1],
                pickup_lng=p_loc[2],
                dropoff_address=d_loc[0],
                dropoff_lat=d_loc[1],
                dropoff_lng=d_loc[2],
                distance_m=3200,
                duration_s=550,
                fare=fare,
                payment_method='cash',
                status='ARRIVED',
                created_at=ride_time,
                accepted_at=ride_time + timedelta(seconds=20),
                arrived_at=ride_time + timedelta(minutes=2),
            )
            rides_to_create.append(ride)

        # 3 Pending rides
        for i in range(3):
            c_user, _ = random.choice(created_customers)
            p_loc, d_loc = random.sample(LOCATIONS, 2)
            ride_time = now - timedelta(seconds=random.randint(20, 90))
            v_type = random.choice(['bike', 'car4', 'car7'])
            fare = 20000 if v_type == 'bike' else (55000 if v_type == 'car4' else 85000)

            ride = Ride(
                customer=c_user,
                driver=None,
                vehicle_type=v_type,
                pickup_address=p_loc[0],
                pickup_lat=p_loc[1],
                pickup_lng=p_loc[2],
                dropoff_address=d_loc[0],
                dropoff_lat=d_loc[1],
                dropoff_lng=d_loc[2],
                distance_m=3000,
                duration_s=500,
                fare=fare,
                payment_method='cash',
                status='PENDING',
                created_at=ride_time,
            )
            rides_to_create.append(ride)

        Ride.objects.bulk_create(rides_to_create)
        self.stdout.write(self.style.SUCCESS(f'Created {len(rides_to_create)} Rides.'))

        # Ensure demo superuser admin1 exists
        admin_user, created_admin = User.objects.get_or_create(username='admin1')
        if created_admin:
            admin_user.set_password(PASSWORD)
            admin_user.is_superuser = True
            admin_user.is_staff = True
            admin_user.first_name = 'Admin'
            admin_user.save()
            self.stdout.write(self.style.SUCCESS(f'Superuser "admin1" created (password: {PASSWORD}).'))

        self.stdout.write(self.style.SUCCESS(
            f'\n=== Seeding Finished Successfully! ===\n'
            f'- Total Customers: {Customer.objects.count()}\n'
            f'- Total Drivers: {DriverProfile.objects.count()}\n'
            f'- Total Rides: {Ride.objects.count()}\n'
            f'- Password for all accounts: {PASSWORD}\n'
        ))
