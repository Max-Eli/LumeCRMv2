"""
Liveness + readiness endpoints.

Two endpoints, each answering a different operational question:

  /healthz/live    — am I a Python process that responds to HTTP?
                     Used by ECS task health checks ("is the container
                     alive, or do I need to restart it?"). Always 200
                     unless the process is genuinely dead. NEVER touches
                     the database — a transient RDS blip should NOT
                     trigger a task restart loop.

  /healthz         — am I ready to serve traffic? Hits the database
                     with a SELECT 1. Used by the ALB target group to
                     decide "should this task get traffic?" — a slow
                     DB or migrations-in-progress task gets pulled out
                     of rotation without being killed.

Both endpoints are unauthenticated by design (ALB and ECS can't carry
session cookies), and both leak nothing but their own status. Don't
extend either to surface internal version, environment, or secret
metadata — these endpoints are public from the moment we attach a
load-balancer.
"""

from __future__ import annotations

from django.db import DatabaseError, connections
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET


@csrf_exempt
@require_GET
@never_cache
def liveness(_request):
    """200 if the process can respond. Never touches the database."""
    return JsonResponse({'status': 'alive'})


@csrf_exempt
@require_GET
@never_cache
def readiness(_request):
    """200 only when the database is reachable.

    Returns 503 with `{"status": "not-ready", "reason": "database"}` on
    a failed `SELECT 1`. ALB pulls the task out of rotation, ECS does
    NOT restart it (that's `liveness`'s job).
    """
    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse(
            {'status': 'not-ready', 'reason': 'database'},
            status=503,
        )
    return JsonResponse({'status': 'ready'})
