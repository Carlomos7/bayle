import { useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import type { Slot } from '@/api';
import { Sheet, Tabs } from '@/components/bayle/overlay';
import { SectionLabel } from '@/components/bayle/layout';

export interface OpenCharacter { slot: Slot; where: string }

/** Read-only details of one character, as last saved. */
export function CharacterSheet({ open, onClose }: { open: OpenCharacter | null; onClose: () => void }) {
  const [tab, setTab] = useState('ov');
  const ch = open?.slot.character;
  const rows: [string, string][] = ch ? [
    ['Level', String(ch.level)],
    ['Body', ch.body ?? 'unknown'],
    ['Where', ch.location ?? 'unknown'],
    ['Played', ch.playtime ?? 'unknown'],
    ['Runes held', ch.runesHeld?.toLocaleString() ?? '0'],
    ['Mod items', ch.modItems ?? 'none'],
  ] : [];
  return (
    <Sheet open={!!open} onOpenChange={(o) => !o && onClose()} width={440} title={ch?.name ?? ''} subtitle={open ? `${open.where}` : undefined}>
      {open?.slot.problem && (
        <div className="mb-4 flex gap-2 rounded-lg border border-warn/35 bg-warn-bg p-3 text-ui">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" />{open.slot.problem} Repair the save to fix it.
        </div>
      )}
      <Tabs value={tab} onValueChange={setTab} tabs={[
        { value: 'ov', label: 'Overview', content: (
          <div className="rounded-lg border border-line2 bg-panel p-4">
            <SectionLabel className="mb-3">As last saved</SectionLabel>
            <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 text-body">
              {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-t3">{k}</dt><dd className="m-0 tabular-nums">{v}</dd></div>)}
            </dl>
          </div>
        ) },
        { value: 'st', label: 'Stats', content: (
          <div className="rounded-lg border border-dashed border-line2 px-4 py-8 text-center text-ui text-t3">
            Attributes and equipment appear here once the save reader exposes them.
          </div>
        ) },
      ]} />
    </Sheet>
  );
}
