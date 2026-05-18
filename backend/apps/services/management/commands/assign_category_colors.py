"""Assign distinct colors to ServiceCategory rows that still carry
the default grey `#6b7280` color.

Useful after a bulk import (e.g. Zenoti migration) where categories
land with the model default. Once colors are assigned the calendar's
appointment blocks render with each category's accent instead of
falling back to the grey placeholder.

Idempotent: only categories with the default-grey color are
touched. Operator-edited categories are left alone. Re-runs are
safe.

Palette: a hand-curated set of medspa-friendly colors keyed by
keyword in the category name (so Injectables get warm reds,
Laser-related categories get blues, Facials get greens, etc.).
Anything not matching a keyword cycles through a generic palette
so two unknown categories never end up with the same color.

Usage:

    # All tenants.
    python manage.py assign_category_colors

    # Single tenant.
    python manage.py assign_category_colors --tenant demo

    # Show what would change without writing.
    python manage.py assign_category_colors --dry-run

    # Force re-color every category (overwrite operator edits).
    # Avoid this unless you know what you're doing.
    python manage.py assign_category_colors --force
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.services.models import ServiceCategory


# The Django model's default value. Any category still on this color
# is treated as "never customized" and is safe to overwrite.
DEFAULT_GREY = '#6b7280'


# Keyword → color. Lowercase substring match against `category.name`.
# Order matters — first hit wins (so "Laser Facial" picks up the
# Laser color, not the Facial one).
KEYWORD_COLORS: list[tuple[str, str]] = [
    ('injectable', '#dc2626'),     # red — Botox, Filler, etc.
    ('botox', '#dc2626'),
    ('filler', '#dc2626'),
    ('pdo', '#b91c1c'),
    ('juvederm', '#ef4444'),
    ('laser hair', '#2563eb'),     # blue — laser hair removal
    ('laser facial', '#06b6d4'),   # cyan — laser facials specifically
    ('laser', '#3b82f6'),
    ('cool', '#0ea5e9'),           # coolsculpting
    ('emsculpt', '#0284c7'),
    ('facial', '#10b981'),         # green — facials
    ('skin', '#16a34a'),
    ('microneedling', '#84cc16'),
    ('body', '#f59e0b'),           # amber — body treatments
    ('massage', '#f97316'),        # orange — massage
    ('wellness', '#fb923c'),
    ('iv', '#fbbf24'),
    ('hair therapy', '#a855f7'),   # purple — hair therapy / PRP
    ('permanent make', '#ec4899'), # pink — permanent makeup
    ('eyelash', '#f472b6'),
    ('nail', '#d946ef'),           # magenta — nails
    ('tattoo', '#64748b'),         # slate
    ('ultherapy', '#8b5cf6'),      # violet
    ('consult', '#94a3b8'),        # cool grey-blue — consultations
    ('promo', '#fcd34d'),          # yellow — promotions
]

# Fallback rotation for categories that don't hit any keyword.
FALLBACK_PALETTE = [
    '#6366f1', '#8b5cf6', '#a855f7', '#d946ef',
    '#ec4899', '#f43f5e', '#f97316', '#eab308',
    '#84cc16', '#22c55e', '#10b981', '#14b8a6',
    '#06b6d4', '#0ea5e9', '#3b82f6', '#6366f1',
]


class Command(BaseCommand):
    help = 'Assign distinct colors to ServiceCategory rows that still have the default grey color.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', type=str, default=None)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--force', action='store_true',
            help='Recolor every category, even those already customized.',
        )

    def handle(self, *args, **opts):
        qs = ServiceCategory.objects.all()
        if opts['tenant']:
            qs = qs.filter(tenant__slug=opts['tenant'])
        if not opts['force']:
            qs = qs.filter(color=DEFAULT_GREY)

        total = qs.count()
        self.stdout.write(self.style.NOTICE(
            f'Found {total} category/categories to color '
            f'(force={opts["force"]}, dry_run={opts["dry_run"]})'
        ))

        # Per-tenant fallback cursor so unknown categories cycle without
        # bleed across tenants.
        per_tenant_cursor: dict[int, int] = {}
        changed = 0
        for cat in qs.select_related('tenant'):
            new_color = _pick_color(
                name=cat.name,
                tenant_cursor=per_tenant_cursor.setdefault(cat.tenant_id, 0),
            )
            per_tenant_cursor[cat.tenant_id] += 1
            if new_color == cat.color:
                continue
            self.stdout.write(
                f'  {cat.tenant.slug:20s} {cat.name:30s} {cat.color} → {new_color}'
            )
            if not opts['dry_run']:
                cat.color = new_color
                cat.save(update_fields=['color'])
            changed += 1

        self.stdout.write('')
        if opts['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                f'DRY-RUN complete. Would update {changed}.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Done. Updated {changed} category color(s).'
            ))


def _pick_color(*, name: str, tenant_cursor: int) -> str:
    """Match keyword first; fall back to a cycling palette."""
    lower = (name or '').lower()
    for keyword, color in KEYWORD_COLORS:
        if keyword in lower:
            return color
    return FALLBACK_PALETTE[tenant_cursor % len(FALLBACK_PALETTE)]
