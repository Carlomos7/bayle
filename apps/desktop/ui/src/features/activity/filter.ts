import type { ActivityEntry, ActivityKind } from '@/api';

export interface ActivityFilter {
  kind: ActivityKind | 'all';
  gameId: string;
  failed: boolean;
  undoable: boolean;
  q: string;
}

export const emptyFilter: ActivityFilter = { kind: 'all', gameId: 'all', failed: false, undoable: false, q: '' };

export const canUndo = (a: ActivityEntry) => a.undoable && !a.undone;

/** Does an entry pass the filter? `skip` ignores one dimension, so counts on that control stay meaningful. */
export function matches(a: ActivityEntry, f: ActivityFilter, skip?: 'kind' | 'failed'): boolean {
  const q = f.q.trim().toLowerCase();
  return (skip === 'kind' || f.kind === 'all' || a.kind === f.kind)
    && (f.gameId === 'all' || a.gameId === f.gameId)
    && (skip === 'failed' || !f.failed || !a.ok)
    && (!f.undoable || canUndo(a))
    && (!q || `${a.title} ${a.detail}`.toLowerCase().includes(q));
}

const fmt = (d: Date) => d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });

/** Secondary label for a day header: "Today" → "Wed, Oct 21". */
export function dayNote(day: string): string {
  const now = new Date();
  if (day === 'Today') return fmt(now);
  if (day === 'Yesterday') { const y = new Date(now); y.setDate(now.getDate() - 1); return fmt(y); }
  return '';
}

export function groupByDay(rows: ActivityEntry[]): { day: string; rows: ActivityEntry[] }[] {
  const out: { day: string; rows: ActivityEntry[] }[] = [];
  rows.forEach((a) => {
    let g = out.find((x) => x.day === a.day);
    if (!g) out.push((g = { day: a.day, rows: [] }));
    g.rows.push(a);
  });
  return out;
}
