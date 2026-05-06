import { FeaturePage } from '@/components/feature-page';
import { FormMock, ChartMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Consent forms & e-signature',
  description:
    'E-signed consent forms for medspas: schema-versioned templates, tokenized fill links, snapshot-on-signing, and a full audit trail with IP and user-agent.',
};

export default function FormsFeaturePage() {
  return (
    <FeaturePage
      eyebrow="Consent forms"
      headline={
        <>
          E-signed consent that holds up{' '}
          <span className="accent-italic">under audit.</span>
        </>
      }
      standfirst="Schema-versioned templates for intake and per-treatment consent. Sent as tokenized links, signed on a tablet, snapshotted at the moment of signing. Audit trail captures IP, user-agent, and timestamp on every signature — the kind of record a medical board or HIPAA reviewer expects."
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
                Lumè ships with a library of starter templates: general
                intake, Botox consent, filler consent, laser consent,
                photo release. Edit any starter, save it as your own
                version, and the system auto-bumps the version number on
                schema changes.
              </p>
              <p>
                Per-service consent forms auto-assign when an appointment
                with that service is booked. Lifetime intake forms
                assign once, on first visit.
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
                The front desk sends the form via SMS or hands the client
                an iPad. The fill page works without a login — a
                256-bit URL token is the credential. The client fills
                the form, signs with their finger or a stylus, and the
                signed copy lands in the chart.
              </p>
              <p>
                Tokens are single-use for signing. Once signed, the form
                is immutable; reopening it returns the signed view, not
                the editable view.
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
                When a form is signed, Lumè captures: the IP address, the
                user-agent string, the timestamp, the signature image,
                and a snapshot of the template at the moment of signing.
                That snapshot means an evolving template never rewrites
                a signed past — what the client signed is what stays.
              </p>
              <p>
                Voids are a separate transition with a required reason.
                Voided forms remain in the audit log; they don't get
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
