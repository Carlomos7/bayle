import { Fragment } from 'react';
import type { ActivityEntry, Game } from '@/api';
import { EmptyState } from '@/components/bayle/layout';
import { LinkButton } from '@/components/ui/button';
import { dayNote, groupByDay } from './filter';
import { EntryRow } from './EntryRow';
import { EntryDetail } from './EntryDetail';

interface Props {
  rows: ActivityEntry[];
  games: Game[];
  showGame: boolean;
  openId: string | null;
  query: string;
  onToggle: (id: string) => void;
  onUndo: (e: ActivityEntry) => void;
  onOpenLog: (e: ActivityEntry) => void;
  onClear: () => void;
}

/** Entries grouped by day, each day its own card with a header that stays put while you scroll. */
export function Timeline({ rows, games, showGame, openId, query, onToggle, onUndo, onOpenLog, onClear }: Props) {
  if (!rows.length) {
    return <EmptyState title={`Nothing matches${query ? ` “${query}”` : ' these filters'}.`} action={<LinkButton onClick={onClear}>Clear filters</LinkButton>} />;
  }
  return (
    <div className="flex flex-col gap-[18px]">
      {groupByDay(rows).map((d) => (
        <section key={d.day} aria-label={d.day} className="rounded-lg border border-line2 bg-panel">
          <header className="sticky top-[54px] z-[2] flex items-baseline gap-2 rounded-t-lg border-b border-line2 bg-[color-mix(in_srgb,var(--t1)_4%,var(--panel))] px-4 py-[9px]">
            <b className="text-xs font-semibold tracking-[.08em] text-t2 uppercase">{d.day}</b>
            <span className="text-xs text-t4">{dayNote(d.day)}</span>
            <span className="ml-auto text-xs tabular-nums text-t4">{d.rows.length}</span>
          </header>
          {d.rows.map((a, i) => (
            <Fragment key={a.id}>
              <EntryRow entry={a} game={games.find((g) => g.id === a.gameId)} showGame={showGame} open={openId === a.id}
                first={i === 0} last={i === d.rows.length - 1} onToggle={() => onToggle(a.id)} onUndo={onUndo} onOpenLog={onOpenLog} />
              {openId === a.id && <EntryDetail entry={a} game={games.find((g) => g.id === a.gameId)} onUndo={onUndo} onOpenLog={onOpenLog} />}
            </Fragment>
          ))}
        </section>
      ))}
    </div>
  );
}
