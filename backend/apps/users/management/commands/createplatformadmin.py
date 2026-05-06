"""Bootstrap a platform admin account.

Mirrors Django's stock `createsuperuser` but creates a user with
`is_platform_admin=True` and verifies the account ends up disjoint
from any tenant memberships.

Usage:
    python manage.py createplatformadmin --email max@voxtro.io
    # then enters password interactively

Or non-interactive (for CI / one-shot scripts):
    python manage.py createplatformadmin --email max@voxtro.io --password "$PWD" --noinput

Refuses to elevate an existing user who already has tenant
memberships — the customer and platform worlds are deliberately
disjoint, see apps.users.views.PlatformLoginView.
"""

import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a platform admin account (separate from tenant users).'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True, help='Email for the platform admin account.')
        parser.add_argument('--password', help='Password (interactive prompt if omitted).')
        parser.add_argument('--first-name', default='', help='Optional first name.')
        parser.add_argument('--last-name', default='', help='Optional last name.')
        parser.add_argument(
            '--noinput', '--no-input',
            action='store_false',
            dest='interactive',
            help='Skip interactive prompts.',
        )

    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        if not email:
            raise CommandError('Email is required.')

        existing = User.objects.filter(email__iexact=email).first()
        if existing:
            # Refuse to mutate an existing user with tenant memberships
            # into a platform admin — the worlds must stay disjoint.
            if existing.memberships.exists():
                raise CommandError(
                    f'User {email} has {existing.memberships.count()} tenant '
                    'membership(s). Platform admins must have zero memberships. '
                    'Pick a different email or delete the memberships first.',
                )
            if existing.is_platform_admin:
                self.stdout.write(self.style.WARNING(
                    f'User {email} is already a platform admin. Nothing to do.',
                ))
                return
            # An existing user with no memberships — fine to elevate.

        password = options.get('password')
        if not password:
            if not options['interactive']:
                raise CommandError('--password is required when --noinput is set.')
            while True:
                password = getpass.getpass('Password: ')
                confirm = getpass.getpass('Password (again): ')
                if password != confirm:
                    self.stderr.write('Passwords do not match. Try again.')
                    continue
                if len(password) < 10:
                    self.stderr.write('Password must be at least 10 characters.')
                    continue
                break

        with transaction.atomic():
            if existing:
                existing.set_password(password)
                existing.is_platform_admin = True
                # Don't auto-grant is_superuser — that's for Django admin
                # access, distinct from platform admin. Operator can flip
                # it explicitly if they need /admin/.
                existing.first_name = options.get('first_name') or existing.first_name
                existing.last_name = options.get('last_name') or existing.last_name
                existing.save()
                user = existing
                created = False
            else:
                user = User.objects.create_user(
                    email=email,
                    password=password,
                    first_name=options.get('first_name', ''),
                    last_name=options.get('last_name', ''),
                    is_platform_admin=True,
                )
                created = True

        verb = 'Created' if created else 'Elevated'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} platform admin: {user.email} (id={user.id})',
        ))
        self.stdout.write(
            'They can sign in at /platform/login (NOT the regular /login).',
        )
