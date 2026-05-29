"""Stamp every Tenant that exists at migration time as grandfathered.

Self-serve pricing tiers (Starter / Pro / Enterprise) + Stripe Billing
land in 0013. Tenants created BEFORE that — the original launch spas
onboarded manually — never went through Stripe and were never quoted a
public price. They have to keep operating exactly as they did, which
means:

  - status is not touched (could be TRIAL or ACTIVE — leave alone)
  - plan is set to PRO so they have the full feature set they're used to
  - grandfathered=True so:
      * capacity gates (max_staff / max_locations) skip them
      * the upgrade banner never renders for them
      * they're never enrolled in Stripe Billing
      * dunning jobs ignore them
  - stripe_customer_id / stripe_subscription_id stay empty (no Stripe
    relationship)

New tenants (created via self-serve signup after this point) start with
``grandfathered=False`` and go through the normal signup flow that
populates plan + Stripe IDs.

This migration is idempotent and additive — it only sets values on rows
where ``grandfathered`` is still the default (False) AND ``plan`` is
still the default (TRIAL). If somehow a row already has those set,
we leave it alone.
"""

from django.db import migrations


def grandfather_existing(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    # We can't import the model's TextChoices classes from inside a
    # migration (Django warns against it), so use the raw string values.
    qs = Tenant.objects.filter(grandfathered=False, plan='trial')
    qs.update(plan='pro', grandfathered=True)


def reverse_grandfather(apps, schema_editor):
    # Best-effort reverse: only un-set rows that match the exact state
    # we'd have produced (PRO + grandfathered). Anything else was
    # changed after this migration and shouldn't be touched.
    Tenant = apps.get_model('tenants', 'Tenant')
    qs = Tenant.objects.filter(grandfathered=True, plan='pro')
    qs.update(plan='trial', grandfathered=False)


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0013_add_billing_plan_addon_fields'),
    ]

    operations = [
        migrations.RunPython(grandfather_existing, reverse_grandfather),
    ]
