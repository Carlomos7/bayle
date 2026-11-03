import type { KeyboardEvent } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, MoreHorizontal, Pin } from 'lucide-react';
import type { Mod } from '@/api';
import { Checkbox, Switch } from '@/components/bayle/controls';
import { StatusChip, Tag } from '@/components/bayle/badge';
import { ContextMenu, DropdownMenu } from '@/components/bayle/menu';
import { ModThumb } from '@/components/bayle/mod-thumb';
import { FEATURES } from '@/lib/features';
import { cn } from '@/lib/utils';
import { modMenu, useMods } from './controller';
import { modStatus } from './status';
import { dllFile, dllLabel, namedByFile, thumbName } from './identity';

/** Shared by the header, group bands and rows so every column lines up. */
/** Narrow windows drop columns (order, status, then the drag handle) rather than squeezing them: a zero-width column still costs its gap. */
export const GRID = 'grid grid-cols-[28px_18px_22px_32px_minmax(0,1fr)_132px_52px_36px] items-center gap-2.5 pr-3 pl-2 max-[820px]:grid-cols-[28px_18px_32px_minmax(0,1fr)_44px_32px] max-[820px]:gap-2 max-[480px]:grid-cols-[28px_32px_minmax(0,1fr)_40px_28px] max-[480px]:pr-1';
/** Cells hidden as the table narrows, matching GRID. */
export const HIDE_NARROW = 'max-[820px]:hidden';
export const HIDE_PHONE = 'max-[480px]:hidden';

export interface ModRowProps {
  mod: Mod;
  order: number;
  checked: boolean;
  /** The mod whose panel is open. */
  active: boolean;
  dragDisabled: boolean;
  onCheck: (on: boolean, shift: boolean) => void;
  onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => void;
}

/**
 * A click that started on a control in the row (checkbox, switch, menu, a
 * clickable chip, or a menu item rendered in a portal, whose events still
 * bubble through React) is that control's, not "open the panel".
 */
const fromControl = (t: EventTarget | null) => t instanceof Element && !!t.closest('button, a, input, [role="switch"], [role="checkbox"], [role="menuitem"], [role="menu"]');

export function ModRow({ mod: m, order, checked, active, dragDisabled, onCheck, onKeyDown }: ModRowProps) {
  const c = useMods();
  const st = modStatus(m, c.profile);
  const { setNodeRef, setActivatorNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({ id: m.id, disabled: dragDisabled || !!m.staysLast });
  const style = { transform: CSS.Translate.toString(transform), transition };
  const menu = () => modMenu(c, m);

  return (
    <ContextMenu items={menu}>
      <div
        ref={setNodeRef}
        style={style}
        role="row"
        tabIndex={0}
        data-mod={m.id}
        aria-selected={active}
        onKeyDown={onKeyDown}
        onClick={(e) => { if (!fromControl(e.target)) c.openPanel(m.id); }}
        className={cn(GRID, 'group relative min-h-[54px] border-b border-line bg-panel outline-hidden last:border-b-0 hover:bg-[color-mix(in_srgb,var(--t1)_3%,var(--panel))] focus-visible:shadow-[inset_0_0_0_2px_var(--focus)]',
          checked && 'bg-[color-mix(in_srgb,var(--accent)_8%,var(--panel))]',
          active && 'bg-accent-soft shadow-[inset_2px_0_0_var(--accent)]',
          isDragging && 'z-10 opacity-90 shadow-pop',
          !m.enabled && '[&_.mod-name]:text-t3 [&_.mod-line]:text-t4')}
      >
        <span role="cell" className="grid place-items-center">
          <Checkbox checked={checked} onCheckedChange={(on, e) => onCheck(on, !!e?.shiftKey)} aria-label={`Select ${dllLabel(m)}`} title="Select (X). Shift-click selects a range." />
        </span>
        <span role="cell" className={cn('grid place-items-center overflow-hidden text-t4', HIDE_PHONE)}>
          {m.staysLast
            ? <Pin className="size-3.5" aria-label="Stays last" />
            : (
              <button type="button" ref={setActivatorNodeRef} {...attributes} {...listeners} disabled={dragDisabled}
                aria-label={`Drag ${dllLabel(m)} to change the load order`} title={dragDisabled ? 'Clear the search and filter to drag' : 'Drag to change the load order'}
                onClick={(e) => e.stopPropagation()}
                className="grid cursor-grab place-items-center opacity-0 group-hover:opacity-90 group-focus-within:opacity-90 disabled:cursor-not-allowed active:cursor-grabbing">
                <GripVertical className="size-3.5" />
              </button>
            )}
        </span>
        <span role="cell" className={cn('overflow-hidden text-right text-xs tabular-nums text-t4', HIDE_NARROW)}>{order}</span>
        <span role="cell" className="grid place-items-center"><ModThumb name={thumbName(m, c.profile)} src={m.thumbnail} dim={!m.enabled || !!m.missing} /></span>
        <div role="cell" className="flex min-w-0 flex-col gap-0.5 py-1.5">
          <div className="flex min-w-0 items-center gap-1.5 max-[820px]:flex-wrap max-[820px]:gap-y-0.5">
            <b className={cn('mod-name max-w-full truncate text-emphasis font-semibold', namedByFile(m) && 'font-mono text-body')}>{m.name}</b>
            {m.kind === 'native' && !namedByFile(m) && <code className="shrink-0 bg-transparent px-0 text-caption text-t3" title="The DLL file me3 loads">{dllFile(m)}</code>}
            {m.tags.map((t) => <Tag key={t.label} tone={t.tone}>{t.label}</Tag>)}
            {FEATURES.modVersions && m.update && <button type="button" onClick={(e) => { e.stopPropagation(); c.openPanel(m.id, 'update'); }} title={`${m.update.version} is out. See what it changes.`}><Tag tone="info">{m.update.version} available</Tag></button>}
          </div>
          <div className={cn('mod-line truncate text-xs text-t3', st.lineTone === 'warn' && 'text-warn', st.lineTone === 'bad' && 'text-bad')}>{st.line}</div>
        </div>
        <span role="cell" className={cn('overflow-hidden', HIDE_NARROW)}>
          <StatusChip tone={st.tone} title={st.action === 'reinstall' ? 'Install it again' : st.action === 'merge' ? 'Show on Merge' : undefined}
            onClick={st.action === 'reinstall' ? () => c.reinstall(m.id) : st.action === 'merge' ? () => c.openMerge(m.id) : undefined}>{st.label}</StatusChip>
        </span>
        <span role="cell" className="grid place-items-center">
          <Switch size="sm" checked={m.enabled} disabled={!!m.missing} onCheckedChange={(on) => c.setEnabled([m.id], on)}
            aria-label={`${dllLabel(m)} on`} title={m.missing ? 'Its folder is missing: install it again or remove it' : m.enabled ? 'Turn off' : 'Turn on'} />
        </span>
        <span role="cell" className="grid place-items-center">
          <DropdownMenu align="end" items={menu()} trigger={
            <button type="button" aria-label={`More for ${dllLabel(m)}`} title="More"
              className="grid size-7 place-items-center rounded-sm text-t3 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 hover:bg-press hover:text-t1 data-[state=open]:opacity-100 aria-selected:opacity-100">
              <MoreHorizontal className="size-4" />
            </button>
          } />
        </span>
      </div>
    </ContextMenu>
  );
}
