"""Field-level encryption for OAuth tokens stored on `Connection`.

The model docstring has promised this since v1; ADR 0027 makes good
on it. Wraps `cryptography.fernet` with a JSON-dict-in / -out shape
matched to the way `Connection.auth_data` is used.

Why Fernet vs AES-GCM-by-hand:

  - Fernet is AES-128-CBC + HMAC-SHA256 in a single audited primitive.
    Saves us from getting the IV/nonce dance wrong (the most common
    crypto footgun).
  - Built into the `cryptography` library Django already depends on
    transitively.
  - Supports key rotation natively via `MultiFernet`, which we use
    so a 60-day token rotation in prod can swap keys without
    invalidating existing tokens.

Why we DON'T use a custom Django field class (`EncryptedJSONField`):

  - SOC 2 posture: a Connection row that gets accidentally
    serialised by admin/DRF/print should leak an opaque ciphertext
    string, NOT a decrypted JSON dict. A custom field class silently
    decrypts in serializers, which is exactly the wrong default.
  - Callers explicitly invoke `connection.auth_data_dict` to get
    plaintext; everywhere else the field is just an opaque string.

Key configuration:

  settings.INTEGRATIONS_FERNET_KEY = '<32-byte url-safe base64>'

In prod, the key comes from Secrets Manager (one-key generation:
`python -c "from cryptography.fernet import Fernet;
print(Fernet.generate_key().decode())"`). In dev it lives in `.env`
with a checked-in deterministic dev key (acceptable — dev encrypts
no real tokens).

Key rotation:

  settings.INTEGRATIONS_FERNET_KEYS = ['<new-key>', '<old-key>']

When this list is set (overrides INTEGRATIONS_FERNET_KEY), encrypt
uses the FIRST key and decrypt tries each in order. Set the new key
first, redeploy, let tokens re-encrypt via OAuth refresh over the
rotation window, then drop the old key.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class EncryptionError(Exception):
    """Raised when encryption or decryption fails. Distinct from
    InvalidToken so callers can catch our wrapper without importing
    cryptography directly."""


_fernet: MultiFernet | None = None


def _get_fernet() -> MultiFernet:
    """Lazily construct the MultiFernet from settings. Cached at
    module level; re-imported during tests via `_reset_fernet()`."""
    global _fernet
    if _fernet is not None:
        return _fernet

    keys = getattr(settings, 'INTEGRATIONS_FERNET_KEYS', None)
    if not keys:
        single_key = getattr(settings, 'INTEGRATIONS_FERNET_KEY', None)
        if not single_key:
            raise ImproperlyConfigured(
                'INTEGRATIONS_FERNET_KEY (or INTEGRATIONS_FERNET_KEYS) is '
                'required to encrypt integration OAuth tokens. Generate one '
                'with: python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        keys = [single_key]

    try:
        ferns = [Fernet(k.encode() if isinstance(k, str) else k) for k in keys]
    except (ValueError, TypeError) as e:
        raise ImproperlyConfigured(
            f'INTEGRATIONS_FERNET_KEY is not a valid Fernet key: {e}. '
            'Must be 32 url-safe base64-encoded bytes.'
        ) from e

    _fernet = MultiFernet(ferns)
    return _fernet


def _reset_fernet() -> None:
    """Test hook — call after overriding INTEGRATIONS_FERNET_KEY in
    a setting override so the cached instance picks up the change."""
    global _fernet
    _fernet = None


def encrypt_auth_data(data: dict[str, Any]) -> str:
    """Serialise + encrypt a JSON-able dict. Returns the ciphertext
    as a URL-safe base64 string suitable for storage in a TextField.

    Empty dict serialises to `{}` and round-trips correctly — we
    don't short-circuit because a "should this be encrypted?" branch
    is exactly the kind of inconsistency that produces leaks."""
    plaintext = json.dumps(data, separators=(',', ':'), sort_keys=True)
    try:
        return _get_fernet().encrypt(plaintext.encode('utf-8')).decode('ascii')
    except Exception as e:
        raise EncryptionError(f'Failed to encrypt auth data: {e}') from e


def decrypt_auth_data(ciphertext: str) -> dict[str, Any]:
    """Decrypt + deserialise. Empty / whitespace input returns `{}`
    so callers don't need to null-check first (matches the
    `Connection.auth_data` "no tokens yet" idiom)."""
    if not ciphertext or not ciphertext.strip():
        return {}
    try:
        plaintext = _get_fernet().decrypt(ciphertext.encode('ascii'))
    except InvalidToken as e:
        raise EncryptionError(
            'Could not decrypt auth data — wrong key, corrupted ciphertext, '
            'or key rotation incomplete.'
        ) from e
    return json.loads(plaintext.decode('utf-8'))


def generate_key() -> str:
    """Convenience for setup runbooks and tests — returns a fresh
    Fernet key as a decoded string ready to drop into env."""
    return Fernet.generate_key().decode('ascii')
