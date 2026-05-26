/**
 * Calendar-side date/time helpers shared between the day-view grid,
 * the new-appointment sheet, and the block-out sheet.
 *
 * Two of these used to live as private copies inside day-view.tsx and
 * new-appointment-sheet.tsx with a comment noting they'd be lifted on
 * the third caller — block-out-sheet.tsx is that caller.
 *
 * Times in the rest of the app are stored UTC; the calendar always
 * works in the location's timezone, so the conversion below is the
 * single boundary between display-local and storage-UTC.
 */

/** Today's date in the user's local calendar, as YYYY-MM-DD. */
export function todayLocalISODate(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** Sensible default start time when opening cold — top of the next
 *  hour, clamped to business hours (9 AM – 7 PM). */
export function defaultStartTimeLabel(): string {
  const now = new Date();
  let h = now.getHours() + (now.getMinutes() >= 1 ? 1 : 0);
  if (h < 9) h = 9;
  if (h > 19) h = 19;
  return `${String(h).padStart(2, '0')}:00`;
}

/** Parse an "HH:MM" 24h string into a [hours, minutes] tuple. */
export function parseHHMM(s: string): [number, number] {
  const [h, m] = s.split(':').map(Number);
  return [h ?? 0, m ?? 0];
}

/**
 * Local date+time (in `timezone`) → UTC ISO. Standard IANA-aware offset
 * derivation: format the naive UTC value back out in the target zone,
 * subtract to discover the offset, then apply it.
 */
export function localDateTimeToUtcIso(
  date: string,
  hours: number,
  minutes: number,
  timezone: string,
): string {
  const naive = new Date(`${date}T${pad2(hours)}:${pad2(minutes)}:00Z`);
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
  const parts: Record<string, string> = {};
  for (const p of fmt.formatToParts(naive)) parts[p.type] = p.value;
  const formattedAsUtcMs = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    // Intl can return "24" for midnight in some locales — wrap to 0.
    Number(parts.hour) % 24,
    Number(parts.minute),
    Number(parts.second),
  );
  const offsetMs = formattedAsUtcMs - naive.getTime();
  return new Date(naive.getTime() - offsetMs).toISOString();
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}
