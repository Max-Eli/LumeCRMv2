# SEO playbook for lumècrm.com

The complete cost-conscious SEO workflow for a solo operator. Every
tool listed here is free or has a meaningful free tier. The whole
playbook takes about three hours to set up the first time, then
roughly two hours a month to maintain.

If you've never done SEO before, work through the sections in order.
Skip ahead only after the previous step is done.

---

## How SEO actually works in 60 seconds

Three buckets, in order of difficulty to influence:

1. **Technical SEO** — does Google's crawler find your site, render
   it correctly, and understand what each page is about? This is
   the substrate. **Already handled** — sitemap.xml, robots.txt,
   JSON-LD, OG metadata, mobile responsive, fast page loads.
2. **On-page SEO** — does each page satisfy the search intent
   behind a specific keyword? Title tags, meta descriptions,
   headings, body copy quality, internal links. **Mostly done** —
   every page has a unique title + description, headings are
   structured, internal linking is clean. Worth revisiting every
   3–6 months as you learn what's converting.
3. **Off-page SEO** — does the rest of the internet treat your
   site as authoritative? Backlinks (other sites linking to yours)
   are the single biggest ranking factor Google still uses.
   **This is the hard part** and requires real human work — see
   the backlink section below.

Content marketing (the blog) bridges all three: each post is a
technical surface (URL, JSON-LD), an on-page asset (targets a
keyword), and a backlink magnet (other sites cite useful content).

---

## Step 1 — Submit your site to Google (30 minutes)

You need Google to discover, crawl, and index every page on the
site. The mechanism is **Google Search Console**.

### 1.1 Verify ownership

1. Open https://search.google.com/search-console and sign in with a
   Google account. Use a dedicated business Google account if you
   have one; this account becomes the audit trail for everything
   that happens here.
2. Click "Add property." Choose **Domain** (not URL prefix) and
   enter `lumècrm.com`. The Domain option covers every protocol
   and subdomain in one shot — `https`, `http`, `www`, the apex,
   and any subdomain.
3. Google gives you a TXT record to add to your DNS. It looks
   like `google-site-verification=abc123...`.
4. Open your domain registrar (Namecheap, GoDaddy, Cloudflare,
   Route 53 — wherever you bought lumècrm.com). Find the DNS
   settings.
5. Add a **TXT record** at the root (`@` or blank host). Type:
   `TXT`. Value: the entire `google-site-verification=...` string
   Google gave you. TTL: leave default.
6. Back in Search Console, click **Verify**. DNS propagation
   usually takes 5–15 minutes; if it fails on the first attempt,
   wait and try again.

### 1.2 Submit the sitemap

Once verified:

1. In Search Console, open the **Sitemaps** section (left nav).
2. Add a new sitemap: type `sitemap.xml` (Google figures out the
   full URL). Submit.
3. Within a few hours, Google will report status as "Success" with
   a count of URLs discovered.

The sitemap currently lists 21 URLs. Google will crawl them over
the next 2–7 days. You can speed this up for priority pages with
URL Inspection (next step).

### 1.3 Request indexing for priority pages

For each of these URLs, paste into the **URL Inspection** bar at
the top of Search Console and click **Request Indexing**:

```
https://lumècrm.com/
https://lumècrm.com/features
https://lumècrm.com/pricing
https://lumècrm.com/medspas
https://lumècrm.com/blog
https://lumècrm.com/blog/hipaa-checklist-for-medspas
https://lumècrm.com/blog/reducing-medspa-no-shows
https://lumècrm.com/blog/when-to-migrate-off-a-salon-crm
https://lumècrm.com/blog/what-a-baa-actually-covers
```

Google rate-limits manual indexing requests to roughly 10 per day
per property, so prioritize: home + the 4 blog posts on day one,
the rest on day two.

### 1.4 Set up Bing Webmaster Tools (15 minutes)

Bing's index also powers ChatGPT search, DuckDuckGo, and Yahoo. Free.

1. Go to https://www.bing.com/webmasters and sign in.
2. Click **Import from Google Search Console** — Bing reuses your
   verification, so this is the fast path. Approve the import.
3. Submit `https://lumècrm.com/sitemap.xml` in the **Sitemaps**
   section.

That's it for the first day. Search engines now know your site
exists and have a complete map of its pages.

---

## Step 2 — What to check after Google starts crawling (~7 days)

A week after submission, log into Search Console and look at the
following reports.

### 2.1 Indexing → Pages

Three buckets:

