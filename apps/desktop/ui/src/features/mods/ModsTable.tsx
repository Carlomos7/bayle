import { useState, type KeyboardEvent } from 'react';
import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, arrayMove, sortableKeyboardCoordinates, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { restrictToVerticalAxis } from './dndModifiers';
import { ChevronRight } from 'lucide-react';
import type { Mod, ModKind } from '@/api';
import { Checkbox } from '@/components/bayle/controls';
import { StatusChip } from '@/components/bayle/badge';
import { cn } from '@/lib/utils';
import { useMods } from './controller';
import { GRID, ModRow, HIDE_NARROW, HIDE_PHONE } from './ModRow';
import { KIND_INFO, byKind, modStatus } from './status';

export interface ModsTableProps {
  visible: Mod[];
  checked: Set<string>;
  activeId: string | null;
  dragDisabled: boolean;
  onCheck: (ids: string[], on: boolean) => void;
  onRowCheck: (id: string, on: boolean, shift: boolean) => void;
  onRowKey: (m: Mod, e: KeyboardEvent<HTMLDivElement>) => void;
  onReorder: (kind: ModKind, ids: string[]) => void;
}

function checkState(ids: string[], checked: Set<string>): boolean | 'indeterminate' {
  const n = ids.filter((id) => checked.has(id)).length;
  return n && n === ids.length ? true : n ? 'indeterminate' : false;
}

/** The bordered table: sticky column header, one banded collapsible group per kind. */
export function ModsTable({ visible, checked, activeId, dragDisabled, onCheck, onRowCheck, onRowKey, onReorder }: ModsTableProps) {
  const c = useMods();
  const [shut, setShut] = useState<Set<ModKind>>(new Set());
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const allIds = visible.map((m) => m.id);

  const onDragEnd = (kind: ModKind) => (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const ids = byKind(c.profile, kind).map((m) => m.id);
    const from = ids.indexOf(String(e.active.id));
    let to = ids.indexOf(String(e.over.id));
    const lockAt = byKind(c.profile, kind).findIndex((m) => m.staysLast);
    if (lockAt >= 0 && to >= lockAt) to = lockAt - 1;
    if (from < 0 || to < 0 || from === to) return;
    onReorder(kind, arrayMove(ids, from, to));
  };

  return (
    <div role="table" aria-label="Mods in this profile" className="overflow-clip rounded-lg border border-line2 bg-panel">
      <div role="row" className={cn(GRID, 'sticky top-0 z-[3] h-9 border-b border-line2 bg-[color-mix(in_srgb,var(--t1)_4%,var(--panel))] text-micro font-semibold tracking-[.07em] text-t3 uppercase')}>
        <span className="grid place-items-center"><Checkbox checked={checkState(allIds, checked)} disabled={!allIds.length} onCheckedChange={(on) => onCheck(allIds, on)} aria-label="Select all shown" /></span>
        <span className={HIDE_PHONE} />
        <span role="columnheader" className={cn('overflow-hidden text-right', HIDE_NARROW)} title="Load order within its group">#</span>
        <span role="columnheader" className="col-span-2 border-l border-line pl-2.5">Name</span>
        <span role="columnheader" className={cn('overflow-hidden border-l border-line pl-2.5', HIDE_NARROW)}>Status</span>
        <span role="columnheader" className="border-l border-line text-center">On</span>
        <span />
      </div>
      {(['package', 'native'] as const).map((kind) => {
        const all = byKind(c.profile, kind);
        const rows = visible.filter((m) => m.kind === kind);
        if (!rows.length) return null;
        const closed = shut.has(kind);
        const issues = rows.filter((m) => modStatus(m, c.profile).issue).length;
        const ids = rows.map((m) => m.id);
        const info = KIND_INFO[kind];
        return (
          <div key={kind} role="rowgroup">
            <div role="row" className={cn(GRID, 'sticky top-9 z-[2] h-[38px] border-y border-line border-b-line2 bg-[color-mix(in_srgb,var(--t1)_3%,var(--bg))] first:border-t-0')}>
              <span className="grid place-items-center"><Checkbox checked={checkState(ids, checked)} onCheckedChange={(on) => onCheck(ids, on)} aria-label={`Select all ${info.title.toLowerCase()}`} /></span>
              <button type="button" onClick={() => setShut((s) => { const n = new Set(s); if (n.has(kind)) n.delete(kind); else n.add(kind); return n; })}
                aria-expanded={!closed} aria-label={`${closed ? 'Show' : 'Hide'} ${info.title}`}
                className="grid size-[18px] place-items-center rounded-xs text-t3 hover:bg-press hover:text-t1">
                <ChevronRight className={cn('size-3 transition-transform', !closed && 'rotate-90')} />
              </button>
              <span role="cell" className="col-span-6 flex min-w-0 items-center gap-2 max-[820px]:col-span-4 max-[480px]:col-span-3">
                <b className="text-ui font-semibold">{info.title}</b>
                <span className="text-xs tabular-nums text-t3">{all.filter((m) => m.enabled).length}/{all.length} on</span>
                {closed && issues > 0 && <StatusChip tone="warn">{issues} need{issues === 1 ? 's' : ''} a look</StatusChip>}
                <span className="ml-1.5 truncate text-ui text-t4 max-[820px]:hidden">{info.hint}</span>
              </span>
            </div>
            {!closed && (
              <DndContext sensors={sensors} collisionDetection={closestCenter} modifiers={[restrictToVerticalAxis]} onDragEnd={onDragEnd(kind)}>
                <SortableContext items={ids} strategy={verticalListSortingStrategy}>
                  {rows.map((m) => (
                    <ModRow key={m.id} mod={m} order={all.indexOf(m) + 1} checked={checked.has(m.id)} active={activeId === m.id} dragDisabled={dragDisabled}
                      onCheck={(on, shift) => onRowCheck(m.id, on, shift)} onKeyDown={(e) => onRowKey(m, e)} />
                  ))}
                </SortableContext>
              </DndContext>
            )}
          </div>
        );
      })}
    </div>
  );
}
