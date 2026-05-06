import Image from 'next/image';
import Link from 'next/link';

import { Button } from '@/components/ui/button';

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col">
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-24 text-center">
        <Image
          src="/logosquare.png"
          alt="Lumè"
          width={200}
          height={200}
          priority
          className="mb-2"
        />
        <p className="mt-3 text-sm uppercase tracking-[0.2em] text-muted-foreground">
          A modern CRM for medical spas
        </p>
        <p className="mt-8 max-w-xl text-base text-muted-foreground leading-relaxed">
          Booking, customer charts, e-signed forms, payments, memberships, and reporting —
          built for the way medical spas actually run.
        </p>
        <div className="mt-10 flex gap-3">
          <Button render={<Link href="/login" />} nativeButton={false} size="lg">
            Sign in
          </Button>
          <Button
            render={<Link href="/dashboard" />}
            nativeButton={false}
            size="lg"
            variant="outline"
          >
            Go to dashboard
          </Button>
        </div>
        <p className="mt-12 text-xs text-muted-foreground/70 uppercase tracking-wide">
          Build in progress · Phase 1A complete
        </p>
      </div>
    </main>
  );
}
