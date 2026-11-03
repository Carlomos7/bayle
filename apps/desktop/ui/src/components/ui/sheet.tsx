import * as React from 'react';
import { Dialog as SheetPrimitive } from 'radix-ui';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

function Sheet(props: React.ComponentProps<typeof SheetPrimitive.Root>) { return <SheetPrimitive.Root data-slot="sheet" {...props} />; }
function SheetTrigger(props: React.ComponentProps<typeof SheetPrimitive.Trigger>) { return <SheetPrimitive.Trigger data-slot="sheet-trigger" {...props} />; }
function SheetClose(props: React.ComponentProps<typeof SheetPrimitive.Close>) { return <SheetPrimitive.Close data-slot="sheet-close" {...props} />; }

function SheetContent({ className, children, side = 'right', ...props }: React.ComponentProps<typeof SheetPrimitive.Content> & { side?: 'right' | 'left' }) {
  return (
    <SheetPrimitive.Portal>
      <SheetPrimitive.Overlay data-slot="sheet-overlay" className="fixed inset-0 z-30 bg-black/35 backdrop-blur-[1.5px] data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0" />
      <SheetPrimitive.Content data-slot="sheet-content"
        className={cn('bayle-sheet fixed top-0 bottom-0 z-30 flex flex-col bg-panel shadow-pop outline-hidden data-[state=open]:animate-in data-[state=open]:duration-200 data-[state=closed]:animate-out data-[state=closed]:duration-150',
          side === 'right' ? 'right-0 border-l border-line2 data-[state=open]:slide-in-from-right-4 data-[state=open]:fade-in-0 data-[state=closed]:slide-out-to-right-4 data-[state=closed]:fade-out-0' : 'left-0 border-r border-line2 data-[state=open]:slide-in-from-left-4', className)}
        {...props}>
        {children}
      </SheetPrimitive.Content>
    </SheetPrimitive.Portal>
  );
}

function SheetHeader({ className, ...props }: React.ComponentProps<'div'>) { return <div data-slot="sheet-header" className={cn('flex items-start gap-3 border-b border-line px-5 pt-4 pb-3', className)} {...props} />; }
function SheetFooter({ className, ...props }: React.ComponentProps<'div'>) { return <div data-slot="sheet-footer" className={cn('flex items-center gap-2 border-t border-line px-5 py-3', className)} {...props} />; }
function SheetTitle({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Title>) { return <SheetPrimitive.Title data-slot="sheet-title" className={cn('m-0 truncate font-serif text-heading leading-tight font-semibold', className)} {...props} />; }
function SheetDescription({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Description>) { return <SheetPrimitive.Description data-slot="sheet-description" className={cn('mt-0.5 text-xs text-t3', className)} {...props} />; }
function SheetCloseButton() {
  return <SheetPrimitive.Close className="grid size-8 shrink-0 place-items-center rounded-sm text-t2 hover:bg-hover hover:text-t1" aria-label="Close"><X className="size-4" /></SheetPrimitive.Close>;
}

export { Sheet, SheetTrigger, SheetClose, SheetContent, SheetHeader, SheetFooter, SheetTitle, SheetDescription, SheetCloseButton };