- **Indexed** — pages Google has added to its index. Goal: every
  page in the sitemap shows up here.
- **Not indexed: Crawled but not indexed** — Google saw the page
  but chose not to add it. Common causes: thin content (low word
  count), duplicate content, no inbound links. The current site's
  pages should all be substantive enough to avoid this, but
  monitor.
- **Not indexed: Discovered – currently not indexed** — Google
  knows the URL exists but hasn't crawled it yet. Normal for the
  first few weeks. If a URL stays here longer than 30 days,
  request indexing manually.

### 2.2 Experience → Core Web Vitals

The three numbers Google watches:

- **LCP (Largest Contentful Paint)** — how fast the main content
  loads. Target: under 2.5 seconds. Should be green on a static
  Next.js site.
- **INP (Interaction to Next Paint)** — how responsive the page
  feels. Target: under 200ms.
- **CLS (Cumulative Layout Shift)** — how much the page jumps
  around as it loads. Target: under 0.1.

If any of these go yellow or red, run the page through
https://pagespeed.web.dev/ to see what's slow. The marketing site
is already fast — the only things that could hurt CWV later are
adding large images without optimization, or third-party scripts.

### 2.3 Performance → Queries

This is where the value starts. Search Console shows you which
queries are bringing people to your site, how many impressions
each query generates, and what the average position is.

Look for:

- Queries you're ranking for that you didn't plan to rank for
  (often surprising — these become targets for new content)
- Queries where your average position is 6–15 (page 1 or page 2
  bottom) — these are the realistic short-term targets to push to
  positions 1–5 with small edits
