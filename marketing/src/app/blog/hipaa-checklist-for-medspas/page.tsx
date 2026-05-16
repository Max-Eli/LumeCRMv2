/**
 * Blog post: The HIPAA checklist for medspas.
 *
 * Compliance-fear anchor post. Cites HIPAA §164.308/312, OCR
 * enforcement data, and state-law overlays. Subtle Lumè integration
 * in one closing section, not throughout.
 *
 * Target query: "HIPAA compliance for medspas"
 */

import Link from 'next/link';
import type { Metadata } from 'next';

import { BlogCallout, BlogPostLayout } from '@/components/blog-post-layout';
import { findPost } from '@/lib/blog';

const meta = findPost('hipaa-checklist-for-medspas')!;

export const metadata: Metadata = {
  title: meta.title,
  description: meta.summary,
  openGraph: {
    type: 'article',
    title: meta.title,
    description: meta.summary,
    publishedTime: meta.publishedAt,
  },
};

export default function Post() {
  return (
    <BlogPostLayout
      meta={meta}
      standfirst="Most medical spas operate in a HIPAA gray zone — somewhere between a salon and a medical practice, but treated like neither by the off-the-shelf software they buy. Here is what HIPAA actually requires, where state law adds teeth, and the vendor checks every operator should run before signing a contract."
    >
      <p>
        A short, uncomfortable fact: the Office for Civil Rights at
        the Department of Health and Human Services collected{' '}
        <strong>$144 million in HIPAA settlements between 2018 and 2024</strong>
        , and the per-violation civil penalty maxes out at $2.13 million
        per identical violation per year. Most medspas hear "HIPAA fine"
        and assume it does not apply to them, because they do not file
        insurance claims. That is half a story.
      </p>

      <p>
        The other half is that several state attorneys general now
        enforce HIPAA-aligned obligations under their own laws —
        sometimes with broader scope than federal HIPAA itself — and
        the threshold for being treated as a "covered entity" is
        lower than it looks once you accept HSA cards, transmit
        treatment records electronically, or share lab results with a
        partner physician.
      </p>

      <p>
        This piece walks through the practical compliance work that
        actually matters for a medspa: the threshold question, the
        ten Security Rule line items, the four state overlays most
        likely to apply, and the vendor checks you should run before
        you onboard new software.
      </p>

      <h2>Are you a covered entity? The threshold question</h2>

      <p>
        HIPAA distinguishes between two roles: <strong>Covered Entities</strong>{' '}
        (health plans, clearinghouses, and "health care providers who
        transmit any health information in electronic form in
        connection with a transaction" covered by HIPAA) and{' '}
        <strong>Business Associates</strong> (vendors who handle PHI
        on behalf of a Covered Entity).
      </p>

      <p>The Covered Entity test for a medspa hinges on a few facts:</p>

      <ul>
        <li>
          <strong>Do you bill any insurance, including supplemental
          plans for cosmetic procedures?</strong> If yes, you are a
          Covered Entity. Even infrequent insurance billing for
          reconstruction or scar revision puts you in scope.
        </li>
        <li>
          <strong>Do you accept HSA or FSA cards through any electronic
          rail?</strong> The IRS treats those rails as health-payment
          systems; the HIPAA analysis follows the transmission, not
          the diagnosis.
        </li>
        <li>
          <strong>Do you transmit treatment records electronically to a
          collaborating physician, dermatologist, or plastic
          surgeon?</strong> If yes, those transmissions are covered
          transactions under HIPAA §1320d-2.
        </li>
        <li>
          <strong>Do you store electronic protected health information
          (ePHI) for your own treatment records?</strong> Storage alone
          does not make you a Covered Entity, but it triggers state
          medical-records laws in every U.S. state.
        </li>
      </ul>

      <BlogCallout label="Plain English">
        <p>
          If your medspa does anything more than cash-only retail
          aesthetics with paper charts, you are likely either a HIPAA
          Covered Entity yourself or operating under a Covered Entity
          (a collaborating physician). In either case, every vendor
          that touches your patient data needs a Business Associate
          Agreement on file.
        </p>
      </BlogCallout>

      <h2>The ten line items the Security Rule actually requires</h2>

      <p>
        HIPAA's Security Rule (45 CFR §164.308–.312) is the part most
        medspas actually have to operationalize. The Privacy Rule is
        important but mostly governs how you communicate with
        patients, which a competent front desk already handles.
        Security is where the audits land. Here are the ten line items
        an OCR investigator will ask about.
      </p>

      <h3>1. A documented risk assessment</h3>
      <p>
        §164.308(a)(1)(ii)(A) requires you to "conduct an accurate and
        thorough assessment of the potential risks and vulnerabilities
        to the confidentiality, integrity, and availability of
        electronic protected health information." In practice: a
        written document, dated, listing the systems that touch PHI
        and the known risks for each. Update it annually or whenever a
        major vendor changes. The NIST HIPAA Security Toolkit is a
        reasonable starting framework.
      </p>

      <h3>2. Audit controls on every system that touches PHI</h3>
      <p>
        §164.312(b) requires "hardware, software, and/or procedural
        mechanisms that record and examine activity in information
        systems that contain or use electronic protected health
        information." In CRM terms: an audit log that captures who
        viewed, modified, exported, or deleted what — append-only,
        queryable, retained for at least six years per §164.316(b)(2).
      </p>

      <h3>3. Access controls and unique user IDs</h3>
      <p>
        §164.312(a)(2)(i) requires unique user IDs for every member
        of your workforce. Shared logins fail the audit immediately,
        because the audit log cannot then attribute action to
        person. Multi-factor authentication is not technically
        required, but every regulator-aligned auditor will ask why
        you don't have it.
      </p>

      <h3>4. Encryption at rest and in transit</h3>
      <p>
        §164.312(a)(2)(iv) makes encryption an "addressable"
        specification, not strictly required — but the OCR's
        practical position is that anything else is a documented
        risk you carry. The defensible answer: TLS 1.2+ for
        transmission and AES-256 for storage. The Safe Harbor in the
        HITECH breach-notification rule effectively exempts encrypted
        data from notification obligations, which is a significant
        operational benefit.
      </p>

      <h3>5. Backup and disaster recovery</h3>
      <p>
        §164.308(a)(7)(ii)(A) requires "retrievable exact copies of
        electronic protected health information." Translation: tested
        backups. The phrase the auditor uses is "have you ever
        actually restored from a backup?" The honest answer for most
        independent spas is no. Schedule one restore drill per
        quarter.
      </p>

      <h3>6. Workforce training</h3>
      <p>
        §164.308(a)(5)(i) requires a security awareness and training
        program. There is no specific curriculum, but the OCR's
        common request is documentation: who took what training, when,
        signed by them. Annual training plus on-hire training is
        defensible.
      </p>

      <h3>7. A sanction policy</h3>
      <p>
        §164.308(a)(1)(ii)(C) requires "appropriate sanctions against
        workforce members who fail to comply." This is usually a
        single paragraph in the employee handbook stating that HIPAA
        violations are grounds for discipline up to and including
        termination. Get it in writing; reference it in the training
        log.
      </p>

      <h3>8. Incident response procedures</h3>
      <p>
        §164.308(a)(6) requires you to "identify and respond to
        suspected or known security incidents." In a small-business
        context, this is a one-page document: who do staff tell when
        something looks wrong, who notifies the practice manager, who
        decides whether the breach-notification clock has started.
      </p>

      <h3>9. A BAA with every vendor handling PHI</h3>
      <p>
        §164.502(e) requires a Business Associate Agreement with every
        vendor that creates, receives, maintains, or transmits PHI on
        your behalf. This includes the CRM, the SMS provider, the
        email provider, the cloud-storage host, and the payment
        processor where they handle treatment-tied receipts. We
        wrote a separate piece on{' '}
        <Link href="/blog/what-a-baa-actually-covers">
          what a BAA actually covers
        </Link>
        .
      </p>

      <h3>10. Physical safeguards</h3>
      <p>
        §164.310 covers facility access controls, workstation security,
        device and media controls. In a small medspa: locking
        workstations when stepping away, screen filters in any
        front-desk position visible to the public, encrypted laptop
        hard drives, and a written policy for what happens to devices
        when an employee leaves.
      </p>

      <h2>The state overlays most medspas miss</h2>

      <p>
        HIPAA preempts less than people assume. State laws can add
        obligations on top, and several states actively enforce
        them. The four that catch medspas most often:
      </p>

      <h3>California — CMIA + CCPA</h3>
      <p>
        The Confidentiality of Medical Information Act (CMIA) covers
        any provider who delivers "health care," which is interpreted
        broadly enough to include cosmetic medical providers. The
        California Privacy Rights Act adds rights to access and delete
        personal information; for medical records, CMIA controls. The
        California AG has pursued CMIA actions independently of
        federal HIPAA enforcement.
      </p>

      <h3>New York — SHIELD Act</h3>
      <p>
        The SHIELD Act (General Business Law §899-bb) requires
        "reasonable safeguards" for any business that holds private
        information about a New York resident. The safeguards
        framework closely mirrors HIPAA's Security Rule, but the
        SHIELD Act applies regardless of whether you are a Covered
        Entity.
      </p>

      <h3>Texas — HB 300</h3>
      <p>
        Texas HB 300 broadens the definition of "Covered Entity"
        beyond federal HIPAA to include any business that "comes
        into possession" of PHI. Training requirements are stricter:
        within 60 days of hire, and every two years thereafter, with
        documented attendance.
      </p>

      <h3>Massachusetts — 201 CMR 17.00</h3>
      <p>
        Massachusetts' data security regulation requires a Written
        Information Security Program (WISP) for any business that
        holds Massachusetts residents' personal information,
        including a designated security officer and written policies
        on encryption, access, and disposal.
      </p>

      <h2>The vendor checks you should actually run</h2>

      <p>
        Most HIPAA failures inside medspas trace back to the vendor
        layer: a CRM without a BAA, an SMS provider that has not signed
        one, an email tool used to send signed-consent copies to
        patients without authorization. Five questions to ask any
        vendor before signing:
      </p>

      <ol>
        <li>
          Will you sign a BAA, and can I see your template before we
          contract?
        </li>
        <li>
          What does your audit log capture, and how long do you retain
          it? (Six years is the HIPAA-required minimum.)
        </li>
        <li>
          Where does my data live? Which AWS or Azure region? Is it
          encrypted at rest with a managed-key service?
        </li>
        <li>
          Have you completed a SOC 2 Type II audit, and can I see the
          attestation report under NDA?
        </li>
        <li>
          What happens to my data on termination — return, destruction,
          or both? On what timeline? Is there an export fee?
        </li>
      </ol>

      <p>
        Any vendor unwilling to answer these in writing is a vendor
        you cannot rely on for HIPAA defensibility. The trade-off is
        not cost. It is whether the OCR investigator finds documented
        diligence when they ask.
      </p>

      <h2>When to bring in a consultant</h2>

      <p>
        A HIPAA compliance consultant typically runs $1,500 to $5,000
        for an initial gap assessment, plus a similar amount annually
        for ongoing review. The math: a single tier-1 HIPAA violation
        is $137 to $68,928 per violation as of 2024 adjustment.
        Tier-4 willful neglect, uncorrected, is up to $2.13 million
        per identical violation per year. The consultant fee is
        almost always worth paying once you have more than two
        providers or a multi-location practice.
      </p>

      <h2>A reasonable order of operations</h2>

      <p>
        For an independent medspa with one location, the realistic
        90-day plan:
      </p>

      <ul>
        <li>
          <strong>Week 1</strong>: Inventory every vendor that touches
          patient data. Note which have BAAs on file.
        </li>
        <li>
          <strong>Weeks 2–3</strong>: Request BAAs from vendors that
          lack one. Escalate any vendor that refuses.
        </li>
        <li>
          <strong>Weeks 4–6</strong>: Draft a written risk assessment
          using the HHS Security Risk Assessment Tool.
        </li>
        <li>
          <strong>Weeks 7–8</strong>: Write or revise the workforce
          training material; deliver it; collect signed acknowledgments.
        </li>
        <li>
          <strong>Weeks 9–10</strong>: Document the incident response
          procedure and post it where staff can find it.
        </li>
        <li>
          <strong>Weeks 11–12</strong>: Run a backup-restore test.
          Document the result.
        </li>
      </ul>

      <p>
        That gets you defensibly to "HIPAA-aligned." The annual cycle
        is the same list, lighter, plus updated training and a fresh
        risk assessment.
      </p>

      <h2>How Lumè handles the CRM-layer items</h2>

      <p>
        We built Lumè around the parts of this list that fall on the
        CRM specifically. Worth knowing when you evaluate vendors:
      </p>

      <ul>
        <li>
          <strong>Tenant isolation</strong> is enforced at the database
          layer — every PHI-bearing table carries a tenant FK, and
          queries route through a tenant-scoped manager.
        </li>
        <li>
          <strong>Audit logging</strong> is append-only at the Postgres
          trigger level. UPDATE and DELETE statements on the audit
          table are rejected. Every PHI read, every state change,
          every report export writes an entry with IP and user-agent.
        </li>
        <li>
          <strong>Encryption</strong> is AES-256 at rest via AWS KMS,
          TLS 1.2+ in transit.
        </li>
        <li>
          <strong>The BAA</strong> is included in every customer
          contract — not a premium tier. We summarize what it covers
          on{' '}
          <Link href="/baa">/baa</Link>.
        </li>
        <li>
          <strong>Data export</strong> is one click on every report.
          On termination, return or destruction is in the BAA. No
          export fees, ever.
        </li>
      </ul>

      <p>
        The rest — workforce training, written sanction policies,
        physical safeguards in your own facility — is your
        responsibility. No CRM can do that piece for you, and any CRM
        that claims to is exaggerating.
      </p>

      <hr />

      <p>
        <em>References:</em> 45 CFR §164.302–.318 (HIPAA Security
        Rule); 45 CFR §164.500–.534 (HIPAA Privacy Rule); HHS Office
        for Civil Rights{' '}
        <a
          href="https://www.hhs.gov/hipaa/for-professionals/compliance-enforcement/data/index.html"
          target="_blank"
          rel="noopener noreferrer"
        >
          enforcement highlights
        </a>
        ; California Civil Code §56 (CMIA); New York General Business
        Law §899-bb (SHIELD Act); Texas Health and Safety Code §181
        (HB 300); 201 CMR 17.00 (Massachusetts).
      </p>
    </BlogPostLayout>
  );
}
