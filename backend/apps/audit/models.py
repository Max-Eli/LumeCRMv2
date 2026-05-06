"""HIPAA-aligned audit log.

Required by HIPAA Security Rule §164.312(b) "Audit controls". Records who did
what when across the system. Designed as append-only — entries are never
modified or deleted at the application level. Production will additionally
enforce immutability via a Postgres trigger that rejects UPDATE/DELETE.

Indexes are tuned for the common access patterns:
  - "show me what tenant X did in the last 30 days" → (tenant, -timestamp)
  - "show me everything user Y touched" → (user, -timestamp)
  - "who looked at this customer record" → (resource_type, resource_id)
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = 'create', 'Create'
        READ = 'read', 'Read'
        UPDATE = 'update', 'Update'
        DELETE = 'delete', 'Delete'
        LOGIN = 'login', 'Login'
        LOGOUT = 'logout', 'Logout'
        LOGIN_FAILED = 'login_failed', 'Login Failed'
        EXPORT = 'export', 'Export'
        PERMISSION_GRANTED = 'permission_granted', 'Permission Granted'
        PERMISSION_REVOKED = 'permission_revoked', 'Permission Revoked'

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    resource_type = models.CharField(max_length=100, blank=True, help_text='e.g. customer, invoice, appointment')
    resource_id = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['tenant', '-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['resource_type', 'resource_id']),
            models.Index(fields=['action', '-timestamp']),
        ]

    def __str__(self):
        who = self.user.email if self.user else 'anonymous'
        return f"{self.timestamp:%Y-%m-%d %H:%M:%S} [{self.action}] {who}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError('AuditLog entries are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('AuditLog entries cannot be deleted.')
