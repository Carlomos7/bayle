import { useDraggable, useDroppable } from '@dnd-kit/core';
import { Clock, MoreHorizontal, Plus, TriangleAlert } from 'lucide-react';
import type { Slot, SlotRef } from '@/api';
import { ContextMenu, DropdownMenu, type MenuEntry } from '@/components/bayle/menu';
import { Tooltip } from '@/components/bayle/overlay';
import { cn } from '@/lib/utils';
import { refKey, type DragChar, type DropTarget } from './model';

export interface SlotRowProps {
  slot: Slot;
  /** Where this slot lives, so it can be dragged. */
  ref_: SlotRef;
  /** Live saves accept drops onto their slots. */
  dropSaveId?: string;
  menu: MenuEntry[];
  /** Menu for an empty slot: copy a character here. */
  emptyMenu?: MenuEntry[];
  onOpen: () => void;
}

/** One character slot. Every row is the same height, empty or not. */
export function SlotRow({ slot, ref_, dropSaveId, menu, emptyMenu, onOpen }: SlotRowProps) {
  const ch = slot.character;
  // Menus render in a portal, but React still bubbles their events through this row. Keep them from opening the sheet or starting a drag.
  const stop = { onClick: (e: React.SyntheticEvent) => e.stopPropagation(), onKeyDown: (e: React.SyntheticEvent) => e.stopPropagation(), onPointerDown: (e: React.SyntheticEvent) => e.stopPropagation() };
  const drag: DragChar | undefined = ch ? { ref: ref_, name: ch.name, level: ch.level } : undefined;
  const { setNodeRef: dragRef, listeners, attributes, isDragging } = useDraggable({ id: `char:${refKey(ref_)}`, data: drag, disabled: !ch });
  const target: DropTarget | undefined = dropSaveId ? { type: 'slot', saveId: dropSaveId, n: slot.n } : undefined;
  const { setNodeRef: dropRef, isOver } = useDroppable({ id: `slot:${dropSaveId ?? 'none'}:${slot.n}`, data: target, disabled: !dropSaveId });

  const row = (
    <div
      ref={(el) => { dragRef(el); dropRef(el); }}
      {...(ch ? listeners : {})}
      {...(ch ? attributes : {})}
      role={ch ? 'button' : undefined}
      tabIndex={ch ? 0 : -1}
      aria-label={ch ? `${ch.name}, level ${ch.level}, slot ${slot.n}. Drag to copy.` : `Slot ${slot.n}, empty`}
      onClick={ch ? onOpen : undefined}
      onKeyDown={(e) => { if (ch && e.key === 'Enter') onOpen(); }}
      className={cn(
        'group grid h-11 grid-cols-[28px_26px_1fr_auto_28px] items-center gap-2 border-b border-line px-2 text-body last:border-b-0',
        ch ? 'cursor-grab hover:bg-hover active:cursor-grabbing' : 'text-t4',
        isDragging && 'opacity-40',
        isOver && 'bg-accent-soft shadow-[inset_0_0_0_1px_var(--accent-ring)]',
      )}
    >
      <span className="text-center text-xs tabular-nums text-t4">{slot.n}</span>
      {ch ? (
        <>
          <span className="grid size-[22px] place-items-center rounded-full bg-accent-soft font-serif text-body font-semibold text-accent">{ch.name[0]}</span>
          <span className="flex min-w-0 flex-col leading-tight">
            <b className={cn('truncate font-medium', slot.stale && 'text-t3')}>{ch.name}</b>
            <span className="truncate text-caption text-t3">{[ch.location, ch.playtime].filter(Boolean).join(' · ')}</span>
          </span>
          <span className="flex items-center gap-1.5 text-xs tabular-nums text-t2">
            Lv {ch.level}
            {slot.problem && <Tooltip side="top" content={slot.problem}><TriangleAlert className="size-3.5 text-warn" aria-label={slot.problem} /></Tooltip>}
            {slot.stale && <Tooltip side="top" content="Not played in a long time"><Clock className="size-3.5 text-t4" aria-label="Not played in a long time" /></Tooltip>}
          </span>
          <span className="contents" {...stop}>
          <DropdownMenu align="end" items={menu} trigger={
            <button type="button" aria-label={`More for ${ch.name}`}
              className="grid size-7 place-items-center rounded-xs text-t3 opacity-60 hover:bg-press hover:text-t1 group-hover:opacity-100 data-[state=open]:opacity-100">
              <MoreHorizontal className="size-4" />
            </button>
          } />
          </span>
        </>
      ) : (
        <>
          <span />
          <span className="text-ui italic">Empty slot</span>
          <span />
          {emptyMenu ? (
            <span className="contents" {...stop}>
            <DropdownMenu align="end" items={emptyMenu} trigger={
              <button type="button" aria-label={`Copy a character into slot ${slot.n}`} title="Copy a character here…"
                className="grid size-7 place-items-center rounded-xs text-t3 opacity-0 hover:bg-accent-soft hover:text-accent focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100">
                <Plus className="size-4" />
              </button>
            } />
            </span>
          ) : <span />}
        </>
      )}
    </div>
  );
  return ch ? <ContextMenu items={menu}>{row}</ContextMenu> : row;
}
