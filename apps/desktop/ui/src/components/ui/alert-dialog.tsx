import * as React from 'react';
import { AlertDialog as AlertDialogPrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';
import { buttonVariants } from './button';

function AlertDialog(props: React.ComponentProps<typeof AlertDialogPrimitive.Root>) { return <AlertDialogPrimitive.Root data-slot="alert-dialog" {...props} />; }
function AlertDialogTrigger(props: React.ComponentProps<typeof AlertDialogPrimitive.Trigger>) { return <AlertDialogPrimitive.Trigger data-slot="alert-dialog-trigger" {...props} />; }

function AlertDialogContent({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Content>) {
  return (
    <AlertDialogPrimitive.Portal>
      <AlertDialogPrimitive.Overlay data-slot="alert-dialog-overlay" className="fixed inset-0 z-40 bg-black/55 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <AlertDialogPrimitive.Content data-slot="alert-dialog-content"
        className={cn('fixed top-1/2 left-1/2 z-40 flex max-h-[calc(100vh-48px)] w-[min(460px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-line2 bg-panel shadow-pop outline-hidden data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[.98]', className)}
        {...props} />
    </AlertDialogPrimitive.Portal>
  );
}
function AlertDialogHeader({ className, ...props }: React.ComponentProps<'div'>) { return <div data-slot="alert-dialog-header" className={cn('flex flex-col gap-1.5 px-5 pt-5 pb-3', className)} {...props} />; }
function AlertDialogFooter({ className, ...props }: React.ComponentProps<'div'>) { return <div data-slot="alert-dialog-footer" className={cn('flex items-center justify-end gap-2 border-t border-line bg-[color-mix(in_srgb,var(--t1)_2%,var(--panel))] px-5 py-3', className)} {...props} />; }
function AlertDialogTitle({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Title>) { return <AlertDialogPrimitive.Title data-slot="alert-dialog-title" className={cn('m-0 font-serif text-heading leading-tight font-semibold', className)} {...props} />; }
function AlertDialogDescription({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Description>) { return <AlertDialogPrimitive.Description data-slot="alert-dialog-description" className={cn('text-ui text-t3', className)} {...props} />; }
function AlertDialogAction({ className, variant = 'primary', ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Action> & { variant?: 'primary' | 'danger' }) { return <AlertDialogPrimitive.Action className={cn(buttonVariants({ variant }), className)} {...props} />; }
function AlertDialogCancel({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Cancel>) { return <AlertDialogPrimitive.Cancel className={cn(buttonVariants({ variant: 'ghost' }), className)} {...props} />; }

export { AlertDialog, AlertDialogTrigger, AlertDialogContent, AlertDialogHeader, AlertDialogFooter, AlertDialogTitle, AlertDialogDescription, AlertDialogAction, AlertDialogCancel };
