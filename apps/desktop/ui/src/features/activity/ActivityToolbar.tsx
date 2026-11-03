import type { Ref } from 'react';
import { XCircle } from 'lucide-react';
import type { ActivityEntry, ActivityKind, Game } from '@/api';
import { Toolbar } from '@/components/bayle/layout';
import { SearchInput, Segmented, Select, type SegmentOption } from '@/components/bayle/controls';
import { cn } from '@/lib/utils';
import { matches, type ActivityFilter } from './filter';
import { KIND, KIND_ORDER } from './kinds';

interface Props { entries: ActivityEntry[]; games: Game[]; filter: ActivityFilter; onFilter: (f: Partial<ActivityFilter>) => void }

/** Sticky: search first, kind filter, then game and the Failed toggle on the right. */
export function ActivityToolbar({ entries, games, filter, onFilter, ref }: Props & { ref?: Ref<HTMLInputElement> }) {
  const kindCount = (k: ActivityKind | 'all') => entries.filter((a) => (k === 'all' || a.kind === k) && matches(a, filter, 'kind')).length;
  const kinds: SegmentOption<ActivityKind | 'all'>[] = [
    { value: 'all', label: 'All', count: kindCount('all') },
    ...KIND_ORDER.map((k) => ({ value: k, label: KIND[k].label, icon: KIND[k].icon, count: kindCount(k) })),
  ];
  const failCount = entries.filter((a) => !a.ok && matches(a, filter, 'failed')).length;
  return (
    <Toolbar sticky>
      <SearchInput ref={ref} value={filter.q} onChange={(q) => onFilter({ q })} hint="/" placeholder="Search activity" aria-label="Search activity" className="w-[260px] max-[820px]:w-auto max-[820px]:flex-1" />
      <Segmented aria-label="Kind" options={kinds} value={filter.kind} onChange={(kind) => onFilter({ kind })} className="max-w-full overflow-x-auto" />
      <span className="flex-1" />
      <Select aria-label="Game" value={filter.gameId} onChange={(e) => onFilter({ gameId: e.target.value })} className="h-[34px]">
        <option value="all">All games</option>
        {games.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
      </Select>
      <button type="button" aria-pressed={filter.failed} onClick={() => onFilter({ failed: !filter.failed })}
        className={cn('inline-flex h-[34px] items-center gap-1.5 rounded-lg border px-3 text-ui [&_svg]:size-3.5',
          filter.failed ? 'border-bad/45 bg-bad-bg font-semibold text-bad' : 'border-line bg-t1/4 text-t2 hover:text-t1')}>
        <XCircle />Failed<span className={cn('text-caption tabular-nums', filter.failed ? 'text-bad' : 'text-t4')}>{failCount}</span>
      </button>
    </Toolbar>
  );
}
