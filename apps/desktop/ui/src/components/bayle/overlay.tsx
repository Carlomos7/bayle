import type { ReactNode } from 'react';
import { Dialog as UiDialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Sheet as UiSheet, SheetCloseButton, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Tooltip as UiTooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Tabs as UiTabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

/*
 * Bayle's ready-made overlays, composed from shadcn/ui parts. Use these for
 * the common cases; drop to the shadcn parts in components/ui for anything custom.
 */

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  /** Shown above the title, e.g. the wordmark. */
  header?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  width?: number;
}

/** Centred modal for decisions. Escape and the scrim close it; focus is trapped inside. */
export function Dialog({ open, onOpenChange, title, description, header, children, footer, width = 460 }: DialogProps) {
  return (
    <UiDialog open={open} onOpenChange={onOpenChange}>
      <DialogContent style={{ width: `min(${width}px, calc(100vw - 32px))` }}>
        <DialogHeader>
          {header}
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className={cn(!description && 'sr-only')}>{description ?? (typeof title === 'string' ? title : 'Dialog')}</DialogDescription>
        </DialogHeader>
        {children && <DialogBody>{children}</DialogBody>}
        {footer && <DialogFooter>{footer}</DialogFooter>}
      </DialogContent>
    </UiDialog>
  );
}

/** Yes/no decision with the consequence spelled out (shadcn AlertDialog: focus starts on Cancel). */
export function ConfirmDialog({ open, onOpenChange, title, description, children, confirmLabel, danger, onConfirm }: Omit<DialogProps, 'footer' | 'header' | 'width'> & { confirmLabel: string; danger?: boolean; onConfirm: () => void }) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription className={cn(!description && 'sr-only')}>{description ?? 'Confirm'}</AlertDialogDescription>
        </AlertDialogHeader>
        {children && <div className="min-h-0 overflow-auto px-5 pb-4">{children}</div>}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction variant={danger ? 'danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export interface SheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  subtitle?: ReactNode;
  width?: number;
  /** Next to the close button, e.g. a step indicator. */
  headerExtra?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}

/** Right-hand panel for editing one thing while the list stays in view. */
export function Sheet({ open, onOpenChange, title, subtitle, width = 520, headerExtra, children, footer }: SheetProps) {
  return (
    <UiSheet open={open} onOpenChange={onOpenChange}>
      <SheetContent style={{ width: `min(${width}px, 100vw)` }}>
        <SheetHeader>
          <div className="min-w-0 flex-1">
            <SheetTitle>{title}</SheetTitle>
            <SheetDescription className={cn(!subtitle && 'sr-only')}>{subtitle ?? 'Panel'}</SheetDescription>
          </div>
          {headerExtra}
          <SheetCloseButton />
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">{children}</div>
        {footer && <SheetFooter>{footer}</SheetFooter>}
      </SheetContent>
    </UiSheet>
  );
}

export function Tooltip({ content, children, side = 'right' }: { content: ReactNode; children: ReactNode; side?: 'top' | 'right' | 'bottom' | 'left' }) {
  return (
    <UiTooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side}>{content}</TooltipContent>
    </UiTooltip>
  );
}
export { TooltipProvider };

export interface TabDef { value: string; label: ReactNode; count?: number; content: ReactNode }

/** Filled, full-width tabs from a list of definitions. */
export function Tabs({ tabs, value, onValueChange, className }: { tabs: TabDef[]; value: string; onValueChange: (v: string) => void; className?: string }) {
  return (
    <UiTabs value={value} onValueChange={onValueChange} className={cn('min-h-0', className)}>
      <TabsList>
        {tabs.map((t) => (
          <TabsTrigger key={t.value} value={t.value}>
            {t.label}{t.count !== undefined && <span className="text-micro tabular-nums text-t4">{t.count.toLocaleString()}</span>}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((t) => <TabsContent key={t.value} value={t.value}>{t.content}</TabsContent>)}
    </UiTabs>
  );
}
