"""Tests for the SES bounce/complaint suppression pipeline (ADR 0029).

Four invariants:

  1. Suppression check is normalised correctly (case, whitespace,
     Gmail +tags) so an opt-out on one form of an address blocks
     all equivalent forms.

  2. SNS signature verification rejects everything that didn't
     come from AWS — bad cert URL, missing fields, tampered
     payload — never raising, always returning False.

  3. The SNS webhook receiver upserts EmailSuppression rows on
     permanent bounces + complaints (idempotent on repeat events,
     never duplicates), logs transient bounces without
     suppressing, and ALWAYS returns 200 even on bad input (per
     ADR 0027 §3 / ADR 0029 — never 4xx the provider).

  4. The custom email backend drops suppressed recipients before
     handing the message to the underlying SES backend, so even a
     callsite that forgot to pre-check is policy-gated.
"""

from __future__ import annotations

import json
from unittest import mock

from django.core.mail import EmailMultiAlternatives
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .deliverability import (
    _normalise_email,
    filter_suppressed_recipients,
    is_suppressed,
    record_bounce,
    record_complaint,
)
from .models import EmailSuppression


# ── _normalise_email ────────────────────────────────────────────────


class NormaliseEmailTests(TestCase):
    def test_lowercases_and_strips(self):
        self.assertEqual(_normalise_email('  Foo@Bar.COM  '), 'foo@bar.com')

    def test_collapses_gmail_plus_tags(self):
        self.assertEqual(_normalise_email('jane+promo@gmail.com'), 'jane@gmail.com')
        self.assertEqual(_normalise_email('jane+promo@googlemail.com'), 'jane@googlemail.com')

    def test_leaves_non_gmail_plus_tags_alone(self):
        # Other providers may route +tags as distinct mailboxes; we
        # only collapse for Gmail where the behaviour is documented.
        self.assertEqual(_normalise_email('jane+promo@example.com'), 'jane+promo@example.com')

    def test_rejects_missing_at(self):
        self.assertEqual(_normalise_email('not-an-email'), '')

    def test_rejects_empty(self):
        self.assertEqual(_normalise_email(''), '')
        self.assertEqual(_normalise_email(None), '')


# ── is_suppressed ───────────────────────────────────────────────────


class IsSuppressedTests(TestCase):
    def test_returns_false_when_no_row(self):
        self.assertFalse(is_suppressed('clean@example.com'))

    def test_returns_true_when_row_exists(self):
        EmailSuppression.objects.create(
            email='dirty@example.com',
            reason=EmailSuppression.Reason.BOUNCE_PERMANENT,
        )
        self.assertTrue(is_suppressed('dirty@example.com'))

    def test_lookup_is_normalised(self):
        EmailSuppression.objects.create(
            email='jane@gmail.com',
            reason=EmailSuppression.Reason.COMPLAINT,
        )
        # +tag form should match the bare form.
        self.assertTrue(is_suppressed('jane+april2026@gmail.com'))
        # Casing + whitespace should match.
        self.assertTrue(is_suppressed('  JANE@gmail.com  '))


# ── record_bounce / record_complaint ────────────────────────────────


class RecordBounceTests(TestCase):
    def test_first_bounce_creates_row(self):
        row = record_bounce(
            email='bouncer@example.com',
            bounce_subtype='General',
            message_id='msg-1',
            raw={'meta': 'forensics'},
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.reason, EmailSuppression.Reason.BOUNCE_PERMANENT)
        self.assertEqual(row.bounce_subtype, 'General')
        self.assertEqual(row.event_count, 1)
        self.assertEqual(row.ses_message_id, 'msg-1')

    def test_repeat_bounce_bumps_event_count(self):
        record_bounce(email='bouncer@example.com', bounce_subtype='General', message_id='msg-1', raw={})
        row = record_bounce(email='bouncer@example.com', bounce_subtype='General', message_id='msg-2', raw={})
        self.assertEqual(row.event_count, 2)
        # Still exactly one row in the table.
        self.assertEqual(EmailSuppression.objects.count(), 1)

    def test_empty_email_returns_none(self):
        self.assertIsNone(record_bounce(email='', bounce_subtype='', message_id='', raw={}))


