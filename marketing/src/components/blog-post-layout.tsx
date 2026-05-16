/**
 * Shared layout for individual blog posts.
 *
 * Structure:
 *   1. Hero — eyebrow (category), serif headline, byline strip,
 *      standfirst paragraph
 *   2. Body — constrained max-w-3xl reading column with `blog-prose`
 *      typography from globals.css
 *   3. Related posts rail — up to two siblings, linked
 *   4. Closing CTA — get-a-demo card
 *   5. Article JSON-LD for SEO
 *
 * Posts pass their full metadata plus a `children` prose tree.
 */

import Link from 'next/link';
import type { ReactNode } from 'react';

import { SITE_URL_ASCII, jsonLd } from '@/lib/seo';
import type { BlogPostMeta } from '@/lib/blog';
import { formatDate, relatedPosts } from '@/lib/blog';

export interface BlogPostLayoutProps {
  meta: BlogPostMeta;
  /** One-sentence lead. Sits below the headline in larger type. */
  standfirst: string;
  /** Long-form body. Wrapped in `<article class="blog-prose">`. */
  children: ReactNode;
}

export function BlogPostLayout({ meta, standfirst, children }: BlogPostLayoutProps) {
  const related = relatedPosts(meta.slug, 2);
  const articleSchema = {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: meta.title,
    description: meta.summary,
    datePublished: meta.publishedAt,
    dateModified: meta.updatedAt ?? meta.publishedAt,
    author: { '@type': 'Organization', name: 'Lumè CRM' },
    publisher: { '@id': `${SITE_URL_ASCII}#organization` },
    mainEntityOfPage: `${SITE_URL_ASCII}/blog/${meta.slug}`,
    image: `${SITE_URL_ASCII}/opengraph-image`,
    articleSection: meta.category,
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd(articleSchema) }}
      />

      {/* Hero */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-3xl px-6 lg:px-10 pt-20 pb-12 lg:pt-28 lg:pb-16">
          <Link
            href="/blog"
            className="eyebrow text-foreground/60 hover:text-foreground transition-colors"
          >
            ← Journal
          </Link>
          <p className="mt-8 eyebrow text-foreground/60">{meta.category}</p>
          <h1 className="mt-4 font-display text-4xl text-foreground sm:text-5xl lg:text-[3.5rem]">
            {meta.title}
          </h1>
          <p className="mt-8 text-lg leading-relaxed text-foreground/80 sm:text-xl">
            {standfirst}
          </p>

          {/* Byline strip */}
          <div className="mt-10 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-foreground/15 pt-6 text-xs uppercase tracking-[0.16em] text-foreground/55">
            <span>{meta.author}</span>
            <span aria-hidden className="text-foreground/30">·</span>
            <time dateTime={meta.publishedAt}>{formatDate(meta.publishedAt)}</time>
            <span aria-hidden className="text-foreground/30">·</span>
            <span>{meta.readMinutes} min read</span>
          </div>
        </div>
      </section>

      {/* Body */}
      <section>
        <div className="mx-auto max-w-3xl px-6 lg:px-10 py-16 lg:py-20">
          <article className="blog-prose">{children}</article>
        </div>
      </section>

      {/* Related posts */}
      {related.length > 0 ? (
        <section className="border-y border-border bg-foreground/[0.02]">
          <div className="mx-auto max-w-7xl px-6 lg:px-10 py-16 lg:py-20">
            <p className="eyebrow text-foreground/60">Keep reading</p>
            <ul className="mt-8 grid gap-10 sm:grid-cols-2">
              {related.map((p) => (
                <li key={p.slug}>
                  <Link
                    href={`/blog/${p.slug}`}
                    className="group block border-t border-foreground/15 pt-6"
                  >
                    <p className="eyebrow text-foreground/55">{p.category}</p>
                    <h3 className="mt-3 font-serif text-xl font-medium text-foreground transition-colors group-hover:text-accent sm:text-2xl">
                      {p.title}
                    </h3>
                    <p className="mt-3 text-sm leading-relaxed text-foreground/70">
                      {p.summary}
                    </p>
                    <span className="mt-4 inline-flex items-center text-xs font-medium uppercase tracking-[0.16em] text-foreground/60 group-hover:text-accent transition-colors">
                      Read article
                      <span aria-hidden className="ml-2">
                        →
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}

      {/* Closing CTA */}
      <section className="border-t border-border bg-foreground text-background">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-16 lg:py-20">
          <div className="grid gap-8 lg:grid-cols-12 lg:items-center">
            <div className="lg:col-span-8">
              <p className="eyebrow text-background/60">Get a demo</p>
              <h2 className="mt-3 font-display text-3xl sm:text-4xl">
                See Lumè running on your medspa, not a generic one.
              </h2>
              <p className="mt-4 max-w-2xl text-base leading-relaxed text-background/80">
                Send us your service menu. We configure the demo on your
                real data. Thirty minutes. The first call is the demo.
              </p>
            </div>
            <div className="lg:col-span-4 lg:text-right">
              <Link
                href="/demo"
                className="inline-flex h-12 items-center rounded-full bg-background px-8 text-sm font-medium uppercase tracking-[0.16em] text-foreground hover:bg-background/90 transition-colors"
              >
                Get a demo
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

/** Small inline callout for definitions / sidebar tangents inside posts. */
export function BlogCallout({
  label = 'In short',
  children,
}: {
  label?: string;
  children: ReactNode;
}) {
  return (
    <aside className="blog-callout">
      <span className="blog-callout-label">{label}</span>
      {children}
    </aside>
  );
}
