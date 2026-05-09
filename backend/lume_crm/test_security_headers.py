"""
Tests for `lume_crm/security_headers.py`.

The middleware must:
  - apply the strict API CSP to JSON responses
  - apply the looser HTML CSP to admin / DRF browsable responses
  - never overwrite a header an upstream view explicitly set
  - be idempotent (calling twice produces the same headers)
"""

from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, SimpleTestCase

from lume_crm.security_headers import SecurityHeadersMiddleware


class SecurityHeadersTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _run(self, response: HttpResponse) -> HttpResponse:
        middleware = SecurityHeadersMiddleware(lambda _req: response)
        return middleware(self.factory.get('/anything'))

    def test_api_response_gets_strict_csp(self):
        resp = self._run(JsonResponse({'ok': True}))
        self.assertIn("default-src 'none'", resp['Content-Security-Policy'])
        self.assertIn("frame-ancestors 'none'", resp['Content-Security-Policy'])

    def test_html_response_gets_html_csp(self):
        resp = self._run(HttpResponse('<html></html>', content_type='text/html'))
        self.assertIn("default-src 'self'", resp['Content-Security-Policy'])
        # Admin needs inline scripts; the HTML policy permits them.
        self.assertIn("script-src 'self' 'unsafe-inline'", resp['Content-Security-Policy'])

    def test_existing_header_is_not_overwritten(self):
        # A view that wants a tighter policy on a specific endpoint can
        # set its own CSP and the middleware respects it. setdefault is
        # what enables this — verify it.
        resp = HttpResponse('hi')
        resp['Content-Security-Policy'] = "default-src 'none'"
        result = self._run(resp)
        self.assertEqual(result['Content-Security-Policy'], "default-src 'none'")

    def test_coop_corp_permissions_present(self):
        resp = self._run(JsonResponse({'ok': True}))
        self.assertEqual(resp['Cross-Origin-Opener-Policy'], 'same-origin')
        self.assertEqual(resp['Cross-Origin-Resource-Policy'], 'same-origin')
        self.assertIn('camera=()', resp['Permissions-Policy'])
        self.assertIn('microphone=()', resp['Permissions-Policy'])
        self.assertIn('geolocation=()', resp['Permissions-Policy'])
