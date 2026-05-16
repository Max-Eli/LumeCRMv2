/**
 * Privacy Policy.
 *
 * Distinguishes between two surfaces:
 *   1. The marketing site (lumècrm.com) — minimal data collected:
 *      demo-form submissions and Plausible's anonymized analytics.
 *   2. The CRM (<tenant>.lumècrm.com) — protected health information
 *      (PHI) governed by the Business Associate Agreement signed
 *      with each tenant. PHI handling is described in the BAA and
 *      summarized on /baa.
 *
 * NOT LEGAL ADVICE. This is reasonable HIPAA-aware boilerplate
 * intended to be reviewed by counsel before launch with paying
 * customers. The BAA itself, signed with each tenant, supersedes
 * this policy for any conflict regarding PHI.
 */

import type { Metadata } from 'next';

import { LegalDocument, LegalNotice, LegalSection } from '@/components/legal-document';
import { PageHero } from '@/components/page-hero';

export const metadata: Metadata = {
  title: 'Privacy Policy',
  description:
    'How Lumè collects, uses, and protects information on the marketing site and inside the CRM. Effective May 15, 2026.',
};

const EFFECTIVE_DATE = 'May 15, 2026';

export default function PrivacyPage() {
  return (
    <>
      <PageHero
        eyebrow="Legal"
        headline={
          <>
            Privacy{' '}
            <span className="accent-italic">policy.</span>
          </>
        }
        standfirst={`How Lumè handles information on the marketing site and inside the CRM. Effective ${EFFECTIVE_DATE}.`}
      />

      <LegalDocument>
        <LegalNotice>
          This policy describes practices in force for Lumè today. The
          version that governs your relationship with us as a paying
          customer is the one provided during contracting, alongside
          our Business Associate Agreement. If there is any conflict
          between this page and the executed BAA regarding protected
          health information, the BAA controls.
        </LegalNotice>

        <LegalSection number="01" title="Who we are">
          <p>
            Lumè CRM ("Lumè", "we", "us", or "our") operates the
            marketing site at lumècrm.com and the medical-spa CRM at
            tenant subdomains of lumècrm.com. Our customers are
            medical spas; their clients receive treatments at those
            spas and may interact with Lumè-hosted forms or booking
            pages.
          </p>
          <p>
            For protected health information ("PHI") collected and
            processed inside the CRM, Lumè acts as a Business
            Associate of the customer (the spa), as defined under
            HIPAA. The spa is the Covered Entity. The terms of that
            relationship live in a signed Business Associate
            Agreement, summarized on{' '}
            <LegalLink href="/baa">/baa</LegalLink>.
          </p>
        </LegalSection>

        <LegalSection number="02" title="Information collected on the marketing site">
          <p>The public marketing site collects two things:</p>
          <ul>
            <li>
              <strong>Demo-request submissions.</strong> When you fill
              out the form at <LegalLink href="/demo">/demo</LegalLink>,
              we receive your name, work email, phone number (if you
              provide one), spa name, location count, provider count,
              the platform you currently use, and any message you
              include. These submissions are emailed to a small
              internal inbox and used to schedule a demo with you. We
              do not sell, share, or syndicate this information.
            </li>
            <li>
              <strong>Anonymized analytics.</strong> We use Plausible
              Analytics, a privacy-first analytics service. Plausible
              does not set cookies, does not collect personal data,
              and does not track visitors across sites. The
              information collected is aggregate (page views,
              referrers, browser type, screen size, country) and
              cannot be used to identify you. See{' '}
              <LegalLink href="https://plausible.io/data-policy" external>
                plausible.io/data-policy
              </LegalLink>{' '}
              for the underlying practices.
            </li>
          </ul>
          <p>
            The marketing site does not use any third-party advertising,
            retargeting, social-media tracking pixels, or session-replay
            tools.
          </p>
        </LegalSection>

        <LegalSection number="03" title="Information collected inside the CRM">
          <p>
            The CRM stores the data customers enter to operate their
            medical spa: appointment records, client charts (contact
            information, treatment history, allergies, signed consent
            forms, provider notes), invoices, payment records, staff
            schedules, and audit logs of every PHI access.
          </p>
          <p>
            All PHI inside the CRM is governed by the signed Business
            Associate Agreement between Lumè and the customer (the
            spa). Lumè does not use PHI for any purpose other than
            providing the CRM service to the customer, as permitted
            by HIPAA §164.504(e) and described in the BAA.
          </p>
          <p>
            Clients of a Lumè customer (the spa's patients) who
            interact with a tokenized form-fill page or online booking
            page submit information directly into the spa's tenant of
            the CRM. The spa is the data controller for that
            information; Lumè processes it as a Business Associate.
          </p>
        </LegalSection>

        <LegalSection number="04" title="How we use information">
          <p>
            Demo-request information is used to schedule a
            walkthrough, send a quote, and follow up with you about
            Lumè. We retain demo submissions for up to twenty-four
            months and then delete them unless you become a customer
            or ask us to delete sooner.
          </p>
          <p>
            CRM data is used to provide the service to the customer.
            Specifically, Lumè uses the data to render the customer's
            calendar, charts, forms, invoices, and reports; to send
            transactional messages (appointment reminders, signed-form
            copies) that the customer has configured; and to generate
            the audit trail required by HIPAA §164.312(b).
          </p>
          <p>
            We do not sell any information collected through the
            marketing site or the CRM. We do not use customer PHI to
            train artificial-intelligence models, advertising systems,
            or analytics products.
          </p>
        </LegalSection>

        <LegalSection number="05" title="Sharing and subprocessors">
          <p>
            We share information only with the subprocessors below,
            each under contractual confidentiality and security
            obligations. Each is also covered by a BAA where PHI is
            processed.
          </p>
          <ul>
            <li>
              <strong>Amazon Web Services (AWS).</strong> Hosting,
              compute, storage, encryption-at-rest, and email delivery
              (SES). Operates under a signed BAA with Lumè.
            </li>
            <li>
              <strong>Twilio.</strong> SMS delivery for appointment
              reminders, confirmations, and form-fill links. Operates
              under a signed BAA with Lumè.
            </li>
            <li>
              <strong>Payment processor.</strong> Card-payment
              processing for transactions inside the CRM. PCI DSS
              Level 1 compliant. Operates under a signed BAA with
              Lumè where the processor handles PHI alongside
              transaction data.
            </li>
            <li>
              <strong>Resend.</strong> Transactional email delivery
              for marketing-site forms only. Does not process PHI.
            </li>
            <li>
              <strong>Plausible Analytics.</strong> Anonymized
              marketing-site analytics. Does not process PHI or
              personal data.
            </li>
          </ul>
          <p>
            We do not share information with law-enforcement agencies
            absent a valid subpoena, court order, or other legal
            process. We will challenge requests we believe to be
            overbroad. Where legally permissible, we will notify the
            affected customer before producing data in response to
            government demand.
          </p>
        </LegalSection>

        <LegalSection number="06" title="Cookies and tracking">
          <p>
            The marketing site does not set advertising or analytics
            cookies. The only cookies Lumè may set on the marketing
            site are functional (e.g., to remember a CSRF token on
            the demo form). The CRM uses a session cookie to keep
            authenticated operators logged in; that cookie is
            HTTPS-only, HttpOnly, and SameSite-strict.
          </p>
        </LegalSection>

        <LegalSection number="07" title="Data retention">
          <p>
            Demo-request submissions are retained for up to
            twenty-four months. Customer data inside the CRM is
            retained for the duration of the contract; upon
            termination, the customer may request export or
            destruction of their tenant data per the BAA's return
            and destruction provisions. Backups are encrypted and
            rotated on a schedule defined in our internal data
            retention policy; backup copies of deleted data are
            purged within thirty days.
          </p>
        </LegalSection>

        <LegalSection number="08" title="Your rights">
          <p>
            If you submitted a demo request, you can ask us to access,
            correct, or delete that submission at any time. Email{' '}
            <LegalLink href="mailto:legal@lumecrm.com">legal@lumecrm.com</LegalLink>{' '}
            and we will respond within thirty days.
          </p>
          <p>
            If you are a patient of a Lumè customer (the spa), your
            access, correction, and deletion rights run through the
            spa as the Covered Entity, in accordance with HIPAA's
            Privacy Rule and applicable state law. Lumè will support
            the spa in fulfilling any such request you make to them.
          </p>
          <p>
            Residents of California, the EEA, the UK, and other
            jurisdictions with comprehensive data-protection
            frameworks may have additional rights — for example, the
            right to data portability or to lodge a complaint with a
            supervisory authority. Email us and we will accommodate
            those rights to the extent required by applicable law.
          </p>
        </LegalSection>

        <LegalSection number="09" title="Security">
          <p>
            Lumè's security posture is summarized on{' '}
            <LegalLink href="/security">/security</LegalLink> and
            includes tenant isolation at the database layer,
            role-based permissions resolved per request, append-only
            audit logging on every PHI access, and AWS infrastructure
            under a signed Business Associate Agreement. SOC 2 Type
            II is in progress.
          </p>
          <p>
            In the event of a breach involving unsecured PHI, Lumè
            will notify affected customers without unreasonable
            delay and no later than sixty days following discovery,
            consistent with the BAA and HIPAA §164.410.
          </p>
        </LegalSection>

        <LegalSection number="10" title="International transfers">
          <p>
            Lumè's production infrastructure runs in the United
            States. If you access the service from another country,
            your information will be transferred to and processed in
            the U.S. Where required, Lumè relies on Standard
            Contractual Clauses or equivalent transfer mechanisms.
          </p>
        </LegalSection>

        <LegalSection number="11" title="Children">
          <p>
            The marketing site is not directed at children. The CRM
            may store information about minors when the customer
            (the spa) treats minors and is authorized to do so by a
            parent or guardian; that handling is governed by the
            customer's own policies and the BAA, not by this notice.
          </p>
        </LegalSection>

        <LegalSection number="12" title="Changes to this policy">
          <p>
            We may update this policy. If a change is material, we
            will give customers reasonable notice before the change
            takes effect — by email to the operator's admin contact
            and an in-CRM notice. The effective date at the top of
            this page reflects the current version.
          </p>
        </LegalSection>

        <LegalSection number="13" title="Contact">
          <p>
            For questions about this policy, our handling of PHI, or
            to exercise your rights:
          </p>
          <p>
            <strong>Email:</strong>{' '}
            <LegalLink href="mailto:legal@lumecrm.com">legal@lumecrm.com</LegalLink>
            <br />
            <strong>Privacy Officer:</strong> Max Elishaev
          </p>
        </LegalSection>
      </LegalDocument>
    </>
  );
}

function LegalLink({
  href,
  children,
  external = false,
}: {
  href: string;
  children: React.ReactNode;
  external?: boolean;
}) {
  return (
    <a
      href={href}
      className="text-accent underline underline-offset-4 hover:text-foreground transition-colors"
      {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
    >
      {children}
    </a>
  );
}