class RecordComplaintTests(TestCase):
    def test_complaint_creates_row(self):
        row = record_complaint(
            email='angry@example.com',
            complaint_subtype='abuse',
            message_id='msg-1',
            raw={},
        )
        self.assertEqual(row.reason, EmailSuppression.Reason.COMPLAINT)
        self.assertEqual(row.complaint_subtype, 'abuse')

    def test_complaint_promotes_bounce(self):
        # A user can both bounce AND complain on different sends. A
        # later complaint should override an earlier bounce because
        # complaint is the stronger signal (ISP-cooperative).
        record_bounce(email='mixed@example.com', bounce_subtype='General', message_id='msg-1', raw={})
        record_complaint(email='mixed@example.com', complaint_subtype='abuse', message_id='msg-2', raw={})
        row = EmailSuppression.objects.get(email='mixed@example.com')
        self.assertEqual(row.reason, EmailSuppression.Reason.COMPLAINT)
        self.assertEqual(row.complaint_subtype, 'abuse')


# ── filter_suppressed_recipients (the production filtering logic) ───
#
# We test the pure function directly. The SuppressionCheckingSESBackend
# wrapper around it is just `filter_suppressed_recipients(messages)`
# + a `super().send_messages(sendable)` call — django-ses isn't
# installed in dev, so exercising the wrapper end-to-end would need
# the whole SES SDK mocked. Instead we verify the only piece of code
# we wrote (the filter) against the real EmailSuppression table.


class FilterSuppressedRecipientsTests(TestCase):
    def setUp(self):
        EmailSuppression.objects.create(
            email='blocked@example.com',
            reason=EmailSuppression.Reason.BOUNCE_PERMANENT,
        )

    def test_passes_clean_recipient_through(self):
        msg = EmailMultiAlternatives(
            subject='hi', body='hello', from_email='from@x.com',
            to=['clean@example.com'],
        )
        sendable = filter_suppressed_recipients([msg])
        self.assertEqual(len(sendable), 1)
        self.assertEqual(sendable[0].to, ['clean@example.com'])

    def test_drops_message_when_all_recipients_suppressed(self):
        msg = EmailMultiAlternatives(
            subject='hi', body='hello', from_email='from@x.com',
            to=['blocked@example.com'],
        )
        sendable = filter_suppressed_recipients([msg])
        self.assertEqual(sendable, [])

    def test_partial_suppression_keeps_clean_recipients(self):
        msg = EmailMultiAlternatives(
            subject='hi', body='hello', from_email='from@x.com',
            to=['clean@example.com', 'blocked@example.com'],
            cc=['blocked@example.com'],
            bcc=['another-clean@example.com'],
        )
        sendable = filter_suppressed_recipients([msg])
        self.assertEqual(len(sendable), 1)
        delivered = sendable[0]
        self.assertEqual(delivered.to, ['clean@example.com'])
        self.assertEqual(delivered.cc, [])
        self.assertEqual(delivered.bcc, ['another-clean@example.com'])

    def test_normalisation_applies(self):
        """A suppressed Gmail address must block its +tag variants too."""
        EmailSuppression.objects.create(
            email='jane@gmail.com',
            reason=EmailSuppression.Reason.COMPLAINT,
        )
        msg = EmailMultiAlternatives(
            subject='hi', body='hello', from_email='from@x.com',
            to=['jane+april@gmail.com'],
        )
        sendable = filter_suppressed_recipients([msg])
        self.assertEqual(sendable, [])


# ── SNS webhook receiver ────────────────────────────────────────────


class _PassThroughSignature:
    """Patch target so signature verification is bypassed in tests."""

    def __enter__(self):
        self._patch = mock.patch(
            'apps.marketing.views_aws_ses.verify_sns_signature',
            return_value=True,
        )
        self._patch.start()
        return self

    def __exit__(self, *args):
        self._patch.stop()


def _ses_notification(inner_event: dict) -> str:
    """Build an SNS Notification envelope wrapping an SES event."""
    return json.dumps({
        'Type': 'Notification',
        'MessageId': 'sns-1',
        'TopicArn': 'arn:aws:sns:us-east-1:000000000000:lume-ses-events',
        'Message': json.dumps(inner_event),
        'Timestamp': '2026-05-17T12:00:00.000Z',
        'SignatureVersion': '1',
        'Signature': 'stub',
        'SigningCertURL': 'https://sns.us-east-1.amazonaws.com/cert.pem',
    })


