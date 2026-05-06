import type { Metadata } from 'next';
import { Fraunces, Geist } from 'next/font/google';

import { Toaster } from '@/components/ui/sonner';
import { Providers } from './providers';
import './globals.css';

const geistSans = Geist({
  variable: '--font-sans',
  subsets: ['latin'],
});

// Display serif for page titles and brand chrome — gives the app a "magazine
// spread" feel that reads as expensive / editorial. Used sparingly via the
// `font-serif` Tailwind utility, never as body text.
const fraunces = Fraunces({
  variable: '--font-serif',
  subsets: ['latin'],
  axes: ['opsz', 'SOFT'],
});

export const metadata: Metadata = {
  title: 'Lumè CRM',
  description: 'A modern, HIPAA-compliant CRM for medical spas and salons.',
  icons: {
    icon: '/favicon.png',
    apple: '/favicon.png',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${fraunces.variable} h-full antialiased`}>
      <body className="min-h-full bg-background text-foreground">
        <Providers>{children}</Providers>
        <Toaster richColors closeButton />
      </body>
    </html>
  );
}
