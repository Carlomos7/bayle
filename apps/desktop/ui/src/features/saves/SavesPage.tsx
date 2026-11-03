import { useMemo, useRef, useState } from 'react';
import { DndContext, DragOverlay, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent, type DragOverEvent, type DragStartEvent } from '@dnd-kit/core';
import { Download, FileUp, FolderOpen, MoreHorizontal, Save, Wrench } from 'lucide-react';
import { useAction, useCall, useCopies, useCurrent, useSaves } from '@/data/hooks';
import { Page, PageHeader, EmptyState } from '@/components/bayle/layout';
import { FirstVisit } from '@/components/bayle/first-visit';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/bayle/overlay';
import { DropdownMenu, item, sep } from '@/components/bayle/menu';
import { toast } from '@/state/toasts';
import { SaveLibrary } from './SaveLibrary';
import { LiveSaveCard } from './LiveSaveCard';
import { CopyCard } from './CopyCard';
import { CharacterSheet, type OpenCharacter } from './CharacterSheet';
import { allSources, planCopy, sameSel, type DragChar, type DropTarget, type PendingCopy, type Selection } from './model';

const SPRING_MS = 700;

export function SavesPage() {
  const { game, profile } = useCurrent();
  const gameId = game?.id ?? '';
  const saves = useSaves(gameId);
  const copies = useCopies(gameId);
  const { run } = useAction();
  const call = useCall();

  const [selected, setSelected] = useState<Selection | null>(null);
  const [query, setQuery] = useState('');
  const [character, setCharacter] = useState<OpenCharacter | null>(null);
  const [pending, setPending] = useState<PendingCopy | null>(null);
  const [dragging, setDragging] = useState<DragChar | null>(null);
  const spring = useRef<{ key: string; timer: number } | null>(null);
  // Spring-open can unmount the row being dragged, which drops dnd-kit's copy of its data; keep our own.
  const dragRef = useRef<DragChar | null>(null);

  const saveList = useMemo(() => saves.data ?? [], [saves.data]);
  const copyList = useMemo(() => copies.data ?? [], [copies.data]);
  const sources = useMemo(() => allSources(saveList, copyList), [saveList, copyList]);

  // What is open: the user's pick while it still exists, else the save Launch uses (derived, not stored, so it can't go stale).
  const pickValid = !!selected && (selected.kind === 'save' ? saveList.some((s) => s.id === selected.id) : copyList.some((c) => c.id === selected.id));
  const fallback = saveList.find((s) => s.id === profile?.saveId) ?? saveList[0];
  const current: Selection | null = pickValid ? selected : fallback ? { kind: 'save', id: fallback.id } : null;

  const plan = (p: PendingCopy | string) => { if (typeof p === 'string') toast({ kind: 'warn', title: p }); else setPending(p); };

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }), useSensor(KeyboardSensor));
  const clearSpring = () => { if (spring.current) window.clearTimeout(spring.current.timer); spring.current = null; };
  const onDragStart = (e: DragStartEvent) => { const d = (e.active.data.current as DragChar | undefined) ?? null; dragRef.current = d; setDragging(d); };
  const onDragOver = (e: DragOverEvent) => {
    const t = e.over?.data.current as DropTarget | undefined;
    if (t?.type !== 'list') { clearSpring(); return; }
    const key = `${t.sel.kind}:${t.sel.id}`;
    if (spring.current?.key === key || sameSel(t.sel, current)) return;
    clearSpring();
    spring.current = { key, timer: window.setTimeout(() => setSelected(t.sel), SPRING_MS) };
  };
  const onDragEnd = (e: DragEndEvent) => {
    clearSpring();
    setDragging(null);
    const drag = dragRef.current;
    dragRef.current = null;
    const t = e.over?.data.current as DropTarget | undefined;
    if (!drag || !t) return;
    const saveId = t.type === 'slot' ? t.saveId : t.sel.kind === 'save' ? t.sel.id : null;
    const to = saveList.find((s) => s.id === saveId);
    if (!to) return;
    if (t.type === 'slot' && 'saveId' in drag.ref && drag.ref.saveId === to.id && drag.ref.n === t.n) return;
    plan(planCopy(drag.ref, drag.name, to, t.type === 'slot' ? t.n : undefined));
  };

  const importSave = async () => {
    const path = await call((a) => a.pickFile({ title: 'Import a save file', filters: [{ name: 'Save files', extensions: ['sl2', 'co2'] }] }));
    if (path) await run((a) => a.importSave(gameId, path));
  };
  const repairAll = () => {
    const broken = saveList.filter((s) => s.health === 'repair');
    if (!broken.length) { toast({ kind: 'info', title: 'Every save is healthy', detail: 'Nothing to repair.' }); return; }
    broken.forEach((s) => void run((a) => a.repairSave(s.id)));
  };

  const openSave = current?.kind === 'save' ? saveList.find((s) => s.id === current.id) : undefined;
  const openCopy = current?.kind === 'copy' ? copyList.find((c) => c.id === current.id) : undefined;

  // the Steam account is the save folder's name (17 digits); shown only when every live save is under one
  const accounts = [...new Set(saveList.map((s) => /[\\/](\d{17})[\\/][^\\/]+$/.exec(s.id)?.[1]).filter(Boolean))];
  const account = accounts.length === 1 ? accounts[0]! : null;

  return (
    <Page>
      <PageHeader
        eyebrow={<>{game?.name}{account && <><span aria-hidden>·</span>Steam account {account.slice(0, 4)}…{account.slice(-4)}</>}</>}
        title="Saves"
        subtitle="Drag a character onto a live save, or open a copy to compare and restore. Every write is backed up first and can be undone."
        actions={<>
          <Button icon={<FileUp />} onClick={() => void importSave()}>Import a save file…</Button>
          <Button icon={<Save />} onClick={() => void run((a) => a.backupNow(gameId))}>Back up now</Button>
          <DropdownMenu align="end" items={[
            item('Open saves folder', () => void call(async (a) => { const s = await a.getSettings(); await a.openPath(s.paths.backups); }), { icon: <FolderOpen /> }),
            item('Repair all', repairAll, { icon: <Wrench /> }),
            sep,
            item('Import a save file…', () => void importSave(), { icon: <Download /> }),
          ]} trigger={<Button variant="ghost" iconOnly aria-label="More" icon={<MoreHorizontal />} />} />
      <FirstVisit tipKey="saves" title="Your saves are safe here">
        Modded games can leave a save in a state the game refuses. Bayle checks every save after you play, repairs the known problems, and keeps a backup before every change.
        You only need this page to copy a character between saves, keep a copy you care about, or bring one back.
      </FirstVisit>
        </>}
      />

      {saves.isLoading ? (
        <div className="text-ui text-t3">Reading saves…</div>
      ) : !saveList.length ? (
        <EmptyState title="No saves found" action={<Button onClick={() => void importSave()}>Import a save file…</Button>}>
          Bayle looks in the game's save folder for this Steam account. Play once, or import a save file.
        </EmptyState>
      ) : (
        <DndContext sensors={sensors} onDragStart={onDragStart} onDragOver={onDragOver} onDragEnd={onDragEnd} onDragCancel={() => { clearSpring(); dragRef.current = null; setDragging(null); }}>
          <div className="grid grid-cols-[280px_minmax(0,1fr)] items-start gap-7 max-[1000px]:grid-cols-[240px_minmax(0,1fr)] max-[880px]:grid-cols-1">
            <aside className="sticky top-4 max-[760px]:static">
              <SaveLibrary saves={saveList} copies={copyList} launchSaveId={profile?.saveId} selected={current} onSelect={setSelected}
                query={query} onQuery={setQuery} onAdd={() => void importSave()} />
            </aside>
            <div className="min-w-0">
              {openSave && <LiveSaveCard save={openSave} launchUses={openSave.id === profile?.saveId} saves={saveList} sources={sources} onPlan={plan} onOpenChar={setCharacter} />}
              {openCopy && <CopyCard copy={openCopy} saves={saveList} onPlan={plan} onOpenChar={setCharacter} onRemoved={() => setSelected(null)} />}
            </div>
          </div>
          <DragOverlay dropAnimation={null}>
            {dragging && (
              <div className="pointer-events-none inline-flex items-center gap-2 rounded-sm border border-accent-ring bg-raise px-3 py-1.5 text-body shadow-pop">
                <span className="grid size-5 place-items-center rounded-full bg-accent-soft font-serif text-xs font-semibold text-accent">{dragging.name[0]}</span>
                {dragging.name}<span className="text-xs text-t3">Lv {dragging.level}</span>
              </div>
            )}
          </DragOverlay>
        </DndContext>
      )}

      <CharacterSheet open={character} onClose={() => setCharacter(null)} />
      <ConfirmDialog open={!!pending} onOpenChange={(o) => !o && setPending(null)} confirmLabel={pending?.replaces ? 'Replace' : 'Copy'} danger={!!pending?.replaces}
        title={`Copy ${pending?.name} into ${pending?.saveLabel}?`}
        description={pending?.replaces
          ? `Slot ${pending.n} holds ${pending.replaces}. It is backed up first, and Undo in Activity brings it back.`
          : `Into slot ${pending?.n}, which is empty. The save is backed up first.`}
        onConfirm={() => { const p = pending; if (p) void run((a) => a.copyCharacter(p.from, { saveId: p.saveId, n: p.n })); }} />
    </Page>
  );
}
