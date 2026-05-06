import type { Metadata } from 'next';
import { Fraunces, Geist } from 'next/font/google';

import { Footer } from '@/components/footer';
import { TopNav } from '@/components/top-nav';

import './globals.css';

const geistSans = Geist({
  variable: '--font-sans',
  subsets: ['latin'],
});

const fraunces = Fraunces({
  variable: '--font-serif',
  subsets: ['latin'],
  axes: ['opsz', 'SOFT'],
});

export const metadata: Metadata = {
  title: {
    default: 'Lumè — CRM for medical spas',
    template: '%s · Lumè',
  },
  description:
    'A modern, HIPAA-ready CRM built for the way medical spas actually run. Booking, charts, e-signed forms, payments, and reporting in one warm-luxe surface.',
  icons: {
    icon: '/favicon.png',
    apple: '/favicon.png',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${fraunces.variable} h-full antialiased`}>
      <body className="min-h-full bg-background text-foreground">
        <TopNav />
        <main className="min-h-[60vh]">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
