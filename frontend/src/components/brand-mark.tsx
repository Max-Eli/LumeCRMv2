/**
 * Brand lockup. Two variants:
 *
 *   - `icon` — just the monogram (square, `favicon.png`). Use in tight
 *     chrome (collapsed sidebar, favicon-style spots).
 *   - `lockup` — the horizontal monogram + "LUMÈ" wordmark image
 *     (`mainlogo.png`). Use in any header / hero / sidebar where the
 *     full brand should read.
 *
 * The big square stacked logo (`logosquare.png`) is reserved for
 * page-level heroes (landing page, sign-in screen) and is NOT served
 * through this component — those few surfaces use `<Image>` directly.
 *
 * `size` is the rendered HEIGHT in pixels. Width is auto-derived by
 * Next/Image from the natural aspect ratio so the lockup keeps its
 * proportions across font-size changes.
 */

import Image from 'next/image';

import { cn } from '@/lib/utils';

export interface BrandMarkProps {
  variant?: 'icon' | 'lockup';
  /** Pixel HEIGHT of the rendered mark. Width auto-scales. */
  size?: number;
  className?: string;
}

// Natural aspect ratios of the source PNGs — feeding these to
// next/image with `height` lets us render at any size while
// preserving sharpness + correct intrinsic width.
const LOCKUP_ASPECT = 1920 / 1080;   // mainlogo.png
const ICON_ASPECT = 1;               // favicon.png is square

export function BrandMark({
  variant = 'icon',
  size = 32,
  className,
}: BrandMarkProps) {
  const isLockup = variant === 'lockup';
  const src = isLockup ? '/mainlogo.png' : '/favicon.png';
  const aspect = isLockup ? LOCKUP_ASPECT : ICON_ASPECT;
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
