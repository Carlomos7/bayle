import { useEffect, useMemo, useRef, useState } from 'react';
import type { ActivityEntry } from '@/api';
import { useAction, useActivity, useGames } from '@/data/hooks';
import { Page, PageHeader } from '@/components/bayle/layout';
import { ConfirmDialog } from '@/components/bayle/overlay';
import { emptyFilter, matches, type ActivityFilter } from './filter';
import { StatTiles } from './StatTiles';
import { ActivityToolbar } from './ActivityToolbar';
import { Timeline } from './Timeline';
import { LogSheet } from './LogSheet';

/** Everything Bayle did, newest first: filters, a day-grouped timeline, logs and Undo. */
export function ActivityPage() {
  const activity = useActivity();
  const games = useGames();
  const { undo } = useAction();
  const [filter, setFilter] = useState<ActivityFilter>(emptyFilter);
  const [openId, setOpenId] = useState<string | null>(null);
  const [undoTarget, setUndoTarget] = useState<ActivityEntry | null>(null);
  const [logTarget, setLogTarget] = useState<ActivityEntry | null>(null);
  const search = useRef<HTMLInputElement>(null);

  const entries = useMemo(() => activity.data ?? [], [activity.data]);
  const rows = useMemo(() => entries.filter((a) => matches(a, filter)), [entries, filter]);
  const onFilter = (f: Partial<ActivityFilter>) => setFilter((s) => ({ ...s, ...f }));

  // "/" focuses search on this page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || (e.target as HTMLElement | null)?.closest('input,textarea,select')) return;
      e.preventDefault(); search.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <Page>
      <PageHeader eyebrow="All games" title="Activity" subtitle="Everything Bayle did, newest first. Open an entry to see its log or undo it." />
      <StatTiles entries={entries} games={games.data ?? []} filter={filter} onFilter={onFilter} />
      <ActivityToolbar ref={search} entries={entries} games={games.data ?? []} filter={filter} onFilter={onFilter} />
      {activity.isLoading
        ? <div className="py-10 text-center text-ui text-t3">Loading activity…</div>
        : <Timeline rows={rows} games={games.data ?? []} showGame={filter.gameId === 'all'} openId={openId} query={filter.q}
            onToggle={(id) => setOpenId((o) => (o === id ? null : id))} onUndo={setUndoTarget} onOpenLog={setLogTarget} onClear={() => setFilter(emptyFilter)} />}
      <ConfirmDialog open={!!undoTarget} onOpenChange={(o) => !o && setUndoTarget(null)}
        title={`${undoTarget?.undoLabel ?? 'Undo'}: ${undoTarget?.title ?? ''}`} confirmLabel={undoTarget?.undoLabel ?? 'Undo'}
        description="This puts things back exactly as they were before." onConfirm={() => { if (undoTarget) void undo(undoTarget.id); }}>
        <ul className="m-0 flex flex-col gap-1 pl-[18px] text-ui text-t2">{(undoTarget?.undoLines ?? ['It goes back to what it was before']).map((l) => <li key={l}>{l}</li>)}</ul>
      </ConfirmDialog>
      <LogSheet entry={logTarget} onClose={() => setLogTarget(null)} />
    </Page>
  );
}
