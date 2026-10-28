import type { KeyboardEvent } from 'react';
import { ChevronRight, FileText, Undo2, X } from 'lucide-react';
import type { ActivityEntry, Game } from '@/api';
import { Button } from '@/components/ui/button';
import { Tag } from '@/components/bayle/badge';
import { cn } from '@/lib/utils';
import { canUndo } from './filter';
import { KIND } from './kinds';

interface Props {
  entry: ActivityEntry;
  game?: Game;
  showGame: boolean;
  open: boolean;
  first: boolean;
  last: boolean;
  onToggle: () => void;
  onUndo: (e: ActivityEntry) => void;
  onOpenLog: (e: ActivityEntry) => void;
}

/** One line of the timeline. The whole row toggles its detail; buttons inside do their own thing. */
export function EntryRow({ entry: a, game, showGame, open, first, last, onToggle, onUndo, onOpenLog }: Props) {
  const quick = !a.ok && a.hasLog
    ? <Button size="sm" variant="ghost" icon={<FileText />} onClick={(e) => { e.stopPropagation(); onOpenLog(a); }}>Log</Button>
    : canUndo(a)
      ? <Button size="sm" variant="ghost" icon={<Undo2 />} onClick={(e) => { e.stopPropagation(); onUndo(a); }}>{a.undoLabel ?? 'Undo'}</Button>
      : a.hasLog ? <Button size="sm" variant="ghost" icon={<FileText />} onClick={(e) => { e.stopPropagation(); onOpenLog(a); }}>Log</Button> : null;

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const rows = [...document.querySelectorAll<HTMLElement>('[data-activity-row]')];
      const i = rows.indexOf(e.currentTarget);
      rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))]?.focus();
    }
  };

  return (
    <div role="button" tabIndex={0} aria-expanded={open} data-activity-row data-kind={a.kind} onClick={onToggle} onKeyDown={onKey}
      className={cn('group relative grid min-h-[58px] cursor-pointer grid-cols-[30px_minmax(0,1fr)_auto_auto_18px] items-center gap-3.5 border-b border-line py-2 pr-3.5 pl-4 hover:bg-[color-mix(in_srgb,var(--t1)_2.5%,var(--panel))] max-[820px]:grid-cols-[30px_minmax(0,1fr)_auto_18px]',
        open && 'bg-[color-mix(in_srgb,var(--t1)_4%,var(--panel))]', last && !open && 'border-b-0')}>
      {/* the rail joining icons within a day */}
      {!(first && last) && <span aria-hidden className={cn('absolute left-[30px] w-px bg-line', first ? 'top-1/2 bottom-0' : last ? 'top-0 bottom-1/2' : 'top-0 bottom-0')} />}
      <span className={cn('relative z-[1] grid size-[30px] place-items-center rounded-full shadow-[0_0_0_3px_var(--panel)] [&>svg]:size-3.5', KIND[a.kind].tint,
        !a.ok && 'shadow-[0_0_0_3px_var(--panel),0_0_0_4px_color-mix(in_srgb,var(--bad)_55%,transparent)]')}>
        {KIND[a.kind].icon}
        {!a.ok && <span className="absolute -right-[3px] -bottom-[3px] grid size-3.5 place-items-center rounded-full bg-bad text-bg shadow-[0_0_0_2px_var(--panel)]"><X className="size-[9px]" strokeWidth={3} /></span>}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="flex min-w-0 items-center gap-[7px]">
          <b className={cn('truncate text-emphasis font-[550]', a.undone && 'text-t3')}>{a.title}</b>
          {showGame && game && <Tag tone="neutral"><span title={game.name}>{game.abbr}</span></Tag>}
          {a.undone && <Tag tone="neutral">Undone</Tag>}
          {!a.ok && <Tag tone="bad">Failed</Tag>}
        </span>
        {a.detail && <span className={cn('truncate text-xs', a.ok ? 'text-t3' : 'text-bad')}>{a.detail}</span>}
      </span>
      <span className="flex flex-col items-end gap-0.5">
        <b className="font-mono text-ui font-medium text-t2">{a.time}</b>
        <small className="text-caption whitespace-nowrap text-t4">{a.duration}</small>
      </span>
      <span className="flex min-w-[92px] justify-end opacity-75 group-hover:opacity-100 group-focus-within:opacity-100 max-[820px]:hidden">{quick}</span>
      <ChevronRight className={cn('size-3 text-t4 transition-transform', open && 'rotate-90 text-t2')} />
    </div>
  );
}
