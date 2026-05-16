/**
 * Terms of Service.
 *
 * The master legal agreement between Lumè and a customer (the spa).
 * Covers account responsibilities, acceptable use, fees, IP, the
 * BAA reference, disclaimers, and termination.
 *
 * NOT LEGAL ADVICE. This is reasonable HIPAA-aware boilerplate
 * intended to be reviewed by counsel before launch with paying
 * customers. The version that governs a specific customer
 * relationship is the executed Master Service Agreement, which
 * supersedes anything published here.
 */

import type { Metadata } from 'next';

import { LegalDocument, LegalNotice, LegalSection } from '@/components/legal-document';
import { PageHero } from '@/components/page-hero';

export const metadata: Metadata = {
  title: 'Terms of Service',
  description:
    'The terms governing use of Lumè by medical-spa customers. Effective May 15, 2026.',
};

const EFFECTIVE_DATE = 'May 15, 2026';

export default function TermsPage() {
  return (
    <>
      <PageHero
        eyebrow="Legal"
        headline={
          <>
            Terms of{' '}
            <span className="accent-italic">service.</span>
          </>
        }
        standfirst={`The agreement that governs your use of Lumè. Effective ${EFFECTIVE_DATE}.`}
      />

      <LegalDocument>
        <LegalNotice>
          These Terms describe the framework in force for Lumè today.
          The agreement that governs your specific use of Lumè as a
          paying customer is the executed Master Service Agreement
          provided during contracting, which supersedes anything
          published on this page if there is a conflict.
        </LegalNotice>

        <LegalSection number="01" title="Acceptance">
          <p>
            These Terms of Service ("Terms") form a binding agreement
            between Lumè CRM ("Lumè", "we", "us", or "our") and the
            organization that signs up for or uses the Lumè service
            ("Customer", "you", or "your"). By accessing the service,
            you agree to these Terms.
          </p>
          <p>
            If you are agreeing on behalf of a company or other
            entity, you represent that you have the authority to bind
            that entity. If you do not, do not use the service.
          </p>
        </LegalSection>

        <LegalSection number="02" title="The service">
          <p>
            "The service" means the Lumè customer-relationship
            management platform for medical spas, including all
            features described on lumècrm.com — booking, client
            charts, e-signed consent forms, payments, reporting,
            multi-location management, and the customer-facing booking
            and form surfaces hosted on Lumè-managed subdomains.
          </p>
          <p>
            We may add, remove, or change features. Material
            reductions to functionality you are paying for will be
            preceded by reasonable advance notice. We will not
            reduce the security or compliance posture of the service
            during a paid term.
          </p>
        </LegalSection>

        <LegalSection number="03" title="Accounts and eligibility">
          <p>
            To use the service you must (a) be a legally operating
            medical spa or business engaged in providing aesthetic
            medical services, (b) be at least eighteen years old,
            and (c) provide accurate registration information.
          </p>
          <p>
            You are responsible for safeguarding your account
            credentials, for any actions taken using your account,
            and for ensuring that your staff use the service in
            compliance with these Terms, our Acceptable Use Policy,
            and applicable law.
          </p>
        </LegalSection>

        <LegalSection number="04" title="The BAA">
          <p>
            Lumè acts as a Business Associate of the Customer under
            HIPAA. A signed Business Associate Agreement is provided
            as part of every customer contract and is summarized on{' '}
            <a
              href="/baa"
              className="text-accent underline underline-offset-4 hover:text-foreground transition-colors"
            >
              /baa
            </a>
            . If a conflict exists between these Terms and the BAA
            with respect to PHI, the BAA controls.
          </p>
        </LegalSection>

        <LegalSection number="05" title="Fees and payment">
          <p>
            Fees are set out in the Order Form executed with each
            customer. Unless otherwise stated, fees are billed monthly
            in advance and are non-refundable except as required by
            law. Adding a location during a term will increase the
            invoice on the next billing cycle; closing a location
            will reduce it from the next billing cycle.
          </p>
          <p>
            Card-payment processing is provided through a licensed
            third-party payment processor with which Lumè has
            integrated. Card-processing fees are passed through to
            Customer and are set out in the applicable Order Form.
            Specific rates are quoted at contracting based on the
            Customer's card-present and card-not-present mix.
          </p>
          <p>
            Late payments accrue interest at the lesser of 1.5% per
            month or the maximum permitted by law. If an invoice
            remains unpaid for more than thirty days, we may suspend
            the service after providing written notice.
          </p>
        </LegalSection>

        <LegalSection number="06" title="Acceptable use">
          <p>You agree not to use the service to:</p>
          <ul>
            <li>
              Violate any law, regulation, or third-party right,
              including state medical-board rules applicable to
              aesthetic medicine in your jurisdiction.
            </li>
            <li>
              Send unsolicited commercial messages, marketing
              communications without opt-in consent, or any
              communications in violation of TCPA, CAN-SPAM, or
              equivalent law.
            </li>
            <li>
              Reverse-engineer, decompile, or attempt to extract the
              source code of the service.
            </li>
            <li>
              Resell, sublicense, or otherwise commercialize the
              service except as expressly permitted.
            </li>
            <li>
              Probe, scan, or test the vulnerability of the service
              without prior written consent. Coordinated disclosure
              of security findings is welcomed —{' '}
              <a
                href="mailto:security@lumecrm.com"
                className="text-accent underline underline-offset-4 hover:text-foreground transition-colors"
              >
                security@lumecrm.com
              </a>
              .
            </li>
            <li>
              Upload malware, infringing material, or content that
              violates applicable law.
            </li>
          </ul>
        </LegalSection>

        <LegalSection number="07" title="Intellectual property">
          <p>
            Lumè owns all rights in the service, including the
            software, infrastructure, brand, and documentation. You
            own the data you put into the service.
          </p>
          <p>
            You grant Lumè a worldwide, royalty-free, non-exclusive
            license to host, copy, transmit, and display your data
            solely to provide the service to you. We do not use
            customer data to train artificial-intelligence models,
            advertise to your clients, or sell to third parties.
          </p>
          <p>
            If you provide feedback or suggestions, you grant Lumè a
            non-exclusive, perpetual license to use them in the
            product without obligation to you.
          </p>
        </LegalSection>

        <LegalSection number="08" title="Confidentiality">
          <p>
            Each party will protect the other's confidential
            information with at least the same degree of care it uses
            for its own, and never less than reasonable care.
            Confidential information includes business terms, security
            architecture details, and customer lists. Neither party
            will disclose confidential information except as needed
            to perform under this agreement or as required by law,
            in which case the disclosing party will give prompt
            notice and a reasonable opportunity to seek a protective
            order.
          </p>
        </LegalSection>

        <LegalSection number="09" title="Term and termination">
          <p>
            The agreement begins on the effective date stated in the
            Order Form and continues until terminated. Either party
            may terminate for material breach not cured within thirty
            days of written notice. You may cancel for convenience
            with thirty days' notice; we will not charge the
            following month's fees.
          </p>
          <p>
            On termination we will, at your request and within thirty
            days, make available an export of your tenant data in a
            structured electronic format. After ninety days we may
            delete the tenant; backups containing residual copies are
            purged within thirty days thereafter, consistent with the
            BAA.
          </p>
        </LegalSection>

        <LegalSection number="10" title="Disclaimers">
          <p>
            The service is provided on an "as is" and "as available"
            basis. To the maximum extent permitted by law, we
            disclaim all warranties, express or implied, including
            warranties of merchantability, fitness for a particular
            purpose, and non-infringement.
          </p>
          <p>
            Lumè does not provide medical, clinical, regulatory, or
            legal advice. Decisions about patient care, treatment,
            and recordkeeping are the responsibility of the licensed
            professionals operating the customer's medical spa.
          </p>
        </LegalSection>

        <LegalSection number="11" title="Limitation of liability">
          <p>
            To the maximum extent permitted by law, neither party
            will be liable for indirect, incidental, special,
            consequential, or punitive damages, or for lost profits,
            revenues, or data, even if advised of the possibility of
            such damages.
          </p>
          <p>
            Each party's total liability arising out of or related
            to this agreement will not exceed the fees paid by
            Customer to Lumè in the twelve months preceding the
            event giving rise to liability. This limitation does
            not apply to (i) breach of confidentiality, (ii) breach
            of the BAA, (iii) gross negligence or willful
            misconduct, or (iv) indemnification obligations.
          </p>
        </LegalSection>

        <LegalSection number="12" title="Indemnification">
          <p>
            Each party will indemnify the other against third-party
            claims arising from its breach of these Terms, its
            violation of applicable law, or its infringement of
            third-party rights. The indemnified party will give
            prompt notice and reasonable cooperation; the
            indemnifying party will control the defense and any
            settlement, provided the settlement does not impose
            non-monetary obligations on the indemnified party
            without consent.
          </p>
        </LegalSection>

        <LegalSection number="13" title="Governing law">
          <p>
            These Terms are governed by the laws of the State of
            Delaware, without regard to its conflict-of-laws
            principles. Any dispute will be brought exclusively in
            the state or federal courts located in Delaware, and
            each party consents to that jurisdiction.
          </p>
        </LegalSection>

        <LegalSection number="14" title="Changes to these terms">
          <p>
            We may update these Terms. Material changes will be
            communicated by email to the operator's admin contact
            and an in-CRM notice, with at least thirty days' notice
            before the change takes effect. Continued use after the
            effective date constitutes acceptance.
          </p>
        </LegalSection>

        <LegalSection number="15" title="Contact">
          <p>
            For questions about these Terms or to give notice under
            this agreement:
          </p>
          <p>
            <strong>Email:</strong>{' '}
            <a
              href="mailto:legal@lumecrm.com"
              className="text-accent underline underline-offset-4 hover:text-foreground transition-colors"
            >
              legal@lumecrm.com
            </a>
          </p>
        </LegalSection>
      </LegalDocument>
    </>
  );
}
