/**
 * Dialog primitive — thin wrapper around Base UI's `@base-ui/react/dialog`,
 * keeping our chrome (backdrop tint, popup card, focus ring, scroll
 * behavior, animations) consistent across every modal in the app.
 *
 * Usage:
 *
 *   const [open, setOpen] = useState(false);
 *
 *   <Dialog open={open} onOpenChange={setOpen}>
 *     <DialogContent>
 *       <DialogHeader>
 *         <DialogTitle>Title</DialogTitle>
 *         <DialogDescription>Optional subtitle</DialogDescription>
 *       </DialogHeader>
 *       <div className="px-6 py-4 space-y-4">
 *         {form contents}
 *       </div>
 *       <DialogFooter>
 *         <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
 *         <Button type="submit">Confirm</Button>
 *       </DialogFooter>
 *     </DialogContent>
 *   </Dialog>
 *
 * Default chrome:
 *   - Backdrop is a translucent dark veil with subtle blur.
 *   - Popup is a card-surface centered with `max-w-lg` and a 16-vh top
 *     offset so the dialog feels grounded, not pasted to the top.
 *   - Focus is trapped + initial focus lands on the first focusable
 *     element (Base UI default).
 *   - Escape and outside-click both close (also Base UI defaults).
 */

'use client';

import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import { X } from 'lucide-react';
import * as React from 'react';

import { cn } from '@/lib/utils';

function Dialog(props: DialogPrimitive.Root.Props) {
  return <DialogPrimitive.Root {...props} />;
}

function DialogTrigger(props: DialogPrimitive.Trigger.Props) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: DialogPrimitive.Popup.Props & { showCloseButton?: boolean }) {
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
        data-slot="dialog-content"
        className={cn(
          'fixed left-1/2 top-[16vh] -translate-x-1/2 z-50',
          'w-[92vw] max-w-lg max-h-[80vh] flex flex-col',
          'rounded-lg border bg-card text-card-foreground shadow-2xl ring-1 ring-foreground/10',
          'outline-none',
          'duration-150',
          'data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-open:slide-in-from-top-4',
          'data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95 data-closed:slide-out-to-top-4',
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

function DialogHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="dialog-header"
      className={cn('shrink-0 px-6 pt-5 pb-4 border-b space-y-1', className)}
      {...props}
    />
  );
}

function DialogTitle({ className, ...props }: DialogPrimitive.Title.Props) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn('font-serif text-lg font-semibold tracking-tight', className)}
      {...props}
    />
  );
}

function DialogDescription({
  className,
  ...props
}: DialogPrimitive.Description.Props) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn('text-sm text-muted-foreground', className)}
      {...props}
    />
  );
}

function DialogBody({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="dialog-body"
      className={cn('flex-1 min-h-0 overflow-y-auto px-6 py-4', className)}
      {...props}
    />
  );
}

function DialogFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        'shrink-0 px-6 py-3 border-t flex items-center justify-end gap-2',
        className,
      )}
      {...props}
    />
  );
}

function DialogClose(props: DialogPrimitive.Close.Props) {
  return <DialogPrimitive.Close {...props} />;
}

export {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogBody,
  DialogFooter,
  DialogClose,
};
