import uuid

import django.db.models.deletion
from django.db import migrations, models

VEHICLE_CHOICES = [('bike', 'GoBike (xe máy)'), ('car4', 'GoCar 4 chỗ'), ('car7', 'GoCar 7 chỗ')]


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_fill_driver_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='driverprofile',
            name='phone',
            field=models.CharField(help_text='Số điện thoại (+84...)', max_length=12, unique=True),
        ),
        migrations.AlterField(
            model_name='driverprofile',
            name='vehicle_type',
            field=models.CharField(choices=VEHICLE_CHOICES, db_index=True, default='bike', max_length=10),
        ),
        migrations.AddField(
            model_name='driverprofile',
            name='vehicle_name',
            field=models.CharField(blank=True, default='', help_text='VD: Honda Vision · Đỏ', max_length=100),
        ),
        migrations.AddField(
            model_name='driverprofile',
            name='location_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='driverprofile',
            name='rating',
            field=models.FloatField(default=5.0),
        ),
        # --- Route ---------------------------------------------------------
        migrations.CreateModel(
            name='Route',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('mode', models.CharField(help_text='Geoapify mode: motorcycle / drive', max_length=20)),
                ('from_lat', models.FloatField()),
                ('from_lng', models.FloatField()),
                ('to_lat', models.FloatField()),
                ('to_lng', models.FloatField()),
                ('distance_m', models.PositiveIntegerField()),
                ('duration_s', models.PositiveIntegerField()),
                ('geometry', models.JSONField(help_text='GeoJSON LineString, toạ độ [lng, lat]')),
                ('provider', models.CharField(choices=[('geoapify', 'Geoapify'), ('straight_line', 'Đường thẳng (dự phòng)')], default='geoapify', max_length=20)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('mode', 'from_lat', 'from_lng', 'to_lat', 'to_lng'), name='unique_route_endpoints')],
            },
        ),
        # --- Ride ----------------------------------------------------------
        migrations.RenameField(model_name='ride', old_name='pickup_location', new_name='pickup_address'),
        migrations.RenameField(model_name='ride', old_name='dropoff_location', new_name='dropoff_address'),
        migrations.AlterModelOptions(
            name='ride',
            options={'ordering': ['-created_at'], 'verbose_name': 'Ride', 'verbose_name_plural': 'Rides'},
        ),
        migrations.AddField(
            model_name='ride',
            name='vehicle_type',
            field=models.CharField(choices=VEHICLE_CHOICES, default='bike', max_length=10),
        ),
        # Old rows had no coordinates; 0 marks them as unknown.
        migrations.AddField(model_name='ride', name='pickup_lat', field=models.FloatField(default=0), preserve_default=False),
        migrations.AddField(model_name='ride', name='pickup_lng', field=models.FloatField(default=0), preserve_default=False),
        migrations.AddField(model_name='ride', name='dropoff_lat', field=models.FloatField(default=0), preserve_default=False),
        migrations.AddField(model_name='ride', name='dropoff_lng', field=models.FloatField(default=0), preserve_default=False),
        migrations.AddField(
            model_name='ride',
            name='route',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='rides', to='core.route'),
        ),
        migrations.AddField(
            model_name='ride',
            name='approach_route',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approach_rides', to='core.route'),
        ),
        migrations.AddField(model_name='ride', name='distance_m', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='ride', name='duration_s', field=models.PositiveIntegerField(default=0)),
        migrations.AlterField(
            model_name='ride',
            name='fare',
            field=models.PositiveIntegerField(help_text='Cước phí chuyến đi (VND)'),
        ),
        migrations.AddField(model_name='ride', name='payment_method', field=models.CharField(default='cash', max_length=20)),
        migrations.AlterField(
            model_name='ride',
            name='status',
            field=models.CharField(choices=[('PENDING', 'Chờ tài xế'), ('ACCEPTED', 'Đã nhận cuốc'), ('ARRIVED', 'Tài xế đã đến điểm đón'), ('IN_PROGRESS', 'Đang chở khách'), ('COMPLETED', 'Hoàn thành'), ('CANCELLED', 'Đã hủy')], db_index=True, default='PENDING', max_length=20),
        ),
        migrations.AddField(model_name='ride', name='accepted_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='ride', name='arrived_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='ride', name='started_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='ride', name='completed_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='ride', name='cancelled_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(
            model_name='ride',
            name='cancelled_by',
            field=models.CharField(blank=True, choices=[('customer', 'Khách hàng'), ('driver', 'Tài xế'), ('system', 'Hệ thống')], default='', max_length=10),
        ),
        migrations.AddField(model_name='ride', name='cancel_reason', field=models.CharField(blank=True, default='', max_length=255)),
        migrations.AddField(
            model_name='ride',
            name='rating',
            field=models.PositiveSmallIntegerField(blank=True, help_text='Khách đánh giá tài xế (1-5)', null=True),
        ),
        migrations.AddField(model_name='ride', name='rating_comment', field=models.CharField(blank=True, default='', max_length=500)),
        ]
