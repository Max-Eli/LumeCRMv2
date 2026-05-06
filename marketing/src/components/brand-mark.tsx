/**
 * Brand lockup. Two variants:
 *
 *   - `icon`   — `/favicon.png`, the bare monogram. For tight spots.
 *   - `lockup` — `/mainlogo.png`, the horizontal monogram + LUMÈ
 *                wordmark. The marketing standard.
 *
 * Mirrors the same component in the CRM app so the brand stays
 * identical across both surfaces. `size` is the rendered HEIGHT in
 * pixels; width auto-derives from the source aspect ratio.
 */

import Image from 'next/image';

import { cn } from '@/lib/utils';

const LOCKUP_ASPECT = 1920 / 1080;

export interface BrandMarkProps {
  variant?: 'icon' | 'lockup';
  size?: number;
  className?: string;
}

export function BrandMark({ variant = 'icon', size = 32, className }: BrandMarkProps) {
  const isLockup = variant === 'lockup';
  const src = isLockup ? '/mainlogo.png' : '/favicon.png';
  const aspect = isLockup ? LOCKUP_ASPECT : 1;
  const width = Math.round(size * aspect);
  return (
    <Image
      src={src}
      alt="Lumè"
      width={width}
      height={size}
      priority
      className={cn('shrink-0 select-none', className)}
    />
  );
}
