/**
 * Blog post: AI SMS agents for medical spas.
 *
 * Feature-forward piece explaining how AI SMS concierge agents work
 * in a medspa context, what they can and can't do, how they compare
 * to human front-desk SMS, and how Lumè's implementation handles
 * HIPAA and booking reliability.
 *
 * Target queries:
 *   - "AI SMS agent medical spa"
 *   - "AI booking assistant medspa"
 *   - "automated SMS booking medspa"
 *   - "best AI text messaging for medical spas"
 *   - "Podium alternative for medical spa"
 */

import Link from 'next/link';
import type { Metadata } from 'next';

import { BlogCallout, BlogPostLayout } from '@/components/blog-post-layout';
import { findPost } from '@/lib/blog';

const meta = findPost('ai-sms-agent-for-medspas')!;

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
      standfirst="An AI SMS agent answers texts around the clock, proposes available slots, books appointments, and escalates to a human when the conversation needs one. For a medspa, the math is simple: if a front desk misses a text at 9pm, that client books somewhere else by morning."
    >
      <p>
        The front desk at most medical spas operates from 9am to 6pm.
        Client interest does not. People text during their lunch
        break, at 11pm after seeing a social post, on Sunday morning
        after a friend mentions laser results. A response that arrives
        eight hours later isn't a response — it's a slot your
        competitor filled.
      </p>

      <p>
        AI SMS agents are not a novelty at this point. They're a
        solved category in restaurant reservations, real estate
        showings, and dental practices. Medical spas are adopting
        them later than they should, in part because the HIPAA
        surface — treatment history, provider schedules, client
        records — makes the integration harder than a simple
        chatbot. The category is now mature enough that
        HIPAA-compliant implementations exist.
      </p>

      <h2>What an AI SMS agent actually does</h2>

      <p>
        A well-designed AI SMS agent for a medspa handles the
        full inbound booking flow without human intervention:
      </p>

      <ol>
        <li>
          <strong>Greet and qualify.</strong> When a new number
          texts the spa's line, the agent greets them, captures
          their name, and asks what service they're interested in.
          It checks your service catalog to match their intent to
          a real service — "I want something for my forehead
          lines" becomes a Botox consultation in the booking
          system, not a generic "facial."
        </li>
        <li>
          <strong>Check availability.</strong> The agent queries
          real-time schedule data, filtering to providers who are
          qualified for the requested service — a laser technician
          for laser hair removal, an RN or NP for injectables.
          When the client says "Monday around 2pm," the agent
          returns afternoon slots, not 9am ones.
        </li>
        <li>
          <strong>Propose and confirm.</strong> The agent offers
          two to three specific times in plain language: "I have
          Monday at 1:30pm with Julia, Tuesday at 2pm with Lilian,
          or Friday at 2:15pm with Sloane. Reply 1, 2, or 3 to
          confirm." A digit reply commits the booking.
        </li>
        <li>
          <strong>Handle objections.</strong> If the client says
          "that's expensive," the agent doesn't just repeat the
          price — it checks whether the client has an active
          package or membership covering the service, mentions
          package pricing that reduces per-session cost, and
          offers a free consultation. This is where most basic
          chatbots fail; a trained agent treats it as a sales
          conversation.
        </li>
        <li>
          <strong>Escalate to human.</strong> Anything outside its
          scope — a refund dispute, a clinical question, a
          complaint, or an explicit "I want to talk to a person"
          — is handed off immediately. The agent sends a handoff
          message to the client and fires an alert to the spa's
          staff inbox. A staff member sees the conversation in the
          messaging inbox with full context.
        </li>
      </ol>

      <BlogCallout label="How Lumè implements this">
        <p>
          Lumè's AI SMS agent runs on Claude Sonnet (Anthropic's
          model) via a HIPAA-eligible infrastructure path. The
          system prompt carries only tenant configuration —
          business name, service hours, escalation keywords — never
          client PHI. Client data (appointment history, packages,
          memberships) flows to the agent only through explicit,
          allow-listed tool calls, with hard exclusions on chart
          notes, medical history, and intake form answers. Every
          tool call writes an audit log entry. The agent's daily
          send cap prevents runaway messaging. Staff can pause the
          AI per-conversation from the messaging inbox at any time.
        </p>
      </BlogCallout>

      <h2>What an AI SMS agent doesn't do</h2>

      <p>
        Being clear about limits is part of building trust. A
        mature AI SMS agent for a medspa should not attempt:
      </p>

      <ul>
        <li>
          <strong>Medical advice.</strong> Any question about
          whether a treatment is right for a specific condition,
          drug interactions, contraindications, or dosage triggers
          an immediate escalation to a qualified provider. Full
          stop.
        </li>
        <li>
          <strong>Cancellations and reschedules of existing
          appointments.</strong> These require policy decisions
          (deposit forfeiture, waitlist management, provider
          notification) that belong to a human and your practice
          management software's workflow. The agent flags these
          for staff rather than attempting them.
        </li>
        <li>
          <strong>Refunds and payment disputes.</strong> Same
          reason. These get escalated immediately.
        </li>
      </ul>

      <h2>The HIPAA surface</h2>

      <p>
        This is the reason most medspas have been slow to adopt AI
        SMS. The concern is legitimate: if an AI agent has access
        to your client records, and that agent sends PHI over SMS,
        you have a breach. There are three layers where this can go
        wrong.
      </p>

      <p>
        The first is <strong>the LLM provider itself.</strong>{' '}
        OpenAI, Anthropic, and Google all offer BAA-eligible
        infrastructure paths. Using a model through a BAA-covered
        endpoint is a prerequisite for any PHI-adjacent AI
        application. Using the consumer API is not.
      </p>

      <p>
        The second is <strong>what data reaches the model.</strong>{' '}
        System prompts — the instructions that tell the model how
        to behave — must be PHI-free. Client data should reach the
        model only through structured tool calls with explicit
        allow-lists. An agent that ingests chart notes or medical
        history is operating outside your BAA scope.
      </p>

      <p>
        The third is <strong>the outbound channel itself.</strong>{' '}
        SMS is not encrypted end-to-end. What you say in a text
        is what the carrier can see. Keeping AI-generated SMS to
        booking logistics — times, confirmations, service names —
        and escalating anything clinical or payment-related to a
        phone call or a secure portal keeps you in a defensible
        position.
      </p>

      <BlogCallout label="The safeguard Lumè runs">
        <p>
          Before every outbound SMS is sent, Lumè's AI agent runs
          a pattern scan for sensitive data sequences (SSN, DOB,
          payment card numbers). A match blocks the send and
          escalates the conversation immediately. It&apos;s a
          defense-in-depth measure: the agent is instructed not to
          produce those patterns, and the pre-send scanner catches
          the rare case where instruction doesn&apos;t hold.
        </p>
      </BlogCallout>

      <h2>The business case in plain numbers</h2>

      <p>
        A medspa doing $1.2M in annual revenue — typical for a
        two-provider practice in a metro market — handles roughly
        15–25 inbound booking texts per day. If the practice
        misses 20% of those because they come in outside business
        hours or during a busy treatment block, that's 3–5 missed
        contacts per day. At a $350 average ticket, that's $1,050
        to $1,750 in daily lost opportunity, or roughly $250,000
        to $420,000 annualized — assuming even half of those
        contacts would have converted.
      </p>

      <p>
        Recovering 30% of those missed contacts with an AI agent
        — a conservative estimate based on response rates in
        comparable service industries — would represent $75,000
        to $125,000 in recovered revenue per year. The agent
        costs a fraction of that.
      </p>

      <p>
        The operational argument is separate: front-desk staff
        handling inbound SMS during a busy treatment day is
        distracted front-desk staff. The AI handles routine
        booking while the human handles check-in, payment, and
        the conversations that actually require a human.
      </p>

      <h2>Comparing Lumè to Podium for medspa AI SMS</h2>

      <p>
        Podium is the most common AI SMS tool medspas evaluate.
        It is purpose-built for review management and lead
        response, and its AI agent is solid. The limitation for
        medspas is integration depth: Podium connects to your
        CRM via Zapier or a webhook, but it doesn't read your
        live schedule, provider eligibility rules, or package
        balances. The agent can respond and refer, but it can't
        actually check a slot, confirm provider availability for
        a specific service, or tell a client they have two
        remaining sessions on their package.
      </p>

      <p>
        Lumè's AI agent runs inside the same system that manages
        your calendar, so it has real-time access to availability,
        staff schedules, and client account balances through
        structured, audited tool calls. When the agent proposes
        a slot, it's a real slot the booking system will hold.
        When it mentions a package balance, that's the live
        number from your account.
      </p>

      <p>
        Podium costs approximately $400–$600/month as a standalone
        add-on. Lumè's AI SMS agent is included in the Pro tier
        at $249/month, alongside the full medspa CRM.
      </p>

      <h2>What to look for in an AI SMS agent</h2>

      <p>
        If you're evaluating options, the questions that separate
        capable implementations from marketing claims:
      </p>

      <ul>
        <li>Does the agent check real-time schedule data, or does it route to a human for availability?</li>
        <li>Does it filter providers by service eligibility (not just "anyone bookable")?</li>
        <li>What data does the system prompt contain — is it PHI-free?</li>
        <li>Is the LLM provider on a BAA-eligible path?</li>
        <li>Can staff pause the AI per-conversation from the inbox?</li>
        <li>What is the escalation trigger — how does it decide to hand off?</li>
        <li>Is there a daily send cap? What happens when it's hit?</li>
        <li>How does the agent handle price objections? Does it escalate or sell?</li>
      </ul>

      <p>
        The technology is available and HIPAA-defensible. The
        question for each practice is whether the integration is
        deep enough to actually book — not just respond.
      </p>

      <p>
        Lumè's AI SMS agent is included in Pro.{' '}
        <Link
          href="/demo"
          className="text-accent underline underline-offset-2 hover:text-foreground transition-colors"
        >
          Request a demo
        </Link>{' '}
        to see it configured on your service catalog and schedule.
      </p>
    </BlogPostLayout>
  );
}