- Queries where you have impressions but no clicks (means your
  title/meta description aren't compelling — rewrite them)

---

## Step 3 — Keyword research, the cheap way

You don't need Ahrefs or SEMrush ($100+/month each). Free tools:

### 3.1 Google Keyword Planner (free with Google Ads account)

Sign up at https://ads.google.com with the same Google account you
used for Search Console. You don't have to run ads — you just need
the account to access the Keyword Planner tool.

How to use:

1. Open **Tools → Keyword Planner → Discover new keywords**.
2. Enter a seed phrase like `medspa CRM` or `HIPAA compliance for
   medspas` or `Botox appointment software`.
3. Keyword Planner returns related queries with monthly search
   volume estimates and competition ranges.
4. Filter for queries with **10–1,000 monthly searches** and
   **low/medium competition**. These are the realistic targets
   for a new site without a backlink profile.

Don't chase "medspa software" (50K+ searches/month) on day one.
Chase "consent form software for botox" (50–200 searches/month).
Lower volume but achievable, and high-intent.

### 3.2 Google's own free tools

- **Google Autocomplete** — start typing a query in the Google
  search bar and watch what it suggests. Every suggestion is a
  real query people search for.
- **People Also Ask** — appears in many search results. Each
  question is a potential blog post topic.
- **Related searches** — at the bottom of every Google results
  page.
- **Google Trends** — https://trends.google.com — shows whether
  search volume is rising or falling for a query.

### 3.3 Where to find what your competitors rank for

The free reconnaissance approach:

- **Ubersuggest** (https://neilpatel.com/ubersuggest) gives 3 free
  competitor searches per day. Enter `joinblvd.com` or
  `mindbodyonline.com` and see their top organic keywords.
- **AnswerThePublic** (https://answerthepublic.com) gives 2 free
  queries per day. Enter a seed term and it visualizes every
  question people ask around it.

These two together cover 80% of what a $100/month tool would tell
you.

---

## Step 4 — Backlinks (the part nobody tells you is the hard one)

Google still uses backlinks as the single biggest non-content
signal of authority. A site with 20 high-quality backlinks
outranks a site with 0 backlinks every time, regardless of content
quality. The good news is you don't need 1,000 — you need 20–50
high-quality ones.

How to get them without paying:

### 4.1 List yourself on industry directories

Free or low-cost directories every medspa software should be on:

- https://www.capterra.com — submit your software profile
- https://www.softwareadvice.com — same company as Capterra,
  separate listing
- https://www.g2.com — submit, then encourage early customers to
  review
- https://www.getapp.com — same parent, separate listing
- https://www.producthunt.com — for product launches
- https://saasworthy.com
- https://www.crozdesk.com

Each profile is also a backlink to your site.

### 4.2 Industry publications + guest posts

Medspa industry publications that accept contributed articles:

- American Med Spa Association blog (https://americanmedspa.org)
- Modern Aesthetics
- The Aesthetic Guide
- MedEsthetics magazine
- Aesthetic Authority

Pitch them an article based on one of your blog posts — the same
content, rewritten for their audience, with an author bio that
links back to your site.

### 4.3 HARO / Qwoted (free for sources)

Sign up at https://www.helpareporter.com (HARO) or
https://www.qwoted.com. Three times a day, you receive an email
listing journalists who need expert sources for stories. When the
story is about medspa software, HIPAA in healthcare, or small
business operations, reply with a quote. If the journalist uses
it, you get a high-authority backlink (often from major
publications).

This is high-leverage but inconsistent — you might land one
backlink a month if you respond often.

### 4.4 Customer logos / case studies (when you have customers)

The single most valuable backlink type: a customer page that links
to your site. Each onboarded medspa is a potential backlink. Ask
their permission once they're live.

---

## Step 5 — Publishing cadence

Realistic target for a solo operator: **one new blog post per
month**, plus quarterly refreshes of the existing posts.

Why monthly and not weekly:

- Quality matters more than frequency. One 2,000-word post that
  ranks beats four 500-word posts that don't.
- Each post takes 4–8 hours to write properly (research + draft +
  edit + publish). At weekly cadence, the quality drops.
- Google's helpful-content system explicitly looks at quality
  distribution across your site. A few high-quality pages help
  every page; a pile of mediocre ones hurts every page.

See `BLOG_DRAFTING_WORKFLOW.md` for the cheap, AI-assisted
workflow that gets you to 2 hours per post instead of 6.

---

## Step 6 — Track what's working (monthly review)

Once a month, spend 30 minutes in Search Console:

1. **Performance report (last 28 days vs previous 28 days)** —
   total clicks, total impressions, average position. Trend up?
   What changed?
2. **Top queries** — what 5–10 queries are sending the most
   traffic? Do you have content that targets each?
3. **Top pages** — which pages are getting the most traffic? What
   makes them work? Can you write a sibling post on a related
   topic?
4. **Coverage report** — anything newly broken (404s, redirect
   chains, blocked by robots.txt)? Fix immediately.

Then in Plausible (your analytics):

1. **Top referrers** — who's linking to you? Reach out and thank
   them. Reach out to other similar sites for backlinks.
2. **Top pages by engagement** — which pages have low bounce
   rates? Those are the strongest assets. Build on them.

---

## Step 7 — On-page SEO refresh (every 3–6 months)

A reasonable rotation:

- Audit every page's **title tag** — under 60 characters,
  primary keyword early.
- Audit every page's **meta description** — under 160 characters,
  compelling enough to earn the click.
- Check **headings hierarchy** — every page has exactly one h1,
  h2s for major sections, h3s for subsections.
- Check **internal links** — every page links to 2–4 other pages
  on the site. Use descriptive anchor text (not "click here").
- Check **image alt text** — every image describes its content.

The marketing site is already in good shape on all of these as of
the production launch. The pages most likely to need attention
later are the blog posts as the publish list grows.

---

## What this playbook intentionally does NOT do

- **No keyword stuffing.** Modern Google penalizes it.
- **No paid link buying.** This is the fastest way to a manual
  penalty. Every "buy backlinks for $50" service is a trap.
- **No mass-generated AI content.** See `BLOG_DRAFTING_WORKFLOW.md`
  for why and what to do instead.
- **No private blog networks (PBNs).** Same as paid link buying.
- **No directory submission spam.** The directories listed above
  are legitimate industry destinations; resist the urge to submit
  to hundreds of low-quality directories.

The slow, expensive-to-fake stuff is what works.

---

## Realistic timeline

If you do everything in this playbook:

- **Week 1**: Site is submitted, sitemap is live, first 10
  high-priority URLs requested for indexing.
- **Weeks 2–4**: Google indexes most pages. You start appearing
  for long-tail queries.
- **Months 2–3**: First organic clicks. Mostly low-volume
  long-tail terms. Each blog post starts climbing.
- **Months 4–6**: Some posts hit page 1 for their target queries.
  Total monthly clicks reach low triple digits if you've published
  monthly.
- **Months 6–12**: Compounding kicks in. Older posts mature, you
  start ranking for more competitive terms, backlinks accumulate.
- **Year 2+**: Real organic traffic. The whole strategy compounds.

SEO is slow. The medspas already running on Boulevard or Zenoti
have years of head start. Patience and consistency beat clever
hacks every time.
