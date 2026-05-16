/**
 * Business Associate Agreement summary page.
 *
 * Two purposes: legal (give visitors a clear picture of what a BAA
 * is and what Lumè's covers) and sales (the BAA-included claim is
 * one of Lumè's three core differentiators — Mindbody and Boulevard
 * historically charged a premium for it). This page substantiates
 * the claim.
 *
 * NOT LEGAL ADVICE. The actual BAA signed with each customer
 * supersedes anything described on this page.
 */

import Link from 'next/link';
import type { Metadata } from 'next';

import { LegalDocument, LegalNotice, LegalSection } from '@/components/legal-document';
import { PageHero } from '@/components/page-hero';

export const metadata: Metadata = {
  title: 'Business Associate Agreement',
  description:
    'The HIPAA Business Associate Agreement is included in every Lumè contract. Here is what it covers and why it matters.',
};

export default function BaaPage() {
  return (
    <>
      <PageHero
        eyebrow="Legal"
        headline={
          <>
            The BAA is in{' '}
            <span className="accent-italic">every contract.</span>
          </>
        }
        standfirst="The Business Associate Agreement is part of the standard Lumè contract. Not a premium tier. Not a separate negotiation. Here is what that means in practice."
      />

      <LegalDocument>
        <LegalNotice>
          This page summarizes the Business Associate Agreement
          ("BAA") that Lumè provides to every customer. The executed
          BAA, signed during contracting, is the document that
          governs the relationship between Lumè and the customer as
          a Business Associate of a Covered Entity under HIPAA.
        </LegalNotice>

        <LegalSection number="01" title="What a BAA is">
          <p>
            Under the HIPAA Privacy and Security Rules, a "Covered
            Entity" (most medical spas, depending on the services
            they offer and their payment posture) cannot share
            protected health information ("PHI") with a vendor unless
            that vendor has signed a Business Associate Agreement.
          </p>
          <p>
            The BAA contractually obligates the vendor — Lumè — to
            handle PHI with the same care HIPAA requires of the
            Covered Entity, including specific technical safeguards,
            workforce training, breach notification timelines, and
            cooperation with the Covered Entity's compliance
            program. The required scope is set out in HIPAA{' '}
            §164.504(e).
          </p>
        </LegalSection>

        <LegalSection number="02" title="Why Lumè includes the BAA in every contract">
          <p>
            Several competing platforms classify HIPAA-compliance as
            a premium feature. The BAA is gated behind a higher
            pricing tier or an annual contract commitment. We think
            that is the wrong model for a category of software where
            the only real customer is a medical practice.
          </p>
          <p>
            Lumè runs on a single architecture. Every customer is on
            the HIPAA-compliant infrastructure because there isn't a
            second infrastructure. Charging extra for the BAA would
            mean charging extra for a feature every customer already
            has.
          </p>
        </LegalSection>

        <LegalSection number="03" title="What Lumè's BAA covers">
          <p>
            The BAA addresses each obligation a Business Associate
            owes under HIPAA. In plain terms:
          </p>
          <ul>
            <li>
              <strong>Permitted uses and disclosures.</strong> Lumè
              uses PHI only to provide the CRM service to the
              customer. We do not use PHI for marketing, advertising,
              AI training, or any purpose outside the service.
            </li>
            <li>
              <strong>Safeguards.</strong> Lumè implements
              administrative, physical, and technical safeguards
              required under the Security Rule. These include tenant
              isolation at the database layer, role-based
              permissions, append-only audit logging, encryption at
              rest with AWS KMS, and TLS in transit. See{' '}
              <Link
                href="/security"
                className="text-accent underline underline-offset-4 hover:text-foreground transition-colors"
              >
                /security
              </Link>{' '}
              for the technical posture.
            </li>
            <li>
              <strong>Workforce.</strong> Every Lumè staff member
              with access to PHI signs a confidentiality agreement
              and completes HIPAA training. Access is provisioned
              least-privilege and audit-logged.
            </li>
            <li>
              <strong>Subcontractors.</strong> Lumè uses AWS, Twilio,
              and Resend as subprocessors, plus a licensed payment
              processor for card transactions inside the CRM. AWS,
              Twilio, and the payment processor operate under signed
              BAAs with Lumè where applicable. Resend is used only
              for marketing-site email and does not process PHI. The
              payment processor is PCI DSS Level 1 compliant. New
              subprocessors are disclosed in advance with a
              reasonable opportunity to object.
            </li>
            <li>
              <strong>Breach notification.</strong> Lumè will notify
              the customer of any breach of unsecured PHI without
              unreasonable delay, and no later than sixty days
              following discovery, consistent with HIPAA §164.410.
              The notification will include the information required
              under §164.404 to the extent then available.
            </li>
            <li>
              <strong>Access, amendment, accounting.</strong> Lumè
              will support the customer in fulfilling individual
              access, amendment, and accounting-of-disclosures
              requests as required by §164.524, §164.526, and
              §164.528.
            </li>
            <li>
              <strong>Return or destruction.</strong> On termination,
              Lumè will, at the customer's option, return or destroy
              all PHI within the timelines set out in the BAA.
              Backups containing residual copies are purged within
              thirty days thereafter.
            </li>
            <li>
              <strong>HHS audit cooperation.</strong> Lumè will make
              its internal practices, records, and policies available
              to the Department of Health and Human Services as
              required to determine the customer's compliance with
              HIPAA.
            </li>
          </ul>
        </LegalSection>

        <LegalSection number="04" title="What Lumè's BAA does not do">
          <p>
            The BAA does not make Lumè the Covered Entity. The
            customer (the spa) remains the Covered Entity under
            HIPAA, with the underlying obligations to its patients
            — for notice of privacy practices, individual rights,
            and patient communications. Lumè supports the customer
            in meeting those obligations, but does not assume them.
          </p>
          <p>
            The BAA also does not modify your separate obligations
            under state law. Several states (California,
            Massachusetts, New York, Texas) impose privacy and
            breach-notification rules that go beyond HIPAA. Where
            applicable state law is more protective, it applies.
          </p>
        </LegalSection>

        <LegalSection number="05" title="Requesting the template">
          <p>
            We share the BAA template before contracting so that
            counsel for the customer can review it alongside the
            Master Service Agreement. To request a copy:
          </p>
          <p>
            <strong>Email:</strong>{' '}
            <a
              href="mailto:legal@lumecrm.com"
              className="text-accent underline underline-offset-4 hover:text-foreground transition-colors"
            >
              legal@lumecrm.com
            </a>
            , or request it during your{' '}
            <Link
              href="/demo"
              className="text-accent underline underline-offset-4 hover:text-foreground transition-colors"
            >
              demo
            </Link>{' '}
            and we will send it before the follow-up call.
          </p>
        </LegalSection>
      </LegalDocument>
    </>
  );
}
