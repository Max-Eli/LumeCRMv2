"""Permission catalog and role-based resolver for tenant memberships.

Permissions are flat string identifiers. Each role has a default set of permissions.
A `TenantMembership` can grant extra permissions or revoke role defaults per user.

Usage:
    membership.has(P.VOID_INVOICE)          # → True/False
    has_permission(membership, P.VOID_INVOICE)
"""


class P:
    """Permission catalog. Add new permissions here as features land."""

    # Tenant management
    MANAGE_BILLING = 'manage_billing'
    MANAGE_TENANT_SETTINGS = 'manage_tenant_settings'
    DELETE_TENANT = 'delete_tenant'

    # Staff
    MANAGE_STAFF = 'manage_staff'
    VIEW_STAFF_PAYROLL_ALL = 'view_staff_payroll_all'
    VIEW_STAFF_PAYROLL_OWN = 'view_staff_payroll_own'

    # Clients
    VIEW_CLIENT_LIST = 'view_client_list'
    VIEW_CLIENT_PHI = 'view_client_phi'
    EDIT_CLIENT_RECORD = 'edit_client_record'
    DELETE_CLIENT_RECORD = 'delete_client_record'

    # Appointments
    BOOK_APPOINTMENT = 'book_appointment'
    RESCHEDULE_ANY_APPOINTMENT = 'reschedule_any_appointment'
    RESCHEDULE_OWN_APPOINTMENT = 'reschedule_own_appointment'
    CANCEL_APPOINTMENT = 'cancel_appointment'

    # Charts / clinical
    VIEW_CHART = 'view_chart'
    SIGN_CHART = 'sign_chart'
    EDIT_SIGNED_CHART = 'edit_signed_chart'

    # Financials
    PROCESS_PAYMENT = 'process_payment'
    ISSUE_REFUND = 'issue_refund'
    ISSUE_REFUND_UNLIMITED = 'issue_refund_unlimited'
    VOID_INVOICE = 'void_invoice'
    # Editing line-item prices and adding line / invoice discounts
    # changes recognized revenue. Owner + manager default; lower roles
    # must obtain a manager override (verified email + password of an
    # owner / manager on the same tenant) on the API call. Audit
    # captures both the acting user and the authorizer (SOC 2 PI1.1
    # + HIPAA §164.312(b)).
    EDIT_INVOICE_PRICE = 'edit_invoice_price'
    # Reopening a closed (paid) invoice — gated to owner/manager only and
    # locked against per-user override (separation-of-duties; ADR 0007).
    # Time-bounded to 60 days from first close; window enforced in
    # `Invoice.reopen()`, not in this catalog.
    REOPEN_INVOICE = 'reopen_invoice'
    VIEW_FINANCIAL_REPORTS = 'view_financial_reports'
    EXPORT_ACCOUNTING_DATA = 'export_accounting_data'

    # Reports — category gates for the reports module (ADR 0013).
    # Financial + Marketing reuse the existing perms above; the three
    # below are new. Per-report permissions were considered and rejected:
    # category-level matches how operators reason about who-sees-what.
    VIEW_STAFF_REPORTS = 'view_staff_reports'
    VIEW_GUEST_REPORTS = 'view_guest_reports'
    VIEW_OPERATIONS_REPORTS = 'view_operations_reports'

    # Configuration
    MANAGE_SERVICES = 'manage_services'
    MANAGE_PACKAGES_MEMBERSHIPS = 'manage_packages_memberships'
    MANAGE_FORMS = 'manage_forms'
    MANAGE_NOTIFICATIONS = 'manage_notifications'
    # Connect / disconnect external integrations (Meta channels:
    # Facebook Page Messenger, Instagram Business DMs, WhatsApp
    # Business). Touches OAuth tokens with broad scope, so locked
    # against per-user override — must come from role.
    MANAGE_INTEGRATIONS = 'manage_integrations'

    # Marketing
    SEND_MARKETING_CAMPAIGN = 'send_marketing_campaign'
    VIEW_AUDIENCE_SEGMENTS = 'view_audience_segments'
    VIEW_MARKETING_REPORTS = 'view_marketing_reports'


ALL_PERMISSIONS = frozenset(
    v for k, v in vars(P).items() if not k.startswith('_') and isinstance(v, str)
)


# Permissions that cannot be granted via per-user override — must come from role only.
# Prevents an Owner from accidentally granting "delete tenant" to a Front Desk user.
# Locked entries enforce separation-of-duties at the permission layer.
LOCKED_PERMISSIONS = frozenset({
    P.DELETE_TENANT,
    P.MANAGE_BILLING,
    # Reopening a closed (paid) invoice changes recognized revenue. SOC 2
    # change-management requires this be a role-level capability, not
    # something a manager can grant ad-hoc to front-desk staff.
    P.REOPEN_INVOICE,
    # Connecting external integrations grants OAuth tokens with broad
    # scope into the tenant's data — must come from role, not a per-
    # user override that a manager could grant casually.
    P.MANAGE_INTEGRATIONS,
})


ROLE_DEFAULTS = {
    'owner': ALL_PERMISSIONS,

    'manager': ALL_PERMISSIONS - {
        P.MANAGE_BILLING,
        P.DELETE_TENANT,
    },

    'front_desk': frozenset({
        P.VIEW_CLIENT_LIST,
        P.EDIT_CLIENT_RECORD,
        P.BOOK_APPOINTMENT,
        P.RESCHEDULE_ANY_APPOINTMENT,
        P.CANCEL_APPOINTMENT,
        P.PROCESS_PAYMENT,
        P.ISSUE_REFUND,  # within limit; ISSUE_REFUND_UNLIMITED requires manager+
        P.VIEW_AUDIENCE_SEGMENTS,
        P.VIEW_OPERATIONS_REPORTS,  # day-of-business view: status / no-show / cancel rates
        P.VIEW_STAFF_PAYROLL_OWN,
    }),

    'provider': frozenset({
        P.VIEW_CLIENT_LIST,
        P.VIEW_CLIENT_PHI,
        P.VIEW_CHART,
        P.SIGN_CHART,
        P.BOOK_APPOINTMENT,
        P.RESCHEDULE_OWN_APPOINTMENT,
        P.VIEW_STAFF_PAYROLL_OWN,
    }),

    'bookkeeper': frozenset({
        P.VIEW_FINANCIAL_REPORTS,
        P.EXPORT_ACCOUNTING_DATA,
        P.VIEW_STAFF_REPORTS,  # revenue per provider feeds payroll/commission reconciliation
        P.VIEW_STAFF_PAYROLL_OWN,
    }),

    'marketing': frozenset({
        P.SEND_MARKETING_CAMPAIGN,
        P.VIEW_AUDIENCE_SEGMENTS,
        P.VIEW_MARKETING_REPORTS,
        P.VIEW_GUEST_REPORTS,  # birthday lists, inactive-client lists, top spenders
        P.VIEW_CLIENT_LIST,
        P.VIEW_STAFF_PAYROLL_OWN,
    }),
}


def has_permission(membership, permission: str) -> bool:
    """Resolve effective permission for a TenantMembership.

    Inactive memberships have no permissions.
    Effective set = (role defaults ∪ extra_permissions) − revoked_permissions.
    Locked permissions cannot be granted via extra_permissions; they must come from role.
    """
    if not membership.is_active:
        return False

    role_perms = ROLE_DEFAULTS.get(membership.role, frozenset())
    extras = set(membership.extra_permissions or [])
    revoked = set(membership.revoked_permissions or [])

    extras -= LOCKED_PERMISSIONS

    effective = (role_perms | extras) - revoked
    return permission in effective
