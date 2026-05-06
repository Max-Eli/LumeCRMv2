/**
 * Signature canvas — touch + mouse drawing surface, exports a base64
 * PNG of the signature for the form submission payload.
 *
 * Used in the public fill page (`/forms/[token]`). Touch-first
 * because the most common signing surface is an iPad handed across
 * the front-desk counter, with a stylus or finger.
 *
 * Implementation notes:
 *   - Uses raw `<canvas>` rather than a third-party library — keeps
 *     bundle small and avoids dependency churn for one component.
 *   - The visible canvas is drawn at the device-pixel-ratio so the
 *     signature looks crisp on retina + iPad displays. Without DPR
 *     scaling the lines look pixelated on high-DPI screens.
 *   - "Clear" button resets the surface; the parent decides when to
 *     read the signature data via `getSignatureDataUrl()` exposed
 *     through a ref.
 */

'use client';

import { Eraser } from 'lucide-react';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface SignatureCanvasHandle {
  /** Returns a base64-encoded PNG (data URL) of the current signature.
   *  Empty string if the canvas hasn't been drawn on. Callers should
   *  treat empty as "not signed yet." */
  getSignatureDataUrl: () => string;
  /** True if any drawing has been done since last clear / mount. */
  hasSignature: () => boolean;
  /** Clear the canvas — resets the "has signature" flag. */
  clear: () => void;
}

export interface SignatureCanvasProps {
  /** Display height in CSS pixels. Width fills the container. */
  height?: number;
  /** Stroke color. Default: foreground (black-ish). */
  strokeColor?: string;
  /** Optional callback fired the first time the user starts drawing
   *  on an empty canvas — useful for parent-side dirty tracking. */
  onFirstStroke?: () => void;
  className?: string;
}

export const SignatureCanvas = forwardRef<SignatureCanvasHandle, SignatureCanvasProps>(
  function SignatureCanvas(
    { height = 180, strokeColor = '#1a1a1a', onFirstStroke, className },
    ref,
  ) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const drawingRef = useRef(false);
    const lastPointRef = useRef<{ x: number; y: number } | null>(null);
    const [hasInk, setHasInk] = useState(false);

    // Set up the canvas at the device pixel ratio so high-DPI screens
    // render crisp lines. Re-runs on resize so the canvas always
    // matches its container width.
    const resizeCanvas = useCallback(() => {
      const canvas = canvasRef.current;
      const container = containerRef.current;
      if (!canvas || !container) return;
      const dpr = window.devicePixelRatio || 1;
      const cssWidth = container.clientWidth;
      canvas.width = cssWidth * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${cssWidth}px`;
      canvas.style.height = `${height}px`;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.lineWidth = 2;
        ctx.strokeStyle = strokeColor;
      }
    }, [height, strokeColor]);

    useEffect(() => {
      resizeCanvas();
      const handleResize = () => resizeCanvas();
      window.addEventListener('resize', handleResize);
      return () => window.removeEventListener('resize', handleResize);
    }, [resizeCanvas]);

    // Convert an event's clientX/clientY into canvas-local CSS
    // coordinates (NOT scaled to device pixels — the ctx transform
    // handles that). Touch events use the first changed touch.
    const coordsFromEvent = (
      e: React.PointerEvent<HTMLCanvasElement>,
    ): { x: number; y: number } => {
      const canvas = canvasRef.current;
      if (!canvas) return { x: 0, y: 0 };
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    const handlePointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      e.preventDefault();
      canvas.setPointerCapture(e.pointerId);
      drawingRef.current = true;
      lastPointRef.current = coordsFromEvent(e);
      if (!hasInk) {
        setHasInk(true);
        onFirstStroke?.();
      }
    };

    const handlePointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!drawingRef.current) return;
      e.preventDefault();
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext('2d');
      if (!ctx) return;
      const point = coordsFromEvent(e);
      const last = lastPointRef.current;
      if (last) {
        ctx.beginPath();
        ctx.moveTo(last.x, last.y);
        ctx.lineTo(point.x, point.y);
        ctx.stroke();
      }
      lastPointRef.current = point;
    };

    const handlePointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas || !drawingRef.current) return;
      try {
        canvas.releasePointerCapture(e.pointerId);
      } catch {
        // Some browsers throw if the pointer wasn't captured; ignore.
      }
      drawingRef.current = false;
      lastPointRef.current = null;
    };

    const clear = useCallback(() => {
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext('2d');
      if (!canvas || !ctx) return;
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.restore();
      setHasInk(false);
      lastPointRef.current = null;
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        getSignatureDataUrl: () => {
          const canvas = canvasRef.current;
          if (!canvas || !hasInk) return '';
          return canvas.toDataURL('image/png');
        },
        hasSignature: () => hasInk,
        clear,
      }),
      [hasInk, clear],
    );

    return (
      <div ref={containerRef} className={cn('w-full space-y-2', className)}>
        <div className="relative rounded-md border bg-background overflow-hidden">
          <canvas
            ref={canvasRef}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            onPointerLeave={handlePointerUp}
            // touch-action:none is required on mobile so the browser
            // doesn't intercept touch as scroll/zoom while the user
            // is signing.
            style={{ touchAction: 'none' }}
            className="block w-full cursor-crosshair"
          />
          {!hasInk ? (
            <span
              className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground/50 italic pointer-events-none"
              aria-hidden
            >
              Sign here
            </span>
          ) : null}
        </div>
        <div className="flex items-center justify-end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={clear}
            disabled={!hasInk}
          >
            <Eraser className="size-3.5" />
            Clear
          </Button>
        </div>
      </div>
    );
  },
);
