import { useState } from 'react';
import type { Profile } from '@/api';
import { SearchInput } from '@/components/bayle/controls';
import { Tag } from '@/components/bayle/badge';
import { LinkButton } from '@/components/ui/button';
import { usePieceSearch } from '@/data/hooks';
import { FAMILY } from './words';

/**
 * "Why is my game doing X?" Type what you saw (dash, Dagger, a row id) and
 * see which mod last changed it. The answer is the piece index the merger
 * already keeps, read the other way round.
 */
export function PieceSearch({ profile, onOpenMod, onOpenClash }: { profile: Profile; onOpenMod: (id: string) => void; onOpenClash: (clashId: string) => void }) {
  const [q, setQ] = useState('');
  const hits = usePieceSearch(profile.id, q);
  const name = (id: string) => profile.mods.find((m) => m.id === id)?.name ?? id;
  const list = q.trim() ? hits.data ?? [] : [];
  return (
    <section aria-label="Find what changed something" className="rounded-lg border border-line2 bg-panel">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="text-body font-medium">Something looks different in game?</div>
          <div className="text-xs text-t3">Type what you saw: a weapon, a move, a menu line. Bayle says which mod changed it.</div>
        </div>
        <SearchInput value={q} onChange={setQ} placeholder="dash, Dagger, Rot of Pride…" aria-label="Find what changed something" className="w-[300px] max-[720px]:w-full" />
      </div>
      {q.trim() && (
        <div className="border-t border-line">
          {!list.length ? <p className="m-0 px-4 py-3 text-ui text-t3">{hits.isFetching ? 'Looking…' : `Nothing in this profile mentions "${q.trim()}". Try a shorter word, or the game's own name for it.`}</p> : (
            <ul className="m-0 list-none p-0">
              {list.map((h) => (
                <li key={`${h.file}:${h.piece}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-line px-4 py-2 text-ui last:border-b-0 max-[720px]:grid-cols-1">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5"><span className="truncate">{h.piece}</span><Tag>{FAMILY[h.family].label}</Tag>{h.clashId && <Tag tone="warn">clash</Tag>}</div>
                    <div className="truncate font-mono text-caption text-t3">{h.value}</div>
                  </div>
                  <div className="shrink-0 text-right text-xs text-t3">
                    <LinkButton onClick={() => onOpenMod(h.winnerId)} className="font-medium">{name(h.winnerId)}</LinkButton>
                    {h.changedBy.length > 1 && <> over {h.changedBy.filter((m) => m !== h.winnerId).map(name).join(', ')}</>}
                    {h.clashId && <> · <LinkButton onClick={() => onOpenClash(h.clashId!)}>see why</LinkButton></>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
