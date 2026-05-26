"""Permission class for the appointments API.

Read access is open to any authenticated tenant member — every staff role needs
the calendar to do their job. Mutating actions are gated:

    create        ─► BOOK_APPOINTMENT
    update        ─► RESCHEDULE_ANY_APPOINTMENT (or RESCHEDULE_OWN if it's their own)
    partial_update─► same
    destroy       ─► CANCEL_APPOINTMENT

For v1, "own appointment" means `appointment.provider == request.tenant_membership`.
The full RESCHEDULE_OWN ownership check lives in `has_object_permission`.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


class AppointmentPermission(BasePermission):
    READ_ACTIONS = frozenset({'list', 'retrieve', 'activity'})

    # Editing the services on an appointment (add / change / remove) is
    # gated like a reschedule — it changes what was booked. Grouped with
    # update / partial_update so the same ownership fallback applies.
    EDIT_ACTIONS = frozenset({
        'update', 'partial_update',
        'add_service', 'change_service', 'remove_extra_service',
    })

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        if view.action in self.READ_ACTIONS:
            return True

        if view.action == 'create':
            return membership.has(P.BOOK_APPOINTMENT)
        if view.action == 'destroy':
            return membership.has(P.CANCEL_APPOINTMENT)
        if view.action in self.EDIT_ACTIONS:
            # Allow the action — narrower ownership check lives in has_object_permission.
            return membership.has(P.RESCHEDULE_ANY_APPOINTMENT) or membership.has(
                P.RESCHEDULE_OWN_APPOINTMENT,
            )
        return False

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        if view.action in self.READ_ACTIONS:
            return True

        if view.action in self.EDIT_ACTIONS:
            if membership.has(P.RESCHEDULE_ANY_APPOINTMENT):
                return True
            # Fall back to ownership: only the assigned provider can reschedule their own.
            return membership.has(P.RESCHEDULE_OWN_APPOINTMENT) and obj.provider_id == membership.id

        return True


class TimeBlockPermission(BasePermission):
    """Permission gate for the time-block API.

    Block-outs are operational scheduling, not a billable event, so we
    piggyback on the same permission codes as appointments rather than
    inventing parallel ones:

        list / retrieve  ─► any authenticated tenant member
        create           ─► BOOK_APPOINTMENT
        update           ─► RESCHEDULE_ANY (or RESCHEDULE_OWN if it's
                                            their own block)
        destroy          ─► CANCEL_APPOINTMENT (or RESCHEDULE_OWN if
                                                their own block — a
                                                provider can clear
                                                their own lunch)
    """

    READ_ACTIONS = frozenset({'list', 'retrieve'})

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        if view.action in self.READ_ACTIONS:
            return True

        if view.action == 'create':
            return membership.has(P.BOOK_APPOINTMENT)
        if view.action == 'destroy':
            return (
                membership.has(P.CANCEL_APPOINTMENT)
                or membership.has(P.RESCHEDULE_OWN_APPOINTMENT)
            )
        if view.action in {'update', 'partial_update'}:
            return (
                membership.has(P.RESCHEDULE_ANY_APPOINTMENT)
                or membership.has(P.RESCHEDULE_OWN_APPOINTMENT)
            )
        return False

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        if view.action in self.READ_ACTIONS:
            return True

        if view.action in {'update', 'partial_update'}:
            if membership.has(P.RESCHEDULE_ANY_APPOINTMENT):
                return True
            return (
                membership.has(P.RESCHEDULE_OWN_APPOINTMENT)
                and obj.provider_id == membership.id
            )

        if view.action == 'destroy':
            if membership.has(P.CANCEL_APPOINTMENT):
                return True
            return (
                membership.has(P.RESCHEDULE_OWN_APPOINTMENT)
                and obj.provider_id == membership.id
            )

        return True