class SnsReceiverPermanentBounceTests(TestCase):
    """Permanent bounces add every bounced recipient to suppression."""

    def setUp(self):
        self.url = reverse('aws-ses-events')
        self.client_ = APIClient()

    def test_permanent_bounce_suppresses_recipients(self):
        body = _ses_notification({
            'eventType': 'Bounce',
            'mail': {'messageId': 'ses-msg-1'},
            'bounce': {
                'bounceType': 'Permanent',
                'bounceSubType': 'General',
                'bouncedRecipients': [
                    {'emailAddress': 'bounce1@example.com'},
                    {'emailAddress': 'bounce2@example.com'},
                ],
            },
        })
        with _PassThroughSignature():
            response = self.client_.post(self.url, data=body, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['suppressed_count'], 2)
        self.assertTrue(is_suppressed('bounce1@example.com'))
        self.assertTrue(is_suppressed('bounce2@example.com'))

    def test_transient_bounce_does_not_suppress(self):
        body = _ses_notification({
            'eventType': 'Bounce',
            'mail': {'messageId': 'ses-msg-2'},
            'bounce': {
                'bounceType': 'Transient',
                'bounceSubType': 'MailboxFull',
                'bouncedRecipients': [{'emailAddress': 'temp@example.com'}],
            },
        })
        with _PassThroughSignature():
            response = self.client_.post(self.url, data=body, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['suppressed_count'], 0)
        self.assertFalse(is_suppressed('temp@example.com'))


class SnsReceiverComplaintTests(TestCase):
    def setUp(self):
        self.url = reverse('aws-ses-events')
        self.client_ = APIClient()

    def test_complaint_suppresses_recipient(self):
        body = _ses_notification({
            'eventType': 'Complaint',
            'mail': {'messageId': 'ses-msg-3'},
            'complaint': {
                'complaintSubType': 'abuse',
                'complainedRecipients': [{'emailAddress': 'angry@example.com'}],
            },
        })
        with _PassThroughSignature():
            response = self.client_.post(self.url, data=body, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['suppressed_count'], 1)
        row = EmailSuppression.objects.get(email='angry@example.com')
        self.assertEqual(row.reason, EmailSuppression.Reason.COMPLAINT)
        self.assertEqual(row.complaint_subtype, 'abuse')


class SnsReceiverRobustnessTests(TestCase):
    """Per ADR 0029, the webhook NEVER returns 4xx — even on bad input."""

    def setUp(self):
        self.url = reverse('aws-ses-events')
        self.client_ = APIClient()

    def test_bad_signature_returns_200(self):
        # Cert URL doesn't match the AWS pattern → signature check
        # rejects without touching the network. Proves the URL-pattern
        # guard fires first, AND that an attacker can't redirect us to
        # a cert they host themselves.
        body = json.dumps({
            'Type': 'Notification',
            'MessageId': 'sns-1',
            'TopicArn': 'arn:aws:sns:us-east-1:000000000000:lume-ses-events',
            'Message': json.dumps({'eventType': 'Bounce', 'mail': {}, 'bounce': {}}),
            'Timestamp': '2026-05-17T12:00:00.000Z',
            'SignatureVersion': '1',
            'Signature': 'stub',
            # Attacker-hosted cert URL — must be rejected.
            'SigningCertURL': 'https://evil.example.com/sns-cert.pem',
        })
        response = self.client_.post(self.url, data=body, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['received'])
        self.assertEqual(response.data['reason'], 'invalid_signature')

    def test_bad_json_returns_200(self):
        response = self.client_.post(
            self.url, data='not json', content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reason'], 'bad_json')

    def test_unknown_event_type_returns_200(self):
        body = _ses_notification({'eventType': 'WeirdNewType', 'mail': {}})
        with _PassThroughSignature():
            response = self.client_.post(self.url, data=body, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reason'], 'unknown_event_type')


class SnsSubscriptionConfirmationTests(TestCase):
    def setUp(self):
        self.url = reverse('aws-ses-events')
        self.client_ = APIClient()

    def test_subscription_confirmation_calls_subscribe_url(self):
        body = json.dumps({
            'Type': 'SubscriptionConfirmation',
            'MessageId': 'sub-1',
            'Token': 'tok',
            'TopicArn': 'arn:aws:sns:us-east-1:000000000000:lume-ses-events',
            'Message': 'You have chosen to subscribe.',
            'SubscribeURL': 'https://sns.us-east-1.amazonaws.com/confirm?token=tok',
            'Timestamp': '2026-05-17T12:00:00.000Z',
            'SignatureVersion': '1',
            'Signature': 'stub',
            'SigningCertURL': 'https://sns.us-east-1.amazonaws.com/cert.pem',
        })
        with _PassThroughSignature(), mock.patch(
            'apps.marketing.views_aws_ses.requests.get',
        ) as mock_get:
            mock_get.return_value = mock.Mock(status_code=200, raise_for_status=lambda: None)
            response = self.client_.post(self.url, data=body, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['subscribed'])
        mock_get.assert_called_once()
