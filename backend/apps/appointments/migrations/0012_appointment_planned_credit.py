"""Planned credit redemption on Appointment.

Adds two nullable FKs — `planned_package_item` and
`planned_subscription_item` — so the front desk can book a service
"from" a customer's package or membership. This records INTENT only;
the credit is decremented at checkout, not at booking. A check
constraint enforces that at most one of the two is set.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0011_appointmentservice_provider'),
        ('packages', '0002_purchasedpackage_import_provenance'),
        ('memberships', '0002_subscription_import_provenance'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='planned_package_item',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='packages.purchasedpackageitem',
                help_text='Package credit the front desk plans to apply at checkout.',
            ),
        ),
        migrations.AddField(
            model_name='appointment',
            name='planned_subscription_item',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='memberships.subscriptionitem',
                help_text='Membership credit the front desk plans to apply at checkout.',
            ),
        ),
        migrations.AddConstraint(
            model_name='appointment',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('planned_package_item__isnull', True),
                    ('planned_subscription_item__isnull', True),
                    _connector='OR',
                ),
                name='appointments_single_planned_credit',
            ),
        ),
    ]
