import type { SetupDll } from '@/api';
import { Input, Switch } from '@/components/bayle/controls';
import { Card, EmptyState, SectionLabel } from '@/components/bayle/layout';
import type { Draft } from './actions';

function Row({ label, help, children }: { label: string; help: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-6 border-b border-line py-3 last:border-b-0">
      <div className="min-w-0"><div className="text-body font-medium">{label}</div><p className="m-0 mt-0.5 text-xs text-t3">{help}</p></div>
      <div className="shrink-0 pt-0.5">{children}</div>
    </div>
  );
}

/** Step 2: one card per native the overhaul ships. */
export function DllStep({ draft, onChange }: { draft: Draft; onChange: (d: Draft) => void }) {
  const set = (i: number, patch: Partial<SetupDll>) => onChange({ ...draft, dlls: draft.dlls.map((d, j) => (j === i ? { ...d, ...patch } : d)) });
  if (!draft.dlls.length) return <EmptyState title="No natives">{draft.name} ships no DLLs, so there is nothing to set here.</EmptyState>;
  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-ui text-t3">{draft.name} needs these to start. {draft.savedOn ? 'They come from your saved setup.' : 'Bayle read them from the download.'}</p>
      {draft.dlls.map((d, i) => (
        <Card key={d.name} className="px-4 pt-3 pb-1">
          <SectionLabel className="mb-1 font-mono tracking-normal normal-case text-t1">{d.name}</SectionLabel>
          <Row label="Start early" help="Starts before the game sets itself up. me3 load_early.">
            <Switch checked={d.loadEarly} onCheckedChange={(v) => set(i, { loadEarly: v })} aria-label={`${d.name} starts early`} />
          </Row>
          <Row label="Load after the other natives" help="So it can find the mods it builds on.">
            <Switch checked={d.loadAfterOthers} onCheckedChange={(v) => set(i, { loadAfterOthers: v })} aria-label={`${d.name} loads after the other natives`} />
          </Row>
          <Row label="Function to call when it loads" help="Leave empty if its readme doesn't mention one.">
            <Input className="w-[200px] font-mono" value={d.initFunction} onChange={(e) => set(i, { initFunction: e.target.value })} aria-label={`${d.name} init function`} placeholder="Function name" />
          </Row>
        </Card>
      ))}
    </div>
  );
}
