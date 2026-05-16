import { FeaturePage } from '@/components/feature-page';
import { FormMock, ChartMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Consent forms & e-signature',
  description:
    'Schema-versioned templates for intake and per-treatment consent. Tokenized fill links. IP, user-agent, and timestamp captured on every signature.',
};

export default function FormsFeaturePage() {
  return (
    <FeaturePage
      path="/features/forms"
      breadcrumbLabel="Consent forms & e-signature"
      eyebrow="Consent forms"
      headline={
        <>
          E-signed consent that holds up{' '}
          <span className="accent-italic">under audit.</span>
        </>
      }
      standfirst="Schema-versioned templates for intake and per-treatment consent. Tokenized fill links. IP, user-agent, and timestamp captured on every signature."
      heroMock={<FormMock />}
      heroMockUrl="/sign/9j4k…"
      highlights={[
        { value: 'Versioned', label: 'Templates evolve; signed forms stay frozen.' },
        { value: 'Tokenized', label: 'No login required for the client.' },
        { value: 'Audited', label: 'IP, user-agent, timestamp, signature image.' },
      ]}
      details={[
        {
          eyebrow: 'Template management',
          title: 'Build forms once, version them as your practice evolves.',
          body: (
            <>
              <p>
                Starter templates ship for intake, Botox, filler, laser,
                and photo release. Edit any starter; the system
                auto-bumps the version on schema changes.
              </p>
              <p>
                Per-service consent auto-assigns on booking. Lifetime
                intake assigns once, on first visit.
              </p>
            </>
          ),
          bullets: [
            'Starter library: intake, Botox, filler, laser, photo release',
            'Auto-versioning on schema changes',
            'Per-service auto-assignment',
            'Lifetime vs per-visit recurrence rules',
          ],
        },
        {
          eyebrow: 'Tokenized fill flow',
          title: 'Send a link. The client signs on any device.',
          body: (
            <>
              <p>
                Send the form via SMS or hand the client an iPad. No
                login required — a 256-bit URL token is the credential.
                The client signs with a finger or stylus and the signed
                copy lands in the chart.
              </p>
              <p>
                Tokens are single-use. Once signed, the form is
                immutable; reopening it returns the signed view, not the
                editable one.
              </p>
            </>
          ),
          bullets: [
            'No client login required',
            'Single-use tokens (256-bit entropy)',
            'Works on iPad, phone, or laptop',
            'Signed copy emailed on operator request',
          ],
          mock: <ChartMock />,
          mockUrl: '/clients/sarah-chen',
        },
        {
          eyebrow: 'Audit trail',
          title: 'Every signature, immutable and reviewable.',
          body: (
            <>
              <p>
                Lumè captures the IP, user-agent, timestamp, signature
                image, and a snapshot of the template at signing. So
                when you revise next month's wording, last month's
                signed forms still reference last month's text.
              </p>
              <p>
                Voids are a separate transition with a required reason.
                Voided forms stay in the audit log; they don't get
                deleted.
              </p>
            </>
          ),
          bullets: [
            'IP + user-agent + timestamp on every signature',
            'Schema snapshot at signing — historically legible',
            'Void with required reason; never hard-deleted',
            'Audit log accessible from the chart',
          ],
        },
      ]}
      related={[
        { href: '/features/charts', label: 'Client charts', title: 'Where signed forms land.' },
        { href: '/security', label: 'Security', title: 'How HIPAA shapes the form architecture.' },
      ]}
    />
  );
}
