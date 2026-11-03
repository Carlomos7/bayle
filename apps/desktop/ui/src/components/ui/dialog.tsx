import * as React from 'react';
import { Dialog as DialogPrimitive } from 'radix-ui';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

function Dialog(props: React.ComponentProps<typeof DialogPrimitive.Root>) { return <DialogPrimitive.Root data-slot="dialog" {...props} />; }
function DialogTrigger(props: React.ComponentProps<typeof DialogPrimitive.Trigger>) { return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />; }
function DialogPortal(props: React.ComponentProps<typeof DialogPrimitive.Portal>) { return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />; }
function DialogClose(props: React.ComponentProps<typeof DialogPrimitive.Close>) { return <DialogPrimitive.Close data-slot="dialog-close" {...props} />; }

function DialogOverlay({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return <DialogPrimitive.Overlay data-slot="dialog-overlay" className={cn('fixed inset-0 z-40 bg-black/55 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0', className)} {...props} />;
}

function DialogContent({ className, children, showCloseButton = false, ...props }: React.ComponentProps<typeof DialogPrimitive.Content> & { showCloseButton?: boolean }) {
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content data-slot="dialog-content"
        className={cn('fixed top-1/2 left-1/2 z-40 flex max-h-[calc(100vh-48px)] w-[min(460px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-line2 bg-panel shadow-pop outline-hidden data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[.98] data-[state=open]:slide-in-from-bottom-1 data-[state=closed]:animate-out data-[state=closed]:fade-out-0', className)}
        {...props}>
        {children}
        {showCloseButton && (
          <DialogPrimitive.Close className="absolute top-3.5 right-3.5 grid size-7 place-items-center rounded-xs text-t3 hover:bg-hover hover:text-t1"><X className="size-4" /><span className="sr-only">Close</span></DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPortal>
  );
}

function DialogHeader({ className, ...props }: React.ComponentProps<'div'>) { return <div data-slot="dialog-header" className={cn('flex flex-col gap-1.5 px-5 pt-5 pb-3', className)} {...props} />; }
function DialogBody({ className, ...props }: React.ComponentProps<'div'>) { return <div data-slot="dialog-body" className={cn('min-h-0 overflow-auto px-5 pb-4', className)} {...props} />; }
function DialogFooter({ className, ...props }: React.ComponentProps<'div'>) { return <div data-slot="dialog-footer" className={cn('flex items-center justify-end gap-2 border-t border-line bg-[color-mix(in_srgb,var(--t1)_2%,var(--panel))] px-5 py-3', className)} {...props} />; }
function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) { return <DialogPrimitive.Title data-slot="dialog-title" className={cn('m-0 font-serif text-heading leading-tight font-semibold', className)} {...props} />; }
function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) { return <DialogPrimitive.Description data-slot="dialog-description" className={cn('text-ui text-t3', className)} {...props} />; }

export { Dialog, DialogTrigger, DialogPortal, DialogClose, DialogOverlay, DialogContent, DialogHeader, DialogBody, DialogFooter, DialogTitle, DialogDescription };
