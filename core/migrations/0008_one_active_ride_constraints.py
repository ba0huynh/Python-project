from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0007_seed_fare_rules_and_clean_rides')]

    operations = [
        migrations.AddConstraint(
            model_name='ride',
            constraint=models.UniqueConstraint(
                condition=models.Q(('status__in', ('PENDING', 'ACCEPTED', 'ARRIVED', 'IN_PROGRESS'))),
                fields=('customer',), name='one_active_ride_per_customer',
            ),
        ),
        migrations.AddConstraint(
            model_name='ride',
            constraint=models.UniqueConstraint(
                condition=models.Q(('status__in', ('ACCEPTED', 'ARRIVED', 'IN_PROGRESS'))),
                fields=('driver',), name='one_active_ride_per_driver',
            ),
        ),
    ]
