"""Copy inbound social-DM media to our S3 before Meta's URLs expire.

Meta hosts attachments (photos, videos, voice clips, files) on their
CDN for ~24 hours after delivery, then 404s. A spa that doesn't
triage a client's "here's what I want" photo within a day would
lose it forever. PHI compliance posture also demands long-term
retention with auditable access.

This module:
  - Downloads each URL from `SocialMessage.media_urls` (one per line)
  - Uploads to Django's `default_storage`, which is wired to S3 with
    SSE-KMS in prod (`STORAGES` in settings/prod.py) and to the
    local filesystem in dev
  - Stores the resulting storage keys on
    `SocialMessage.archived_media_keys` (one per line, same order)

On read, `_serialise_message` in views.py prefers the archived keys
+ generates short-lived signed URLs via `default_storage.url()`,
falling back to the Meta URL list when archives haven't been
written (e.g. before this module shipped, or when archive failed).

Sync today; will move to a background worker (Celery / Django-RQ)
once message volume warrants it. The hot path is webhook ingestion
which can tolerate a ~1-2s extra latency per attachment without
Meta retrying.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from urllib.parse import urlparse

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)


# Max bytes we'll accept per file before bailing. Meta-hosted media
# is usually under 5MB but voice clips can run larger. 25MB cap is
# above typical IG message limits + below S3 PutObject simple-upload
# threshold; larger files will be skipped + logged for later
# investigation.
MAX_BYTES_PER_FILE = 25 * 1024 * 1024


def archive_message_media(msg) -> int:
    """Download each Meta media URL on `msg` and store in S3.

    Returns the number of files successfully archived. Failures are
    logged + the original Meta URL stays in `media_urls` as the
    fallback render path.
    """
    raw_urls = [u for u in (msg.media_urls or '').splitlines() if u.strip()]
    if not raw_urls:
        return 0

    keys: list[str] = []
    for index, url in enumerate(raw_urls):
        try:
            key = _archive_one(msg, url, index)
        except Exception as e:
            logger.warning(
                'integrations.meta.archive_one_failed',
                extra={
                    'message_id': msg.pk,
                    'media_index': index,
                    'error': str(e)[:300],
                },
            )
            continue
        if key:
            keys.append(key)

    if keys:
        msg.archived_media_keys = '\n'.join(keys)
        msg.save(update_fields=['archived_media_keys', 'updated_at'])
    return len(keys)


def _archive_one(msg, url: str, index: int) -> str | None:
    """Download a single URL → upload to default_storage → return the key.

    Returns None if the file is too large or the response isn't a
    fetchable media body (HTML error page, etc.).
    """
    response = requests.get(url, timeout=15, stream=True)
    if response.status_code != 200:
        logger.info(
            'integrations.meta.media_url_not_fetchable',
            extra={
                'message_id': msg.pk,
                'media_index': index,
                'status': response.status_code,
            },
        )
        return None

    # Use Content-Length if Meta provides it; otherwise stream + check.
    declared = response.headers.get('Content-Length')
    if declared and int(declared) > MAX_BYTES_PER_FILE:
        logger.info(
            'integrations.meta.media_too_large_skipped',
            extra={
                'message_id': msg.pk,
                'declared_bytes': declared,
            },
        )
        return None

    data = response.content
    if len(data) > MAX_BYTES_PER_FILE:
        logger.info(
            'integrations.meta.media_too_large_after_download',
            extra={'message_id': msg.pk, 'bytes': len(data)},
        )
        return None

    # Derive a stable storage key — tenant prefix scopes per-tenant
    # bucket access if we ever split, and per-message subdir keeps a
    # thread's media co-located for ops triage.
    ext = _infer_extension(response, url)
    key = (
        f'social-media/'
        f'{msg.tenant_id}/'
        f'{msg.thread_id}/'
        f'{msg.pk}-{index}{ext}'
    )
    saved_name = default_storage.save(key, ContentFile(data))
    return saved_name


def _infer_extension(response: requests.Response, url: str) -> str:
    """Guess a file extension from the response Content-Type, falling
    back to the URL path. Returns '' if nothing reliable; S3 doesn't
    require an extension."""
    content_type = (response.headers.get('Content-Type') or '').split(';')[0].strip()
    if content_type:
        guess = mimetypes.guess_extension(content_type)
        if guess:
            return guess
    # Fall back: extract from the URL path before query string.
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext or ''
