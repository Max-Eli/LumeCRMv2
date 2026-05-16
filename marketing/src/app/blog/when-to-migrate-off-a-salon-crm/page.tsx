/**
 * Blog post: When to migrate off a salon CRM.
 *
 * Direct competitor displacement. Names Mindbody, Vagaro, Boulevard
 * specifically, walks through what to export, what's hard to move,
 * and the realistic timeline. Lumè integration confined to the
 * final section.
 *
 * Target query: "migrate from Mindbody / Vagaro to medspa CRM"
 */

import Link from 'next/link';
import type { Metadata } from 'next';

import { BlogCallout, BlogPostLayout } from '@/components/blog-post-layout';
import { findPost } from '@/lib/blog';

const meta = findPost('when-to-migrate-off-a-salon-crm')!;

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
      standfirst="Mindbody, Vagaro, and Boulevard were built for salons. Medspas use them anyway, then spend the next two years working around the gaps. Here are the three operational signals you have outgrown a salon CRM, the data you must extract before signing anywhere new, and what a clean 2–4 week migration actually looks like."
    >
      <p>
        The most common path into a medspa CRM is not a deliberate
        choice. It is whatever the original esthetician used when
        the practice opened with one chair, which then survived
        through provider hires, second locations, and the
        introduction of medical-grade services. By year three, the
        software is doing 60% of what the practice needs and the
        front desk is doing the other 40% in spreadsheets, paper
        forms, and a separate payment terminal.
      </p>

      <p>
        That state is workable. It is also expensive in ways that
        do not show up on the invoice. This piece is for operators
        who have started feeling those costs and are weighing
        whether to migrate.
      </p>

      <h2>Three signals you have outgrown a salon CRM</h2>

      <h3>1. Your consent forms live anywhere but the chart</h3>

      <p>
        Salon-first platforms shipped without per-treatment consent
        because hair salons do not need it. The workarounds — paper
        forms in a filing cabinet, PDF e-sign in a separate tool,
        consent forms scanned and emailed — accumulate compliance
        risk in a way most operators do not see until a state board
        inspection. If your medspa books Botox or filler and the
        consent does not auto-attach to the appointment when it is
        booked, the system is wrong, not your staff.
      </p>

      <h3>2. Your daily close-out involves the word "reconcile"</h3>

      <p>
        A daily close-out where the CRM's number does not match the
        terminal's number is a flag. It usually means the CRM
        treats payment as informational — a record that someone
        paid, but the actual money flowed through a separate system
        the CRM has no visibility into. Multiply that across three
        payment methods and you are doing reconciliation work every
        evening that should not exist in a modern system.
      </p>

      <h3>3. You have started building reporting in Google Sheets</h3>

      <p>
        The clearest signal. When a manager exports a CSV from the
        CRM every Monday, opens it in Sheets, and runs the actual
        report the practice needs — that is software-shaped work
        the platform should be doing. Reporting gaps are the
        operational equivalent of leaks: small at first, expensive
        at scale.
      </p>

      <BlogCallout label="A useful question">
        <p>
          Ask your front desk what they wish the software did that
          it does not. The answer is usually one of three things:
          consent that attaches to appointments, a close-out that
          ties out, or a report that already exists in their head
          but lives in no system.
        </p>
      </BlogCallout>

      <h2>What is actually different for medspas</h2>

      <p>
        Five operational differences between salons and medspas
        that the major salon platforms either do not model or model
        thinly:
      </p>

      <ul>
        <li>
          <strong>Per-treatment consent recurrence.</strong> Hair
          salons need one intake form per client, signed once.
          Medspas need a fresh consent at every Botox, filler, and
          laser visit, because the risk profile is per-procedure.
          Salon platforms attach forms to clients, not appointments.
        </li>
        <li>
          <strong>Treatment-cycle scheduling.</strong> Botox at 12–14
          weeks. Filler at 6–12 months depending on product. Laser
          series at 4–6 weeks. The next-visit suggestion at checkout
          should be deposit-on-book, not "we will see you whenever."
        </li>
        <li>
          <strong>Provider commission and treatment attribution.</strong>{' '}
          Medspas often pay providers per-treatment commission, not
          flat hourly. The CRM must split revenue by provider per
          line item, and report it that way.
        </li>
        <li>
          <strong>Medical-grade audit logging.</strong> If your state
          medical board asks who viewed a chart on a specific day,
          you need to answer in seconds, not days. Salon platforms
          generally do not write that log.
        </li>
        <li>
          <strong>The BAA cascade.</strong> If you are a HIPAA-covered
          medspa (most are, even when they don't realize it), every
          vendor that touches PHI needs a Business Associate
          Agreement on file. Most salon platforms gate the BAA
          behind a premium tier or do not offer it at all.
        </li>
      </ul>

      <h2>What to export before you sign anywhere</h2>

      <p>
        The single biggest migration mistake: signing the new contract
        before confirming you can actually get your data out of the
        old one. The export shape matters more than the new vendor's
        import promise.
      </p>

      <p>The data you must extract:</p>

      <ol>
        <li>
          <strong>Customer records</strong>: contact information,
          birthday, allergies, medical history, treatment history,
          loyalty status. Confirm fields like allergies and notes
          come out in a structured format, not as free-text blobs.
        </li>
        <li>
          <strong>Appointment history</strong>: past appointments,
          including no-shows and cancellations, with timestamps,
          provider, service, and outcome. Two years minimum.
        </li>
        <li>
          <strong>Signed consent forms</strong>: as PDFs, with
          timestamps and signature metadata. This is often the
          hardest export, because some platforms only return the
          form image without the metadata that makes it
          audit-defensible.
        </li>
        <li>
          <strong>Invoice and payment history</strong>: for AR aging,
          revenue history, and tax records. Confirm payment-method
          breakdown comes out (cash vs card vs check), not just
          totals.
        </li>
        <li>
          <strong>Memberships and packages</strong>: outstanding
          balances, expiration dates, attached clients. Skipping
          this on migration is how spas lose revenue they had
          already collected.
        </li>
        <li>
          <strong>Gift card balances</strong>: outstanding balances
          and the underlying ledger. Mishandled gift cards become
          accounting and customer-service problems for years.
        </li>
        <li>
          <strong>Marketing audience and opt-in status</strong>: who
          consented to SMS, who consented to email, when. TCPA
          opt-in does not transfer if the underlying consent record
          does not.
        </li>
      </ol>

      <h3>The platforms that make this hard</h3>

      <p>
        Aesthetic Record has been reported on Capterra and Software
        Advice to charge a <strong>$1,120 fee</strong> to export
        patient data after the first two years. That is a contract
        clause to read carefully before signing.
      </p>

      <p>
        Mindbody and Vagaro typically permit CSV exports but limit
        the level of detail; some structured fields come out as
        free-text. Boulevard's exports are reasonably complete but
        may require a support ticket for historical data beyond a
        certain age.
      </p>

      <p>
        Ask every vendor — yours and the new one — three questions
        in writing:
      </p>

      <ul>
        <li>What is included in a standard data export?</li>
        <li>Are there any fees for export, ever?</li>
        <li>What is the timeline from request to delivery?</li>
      </ul>

      <p>
        Any vendor that cannot answer those in writing is a vendor
        you are not in control of.
      </p>

      <h2>The cost of staying</h2>

      <p>
        Migration is real work. Estimating the cost of the status
        quo is how you justify the work.
      </p>

      <p>Rough math for a one-location medspa with three providers:</p>

      <table>
        <thead>
          <tr>
            <th>Hidden cost</th>
            <th>Estimated annual hit</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Front desk time on workarounds (2 hr/day × $20/hr × 250 days)</td>
            <td>~$10,000</td>
          </tr>
          <tr>
            <td>No-shows above industry-best from missing deposit flow (10pt × ~$300 × 1,200 appts)</td>
            <td>~$36,000</td>
          </tr>
          <tr>
            <td>Card-volume markup at 1.5% on $1.5M annual volume</td>
            <td>~$22,500</td>
          </tr>
          <tr>
            <td>Premium-tier upgrades for features that should be standard (Forms, QuickBooks, etc.)</td>
            <td>~$1,500</td>
          </tr>
          <tr>
            <td>Compliance gap (un-quantifiable until it becomes very expensive)</td>
            <td>—</td>
          </tr>
        </tbody>
      </table>

      <p>
        The numbers vary by practice. The order of magnitude — a
        five-figure annual cost for a single-location medspa — does
        not.
      </p>

      <h2>A realistic 2–4 week migration timeline</h2>

      <h3>Week 1: Scoping</h3>
      <p>
        Pull a sample export from the current platform. Map fields
        between source and destination. Identify any data that
        requires manual cleanup (free-text fields, photos,
        unstructured allergy notes). Write a one-page migration
        spec — what moves, what stays, what gets archived.
      </p>

      <h3>Week 2: Dry run</h3>
      <p>
        Run a non-production import of the export into the new
        platform. Verify customer counts, appointment counts,
        invoice totals match the source. Spot-check a dozen client
        charts end-to-end. Document any discrepancies.
      </p>

      <h3>Week 3: Cutover preparation</h3>
      <p>
        Train front-desk staff on the new platform. Run them
        through 20 mock workflows: book, check in, take payment,
        send consent. Choose a cutover date — typically a Sunday
        evening so the practice goes live on a Monday morning. Send
        client-facing communications about the new booking page if
        the URL is changing.
      </p>

      <h3>Week 4: Cutover + parallel period</h3>
      <p>
        Final export from the source on cutover day. Final import
        into the destination. Verify the daily close-out for the
        first week on the new platform reconciles cleanly. Keep
        the source platform accessible (read-only) for 90 days in
        case a question about historical data comes up.
      </p>

      <h2>What we have learned from medspas migrating onto Lumè</h2>

      <p>
        Two medspas are migrating onto Lumè in 2026. We are taking
        on a small, deliberate number of additional customers this
        year so we stay close to every onboarding. From the two
        we have run so far, three patterns:
      </p>

      <ul>
        <li>
          <strong>The export is always lossier than the vendor
          claims.</strong> Plan for a half-day of manual cleanup
          on consent metadata and provider notes.
        </li>
        <li>
          <strong>The cutover is rarely the hard part.</strong>{' '}
          Training the front desk on the new workflows takes the
          most time. Schedule that ahead of the import, not after.
        </li>
        <li>
          <strong>The first daily close-out is the moment of
          truth.</strong> If the numbers tie out on day one, the
          migration is done. If they do not, you know within 24
          hours where to fix.
        </li>
      </ul>

      <p>
        Our scoping conversation during the demo includes the
        export-shape review and a migration timeline based on your
        actual data. The fee for the migration is bundled into the
        onboarding — there is no separate setup line on the
        invoice. See <Link href="/pricing">pricing</Link> for the
        broader structure.
      </p>

      <p>
        If you are running on Mindbody, Vagaro, Boulevard,
        Aesthetic Record, or a spreadsheet, the migration is in
        scope. Most complete in two to four weeks.{' '}
        <Link href="/demo">Request a demo</Link>; we will look at
        a sample export from your current platform and tell you
        what we see.
      </p>

      <hr />

      <p>
        <em>References:</em> Capterra and Software Advice user
        reviews of Aesthetic Record, Mindbody, Vagaro, and Boulevard
        (2024–2026); HIPAA §164.502(e) (Business Associate
        requirements); state medical board export and retention
        guidance (CA, NY, TX, MA).
      </p>
    </BlogPostLayout>
  );
}
