"""HTTP client for the Zenoti REST API.

The client is intentionally thin — auth + pagination + rate-limit
backoff. Per-entity logic lives in `mappers.py` (transforms) and
`importer.py` (orchestration). Keeping the client dumb means we can
swap it for a different vendor's client without touching the
business logic.

Auth: API-key only (`Authorization: apikey <KEY>`). Token-based
(employee credentials → JWT) is the other Zenoti pattern; we don't
use it because a long-lived migration that depends on an employee's
password staying valid is fragile.

Pagination: Zenoti uses `?page=<N>&size=<N>` with `size <= 100`.
Most list endpoints return `{"<entity_plural>": [...], "page_info":
{...}}`. The `paginate()` helper yields each row, fetching the next
page when the current one is exhausted.

Rate limit: Zenoti's standard tier allows 60 calls/minute. When we
hit a 429 we honour any `Retry-After` header, otherwise back off
exponentially up to a cap. The retry loop is bounded so a sustained
429 storm fails the run instead of looping forever.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Iterator

import requests

logger = logging.getLogger(__name__)


# ── Constants ───────────────────────────────────────────────────────


BASE_URL = 'https://api.zenoti.com/v1'

# Per Zenoti docs: max 100 records per page. We use the max so a
# 7000-customer migration is 70 round-trips, not 700.
DEFAULT_PAGE_SIZE = 100

# Bounds on backoff. We hit 60 calls/min ceiling on the standard
# tier; one over and Zenoti starts returning 429. The first retry
# is short because most 429s clear inside a single window; later
# retries scale up.
INITIAL_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 60.0
MAX_RETRIES = 5

# Soft per-request timeout — Zenoti reports of multi-minute hangs
# on rare slow endpoints. 60s is generous but bounded.
REQUEST_TIMEOUT_SECONDS = 60.0


# ── Errors ──────────────────────────────────────────────────────────


class ZenotiAPIError(Exception):
    """Any non-2xx response from Zenoti that we don't recover from."""

    def __init__(self, status_code: int, body: Any, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ZenotiAuthError(ZenotiAPIError):
    """401 / 403 — credentials rejected or insufficient permissions.
    Different from a transient 5xx because retrying won't help; the
    fix lives in the Zenoti console (rotate key, grant permissions).
    """


class ZenotiRateLimitExceeded(ZenotiAPIError):
    """429 returned after we exhausted our retry budget. Indicates
    the run is consistently slower than the API quota — the
    importer should pause + resume rather than crash."""


# ── Client ──────────────────────────────────────────────────────────


@dataclass
class ZenotiClient:
    """Thin HTTP wrapper around the Zenoti REST API.

    Construct one per import run — the session pool is cheap to
    spin up, and per-run construction means the credentials lifetime
    is bounded by the run rather than by the process. The caller
    pulls the API key from AWS Secrets Manager and passes it in;
    the client never knows about Secrets Manager.
    """

    api_key: str
    base_url: str = BASE_URL
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS
    user_agent: str = 'Lume-CRM-Importer/1.0'

    def __post_init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            'Authorization': f'apikey {self.api_key}',
            'Accept': 'application/json',
            'User-Agent': self.user_agent,
        })

    # ── Low-level: one HTTP call with retry/backoff ────────────────

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> Any:
        """Make a single API call. Returns parsed JSON. Raises one
        of the typed errors above on failure."""
        url = f'{self.base_url}/{path.lstrip("/")}'
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(MAX_RETRIES):
            try:
                response = self._session.request(
                    method, url,
                    params=params, json=json,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as e:
                # Network-layer failure (DNS, connection, read timeout).
                # Treat as retriable up to the budget; on exhaustion
                # surface a typed error so the caller can fail the run.
                if attempt == MAX_RETRIES - 1:
                    raise ZenotiAPIError(
                        status_code=0, body=None,
                        message=f'Network error after {MAX_RETRIES} retries: {e}',
                    ) from e
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

            # Success.
            if 200 <= response.status_code < 300:
                if not response.content:
                    return None
                try:
                    return response.json()
                except ValueError:
                    return response.text

            # Auth / authorization — no point retrying.
            if response.status_code in (401, 403):
                raise ZenotiAuthError(
                    status_code=response.status_code,
                    body=_safe_json(response),
                    message=(
                        f'{method} {path} rejected: {response.status_code} '
                        f'{response.text[:300]}'
                    ),
                )

            # Rate limit — honour Retry-After if present.
            if response.status_code == 429:
                retry_after = _parse_retry_after(response)
                wait = retry_after if retry_after is not None else backoff
                logger.warning(
                    'zenoti.rate_limited',
                    extra={
                        'path': path,
                        'attempt': attempt + 1,
                        'wait_seconds': wait,
                    },
                )
                if attempt == MAX_RETRIES - 1:
                    raise ZenotiRateLimitExceeded(
                        status_code=429,
                        body=_safe_json(response),
                        message='Rate limit exhausted after retries.',
                    )
                time.sleep(wait)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

            # 5xx — server-side, retriable.
            if 500 <= response.status_code < 600:
                if attempt == MAX_RETRIES - 1:
                    raise ZenotiAPIError(
                        status_code=response.status_code,
                        body=_safe_json(response),
                        message=(
                            f'{method} {path} 5xx after {MAX_RETRIES} '
                            f'retries: {response.text[:300]}'
                        ),
                    )
                logger.warning(
                    'zenoti.server_error',
                    extra={
                        'path': path,
                        'status': response.status_code,
                        'attempt': attempt + 1,
                    },
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

            # 4xx that isn't auth or rate-limit — surface to caller.
            raise ZenotiAPIError(
                status_code=response.status_code,
                body=_safe_json(response),
                message=(
                    f'{method} {path} returned {response.status_code}: '
                    f'{response.text[:300]}'
                ),
            )

        # Shouldn't reach here — every code path either returned or
        # raised. Defensive only.
        raise ZenotiAPIError(
            status_code=0, body=None,
            message='Retry loop exited without success or error.',
        )

    # ── High-level: paginated iteration ────────────────────────────

    def paginate(
        self,
        path: str,
        *,
        results_key: str,
        params: dict | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Iterator[dict]:
        """Yield one row at a time from a paginated list endpoint.

        Caller specifies `results_key` because Zenoti uses different
        plural keys per resource (`guests`, `appointments`, etc.).
        Stops when the current page has fewer rows than `page_size`,
        which is Zenoti's signal that we hit the end.
        """
        page = 1
        params = dict(params or {})
        while True:
            params.update({'page': page, 'size': page_size})
            payload = self.request('GET', path, params=params)
            rows = (payload or {}).get(results_key, []) if isinstance(payload, dict) else []
            if not rows:
                return
            for row in rows:
                yield row
            if len(rows) < page_size:
                return
            page += 1

    # ── Convenience wrappers (thin) ────────────────────────────────

    def get(self, path: str, *, params: dict | None = None) -> Any:
        return self.request('GET', path, params=params)


# ── Helpers ────────────────────────────────────────────────────────


def _safe_json(response: requests.Response):
    try:
        return response.json()
    except ValueError:
        return None


def _parse_retry_after(response: requests.Response) -> float | None:
    """Standard `Retry-After` is either an integer seconds value or
    an HTTP-date. We honour the seconds form; an HTTP-date is rare
    enough we fall through to the regular backoff."""
    raw = response.headers.get('Retry-After')
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
