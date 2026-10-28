import { useState } from 'react';
import { ArrowDown, ArrowUp, TriangleAlert } from 'lucide-react';
import type { BuildReport, FileFamily, Profile } from '@/api';
import { Dialog } from '@/components/bayle/overlay';
import { Checkbox } from '@/components/bayle/controls';
import { Button } from '@/components/ui/button';
import { useAction } from '@/data/hooks';
import { cn } from '@/lib/utils';
import { kindOrder, modName } from './explain';
import { FAMILY } from './words';

/** Kinds that belong together. A moveset's animations point at its behaviour graphs; mixing them can leave moves with nothing to play. */
const COUPLE_WITH: Partial<Record<FileFamily, FileFamily[]>> = { animations: ['behaviour'] };

/**
 * Set the order for one kind of file, winner first. Moving a mod to the top
 * of Animations asks whether its behaviour file should come along.
 */
export function RuleDialog({ profile: p, build: b, family, open, onOpenChange }: { profile: Profile; build: BuildReport; family: FileFamily; open: boolean; onOpenChange: (o: boolean) => void }) {
  const current = kindOrder(p, b, family);
  const [order, setOrder] = useState(current.order);
  const couplable = (COUPLE_WITH[family] ?? []).filter((f) => b.clashes.some((c) => c.family === f));
  const [coupled, setCoupled] = useState<FileFamily[]>(current.rule?.coupled ?? couplable);
  const { run, pending } = useAction();
  const loadOrder = [...order].sort((x, y) => p.mods.findIndex((m) => m.id === y) - p.mods.findIndex((m) => m.id === x));
  const same = (a: string[], z: string[]) => a.join() === z.join();
  const isLoadOrder = same(order, loadOrder) && !coupled.length;
  const move = (i: number, d: -1 | 1) => { const n = [...order]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x!); setOrder(n); };
  const kind = FAMILY[family].label;
  const affected = b.clashes.filter((c) => c.family === family || coupled.includes(c.family)).length;

  const save = async () => {
    onOpenChange(false);
    await run((a) => a.setRule(p.id, family, isLoadOrder ? null : order, coupled));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} width={520} title={`Who wins ${kind.toLowerCase()}?`}
      description={`Top wins every ${kind.toLowerCase()} clash between these mods, unless you picked a single piece yourself. It also applies to new clashes later, for example after an update.`}
      footer={<>
        {current.source === 'rule' && <Button variant="ghost" className="mr-auto" onClick={() => { onOpenChange(false); void run((a) => a.setRule(p.id, family, null)); }}>Back to load order</Button>}
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" disabled={pending} onClick={() => void save()}>{isLoadOrder ? 'Follow load order' : 'Save rule'}</Button>
      </>}>
      <div className="flex flex-col gap-3">
        <ol className="m-0 list-none overflow-hidden rounded-lg border border-line2 p-0">
          {order.map((id, i) => (
            <li key={id} className="flex items-center gap-3 border-b border-line px-3 py-2 last:border-b-0">
              <span className="w-12 text-xs text-t4">{i === 0 ? 'wins' : `then ${i + 1}`}</span>
              <span className={cn('flex-1 truncate text-body', i === 0 && 'font-semibold')}>{modName(p, id)}</span>
              <Button size="icon-sm" variant="ghost" iconOnly aria-label={`Move ${modName(p, id)} up`} icon={<ArrowUp />} disabled={i === 0} onClick={() => move(i, -1)} />
              <Button size="icon-sm" variant="ghost" iconOnly aria-label={`Move ${modName(p, id)} down`} icon={<ArrowDown />} disabled={i === order.length - 1} onClick={() => move(i, 1)} />
            </li>
          ))}
        </ol>
        {couplable.map((f) => (
          <label key={f} className="flex items-start gap-2.5 rounded-lg border border-line2 bg-panel px-3 py-2.5 text-ui">
            <Checkbox checked={coupled.includes(f)} onCheckedChange={(on) => setCoupled(on ? [...coupled, f] : coupled.filter((x) => x !== f))} aria-label={`Keep ${FAMILY[f].label.toLowerCase()} together`} />
            <span>
              <b className="font-semibold">Also use {modName(p, order[0])}'s {FAMILY[f].label.toLowerCase()} file</b>
              <span className="block text-t3">A moveset's {kind.toLowerCase()} point at its {FAMILY[f].label.toLowerCase()}. Without it, some moves may not play.</span>
              {!coupled.includes(f) && <span className="mt-1 flex items-center gap-1.5 text-warn"><TriangleAlert className="size-3.5" />Mixing them is something neither author tested.</span>}
            </span>
          </label>
        ))}
        <p className="m-0 text-xs text-t3">Settles {affected} clash{affected === 1 ? '' : 'es'} now. Nothing is written until you rebuild.</p>
      </div>
    </Dialog>
  );
}
