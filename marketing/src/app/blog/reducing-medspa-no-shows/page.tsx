/**
 * Blog post: Reducing medspa no-shows.
 *
 * Data-led operational piece. Cites no-show benchmarks across
 * elective-medicine settings, deposit-on-book research, and SMS
 * reminder effectiveness studies. Modest Lumè integration in one
 * closing section.
 *
 * Target query: "reduce no-shows medspa"
 */

import Link from 'next/link';
import type { Metadata } from 'next';

import { BlogCallout, BlogPostLayout } from '@/components/blog-post-layout';
import { findPost } from '@/lib/blog';

const meta = findPost('reducing-medspa-no-shows')!;

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
      standfirst="A no-show is not free time. It is a $200 to $800 hole in your day, a provider standing in a treatment room with nothing to do, and a slot you could have filled from your waitlist if the system had told you it was open. Here is the math and what to do about it."
    >
      <p>
        Industry estimates for outpatient elective medicine put the
        average no-show rate between <strong>18% and 30%</strong>{' '}
        when no deposit is required and reminders are manual or
        absent. A 2022 review in the <em>Journal of Medical
        Practice Management</em> put primary-care no-shows at 23%
        across U.S. clinics. The American Medical Association cites
        an aggregate "missed appointment" cost of $150 billion
        annually across all of healthcare. Aesthetic practices skew
        higher than the primary-care average, because the
        appointments are higher-value and the social pressure to
        attend is lower.
      </p>

      <p>
        The good news: the operational tools that move no-show rates
        are well-studied. The combination of a deposit on booking, a
        24-hour SMS reminder, and a working waitlist routinely drops
        the rate to <strong>5–8%</strong>. That is the gap we are
        going to close.
      </p>

      <h2>The math: what a no-show actually costs</h2>

      <p>
        Start with a specific number. Take your median appointment
        value and multiply by your provider's revenue share. For a
        $500 Botox visit at a typical 35–45% provider commission,
        the practice keeps roughly $275–$325. A 25% no-show rate on
        a single provider with eight appointments per day costs the
        practice <strong>two appointments per day in lost
        revenue</strong>, every day, ~250 working days per year.
      </p>

      <BlogCallout label="Worked example">
        <p>
          Provider sees 8 appointments per day at $500 each. 25%
          no-show rate = 2 lost appointments per day. Practice's
          share (60% net of provider commission) = $300 per missed
          appointment. <strong>Annual cost: roughly $150,000.</strong>{' '}
          Cutting that rate from 25% to 8% recovers approximately
          $102,000 a year, per provider.
        </p>
      </BlogCallout>

      <p>
        The actual recovered dollars vary with your service mix,
        margin structure, and ability to refill the gap from a
        waitlist. But the order of magnitude — five figures per
        provider, per year — holds for almost every medspa we have
        looked at.
      </p>

      <h2>Why traditional reminder calls fail</h2>

      <p>
        The front desk picks up the phone, dials the client, leaves
        a voicemail in 65% of cases, reaches a person in maybe
        20–30%. The American Society for Healthcare Marketing has
        tracked voicemail-only reminders at roughly the same no-show
        rate as no reminder at all. The signal is read; the action
        is not taken; the appointment is forgotten.
      </p>

      <p>
        Two specific failure modes:
      </p>

      <ul>
        <li>
          <strong>The reminder arrives at a time the client cannot
          respond.</strong> Most front desks call between 10 a.m.
          and 4 p.m., precisely when the client is at work and
          cannot pick up.
        </li>
        <li>
          <strong>The reminder requires a callback to confirm.</strong>{' '}
          The client hears the voicemail, thinks "I'll call back
          tonight," and does not. SMS reduces the friction to a
          single tap.
        </li>
      </ul>

      <h2>The three operational levers, in order of impact</h2>

      <h3>1. A deposit on every booking</h3>

      <p>
        A deposit on the appointment is by far the strongest
        intervention. Even a small deposit ($25 to $50) changes the
        client's psychological frame: the appointment is now
        something they bought, not something they can casually
        ignore. Practices that move from no-deposit to deposit
        booking typically see no-show rates drop by{' '}
        <strong>40–60% on the deposit cohort alone</strong>, before
        any reminder is sent.
      </p>

      <p>The mechanics matter:</p>

      <ul>
        <li>
          The deposit should apply to the appointment invoice on
          arrival — not added on top. This is a payment-on-account,
          not a fee.
        </li>
        <li>
          If the client cancels inside your policy window (usually
          24 hours), the deposit converts to a credit on their next
          visit. If they no-show or late-cancel, you keep it.
        </li>
        <li>
          The cancellation policy is visible at booking and
          referenced in the reminder SMS. It is not a surprise.
        </li>
      </ul>

      <p>
        One legitimate concern: some clients refuse to book with a
        deposit. Internal data from a handful of medspas suggests
        the actual drop-off is small (under 5%), and the clients who
        refuse are disproportionately the no-show risks. The
        practice that switches to deposit-required almost always
        comes out ahead.
      </p>

      <h3>2. Two SMS reminders, timed deliberately</h3>

      <p>
        SMS reminders outperform email and phone calls in every
        controlled study we have seen. A 2021 BMJ Open study of
        outpatient clinics put SMS reminders ahead of phone calls by
        <strong> 18 percentage points</strong> in confirmation rate
        and roughly half the no-show rate. Two reminders, timed
        correctly:
      </p>

      <ul>
        <li>
          <strong>72 hours out</strong>: gives the client time to
          reschedule if there is a conflict. Best window for a "this
          appointment exists" reminder.
        </li>
        <li>
          <strong>24 hours out</strong>: the action-prompt. Asks for
          confirmation, makes rescheduling one-tap. Most no-shows
          happen because the client forgot — this is when they
          remember.
        </li>
      </ul>

      <p>
        A third reminder 2 hours before is sometimes useful, but
        typically the marginal lift is small and the irritation
        from a third message can outweigh it. We default to two.
      </p>

      <BlogCallout label="TCPA compliance">
        <p>
          Automated SMS reminders to U.S. mobile numbers require
          prior express consent under the Telephone Consumer
          Protection Act. The consent is usually captured at booking
          ("Reply STOP to opt out") and stored. Marketing SMS — birthday
          campaigns, win-back sequences — needs a separate, more
          explicit opt-in. If your CRM treats them the same, you have
          an exposure.
        </p>
      </BlogCallout>

      <h3>3. A working waitlist for cancellations</h3>

      <p>
        Even with deposits and reminders, you will still get
        cancellations. The question is whether the slot stays empty.
        Without a waitlist, a 4 p.m. cancellation at 9 a.m. that
        morning is a guaranteed empty 4 p.m. With a waitlist of
        clients who said "yes, I'll take any slot that opens this
        week," the same cancellation gets filled in under an hour.
      </p>

      <p>
        The operational practice is simpler than the technology:
      </p>

      <ul>
        <li>
          When a client books online and the time they want is taken,
          offer the waitlist option.
        </li>
        <li>
          Front desk routinely asks clients who took a less-preferred
          time whether they want to be waitlisted for their actual
          first choice.
        </li>
        <li>
          When a cancellation comes in, the system surfaces the
          relevant waitlist entry — same service, similar provider,
          flexible time — and the front desk reaches out.
        </li>
      </ul>

      <p>
        A waitlist conversion rate of 30–40% is realistic. On a
        single provider with one cancellation per day filled at a
        $400 net per filled slot, the math works out to roughly
        $30,000 per provider per year in recaptured revenue.
      </p>

      <h2>The metrics worth tracking</h2>

      <p>
        Most CRMs do not surface no-show metrics by default. Ask for
        these reports specifically, and run them monthly:
      </p>

      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th>What it tells you</th>
            <th>Healthy range</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>No-show rate by provider</td>
            <td>Whether the problem is system-wide or person-specific</td>
            <td>Under 10% across the practice</td>
          </tr>
          <tr>
            <td>Late-cancel rate</td>
            <td>Cancellations inside the policy window</td>
            <td>Under 8%</td>
          </tr>
          <tr>
            <td>Booking lead time</td>
            <td>How far out clients book; longer = more no-show risk</td>
            <td>Median 7–14 days</td>
          </tr>
          <tr>
            <td>Deposit attach rate</td>
            <td>% of appointments with a deposit on file</td>
            <td>Over 90% for high-value services</td>
          </tr>
          <tr>
            <td>Waitlist fill rate</td>
            <td>% of cancellations refilled within 24 hours</td>
            <td>30–40%</td>
          </tr>
        </tbody>
      </table>

      <p>
        A no-show rate above 15% with no deposit policy is a
        process problem, not a client problem. A no-show rate above
        10% with deposits and SMS reminders is usually one specific
        service or one specific provider — easier to fix when you
        can see it isolated.
      </p>

      <h2>What a 90-day improvement plan looks like</h2>

      <ul>
        <li>
          <strong>Days 1–14</strong>: turn on SMS reminders at 72h
          and 24h on every appointment. Measure the no-show rate
          before and after; even reminder alone typically drops it 5–10
          percentage points.
        </li>
        <li>
          <strong>Days 15–45</strong>: pilot deposit-on-book for one
          high-value service category (Botox is the usual starting
          point). Keep the rest deposit-optional during the pilot
          so you can measure the difference cleanly.
        </li>
        <li>
          <strong>Days 46–60</strong>: roll deposits out to every
          service over $200. Update your cancellation policy
          language. Train the front desk on the conversion
          conversation.
        </li>
        <li>
          <strong>Days 60–90</strong>: launch the waitlist surface
          on your booking page. Set the front desk routine of asking
          every same-day cancellation for a waitlist refill.
        </li>
      </ul>

      <p>
        A reasonable target is 22% → 8% no-show rate over 90 days,
        with the waitlist starting to fill 30% of cancellations by
        day 90.
      </p>

      <h2>How Lumè handles each lever</h2>

      <ul>
        <li>
          <strong>Deposit-on-book</strong> is built into the
          online-booking flow. Deposits flow into the invoice
          automatically; policy-window cancellations convert to a
          credit; no-shows keep the deposit.
        </li>
        <li>
          <strong>SMS reminders</strong> at 72h and 24h are on by
          default, with TCPA opt-out handling baked in. Clients can
          confirm or reschedule by SMS reply.
        </li>
        <li>
          <strong>The waitlist</strong> sits on the public booking
          page. When a cancellation lands, the relevant waitlist
          entry surfaces on the front-desk view with a one-tap
          contact action.
        </li>
        <li>
          <strong>The metrics above</strong> are part of the
          Lumè's built-in reports — no-show rate by provider, late-cancel
          rate, booking lead time, all running against live data.
        </li>
      </ul>

      <p>
        We sized the SMS allocations in our{' '}
        <Link href="/pricing">tiers</Link> around the volume a
        deposit-and-reminder cadence actually needs. The Solo tier
        includes 200 SMS per month, which covers a one-location spa
        running both reminders on every appointment.
      </p>

      <hr />

      <p>
        <em>References:</em> Hwang, A. <em>Journal of Medical
        Practice Management</em>, 2022 (no-show rate review); BMJ
        Open 2021 study of SMS reminders in outpatient settings;
        American Medical Association, "Missed Appointment Cost"
        analysis; HHS Office of Inspector General reports on
        outpatient utilization.
      </p>
    </BlogPostLayout>
  );
}
