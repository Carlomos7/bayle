import * as React from 'react';
import { ContextMenu as ContextMenuPrimitive } from 'radix-ui';
import { Check, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { menuContentClass, menuItemClass } from './dropdown-menu';

function ContextMenu(props: React.ComponentProps<typeof ContextMenuPrimitive.Root>) { return <ContextMenuPrimitive.Root data-slot="context-menu" {...props} />; }
function ContextMenuTrigger(props: React.ComponentProps<typeof ContextMenuPrimitive.Trigger>) { return <ContextMenuPrimitive.Trigger data-slot="context-menu-trigger" {...props} />; }
function ContextMenuContent({ className, ...props }: React.ComponentProps<typeof ContextMenuPrimitive.Content>) {
  return <ContextMenuPrimitive.Portal><ContextMenuPrimitive.Content data-slot="context-menu-content" collisionPadding={8} className={cn(menuContentClass, className)} {...props} /></ContextMenuPrimitive.Portal>;
}
function ContextMenuItem({ className, variant = 'default', ...props }: React.ComponentProps<typeof ContextMenuPrimitive.Item> & { variant?: 'default' | 'destructive' }) {
  return <ContextMenuPrimitive.Item data-slot="context-menu-item" data-variant={variant} className={cn(menuItemClass, className)} {...props} />;
}
function ContextMenuCheckboxItem({ className, children, checked, ...props }: React.ComponentProps<typeof ContextMenuPrimitive.CheckboxItem>) {
  return (
    <ContextMenuPrimitive.CheckboxItem data-slot="context-menu-checkbox-item" checked={checked} className={cn(menuItemClass, 'pl-8', className)} {...props}>
      <span className="absolute left-2.5 grid size-4 place-items-center"><ContextMenuPrimitive.ItemIndicator><Check className="text-accent!" /></ContextMenuPrimitive.ItemIndicator></span>
      {children}
    </ContextMenuPrimitive.CheckboxItem>
  );
}
function ContextMenuLabel({ className, ...props }: React.ComponentProps<typeof ContextMenuPrimitive.Label>) { return <ContextMenuPrimitive.Label data-slot="context-menu-label" className={cn('truncate px-2.5 pt-1.5 pb-1 text-micro font-semibold tracking-[.08em] text-t3 uppercase', className)} {...props} />; }
function ContextMenuSeparator({ className, ...props }: React.ComponentProps<typeof ContextMenuPrimitive.Separator>) { return <ContextMenuPrimitive.Separator data-slot="context-menu-separator" className={cn('my-1 h-px bg-line', className)} {...props} />; }
function ContextMenuSub(props: React.ComponentProps<typeof ContextMenuPrimitive.Sub>) { return <ContextMenuPrimitive.Sub data-slot="context-menu-sub" {...props} />; }
function ContextMenuSubTrigger({ className, children, ...props }: React.ComponentProps<typeof ContextMenuPrimitive.SubTrigger>) {
  return <ContextMenuPrimitive.SubTrigger data-slot="context-menu-sub-trigger" className={cn(menuItemClass, 'data-[state=open]:bg-press', className)} {...props}>{children}<ChevronRight className="ml-auto size-3.5!" /></ContextMenuPrimitive.SubTrigger>;
}
function ContextMenuSubContent({ className, ...props }: React.ComponentProps<typeof ContextMenuPrimitive.SubContent>) {
  return <ContextMenuPrimitive.Portal><ContextMenuPrimitive.SubContent data-slot="context-menu-sub-content" sideOffset={6} alignOffset={-5} className={cn(menuContentClass, className)} {...props} /></ContextMenuPrimitive.Portal>;
}

export { ContextMenu, ContextMenuTrigger, ContextMenuContent, ContextMenuItem, ContextMenuCheckboxItem, ContextMenuLabel, ContextMenuSeparator, ContextMenuSub, ContextMenuSubTrigger, ContextMenuSubContent };
