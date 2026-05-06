/**
 * Pure-SVG sparkline. Plots a single series as a thin line with a
 * subtle fill below it. Designed for the hero revenue chart on the
 * dashboard — small enough to not need a chart library, expressive
 * enough that the operator can see "did I have a Saturday spike."
 *
 * Why not Recharts / Visx: they're 50-150kB minified for what is
 * (a) one line + a fill + a few tick marks. The math is 25 lines of
 * SVG; every dependency we don't take is one fewer tier of breakage
 * when next/turbopack updates land.
 *
 * Render quality decisions:
 *  - The line is `stroke-width: 2` and `vector-effect: non-scaling-stroke`
 *    so it stays crisp regardless of viewBox / container scaling.
 *  - The fill uses an rgba derived from `var(--accent)` for that
 *    "shaded under the line" look without leaning on a stop-gradient
 *    (the brand palette is solid, not gradient-driven).
 *  - Saturdays + Sundays get a subtle background band so the eye
 *    naturally registers weekend revenue spikes.
 */

'use client';

import { cn } from '@/lib/utils';

export interface SparklinePoint {
  /** ISO `YYYY-MM-DD`. Used as a label on hover (via `<title>`). */
  date: string;
  /** Numeric value. Same unit across all points. */
  value: number;
}

export interface SparklineProps {
  data: SparklinePoint[];
  /** Pixel height for the rendered chart. Width fills the container. */
  height?: number;
  /** Optional label callback for the tick on each point's `<title>`. */
  formatTitle?: (point: SparklinePoint) => string;
  className?: string;
}

const VIEW_W = 1000;
const PAD_TOP = 16;
const PAD_BOTTOM = 18;

export function Sparkline({
  data,
  height = 200,
  formatTitle,
  className,
}: SparklineProps) {
  if (data.length === 0) {
    return (
      <div
        className={cn(
          'flex items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground',
          className,
        )}
        style={{ height }}
      >
        No data in this window.
      </div>
    );
  }

  const viewH = height;
  const innerH = viewH - PAD_TOP - PAD_BOTTOM;
  const max = Math.max(...data.map((d) => d.value), 1);
  const stepX = data.length > 1 ? VIEW_W / (data.length - 1) : VIEW_W;

  const points = data.map((d, i) => {
    const x = i * stepX;
    const y = PAD_TOP + (innerH - (d.value / max) * innerH);
    return { x, y, raw: d };
  });

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ');
  // Close the path under the line for the fill.
  const fillPath = `${linePath} L ${VIEW_W} ${PAD_TOP + innerH} L 0 ${PAD_TOP + innerH} Z`;

  // Day-of-week bands — subtly shade Sat + Sun.
  const weekendBands = points.flatMap((p, i) => {
    if (i === points.length - 1) return [];
    const d = new Date(p.raw.date);
    const dow = d.getDay();
    if (dow !== 0 && dow !== 6) return [];
    const next = points[i + 1];
    return [
      <rect
        key={`band-${i}`}
        x={p.x}
        y={PAD_TOP}
        width={next.x - p.x}
        height={innerH}
        fill="var(--color-foreground)"
        opacity={0.025}
      />,
    ];
  });

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${viewH}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Trend chart with ${data.length} data points`}
      className={cn('block w-full', className)}
      style={{ height }}
    >
      {weekendBands}
      <path
        d={fillPath}
        fill="var(--color-accent)"
        opacity={0.08}
      />
      <path
        d={linePath}
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth={2}
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {points.map((p) => (
        <circle
          key={p.raw.date}
          cx={p.x}
          cy={p.y}
          r={3}
          fill="var(--color-background)"
          stroke="var(--color-accent)"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
          opacity={p.raw.value > 0 ? 1 : 0.2}
        >
          <title>{formatTitle ? formatTitle(p.raw) : `${p.raw.date}: ${p.raw.value}`}</title>
        </circle>
      ))}
    </svg>
  );
}
