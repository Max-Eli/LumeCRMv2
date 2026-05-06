/**
 * Avatar with initials fallback. Used for clients, staff, and anywhere a
 * person needs a visual identifier. Initials sit on a soft accent-tinted
 * surface so a list of clients reads as warm, not stark.
 *
 * Color is deterministic based on the seed string so the same person always
 * gets the same chip color across sessions.
 */

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { cn } from '@/lib/utils';

export interface InitialsAvatarProps {
  /** Full name or any string that gives us initials and color seed. */
  name: string;
  /** Optional photo URL. */
  src?: string;
  size?: 'sm' | 'default' | 'lg' | 'xl';
  className?: string;
}

const PALETTE = [
  'bg-amber-100 text-amber-900',
  'bg-rose-100 text-rose-900',
  'bg-emerald-100 text-emerald-900',
  'bg-sky-100 text-sky-900',
  'bg-violet-100 text-violet-900',
  'bg-orange-100 text-orange-900',
  'bg-teal-100 text-teal-900',
  'bg-pink-100 text-pink-900',
];

function pickColor(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(h) % PALETTE.length];
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '·';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function InitialsAvatar({ name, src, size = 'default', className }: InitialsAvatarProps) {
  const sizeClass =
    size === 'sm'
      ? 'size-7 text-[11px]'
      : size === 'lg'
        ? 'size-12 text-sm'
        : size === 'xl'
          ? 'size-20 text-xl'
          : 'size-9 text-xs';
  const tone = pickColor(name || '?');

  return (
    <Avatar className={cn(sizeClass, className)}>
      {src ? <AvatarImage src={src} alt={name} /> : null}
      <AvatarFallback className={cn('font-medium', tone)}>{initials(name)}</AvatarFallback>
    </Avatar>
  );
}
