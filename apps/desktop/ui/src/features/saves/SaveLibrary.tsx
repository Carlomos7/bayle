import { useState, type ReactNode } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Archive, ChevronRight, History, Pin, Plus, Save, TriangleAlert } from 'lucide-react';
import type { SaveCopy, SaveFile } from '@/api';
import { SearchInput } from '@/components/bayle/controls';
import { cn } from '@/lib/utils';
import { sameSel, usedSlots, type DropTarget, type Selection } from './model';

export interface SaveLibraryProps {
  saves: SaveFile[];
  copies: SaveCopy[];
  launchSaveId?: string;
  selected: Selection | null;
  onSelect: (s: Selection) => void;
  query: string;
  onQuery: (q: string) => void;
  onAdd: () => void;
}

function matches(q: string, ...texts: (string | undefined)[]) {
  return !q || texts.some((t) => t?.toLowerCase().includes(q));
}
const charNames = (slots: { character?: { name: string } }[]) => slots.map((s) => s.character?.name).filter((n): n is string => !!n);

function Item({ sel, selected, onSelect, icon, title, line, right, warn, dim, droppable }: {
  sel: Selection; selected: Selection | null; onSelect: (s: Selection) => void; icon: ReactNode; title: string; line: ReactNode; right?: ReactNode; warn?: string; dim?: boolean; droppable: boolean;
}) {
  const data: DropTarget = { type: 'list', sel };
  const { setNodeRef, isOver } = useDroppable({ id: `list:${sel.kind}:${sel.id}`, data, disabled: !droppable });
  const on = sameSel(sel, selected);
  return (
    <button ref={setNodeRef} type="button" onClick={() => onSelect(sel)} aria-current={on ? 'true' : undefined}
      className={cn(
        'relative grid w-full grid-cols-[18px_1fr_auto] items-center gap-x-2.5 rounded-sm border px-2.5 py-2 text-left transition-colors',
        on ? 'border-accent/45 bg-accent-soft before:absolute before:top-2 before:bottom-2 before:-left-px before:w-[3px] before:rounded-r-xs before:bg-accent' : 'border-line bg-panel hover:border-line2 hover:bg-hover',
        isOver && 'border-accent bg-accent-soft shadow-[0_0_0_2px_var(--accent-ring)]',
        dim && 'opacity-70',
      )}>
      <span className={cn('[&_svg]:size-4', warn ? 'text-warn' : on ? 'text-accent' : 'text-t3')}>{icon}</span>
      <span className="min-w-0">
        <b className="block truncate text-body font-medium">{title}</b>
        <span className="block truncate text-caption text-t3">{line}</span>
      </span>
      <span className="flex items-center gap-1.5 text-xs tabular-nums text-t2">
        {warn && <TriangleAlert className="size-3.5 text-warn" aria-label={warn} />}
        {right}
      </span>
    </button>
  );
}

function Usage({ used, total }: { used: number; total: number }) {
  return (
    <span className="flex items-center gap-1.5" title={`${used} of ${total} slots used`}>
      {used}/{total}
      <span className="h-1 w-6 overflow-hidden rounded-full bg-line2"><span className="block h-full bg-t2" style={{ width: `${(used / Math.max(1, total)) * 100}%` }} /></span>
    </span>
  );
}

function Section({ title, count, note, open, onToggle, children }: { title: string; count?: number; note?: string; open?: boolean; onToggle?: () => void; children: ReactNode }) {
  const collapsible = !!onToggle;
  const head = (
    <span className="flex items-center gap-1.5 text-micro font-semibold tracking-[.08em] text-t3 uppercase">
      {collapsible && <ChevronRight className={cn('size-3 transition-transform', open && 'rotate-90')} />}
      {title}{count !== undefined && <span className="font-normal tracking-normal tabular-nums text-t4">{count}</span>}
      {note && <span className="ml-auto font-normal tracking-normal normal-case text-t4">{note}</span>}
    </span>
  );
  return (
    <div className="flex flex-col gap-1.5">
      {collapsible
        ? <button type="button" aria-expanded={open} onClick={onToggle} className="rounded-xs px-1 py-1 text-left hover:bg-hover">{head}</button>
        : <div className="px-1 py-1">{head}</div>}
      {(!collapsible || open) && <div className="flex flex-col gap-1.5">{children}</div>}
    </div>
  );
}

