# Blog drafting workflow

How to write a new post in 2 hours instead of 6, without producing
AI-generated slop that Google demotes.

The TL;DR: do NOT publish AI output unchanged. Use AI as a research
and drafting accelerator, then add your own expertise, your own
opinions, and verify every fact yourself. The published post should
have you (a human who runs a medspa CRM) as the actual author, with
AI as a hidden tool.

---

## Why not just auto-publish AI posts?

Three reasons:

1. **Google's "Scaled Content Abuse" policy** (March 2024) demotes
   sites that publish unsupervised AI content at volume. Sites
   doing this typically lose 60–90% of their organic traffic
   within six months of detection. The detection is good and
   getting better.
2. **The four launch posts rank well because they cite specific
   statutes, real industry numbers, and take opinionated
   positions.** Unsupervised AI won't sustain that quality.
   Hallucinated citations get caught; sycophantic both-sides-ism
   doesn't rank.
3. **Your brand promise on the journal page** says "Long-form,
   opinionated, specific. Not '10 ways to...' listicles." An
   autopilot violates this within a month.

The right model: AI is your research intern, not your byline.

---

## The 2-hour workflow

### Step 1 — Pick a topic (15 minutes)

Use the keyword research process in `SEO_PLAYBOOK.md` to find a
query with:

- **10–500 monthly searches** (Keyword Planner volume)
- **Low or medium competition** (Keyword Planner)
- **High purchase intent** (the searcher is shopping, not browsing)
- **A natural fit for Lumè's positioning** (medspa-specific,
  compliance/operations/payments)

Good candidates:

- "Botox consent form template" — high-intent, niche
- "Medspa pricing strategy" — operational
- "TCPA compliance medspa marketing" — narrow, defensible
- "Membership program for medspa" — relates to actual feature
- "Multi-location medspa accounting" — operational

Avoid: generic "best medspa CRM" (too competitive), "what is HIPAA"
(too broad, low intent).

### Step 2 — Outline (15 minutes)

Open Claude (claude.ai) or ChatGPT. Use this prompt template:

```
You are helping me outline a long-form blog post for a HIPAA-compliant
medspa CRM. The target reader is the owner or operator of a medspa,
likely already running another platform (Mindbody, Vagaro, Boulevard,
Aesthetic Record) and considering alternatives.

Brand voice: short sentences, named competitors, real numbers, no
"in today's landscape" filler, no "let's dive in" transitions.
Opinionated, specific, not balanced both-sides-ism.

Topic: [YOUR TOPIC]
Target keyword: [YOUR KEYWORD]
Target length: 1500-2000 words
Target reader's level of expertise: knows medspa operations but
not necessarily HIPAA law or software architecture.

Generate a structured outline with:
- A hook (one specific scenario or stat to open with)
- 4-7 h2 section headings (plain-English questions or claims)
- Under each h2, 2-4 h3 subsections OR a bulleted list of points
- Specific statutes, studies, or numbers to cite (you research these)
- An "operational implications" section near the end
- A "How a HIPAA-compliant CRM handles this" final section
```

Read what comes back. Edit the outline yourself: cut sections that
feel generic, add sections you know matter, sharpen the questions.
**This is where your expertise enters the post.**

### Step 3 — First draft (45 minutes)

For each section of the outline, prompt:

```
Write the [SECTION TITLE] section of the blog post.

Length: ~200-300 words.
Voice: short declarative sentences. No em-dash sandwiches. No
"in today's landscape" type filler. Lead each paragraph with a
specific claim or number.

Cite specific sources where relevant. For HIPAA: cite 45 CFR
section numbers. For industry stats: name the study or
publication. For competitor pricing: name the platform and the
specific dollar amount.

Do NOT generate citations you can't verify. If you don't have a
specific number, leave a placeholder like [INDUSTRY DATA TBD]
that I can fill in.
```

Generate all sections. Paste them into a single doc.

**Critical**: Read the whole draft top to bottom yourself. Mark
every claim, citation, and number that needs verification.

### Step 4 — Verify, edit, and add your voice (45 minutes)

This is the part that makes the post yours:

1. **Verify every citation.** Look up the actual statute, study,
   or source. AI hallucinates citations constantly. Replace fake
   ones with real ones.
2. **Verify every number.** Industry stats, dollar amounts,
   percentages — Google any number that surprises you. AI will
   fabricate plausible-sounding statistics.
3. **Add specific operator knowledge.** Anywhere the AI generated
   generic advice, replace with something you know from running
   the CRM. "Front desk reconciles cash drawer against the close-out"
   is something only a real practitioner would write; "ensure
   accurate financial tracking" is AI slop.
