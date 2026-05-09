"""
Tests for `lume_crm/logging.py`.

PHI scrubbing is a HIPAA technical safeguard — a regression here is a
breach-notification event. Cover every pattern + the structured-extra
path explicitly. Each test is one assertion: fail loud, fail fast.
"""

import logging
from io import StringIO

from django.test import SimpleTestCase

from lume_crm.logging import PHIScrubFilter, scrub_text


# ── Pattern coverage ────────────────────────────────────────────────


class ScrubTextRegexTests(SimpleTestCase):
    def test_email_replaced(self):
        self.assertEqual(
            scrub_text('user alice@example.com signed in'),
            'user [REDACTED:email] signed in',
        )

    def test_phone_replaced_dashed(self):
        self.assertEqual(
            scrub_text('call 555-555-1234'),
            'call [REDACTED:phone]',
        )

    def test_phone_replaced_parens(self):
        self.assertEqual(
            scrub_text('call (555) 555-1234 today'),
            'call [REDACTED:phone] today',
        )

    def test_phone_replaced_country_code(self):
        self.assertEqual(
            scrub_text('+1 555 555 1234'),
            '[REDACTED:phone]',
        )

    def test_dob_iso_replaced(self):
        self.assertEqual(
            scrub_text('dob=1985-04-21 in chart'),
            'dob=[REDACTED:dob] in chart',
        )

    def test_dob_us_slash_replaced(self):
        self.assertEqual(
            scrub_text('born 4/21/1985.'),
            'born [REDACTED:dob].',
        )

    def test_iso_datetime_not_treated_as_dob(self):
        # 2026-05-07T10:30:00 is a timestamp, not a DOB. The regex
        # negative-lookahead on `T` keeps it intact.
        self.assertEqual(
            scrub_text('event at 2026-05-07T10:30:00 UTC'),
            'event at 2026-05-07T10:30:00 UTC',
        )

    def test_ssn_replaced(self):
        self.assertEqual(
            scrub_text('ssn=123-45-6789'),
            'ssn=[REDACTED:ssn]',
        )


# ── End-to-end through a real logger ────────────────────────────────


class LoggingPipelineTests(SimpleTestCase):
    """Verify the filter mutates the record in place when wired to a logger."""

    def _capture(self, fmt='%(message)s'):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(fmt))
        handler.addFilter(PHIScrubFilter())
        logger = logging.getLogger('lume_crm.test_logging.pipeline')
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        return logger, stream

    def test_msg_string_scrubbed(self):
        logger, stream = self._capture()
        logger.info('user bob@example.com hit the API')
        self.assertEqual(
            stream.getvalue().strip(),
            'user [REDACTED:email] hit the API',
        )

    def test_positional_args_scrubbed(self):
        logger, stream = self._capture()
        logger.info('user %s with phone %s', 'bob@example.com', '555-555-1234')
        self.assertEqual(
            stream.getvalue().strip(),
            'user [REDACTED:email] with phone [REDACTED:phone]',
        )

    def test_extra_phi_keys_redacted(self):
        # `extra={'first_name': 'Alice'}` — the value is a free-form
        # name (not regex-matchable as PHI) so only key-based redaction
        # keeps it out of the log line.
        logger, stream = self._capture(fmt='%(message)s|%(first_name)s')
        logger.info('event', extra={'first_name': 'Alice'})
        self.assertEqual(stream.getvalue().strip(), 'event|[REDACTED]')

    def test_extra_non_phi_key_passes_through(self):
        # `extra={'tenant_slug': 'acmespa'}` — tenant slug is operational
        # metadata and should NOT be redacted. This guards against an
        # over-eager filter bricking observability.
        logger, stream = self._capture(fmt='%(message)s|%(tenant_slug)s')
        logger.info('event', extra={'tenant_slug': 'acmespa'})
        self.assertEqual(stream.getvalue().strip(), 'event|acmespa')

    def test_exc_text_scrubbed(self):
        logger, stream = self._capture(fmt='%(message)s|%(exc_text)s')
        try:
            raise ValueError('lookup failed for alice@example.com')
        except ValueError:
            logger.exception('boom')
        out = stream.getvalue()
        self.assertNotIn('alice@example.com', out)
        self.assertIn('[REDACTED:email]', out)
