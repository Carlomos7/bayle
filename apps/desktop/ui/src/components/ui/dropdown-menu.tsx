import * as React from 'react';
import { DropdownMenu as DropdownMenuPrimitive } from 'radix-ui';
import { Check, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

export const menuContentClass = 'z-50 min-w-[220px] max-w-[340px] overflow-hidden rounded-lg border border-line2 bg-panel p-[5px] shadow-pop data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0';
export const menuItemClass = "relative flex min-h-8 cursor-default items-center gap-2.5 rounded-xs px-2.5 py-1 text-body text-t1 outline-hidden select-none data-[highlighted]:bg-press data-[disabled]:text-t4 data-[variant=destructive]:text-bad data-[variant=destructive]:data-[highlighted]:bg-bad-bg [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 [&_svg:not([class*='text-'])]:text-t3 data-[variant=destructive]:[&_svg]:text-bad!";

function DropdownMenu(props: React.ComponentProps<typeof DropdownMenuPrimitive.Root>) { return <DropdownMenuPrimitive.Root data-slot="dropdown-menu" {...props} />; }
function DropdownMenuTrigger(props: React.ComponentProps<typeof DropdownMenuPrimitive.Trigger>) { return <DropdownMenuPrimitive.Trigger data-slot="dropdown-menu-trigger" {...props} />; }
function DropdownMenuContent({ className, sideOffset = 4, ...props }: React.ComponentProps<typeof DropdownMenuPrimitive.Content>) {
  return <DropdownMenuPrimitive.Portal><DropdownMenuPrimitive.Content data-slot="dropdown-menu-content" sideOffset={sideOffset} collisionPadding={8} className={cn(menuContentClass, className)} {...props} /></DropdownMenuPrimitive.Portal>;
}
function DropdownMenuItem({ className, variant = 'default', ...props }: React.ComponentProps<typeof DropdownMenuPrimitive.Item> & { variant?: 'default' | 'destructive' }) {
  return <DropdownMenuPrimitive.Item data-slot="dropdown-menu-item" data-variant={variant} className={cn(menuItemClass, className)} {...props} />;
}
function DropdownMenuCheckboxItem({ className, children, checked, ...props }: React.ComponentProps<typeof DropdownMenuPrimitive.CheckboxItem>) {
  return (
    <DropdownMenuPrimitive.CheckboxItem data-slot="dropdown-menu-checkbox-item" checked={checked} className={cn(menuItemClass, 'pl-8', className)} {...props}>
      <span className="absolute left-2.5 grid size-4 place-items-center"><DropdownMenuPrimitive.ItemIndicator><Check className="text-accent!" /></DropdownMenuPrimitive.ItemIndicator></span>
      {children}
    </DropdownMenuPrimitive.CheckboxItem>
  );
}
function DropdownMenuLabel({ className, ...props }: React.ComponentProps<typeof DropdownMenuPrimitive.Label>) { return <DropdownMenuPrimitive.Label data-slot="dropdown-menu-label" className={cn('truncate px-2.5 pt-1.5 pb-1 text-micro font-semibold tracking-[.08em] text-t3 uppercase', className)} {...props} />; }
function DropdownMenuSeparator({ className, ...props }: React.ComponentProps<typeof DropdownMenuPrimitive.Separator>) { return <DropdownMenuPrimitive.Separator data-slot="dropdown-menu-separator" className={cn('my-1 h-px bg-line', className)} {...props} />; }
function DropdownMenuShortcut({ className, ...props }: React.ComponentProps<'span'>) { return <span data-slot="dropdown-menu-shortcut" className={cn('ml-auto font-mono text-micro text-t4', className)} {...props} />; }
function DropdownMenuSub(props: React.ComponentProps<typeof DropdownMenuPrimitive.Sub>) { return <DropdownMenuPrimitive.Sub data-slot="dropdown-menu-sub" {...props} />; }
function DropdownMenuSubTrigger({ className, children, ...props }: React.ComponentProps<typeof DropdownMenuPrimitive.SubTrigger>) {
  return <DropdownMenuPrimitive.SubTrigger data-slot="dropdown-menu-sub-trigger" className={cn(menuItemClass, 'data-[state=open]:bg-press', className)} {...props}>{children}<ChevronRight className="ml-auto size-3.5!" /></DropdownMenuPrimitive.SubTrigger>;
}
function DropdownMenuSubContent({ className, ...props }: React.ComponentProps<typeof DropdownMenuPrimitive.SubContent>) {
  return <DropdownMenuPrimitive.Portal><DropdownMenuPrimitive.SubContent data-slot="dropdown-menu-sub-content" sideOffset={6} alignOffset={-5} className={cn(menuContentClass, className)} {...props} /></DropdownMenuPrimitive.Portal>;
}

export { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuCheckboxItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuShortcut, DropdownMenuSub, DropdownMenuSubTrigger, DropdownMenuSubContent };