4. **Cut filler.** Remove every sentence that doesn't either
   teach the reader something or earn its place in the rhythm of
   the piece.
5. **Add one opinionated take.** Every good blog post has at
   least one place where the author plants a flag. "We think
   Mindbody's pricing structure is misleading because [specific
   reason]." Take the position.

### Step 5 — Convert to a TSX file (15 minutes)

The published posts use TypeScript pages. The pattern:

1. Open one of the existing posts as a reference:
   `marketing/src/app/blog/hipaa-checklist-for-medspas/page.tsx`
2. Copy it to a new folder under `marketing/src/app/blog/<your-slug>/page.tsx`
3. Update the imports at the top (`findPost('your-slug')`).
4. Add an entry to `marketing/src/lib/blog.ts` in the `POSTS`
   array with your slug, title, summary, dates, read time,
   category, and author.
5. Write the body inside the `<BlogPostLayout>` component using
   plain HTML: `<h2>`, `<h3>`, `<p>`, `<ul>`, `<ol>`, `<li>`,
   `<table>`, `<blockquote>`, plus the `<BlogCallout>` component
   for sidebar boxes.
6. Internal links to other pages: `<Link href="/pricing">pricing</Link>`.
   External links: `<a href="..." target="_blank" rel="noopener noreferrer">...</a>`.
7. Add `<hr />` before the references section at the bottom.

### Step 6 — Build, preview, publish (5 minutes)

```bash
cd marketing
npm run dev
# visit http://localhost:3001/blog/<your-slug>
```

Skim the rendered post one more time. Edit any awkward line
breaks or formatting. Then:

```bash
git add marketing/src/app/blog/<your-slug>/ marketing/src/lib/blog.ts
git commit -m "feat(blog): <post title>"
git push
```

Vercel auto-deploys on push.

After the post is live:

1. Open Search Console.
2. URL Inspection → paste the new URL → Request Indexing.
3. Share on any social channel you have (LinkedIn especially —
   B2B SaaS traffic comes disproportionately from LinkedIn).

---

## A worked example: the prompt template in practice

Topic: "Medspa membership programs: what actually drives retention"

Opening prompt to Claude:

```
You are helping me outline a long-form blog post for a HIPAA-compliant
medspa CRM. [...standard voice instructions...]

Topic: How medspas should structure membership programs
Target keyword: "medspa membership program"
Target length: 1800 words

Generate a structured outline focusing on:
1. Why membership programs work financially (the LTV math)
2. The three common membership structures (treatment credits,
   tiered, all-access) with operational tradeoffs
3. Pricing model recommendations for each
4. Common operational pitfalls (revenue recognition, expiration
   policies, transferability)
5. How to migrate existing customers into a new membership program
6. The metrics worth tracking
7. How software should support this (final section)
```

The AI returns an outline. You edit:

- Cut the "Why memberships work financially" section. It's
  generic. Replace with "How a $200/mo Botox membership compares
  to $500 ad-hoc revenue over 18 months" — specific numbers.
- Add a section the AI didn't think of: "When NOT to launch
  memberships" (when your retention is already high; when your
  service mix doesn't fit recurrence).

Draft each section with the per-section prompt. Verify the LTV
math yourself. Add an opinionated take on which structure works
best for which kind of spa. Ship.

Total time: about 2 hours. Total result: a post that ranks on
substance, not on volume.

---

## Tools you might add later (none required for v1)

- **Surfer SEO** ($89/mo) — scores your draft against the top 20
  ranking posts for your keyword and suggests adjustments. Worth
  it once you're publishing 2+ posts per month.
- **Ahrefs** ($129/mo) — comprehensive keyword and backlink data.
  Premature for the first six months.
- **Frase.io** ($45/mo) — AI-assisted research and outline tool.
  An alternative to the Claude-prompt workflow above; some
  operators prefer the dedicated UI.

None of these matter until you've published 6–10 posts and have a
sense of which topics work. Free tools cover the first six months.

---

## What I don't recommend (and why)

- **WriteSonic, Jasper, Copy.ai, etc. "AI blog generators"**: they
  produce undifferentiated content that ranks badly. The economics
  don't work for B2B niches.
- **Content farms / freelance bulk writers for $30 a post**: same
  problem. The cheap writers don't have operational expertise; the
  posts read like cheap writers wrote them.
- **Buying "DA 60" guest posts**: this is paid backlink spam. It
  works briefly, then triggers a manual penalty when Google
  catches it (which they do, eventually).

The pattern: things that look like SEO shortcuts almost always
trade short-term gain for long-term penalty. The unglamorous,
slow work is what compounds.
