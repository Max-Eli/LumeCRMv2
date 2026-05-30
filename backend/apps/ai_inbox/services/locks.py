"""DB-backed per-conversation reply lock.

No Redis in this project — we use Postgres row-level locks via
``select_for_update`` to serialize concurrent dispatches for the
same (tenant, customer) pair. The lock is automatically released
at transaction commit / rollback.

The 30s reply-gap window is enforced HERE in addition to the
guardrail layer — guardrails check before the lock is taken;
this check is the source-of-truth inside the locked critical
section.
"""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone as djtz

from apps.ai_inbox.models import AIConversation

if TYPE_CHECKING:
    from apps.customers.models import Customer
    from apps.tenants.models import Tenant


MIN_REPLY_GAP_SECONDS = 30


class ReplyLockBusy(Exception):
    """Raised when the per-conversation reply lock detects another reply within the gap window."""


@contextmanager
def reply_lock(tenant: 'Tenant', customer: 'Customer'):
    """Open a row-level lock on the AIConversation for this (tenant, customer).

    Yields the locked AIConversation row. Caller must do its work
    + commit within the with-block — the lock releases at exit.

    Raises ReplyLockBusy if last_ai_at is within the gap window
    (defense in depth — also checked by guardrails before lock entry).
    """
    with transaction.atomic():
        conversation = (
            AIConversation.objects
            .select_for_update()
            .get(tenant=tenant, customer=customer)
        )
        if conversation.last_ai_at is not None:
            gap = djtz.now() - conversation.last_ai_at
            if gap < dt.timedelta(seconds=MIN_REPLY_GAP_SECONDS):
                raise ReplyLockBusy(
                    f'reply_lock_busy seconds_since_last_ai={gap.total_seconds():.1f}'
                )
        yield conversation
