/**
 * Journal index.
 *
 * Editorial-feeling list of posts. No filter chips, no search bar,
 * no infinite scroll — for a small archive (a dozen or fewer posts)
 * those add friction without value. When the archive grows past 15
 * posts, revisit the layout: paginate or split by category.
 *
 * The hero standfirst sets expectation: long-form, opinionated,
 * specific. Not "10 ways to..." listicles.
 */

import Link from 'next/link';
import type { Metadata } from 'next';

import { PageHero } from '@/components/page-hero';
import { ScrollReveal } from '@/components/scroll-reveal';
import { POSTS, formatDate } from '@/lib/blog';

export const metadata: Metadata = {
  title: 'Journal',
  description:
    'Long-form pieces on HIPAA compliance for medical spas, reducing no-shows, migrating off legacy CRMs, and what a Business Associate Agreement actually covers.',
};

export default function BlogIndexPage() {
  return (
    <>
      <PageHero
        eyebrow="Journal"
        headline={
          <>
            Long-form on the work{' '}
            <span className="accent-italic">of running a medspa.</span>
          </>
        }
        standfirst="Compliance frameworks, operational playbooks, vendor-selection arguments. Written for owners and operators who want substance, not a content marketer's stack of listicles."
      />

      <section>
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
          <ol className="space-y-0">
            {POSTS.map((p, i) => (
              <ScrollReveal
                key={p.slug}
                as="li"
                delay={i * 70}
                className={i === 0 ? 'border-t border-foreground/15' : ''}
              >
                <Link
                  href={`/blog/${p.slug}`}
                  className="group grid gap-6 border-b border-foreground/15 py-10 transition-colors hover:border-accent lg:grid-cols-12 lg:gap-12 lg:py-14"
                >
                  <div className="lg:col-span-3">
                    <p className="eyebrow text-foreground/60">{p.category}</p>
                    <p className="mt-2 text-xs uppercase tracking-[0.16em] text-foreground/50">
                      <time dateTime={p.publishedAt}>{formatDate(p.publishedAt)}</time>
                    </p>
                    <p className="mt-1 text-xs uppercase tracking-[0.16em] text-foreground/45">
                      {p.readMinutes} min read
                    </p>
                  </div>
                  <div className="lg:col-span-9">
                    <h2 className="font-serif text-2xl font-medium text-foreground transition-colors group-hover:text-accent sm:text-3xl lg:text-4xl">
                      {p.title}
                    </h2>
                    <p className="mt-4 max-w-3xl text-base leading-relaxed text-foreground/75 sm:text-lg">
                      {p.summary}
                    </p>
                    <span className="mt-6 inline-flex items-center text-xs font-medium uppercase tracking-[0.16em] text-foreground/65 group-hover:text-accent transition-colors">
                      Read article
                      <span aria-hidden className="ml-2">
                        →
                      </span>
                    </span>
                  </div>
                </Link>
              </ScrollReveal>
            ))}
          </ol>

          <p className="mt-16 text-sm text-foreground/55">
            New pieces land roughly monthly. No newsletter, no email
            capture — bookmark the page or check back.
          </p>
        </div>
      </section>
    </>
  );
}
