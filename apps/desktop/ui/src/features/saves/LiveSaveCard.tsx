import { useState } from 'react';
import { Archive, Eye, FolderOpen, MoreHorizontal, Play, Trash2, TriangleAlert, Wrench } from 'lucide-react';
import type { SaveFile } from '@/api';
import { useAction, useCall } from '@/data/hooks';
import { Button } from '@/components/ui/button';
import { Tag } from '@/components/bayle/badge';
import { NameDialog } from '@/components/bayle/name-dialog';
import { ConfirmDialog } from '@/components/bayle/overlay';
import { DropdownMenu, item, sep } from '@/components/bayle/menu';
import { cn } from '@/lib/utils';
import { toast } from '@/state/toasts';
import { SlotRow } from './SlotRow';
import { copyHereMenu, copyToMenu } from './menus';
import { usedSlots, type CharSource, type PendingCopy } from './model';
import type { OpenCharacter } from './CharacterSheet';

export interface LiveSaveCardProps {
  save: SaveFile;
  launchUses: boolean;
  saves: SaveFile[];
  sources: CharSource[];
  onPlan: (p: PendingCopy | string) => void;
  onOpenChar: (c: OpenCharacter) => void;
}

const today = () => new Date().toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

/** A save the game writes to. Characters can be copied in, out, and deleted; every write is backed up first. */
export function LiveSaveCard({ save, launchUses, saves, sources, onPlan, onOpenChar }: LiveSaveCardProps) {
  const { run, pending } = useAction();
  const call = useCall();
  const [keepOpen, setKeepOpen] = useState(false);
  const [del, setDel] = useState<{ n: number; name: string } | null>(null);
  const used = usedSlots(save.slots);
  const total = save.slots.length;
  const needsRepair = save.health === 'repair';

  const openKeep = () => setKeepOpen(true);

  return (
    <section aria-label={`${save.label} save`} className="overflow-hidden rounded-lg border border-line2 bg-panel">
      <header className="flex flex-wrap items-start gap-3 px-5 pt-4 pb-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="m-0 font-serif text-heading leading-tight font-semibold">{save.label}</h2>
            <Tag>Live</Tag>
            {launchUses && <Tag tone="accent"><Play className="size-2.5" />Launch uses this</Tag>}
          </div>
          <div className="mt-1 truncate text-xs text-t3" title={save.sourceDetail}>
            <span className="font-mono text-t2">{save.fileName}</span> · {used} of {total} slot{total === 1 ? '' : 's'} used · {save.source}{save.usedBy.length ? `, used by ${save.usedBy.join(', ')}` : ''}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant={needsRepair ? 'danger' : 'ghost'} disabled={pending}
            className={cn(needsRepair && 'border-warn/50 text-warn hover:bg-warn-bg')}
            icon={needsRepair ? <TriangleAlert /> : <Wrench />} title={needsRepair ? 'A character is out of step. Repair re-signs the save; a backup is kept first.' : 'Re-sign the save. A backup is kept first.'}
            onClick={() => void run((a) => a.repairSave(save.id))}>Repair</Button>
          <Button size="sm" icon={<Archive />} onClick={openKeep}>Keep a copy</Button>
          <DropdownMenu align="end" items={[
            item('Keep a copy…', openKeep, { icon: <Archive /> }),
            item('Repair', () => void run((a) => a.repairSave(save.id)), { icon: <Wrench /> }),
            sep,
            item('Show in folder', () => void call(async (a) => { const s = await a.getSettings(); await a.openPath(s.paths.backups); }), { icon: <FolderOpen /> }),
            item('Where it comes from', () => toast({ kind: 'info', title: `Made by ${save.source}`, detail: save.sourceDetail }), { icon: <Eye /> }),
          ]} trigger={<Button size="sm" variant="ghost" iconOnly aria-label="More for this save" icon={<MoreHorizontal />} />} />
        </div>
      </header>
      <div className="h-0.5 bg-line" aria-hidden><div className="h-full bg-accent transition-[width]" style={{ width: `${(used / Math.max(1, total)) * 100}%` }} /></div>
      <div role="list" aria-label="Slots">
        {save.slots.map((sl) => {
          const ch = sl.character;
          const from = { saveId: save.id, n: sl.n };
          return (
            <div role="listitem" key={sl.n}>
              <SlotRow slot={sl} ref_={from} dropSaveId={save.id}
                onOpen={() => onOpenChar({ slot: sl, where: `${save.label}, slot ${sl.n}` })}
                menu={ch ? [
                  item('Open', () => onOpenChar({ slot: sl, where: `${save.label}, slot ${sl.n}` }), { icon: <Eye /> }),
                  copyToMenu(from, ch.name, saves, onPlan),
                  sep,
                  item('Delete…', () => setDel({ n: sl.n, name: ch.name }), { icon: <Trash2 />, danger: true, kbd: 'Del' }),
                ] : []}
                emptyMenu={copyHereMenu(save, sl.n, sources.filter((s) => !('saveId' in s.ref && s.ref.saveId === save.id && s.ref.n === sl.n)), onPlan)}
              />
            </div>
          );
        })}
      </div>

      {keepOpen && <NameDialog onOpenChange={setKeepOpen} title="Keep a copy" description={`A copy of the whole ${save.fileName} goes into your library. It never rotates out.`}
        initial={`${save.label} · ${today()}`} submitLabel="Keep copy" optional
        onSubmit={(name) => void run((a) => a.keepCopy(save.id, name || save.label))} />}
      <ConfirmDialog open={!!del} onOpenChange={(o) => !o && setDel(null)} danger confirmLabel="Delete character"
        title={`Delete ${del?.name}?`} description={`Slot ${del?.n} of ${save.label} becomes empty. The save is backed up first, and Restore in Activity brings the character back.`}
        onConfirm={() => { if (del) void run((a) => a.deleteCharacter(save.id, del.n)); }} />
    </section>
  );
}
