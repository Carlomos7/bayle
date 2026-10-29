import { useState } from 'react';
import { Eye, MoreHorizontal, PenLine, Pin, PinOff, Trash2, TriangleAlert, Undo2 } from 'lucide-react';
import type { SaveCopy, SaveFile } from '@/api';
import { useAction } from '@/data/hooks';
import { Button } from '@/components/ui/button';
import { Tag } from '@/components/bayle/badge';
import { NameDialog } from '@/components/bayle/name-dialog';
import { ConfirmDialog } from '@/components/bayle/overlay';
import { DropdownMenu, header, item, sep } from '@/components/bayle/menu';
import { SlotRow } from './SlotRow';
import { restoreToMenu } from './menus';
import type { PendingCopy } from './model';
import type { OpenCharacter } from './CharacterSheet';

export interface CopyCardProps {
  copy: SaveCopy;
  saves: SaveFile[];
  onPlan: (p: PendingCopy | string) => void;
  onOpenChar: (c: OpenCharacter) => void;
  /** Called after Remove, so the page can open something else. */
  onRemoved: () => void;
}

/** A kept copy or a backup. Read-only: restore characters or the whole file into a live save. */
export function CopyCard({ copy, saves, onPlan, onOpenChar, onRemoved }: CopyCardProps) {
  const { run } = useAction();
  const [restoreTo, setRestoreTo] = useState<SaveFile | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [removing, setRemoving] = useState(false);
  const backup = copy.kind === 'backup';
  const chars = copy.slots.filter((s) => s.character);

  return (
    <section aria-label={copy.name} className="overflow-hidden rounded-lg border border-line2 bg-panel">
      <header className="flex flex-wrap items-start gap-3 border-b border-line px-5 pt-4 pb-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="m-0 font-serif text-heading leading-tight font-semibold">{copy.name}</h2>
            <Tag>{backup ? 'Backup' : 'Copy'}</Tag>
            {copy.pinned && <Tag tone="accent"><Pin className="size-2.5" />Kept forever</Tag>}
          </div>
          <div className="mt-1 truncate text-xs text-t3">
            {copy.fromFile && <><span className="font-mono text-t2">{copy.fromFile}</span> · </>}{copy.when} · {copy.note}{copy.size ? ` · ${copy.size}` : ''} · {chars.length} character{chars.length === 1 ? '' : 's'}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <DropdownMenu align="end" items={[header('Restore the whole file over'), ...saves.map((s) => item(s.label, () => setRestoreTo(s), { hint: s.fileName }))]}
            trigger={<Button size="sm" icon={<Undo2 />} disabled={copy.missing}>Restore over…</Button>} />
          <DropdownMenu align="end" items={[
            item('Rename…', () => setRenaming(true), { icon: <PenLine />, disabled: copy.missing, why: 'Its file is missing' }),
            ...(backup ? [item(copy.pinned ? 'Let it rotate out' : 'Keep forever', () => void run((a) => a.pinBackup(copy.id, !copy.pinned)), { icon: copy.pinned ? <PinOff /> : <Pin /> })] : []),
            sep,
            item('Remove…', () => setRemoving(true), { icon: <Trash2 />, danger: true }),
          ]} trigger={<Button size="sm" variant="ghost" iconOnly aria-label="More for this copy" icon={<MoreHorizontal />} />} />
        </div>
      </header>

      {copy.missing ? (
        <div className="flex items-center gap-2 px-5 py-6 text-ui text-warn"><TriangleAlert className="size-4" />Its file is missing, so only Remove works.</div>
      ) : chars.length === 0 ? (
        <div className="px-5 py-6 text-center text-ui text-t3">No characters in this copy.</div>
      ) : (
        <div role="list" aria-label="Characters">
          {chars.map((sl) => {
            const from = { copyId: copy.id, n: sl.n };
            const open = () => onOpenChar({ slot: sl, where: `${copy.name}, slot ${sl.n}` });
            return (
              <div role="listitem" key={sl.n}>
                <SlotRow slot={sl} ref_={from} onOpen={open}
                  menu={[item('Open', open, { icon: <Eye /> }), restoreToMenu(from, sl.character?.name ?? '', saves, onPlan)]} />
              </div>
            );
          })}
        </div>
      )}

      <ConfirmDialog open={!!restoreTo} onOpenChange={(o) => !o && setRestoreTo(null)} confirmLabel="Restore"
        title={`Restore ${copy.name} over ${restoreTo?.label}?`}
        description={`Every slot in ${restoreTo?.fileName} is replaced by this copy. The save is backed up first, and Undo in Activity puts it back.`}
        onConfirm={() => { if (restoreTo) void run((a) => a.restoreCopy(copy.id, restoreTo.id)); }} />
      {renaming && <NameDialog onOpenChange={setRenaming} title={backup ? 'Rename backup' : 'Rename copy'} initial={copy.name} submitLabel="Rename" rename
        onSubmit={(name) => void run((a) => a.renameCopy(copy.id, name))} />}
      <ConfirmDialog open={removing} onOpenChange={setRemoving} danger confirmLabel="Remove" title={`Remove ${copy.name}?`}
        description="Its file goes to the Recycle Bin. Restore in Activity brings it back."
        onConfirm={() => { onRemoved(); void run((a) => a.removeCopy(copy.id)); }} />
    </section>
  );
}
