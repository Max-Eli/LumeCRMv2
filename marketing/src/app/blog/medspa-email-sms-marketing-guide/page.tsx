/**
 * Blog post: Email and SMS marketing guide for medical spas.
 *
 * Operational guide covering compliance, campaign types, benchmarks,
 * and automation strategy for medspa email + SMS marketing.
 *
 * Target queries:
 *   - "medspa email marketing"
 *   - "SMS marketing for medical spa"
 *   - "medical spa marketing campaigns"
 *   - "HIPAA compliant email marketing medspa"
 *   - "medspa retention marketing"
 */

import Link from 'next/link';
import type { Metadata } from 'next';

import { BlogCallout, BlogPostLayout } from '@/components/blog-post-layout';
import { findPost } from '@/lib/blog';

const meta = findPost('medspa-email-sms-marketing-guide')!;

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
      standfirst="The best-performing medspa marketing campaigns are not the ones with the most sophisticated creative. They're the ones sent to the right segment at the right moment in the treatment cycle — re-engagement at 90 days, touch-up at 12 weeks, membership renewal at 29 days. That requires your CRM and your marketing tool to be the same system."
    >
      <p>
        Most medspa marketing conversations start with acquisition:
        Google ads, social posts, influencer partnerships. These
        matter. But the arithmetic of a medspa business — high
        acquisition cost, high lifetime value, a treatment cycle
        that naturally drives repeat visits — means retention
        marketing almost always delivers a higher return per dollar
        than acquisition.
      </p>

      <p>
        A client who books a Botox appointment and gets no follow-up
        for six months is a client who's actively being recruited
        by your competitors. The treatment is wearing off, they're
        noticing it, and whoever gets in front of them first wins
        the rebooking. That can be you or it can be someone else.
      </p>

      <h2>Email vs. SMS: when to use each</h2>

      <p>
        Both channels have a place. The choice is not either/or;
        it's which message belongs on which channel.
      </p>

      <p>
        <strong>Email is better for:</strong>
      </p>
      <ul>
        <li>Longer-form content — seasonal promotions, service spotlights, treatment education</li>
        <li>Visual campaigns — before/after imagery, spa photography, branded templates</li>
        <li>Newsletters and digests — monthly updates, what's new, product launches</li>
        <li>Winback campaigns — lapsed clients who haven't booked in 90–180 days</li>
        <li>Pre-appointment preparation instructions (longer copy)</li>
      </ul>

      <p>
        <strong>SMS is better for:</strong>
      </p>
      <ul>
        <li>Time-sensitive offers — "this week only" fills for open slots</li>
        <li>Re-engagement for clients whose treatment is about to lapse (12-week Botox reminder)</li>
        <li>Appointment confirmations and 24-hour reminders</li>
        <li>Direct conversational booking — the AI SMS agent discussed in a separate post</li>
        <li>Membership renewal nudges (one-line, direct)</li>
      </ul>

      <BlogCallout label="Open rate benchmark">
        <p>
          SMS open rates in appointment-based service businesses
          average 82–98%, typically within 3 minutes of receipt.
          Email open rates in the medspa vertical average 22–28%.
          Both channels are valuable; they reach clients in
          different states of attention.
        </p>
      </BlogCallout>

      <h2>HIPAA and marketing consent: the rules that apply</h2>

      <p>
        Email and SMS marketing to medspa clients sits at the
        intersection of two compliance frameworks: HIPAA and TCPA.
        They are separate, and confusion between them is one of the
        most common compliance mistakes medspa operators make.
      </p>

      <p>
        <strong>HIPAA and marketing.</strong> Under the HIPAA
        Privacy Rule, using PHI to market to patients requires
        either an authorization or a very narrow exception. If
        you send a "come back for your Botox touch-up" email to a
        specific client because your CRM knows they had Botox —
        that is using PHI for marketing, and it requires explicit
        authorization unless your BAA covers it under treatment
        communications. Most medspa CRMs handle this by categorizing
        reminders as "treatment-related communications" (covered)
        vs. "promotional marketing" (requires opt-in). The
        distinction matters operationally: a re-engagement email
        about a service the client has had before is different
        from a promotional email about a new service.
      </p>

      <p>
        <strong>TCPA and SMS consent.</strong> The Telephone
        Consumer Protection Act requires prior express written
        consent before sending marketing text messages. Booking
        a client does not automatically consent them to
        promotional SMS. Best practice: collect a separate
        "I consent to receive marketing texts" checkbox at booking,
        document the timestamp and source, and honor opt-outs
        immediately. Transactional SMS (confirmations, reminders,
        clinical follow-up) operates under a different consent
        standard.
      </p>

      <BlogCallout label="Practical setup">
        <p>
          In Lumè, clients are tagged separately for{' '}
          <code>sms_opt_in</code> (transactional) and{' '}
          <code>sms_marketing_opt_in</code> (promotional). Email
          has the same distinction. Every campaign filters by the
          appropriate consent flag before sending. Opt-outs are
          captured at the carrier level (STOP keyword) and at the
          portal level, both of which immediately suppress the
          client from future marketing sends.
        </p>
      </BlogCallout>

      <h2>The five campaigns every medspa should have running</h2>

      <h3>1. The 90-day lapsed client</h3>
      <p>
        Every client who hasn't booked in 90 days and has a
        history of at least two visits is a winback candidate.
        Email first with a specific, personalized subject line
        referencing the service type (not "we miss you" — that
        pattern has a 2% click rate). Follow with SMS if no open
        at 72 hours. Include a direct booking link and, where
        appropriate, a limited-time offer for existing clients.
      </p>
      <p>
        Typical results in the medspa vertical: 12–18% re-book rate
        from lapsed clients reached by both channels.
      </p>

      <h3>2. The treatment-cycle reminder</h3>
      <p>
        Botox results typically last 10–12 weeks. Fillers, 6–18
        months depending on product and area. Laser packages run
        4–8 sessions. Your CRM knows when a client's last treatment
        was. An automated SMS at 10 weeks for Botox clients —
        "Your results will start fading around now. Want to get
        ahead of it?" — converts at significantly higher rates
        than a generic promotion because it's factually relevant
        to where the client is physically.
      </p>

      <h3>3. The birthday campaign</h3>
      <p>
        Clichéd but effective, because it's personal and the
        offer timing is natural. Birthday month email with a
        client-exclusive offer. A 15% discount on their most-booked
        service, or a complimentary add-on. Keep the copy short
        and the offer specific. "Happy birthday, here's 15% off
        your next facial this month" outperforms elaborate creative
        every time.
      </p>

      <h3>4. The package balance nudge</h3>
      <p>
        Clients who bought a 6-session laser package and have used
        2 sessions six months ago are a specific, high-value
        segment. They've already paid. They just haven't come back.
        An SMS that says "You have 4 sessions left on your laser
        package — want to schedule your next one?" converts because
        there's no purchase decision required, just a calendar
        action.
      </p>

      <h3>5. The membership renewal</h3>
      <p>
        If you run memberships, the renewal window — typically the
        week before and the day before renewal — is the highest
        churn-risk moment. A proactive email explaining what the
        membership includes, what the client has used in the
        current cycle, and what's available to them in the next
        cycle reduces voluntary cancellation meaningfully. Include
        a direct link to the client portal where they can manage
        their membership.
      </p>

      <h2>The content calendar: what to send and when</h2>

      <p>
        For a practice without a full-time marketing person, a
        sustainable email calendar looks like:
      </p>

      <ul>
        <li><strong>Monthly newsletter</strong> — what's new, any seasonal services, provider spotlight. 400–600 words. Send the first Tuesday of each month.</li>
        <li><strong>Quarterly promotion</strong> — meaningful offer tied to a natural event (New Year, spring refresh, holiday packages). Not more than four per year or the urgency evaporates.</li>
        <li><strong>Ad-hoc slot-fill SMS</strong> — when you have last-minute cancellations, a broadcast to clients who have expressed interest in that service. Keep it short: "Opening Monday at 2pm for Botox — first to reply gets it."</li>
      </ul>

      <p>
        Automated campaigns run in the background at whatever cadence
        makes clinical sense for each trigger.
      </p>

      <h2>Segmentation: the difference between spam and marketing</h2>

      <p>
        The most common reason medspa email campaigns underperform
        is sending the same message to everyone. A client who has
        only ever had facials should not receive an injectable
        promotion. A client who purchased a 10-session laser package
        last month does not need a "try laser" email.
      </p>

      <p>
        The minimum useful segments for a medspa:
      </p>

      <ul>
        <li>By last visited service category (injectables, laser, facials, body)</li>
        <li>By recency (booked in last 30 days / 31–90 days / 90+ days lapsed)</li>
        <li>By active packages or memberships</li>
        <li>By channel consent (email only / SMS only / both)</li>
        <li>By new vs. returning client</li>
      </ul>

      <p>
        Cross those segments and you have meaningful targeting. A
        "lapsed injectable client with no active package, email
        consent" is a distinct audience with a specific message
        that will land.
      </p>

      <h2>What the platform needs to support this</h2>

      <p>
        These campaigns are not hard to design. The execution
        challenge is always data access: does your marketing tool
        know who has an active package, when their last appointment
        was, which services they've had, and whether they've
        opted into SMS?
      </p>

      <p>
        Most medspas running on Mindbody, Vagaro, or Boulevard end
        up exporting CSVs to Mailchimp, Klaviyo, or another email
        tool, reconciling data by hand, and losing the real-time
        precision that makes these campaigns work. A client who
        books at 10pm via the AI SMS agent won't be in next week's
        Mailchimp import — so the "don't send to recently booked
        clients" suppression list is always stale.
      </p>

      <p>
        Lumè's marketing campaigns run against live CRM data —
        the same database that holds the appointments, packages,
        memberships, and consent flags. When a client books, they're
        immediately removed from the "lapsed" segment. When a package
        is redeemed, the balance updates in real time. No CSV
        exports, no stale lists, no double-sends to clients who
        booked yesterday.
      </p>

      <p>
        If you'd like to see the campaign builder configured for
        your client base,{' '}
        <Link
          href="/demo"
          className="text-accent underline underline-offset-2 hover:text-foreground transition-colors"
        >
          request a demo
        </Link>
        .
      </p>
    </BlogPostLayout>
  );
}