/** One list for every save: the one Launch uses, the other live saves, kept copies and backups. */
export function SaveLibrary({ saves, copies, launchSaveId, selected, onSelect, query, onQuery, onAdd }: SaveLibraryProps) {
  const [open, setOpen] = useState({ live: true, library: true, backups: false });
  const q = query.trim().toLowerCase();
  const launch = saves.find((s) => s.id === launchSaveId);
  const others = saves.filter((s) => s !== launch && matches(q, s.label, s.fileName, ...charNames(s.slots)));
  const library = copies.filter((c) => c.kind === 'library' && matches(q, c.name, c.fromFile, ...charNames(c.slots)));
  const backups = copies.filter((c) => c.kind === 'backup' && matches(q, c.name, c.fromFile, c.note, ...charNames(c.slots)));
  const searching = !!q;

  const liveItem = (s: SaveFile) => (
    <Item key={s.id} sel={{ kind: 'save', id: s.id }} selected={selected} onSelect={onSelect} droppable icon={<Save />} title={s.label}
      line={<><span className="font-mono">{s.fileName}</span> · {s.source}</>} right={<Usage used={usedSlots(s.slots)} total={s.slots.length} />}
      warn={s.health === 'repair' ? 'Needs a repair' : undefined} />
  );
  const copyItem = (c: SaveCopy) => (
    <Item key={c.id} sel={{ kind: 'copy', id: c.id }} selected={selected} onSelect={onSelect} droppable={false}
      icon={c.kind === 'backup' ? <History /> : <Archive />} title={c.name} dim={c.missing}
      line={c.missing ? 'File missing' : `${c.fromFile ?? ''}${c.fromFile ? ' · ' : ''}${c.kind === 'backup' ? c.note : c.when}`}
      warn={c.missing ? 'File missing' : undefined}
      right={c.pinned ? <Pin className="size-3 text-accent" aria-label="Kept forever" /> : !c.missing ? <span className="text-t3">{charNames(c.slots).length}</span> : undefined} />
  );

  return (
    <div className="flex flex-col gap-4">
      <SearchInput value={query} onChange={onQuery} placeholder="Find a save or character" aria-label="Find a save or character" />
      {launch && matches(q, launch.label, launch.fileName, ...charNames(launch.slots)) && <Section title="Launch uses">{liveItem(launch)}</Section>}
      {others.length > 0 && (
        <Section title="Other live saves" count={others.length} open={open.live || searching} onToggle={searching ? undefined : () => setOpen((o) => ({ ...o, live: !o.live }))}>
          {others.map(liveItem)}
        </Section>
      )}
      {library.length > 0 && (
        <Section title="Library" count={library.length} open={open.library || searching} onToggle={searching ? undefined : () => setOpen((o) => ({ ...o, library: !o.library }))}>
          {library.map(copyItem)}
        </Section>
      )}
      {backups.length > 0 && (
        <Section title="Backups" count={backups.length} note={`newest ${backups[0]?.when ?? ''}`} open={open.backups || searching} onToggle={searching ? undefined : () => setOpen((o) => ({ ...o, backups: !o.backups }))}>
          {backups.map(copyItem)}
        </Section>
      )}
      {searching && !others.length && !library.length && !backups.length && !(launch && matches(q, launch.label, launch.fileName, ...charNames(launch.slots))) && (
        <p className="m-0 px-1 text-ui text-t3">No save or character matches “{query}”.</p>
      )}
      <button type="button" onClick={onAdd} className="flex h-9 items-center justify-center gap-2 rounded-sm border border-dashed border-line2 text-ui text-t3 hover:border-t4 hover:bg-hover hover:text-t1">
        <Plus className="size-3.5" />Add a save file…
      </button>
    </div>
  );
}
