from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_driverprofile_ride_delete_sampleentity'),
    ]

    operations = [
        # --- DriverProfile -------------------------------------------------
        migrations.AddField(
            model_name='driverprofile',
            name='phone',
            field=models.CharField(max_length=12, null=True, help_text='Số điện thoại (+84...)'),
        ),
        migrations.AddField(
            model_name='driverprofile',
            name='full_name',
            field=models.CharField(default='', max_length=150),
        ),
    ]
