/* eslint-disable react-refresh/only-export-components -- tiny entry builders belong with the menu */
import type { ReactNode } from 'react';
import { Check } from 'lucide-react';
import {
  DropdownMenu as UiDropdown, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuShortcut,
  DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  ContextMenu as UiContext, ContextMenuContent, ContextMenuItem, ContextMenuLabel, ContextMenuSeparator, ContextMenuSub,
  ContextMenuSubContent, ContextMenuSubTrigger, ContextMenuTrigger,
} from '@/components/ui/context-menu';

/**
 * One item model for dropdowns and right-click menus, so both look and
 * behave the same. Disabled items say why, instead of just greying out.
 * Rendered with shadcn's DropdownMenu and ContextMenu.
 */
export type MenuEntry =
  | { type: 'item'; label: ReactNode; icon?: ReactNode; kbd?: string; hint?: string; danger?: boolean; checked?: boolean; disabled?: boolean; why?: string; onSelect: () => void }
  | { type: 'sub'; label: ReactNode; icon?: ReactNode; disabled?: boolean; why?: string; items: MenuEntry[] }
  | { type: 'separator' }
  | { type: 'header'; label: ReactNode };

export const item = (label: ReactNode, onSelect: () => void, o: Partial<Omit<Extract<MenuEntry, { type: 'item' }>, 'type' | 'label' | 'onSelect'>> = {}): MenuEntry => ({ type: 'item', label, onSelect, ...o });
export const sep: MenuEntry = { type: 'separator' };
export const header = (label: ReactNode): MenuEntry => ({ type: 'header', label });
export const sub = (label: ReactNode, items: MenuEntry[], o: { icon?: ReactNode; disabled?: boolean; why?: string } = {}): MenuEntry => ({ type: 'sub', label, items, ...o });

/** The inside of one item: check or icon, label with hint/why, shortcut. */
function ItemBody({ e }: { e: Extract<MenuEntry, { type: 'item' }> }) {
  return (
    <>
      {e.checked !== undefined ? <span className="grid size-4 place-items-center">{e.checked && <Check className="text-accent!" />}</span> : e.icon}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate">{e.label}</span>
        {e.hint && <span className="truncate text-caption text-t3">{e.hint}</span>}
        {e.disabled && e.why && <span className="truncate text-caption text-t4">{e.why}</span>}
      </span>
      {e.kbd && <DropdownMenuShortcut>{e.kbd}</DropdownMenuShortcut>}
    </>
  );
}
const empty = <div className="px-2.5 py-1.5 text-xs text-t3">Nothing here</div>;

function DropdownItems({ entries }: { entries: MenuEntry[] }) {
  return entries.map((e, i) => {
    switch (e.type) {
      case 'separator': return <DropdownMenuSeparator key={i} />;
      case 'header': return <DropdownMenuLabel key={i}>{e.label}</DropdownMenuLabel>;
      case 'sub': return (
        <DropdownMenuSub key={i}>
          <DropdownMenuSubTrigger disabled={e.disabled} title={e.disabled ? e.why : undefined}>{e.icon}<span className="flex-1 truncate">{e.label}</span></DropdownMenuSubTrigger>
          <DropdownMenuSubContent>{e.items.length ? <DropdownItems entries={e.items} /> : empty}</DropdownMenuSubContent>
        </DropdownMenuSub>
      );
      default: return (
        <DropdownMenuItem key={i} disabled={e.disabled} variant={e.danger ? 'destructive' : 'default'} onSelect={e.onSelect} title={e.disabled ? e.why : undefined}>
          <ItemBody e={e} />
        </DropdownMenuItem>
      );
    }
  });
}

function ContextItems({ entries }: { entries: MenuEntry[] }) {
  return entries.map((e, i) => {
    switch (e.type) {
      case 'separator': return <ContextMenuSeparator key={i} />;
      case 'header': return <ContextMenuLabel key={i}>{e.label}</ContextMenuLabel>;
      case 'sub': return (
        <ContextMenuSub key={i}>
          <ContextMenuSubTrigger disabled={e.disabled} title={e.disabled ? e.why : undefined}>{e.icon}<span className="flex-1 truncate">{e.label}</span></ContextMenuSubTrigger>
          <ContextMenuSubContent>{e.items.length ? <ContextItems entries={e.items} /> : empty}</ContextMenuSubContent>
        </ContextMenuSub>
      );
      default: return (
        <ContextMenuItem key={i} disabled={e.disabled} variant={e.danger ? 'destructive' : 'default'} onSelect={e.onSelect} title={e.disabled ? e.why : undefined}>
          <ItemBody e={e} />
        </ContextMenuItem>
      );
    }
  });
}

export function DropdownMenu({ trigger, items, align = 'start', side = 'bottom' }: { trigger: ReactNode; items: MenuEntry[]; align?: 'start' | 'end' | 'center'; side?: 'top' | 'bottom' }) {
  return (
    <UiDropdown modal={false}>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent align={align} side={side}><DropdownItems entries={items} /></DropdownMenuContent>
    </UiDropdown>
  );
}

/** Wrap anything to give it a right-click (and Shift+F10) menu. */
export function ContextMenu({ items, children, onOpenChange }: { items: MenuEntry[] | (() => MenuEntry[]); children: ReactNode; onOpenChange?: (open: boolean) => void }) {
  return (
    <UiContext modal={false} onOpenChange={onOpenChange}>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent><ContextItems entries={typeof items === 'function' ? items() : items} /></ContextMenuContent>
    </UiContext>
  );
}
