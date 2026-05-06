/**
 * Sheet primitive — side-anchored, full-height drawer. Built on the same
 * base-ui Dialog primitive as `<Dialog>`, so focus trap, escape-to-close,
 * outside-click, and portal behavior are identical. Differs in:
 *
 *   - Anchored to the left or right edge (not centered)
 *   - Full viewport height
 *   - Slide-in/out animation from the chosen side
 *   - Default width 520px (room for richer forms than a centered modal)
 *
 * Use Sheet when the content is workflow-heavy (booking a new
 * appointment, editing a customer chart) and benefits from full-height
 * vertical space. Use Dialog for terse confirms / quick edits where a
 * centered modal feels lighter.
 *
 * Composition mirrors Dialog:
 *
 *   <Sheet open={open} onOpenChange={setOpen}>
 *     <SheetContent side="left">
 *       <SheetHeader>
 *         <SheetTitle>Title</SheetTitle>
 *         <SheetDescription>Subtitle</SheetDescription>
 *       </SheetHeader>
 *       <SheetBody>{form}</SheetBody>
 *       <SheetFooter>
 *         <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
 *         <Button type="submit">Confirm</Button>
 *       </SheetFooter>
 *     </SheetContent>
 *   </Sheet>
 */

'use client';

import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import { X } from 'lucide-react';
import * as React from 'react';

import { cn } from '@/lib/utils';

type SheetSide = 'left' | 'right' | 'top' | 'bottom';

function Sheet(props: DialogPrimitive.Root.Props) {
  return <DialogPrimitive.Root {...props} />;
}

function SheetTrigger(props: DialogPrimitive.Trigger.Props) {
  return <DialogPrimitive.Trigger data-slot="sheet-trigger" {...props} />;
}

function SheetContent({
  className,
  children,
  side = 'right',
  showCloseButton = true,
  ...props
}: DialogPrimitive.Popup.Props & {
  side?: SheetSide;
  showCloseButton?: boolean;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Backdrop
        className={cn(
          'fixed inset-0 z-50 bg-foreground/40 backdrop-blur-[2px]',
          'data-open:animate-in data-open:fade-in-0',
          'data-closed:animate-out data-closed:fade-out-0',
        )}
      />
      <DialogPrimitive.Popup
        data-slot="sheet-content"
        className={cn(
          'fixed z-50 flex flex-col',
          'bg-card text-card-foreground shadow-2xl ring-1 ring-foreground/10',
          'outline-none',
          'duration-200',
          // Side-anchored variants — left/right are full-height vertical
          // drawers; top/bottom are full-width horizontal sheets centered
          // on the viewport horizontal axis with a max width.
          side === 'left' && [
            'top-0 bottom-0 left-0',
            'w-[520px] max-w-[92vw]',
            'border-r',
            'data-open:animate-in data-open:slide-in-from-left',
            'data-closed:animate-out data-closed:slide-out-to-left',
          ],
          side === 'right' && [
            'top-0 bottom-0 right-0',
            'w-[520px] max-w-[92vw]',
            'border-l',
            'data-open:animate-in data-open:slide-in-from-right',
            'data-closed:animate-out data-closed:slide-out-to-right',
          ],
          side === 'bottom' && [
            'bottom-0 left-1/2 -translate-x-1/2',
            'w-[96vw] max-w-3xl max-h-[85vh]',
            'border-t rounded-t-xl',
            'data-open:animate-in data-open:slide-in-from-bottom',
            'data-closed:animate-out data-closed:slide-out-to-bottom',
          ],
          side === 'top' && [
            'top-0 left-1/2 -translate-x-1/2',
            'w-[96vw] max-w-3xl max-h-[85vh]',
            'border-b rounded-b-xl',
            'data-open:animate-in data-open:slide-in-from-top',
            'data-closed:animate-out data-closed:slide-out-to-top',
          ],
          className,
        )}
        {...props}
      >
        {children}
        {showCloseButton ? (
          <DialogPrimitive.Close
            className="absolute right-3 top-3 inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            aria-label="Close"
          >
            <X className="size-4" />
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Popup>
    </DialogPrimitive.Portal>
  );
}

function SheetHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="sheet-header"
      className={cn('shrink-0 px-6 pt-5 pb-4 border-b space-y-1', className)}
      {...props}
    />
  );
}

function SheetTitle({ className, ...props }: DialogPrimitive.Title.Props) {
  return (
    <DialogPrimitive.Title
      data-slot="sheet-title"
      className={cn('font-serif text-lg font-semibold tracking-tight', className)}
      {...props}
    />
  );
}

function SheetDescription({
  className,
  ...props
}: DialogPrimitive.Description.Props) {
  return (
    <DialogPrimitive.Description
      data-slot="sheet-description"
      className={cn('text-sm text-muted-foreground', className)}
      {...props}
    />
  );
}

function SheetBody({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="sheet-body"
      className={cn('flex-1 min-h-0 overflow-y-auto px-6 py-4', className)}
      {...props}
    />
  );
}

function SheetFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="sheet-footer"
      className={cn(
        'shrink-0 px-6 py-3 border-t flex items-center justify-end gap-2',
        className,
      )}
      {...props}
    />
  );
}

function SheetClose(props: DialogPrimitive.Close.Props) {
  return <DialogPrimitive.Close {...props} />;
}

export {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetBody,
  SheetFooter,
  SheetClose,
};
