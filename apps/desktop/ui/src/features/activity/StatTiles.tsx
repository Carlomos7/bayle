import type { ReactNode } from 'react';
import { CheckCircle2, Play, Undo2, XCircle } from 'lucide-react';
import type { ActivityEntry, Game } from '@/api';
import { cn, plural } from '@/lib/utils';
import { canUndo, type ActivityFilter } from './filter';

function Tile({ pressed, onClick, icon, tint, label, value, sub, bad }: { pressed: boolean; onClick: () => void; icon: ReactNode; tint: string; label: string; value: string; sub: string; bad?: boolean }) {
  return (
    <button type="button" aria-pressed={pressed} onClick={onClick}
      className={cn('flex items-start gap-3 rounded-lg border bg-panel px-4 py-3.5 text-left transition-colors hover:bg-[color-mix(in_srgb,var(--t1)_2%,var(--panel))]',
        bad ? 'border-bad/40' : 'border-line2 hover:border-t1/24',
        pressed && 'border-accent-ring shadow-[inset_0_0_0_1px_var(--accent-ring)]')}>
      <span className={cn('grid size-8 shrink-0 place-items-center rounded-sm [&_svg]:size-[15px]', tint)}>{icon}</span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <small className="text-micro font-semibold tracking-[.08em] text-t3 uppercase">{label}</small>
        <b className={cn('font-serif text-lg leading-tight font-semibold', bad && 'text-bad')}>{value}</b>
        <span className="truncate text-xs text-t3">{sub}</span>
      </span>
    </button>
  );
}

/** Three facts that each open a filtered view. */
export function StatTiles({ entries, games, filter, onFilter }: { entries: ActivityEntry[]; games: Game[]; filter: ActivityFilter; onFilter: (f: Partial<ActivityFilter>) => void }) {
  const last = entries.find((a) => a.kind === 'launch' && a.ok);
  const fails = entries.filter((a) => !a.ok);
  const undo = entries.filter(canUndo);
  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id;
  return (
    <div className="grid grid-cols-3 gap-3 max-[980px]:grid-cols-1">
      <Tile pressed={filter.kind === 'launch'} onClick={() => onFilter({ kind: filter.kind === 'launch' ? 'all' : 'launch' })}
        icon={<Play />} tint="bg-accent-soft text-accent" label="Last played"
        value={last ? gameName(last.gameId) : 'Not yet'} sub={last ? `${last.day} ${last.time} · ${last.duration}` : 'Launch a profile to start'} />
      <Tile pressed={filter.failed} onClick={() => onFilter({ failed: !filter.failed })} bad={fails.length > 0}
        icon={fails.length ? <XCircle /> : <CheckCircle2 />} tint={fails.length ? 'bg-bad-bg text-bad' : 'bg-ok-bg text-ok'} label="Failed"
        value={fails.length ? `${fails.length} need a look` : 'Nothing failed'} sub={fails[0] ? `Latest: ${fails[0].title}, ${fails[0].day.toLowerCase()}` : 'All good'} />
      <Tile pressed={filter.undoable} onClick={() => onFilter({ undoable: !filter.undoable })}
        icon={<Undo2 />} tint="bg-t1/7 text-t2" label="Can be undone"
        value={plural(undo.length, 'change')} sub="Open one to see exactly what Undo does" />
    </div>
  );
}
