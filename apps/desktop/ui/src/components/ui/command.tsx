import * as React from 'react';
import { Command as CommandPrimitive } from 'cmdk';
import { Search } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './dialog';

function Command({ className, ...props }: React.ComponentProps<typeof CommandPrimitive>) { return <CommandPrimitive data-slot="command" className={cn('flex h-full w-full flex-col overflow-hidden bg-panel text-t1', className)} {...props} />; }

/**
 * Stricter than cmdk's default fuzzy match, which lets scattered letters
 * through ("theme" matched "Unlock the FPS"). Ranks: start of the label,
 * start of a word, anywhere in the label, then keywords.
 */
function wordFilter(value: string, search: string, keywords?: string[]): number {
  const q = search.trim().toLowerCase();
  if (!q) return 1;
  const v = value.toLowerCase();
  if (v.startsWith(q)) return 1;
  if (v.split(/[\s·:/()+-]+/).some((w) => w.startsWith(q))) return 0.8;
  if (v.includes(q)) return 0.6;
  if (keywords?.some((k) => k.toLowerCase().includes(q))) return 0.5;
  return 0;
}

function CommandDialog({ title = 'Search', description = 'Type to find a page, mod, profile or action.', children, ...props }: React.ComponentProps<typeof Dialog> & { title?: string; description?: string }) {
  return (
    <Dialog {...props}>
      <DialogContent className="top-[12vh] w-[min(600px,calc(100vw-32px))] translate-y-0">
        <DialogTitle className="sr-only">{title}</DialogTitle>
        <DialogDescription className="sr-only">{description}</DialogDescription>
        <Command filter={wordFilter}>{children}</Command>
      </DialogContent>
    </Dialog>
  );
}
function CommandInput({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <div data-slot="command-input-wrapper" className="flex items-center gap-2.5 border-b border-line px-4">
      <Search className="size-4 shrink-0 text-t3" />
      <CommandPrimitive.Input data-slot="command-input" className={cn('h-12 flex-1 bg-transparent text-[14px] text-t1 outline-hidden placeholder:text-t4', className)} {...props} />
    </div>
  );
}
function CommandList({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.List>) { return <CommandPrimitive.List data-slot="command-list" className={cn('max-h-[52vh] overflow-auto p-1.5', className)} {...props} />; }
function CommandEmpty(props: React.ComponentProps<typeof CommandPrimitive.Empty>) { return <CommandPrimitive.Empty data-slot="command-empty" className="px-3 py-6 text-center text-ui text-t3" {...props} />; }
function CommandGroup({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Group>) {
  return <CommandPrimitive.Group data-slot="command-group" className={cn('[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-micro [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:tracking-[.08em] [&_[cmdk-group-heading]]:text-t3 [&_[cmdk-group-heading]]:uppercase', className)} {...props} />;
}
function CommandItem({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Item>) {
  return <CommandPrimitive.Item data-slot="command-item" className={cn("flex h-9 cursor-default items-center gap-2.5 rounded-xs px-2.5 text-body outline-hidden select-none data-[selected=true]:bg-press [&_svg:not([class*='size-'])]:size-4 [&_svg]:text-t3", className)} {...props} />;
}
function CommandShortcut({ className, ...props }: React.ComponentProps<'span'>) { return <span data-slot="command-shortcut" className={cn('ml-auto truncate text-xs text-t3', className)} {...props} />; }

export { Command, CommandDialog, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem, CommandShortcut };
