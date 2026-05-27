
"""Permission class for the invoices API.

Read access is open to any authenticated tenant member — staff need to
see invoices to do their job. Mutating actions are gated by the
permission catalog (`apps.tenants.permissions`):

    close   → PROCESS_PAYMENT   (owner / manager / front_desk by default)
    reopen  → REOPEN_INVOICE    (owner / manager only; locked against
                                 per-user override — separation of duties,
                                 see ADR 0007)
    void    → VOID_INVOICE      (owner / manager by default)

Generic create/update/destroy on `/api/invoices/` is **disallowed** —
invoices come into existence via the appointment-creation signal and
mutate only through the named action endpoints. This keeps the audit
trail consistent (the actions write structured `AuditLog` entries; a
plain `PATCH` would not).
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


class InvoicePermission(BasePermission):
    READ_ACTIONS = frozenset({'list', 'retrieve', 'pdf'})
    DISALLOWED_ACTIONS = frozenset({'create', 'update', 'partial_update', 'destroy'})

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        action = view.action

        if action in self.DISALLOWED_ACTIONS:
            # Generic CRUD is intentionally not supported — see module docstring.
            return False

        if action in self.READ_ACTIONS:
            return True

        if action == 'close':
            return membership.has(P.PROCESS_PAYMENT)
        if action == 'reopen':
            return membership.has(P.REOPEN_INVOICE)
        if action == 'void':
            return membership.has(P.VOID_INVOICE)
        if action == 'email':
            # Same role group as PROCESS_PAYMENT — owner / manager /
            # front_desk. Emailing the customer is a customer-facing
            # operational action: front desk handles "they lost their
            # receipt, send another copy" as routine work. Marketing,
            # bookkeeper, provider don't have this on their job.
            return membership.has(P.PROCESS_PAYMENT)
        # Adding/removing lines on an open invoice + redeeming
        # credits from a customer's purchased package. Front-desk
        # hand-builds the customer's tab during checkout (Phase 2A
        # POS), so PROCESS_PAYMENT is the right gate — same role
        # group that closes the invoice.
        if action in {
            'create_standalone',
            'add_line',
            'remove_line',
            'redeem_from_package',
            'redeem_from_membership',
            'add_custom_package',
            'add_gift_card_sale',
            'apply_gift_card',
            'reverse_gift_card_redemption',
        }:
            return membership.has(P.PROCESS_PAYMENT)
        # Price + discount edits. PROCESS_PAYMENT is the baseline "can
        # touch this invoice at all" gate; the action body then enforces
        # EDIT_INVOICE_PRICE OR a valid owner/manager credential
        # override before persisting the change.
        if action in {'edit_line', 'set_discount'}:
            return membership.has(P.PROCESS_PAYMENT)

        return False

    def has_object_permission(self, request, view, obj):
        # Tenant-isolation: the queryset is already filtered by tenant
        # via `for_current_tenant()`, so any object the view returns
        # belongs to the request's tenant. Belt + suspenders here.
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        return obj.tenant_id == membership.tenant_id
