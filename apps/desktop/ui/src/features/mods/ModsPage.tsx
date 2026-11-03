import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Download, FolderPlus, GitMerge, MoreHorizontal, FileCode2, Upload, Wand2 } from 'lucide-react';
import { SuggestWinnersDialog } from '@/features/merge/SuggestWinnersDialog';
import { ShareSetupDialog } from './ShareSetupDialog';
import type { Mod, ModKind, Profile } from '@/api';
import { useAction, useBuild, useCall, useConfigFiles, useCurrent, useProfiles } from '@/data/hooks';
import { useGo, useSearchRequest } from '@/app/nav';
import { useDialogs } from '@/state/dialogs';
import { toast } from '@/state/toasts';
import { EmptyState, Page, PageHeader, Toolbar } from '@/components/bayle/layout';
import { Button, LinkButton } from '@/components/ui/button';
import { SearchInput, Segmented } from '@/components/bayle/controls';
import { StatusChip } from '@/components/bayle/badge';
import { ConfirmDialog } from '@/components/bayle/overlay';
import { DropdownMenu, item, sep } from '@/components/bayle/menu';
import { ModsCtx, type ModsController, type PanelTab } from './controller';
import { ModsTable } from './ModsTable';
import { BulkBar } from './BulkBar';
import { ModPanel } from './ModPanel';
import { Attention } from './Attention';
import { AttachDialog, ManageProfileMenu, MoveInDialog, RemoveDialog, RenameModDialog, TakeOverDialog } from './ProfileFlows';
import { byKind, hasOverhaul, matchesFilter, modStatus, type ModFilter } from './status';

/** Apply a pending drag before the backend answers, so the row stays where it was dropped. */
function withOrder(p: Profile, local: { kind: ModKind; ids: string[] } | null): Profile {
  if (!local) return p;
  const ofKind = local.ids.map((id) => p.mods.find((m) => m.id === id)).filter((m): m is Mod => !!m);
  if (ofKind.length !== byKind(p, local.kind).length) return p;
  const mods = local.kind === 'package' ? [...ofKind, ...p.mods.filter((m) => m.kind !== 'package')] : [...p.mods.filter((m) => m.kind !== 'native'), ...ofKind];
  return { ...p, mods };
}

export function ModsPage() {
  const { game, profile: loaded, loading } = useCurrent();
  if (loading && !loaded) return <Page><PageHeader eyebrow="Mods" title="Loading…" /></Page>;
  if (!game || !loaded) return <Page><EmptyState title="No profile for this game yet">Create one from the profile menu in the top bar.</EmptyState></Page>;
  return <ModsView key={loaded.id} game={game} loaded={loaded} />;
}

function ModsView({ game, loaded }: { game: NonNullable<ReturnType<typeof useCurrent>['game']>; loaded: Profile }) {
  const { run } = useAction();
  const call = useCall();
  const show = useDialogs((s) => s.show);
  const go = useGo();
  const profiles = useProfiles(game.id);
  const configFiles = useConfigFiles(loaded.id);

  // A pending drag applies only to the profile data it was made on; fresh data from the backend wins.
  const [local, setLocal] = useState<{ base: Profile; kind: ModKind; ids: string[] } | null>(null);
  const profile = useMemo(() => withOrder(loaded, local?.base === loaded ? local : null), [loaded, local]);

  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<ModFilter>('all');
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const lastCheck = useRef<string | null>(null);
  const [panel, setPanel] = useState<{ id: string; tab: PanelTab } | null>(null);
  // /mods?mod=<id> (palette, other pages) opens that mod's panel.
  useSearchRequest('/mods', 'mod', (id) => { if (loaded.mods.some((m) => m.id === id)) setPanel({ id, tab: 'loading' }); });
  const [removeIds, setRemoveIds] = useState<string[] | null>(null);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [attachId, setAttachId] = useState<string | null>(null);
  const [moveIn, setMoveIn] = useState(false);
  const [takeOver, setTakeOver] = useState(false);
  const [dropOverhaul, setDropOverhaul] = useState(false);
  const [suggest, setSuggest] = useState(false);
  const [share, setShare] = useState(false);
  const build = useBuild(profile?.id);
  const searchRef = useRef<HTMLInputElement>(null);

  const visible = useMemo(() => profile.mods.filter((m) => matchesFilter(m, profile, filter, query)), [profile, filter, query]);
  // Ticks only count while their rows are visible.
  const selected = visible.filter((m) => checked.has(m.id));
  const hasTicks = selected.length > 0;
  const others = (profiles.data ?? []).filter((p) => p.id !== profile.id);
  const counts = {
    all: profile.mods.length,
    on: profile.mods.filter((m) => m.enabled).length,
    off: profile.mods.filter((m) => !m.enabled).length,
    issue: profile.mods.filter((m) => modStatus(m, profile).issue).length,
  };

  const reorder = useCallback((kind: ModKind, ids: string[]) => {
    setLocal({ base: loaded, kind, ids });
    void run((a) => a.reorderMods(profile.id, kind, ids));
  }, [run, profile.id, loaded]);

  const controller = useMemo<ModsController>(() => ({
    profile,
    otherProfiles: others,
    openPanel: (id, tab = 'loading') => setPanel({ id, tab }),
    openMerge: (modId) => go.openMerge(modId),
    setEnabled: (ids, on) => void run((a) => a.setModsEnabled(profile.id, ids, on)),
    move: (id, to) => {
      const m = profile.mods.find((x) => x.id === id);
      if (!m || m.staysLast) return;
      const list = byKind(profile, m.kind);
      const ids = list.map((x) => x.id);
      const from = ids.indexOf(id);
      const lock = list.findIndex((x) => x.staysLast);
      const max = (lock >= 0 ? lock : list.length) - 1;
      const target = to === 'top' ? 0 : to === 'bottom' ? max : Math.max(0, Math.min(max, from + to));
      if (target === from) { if (lock >= 0 && from === max && to !== 'top') toast({ kind: 'info', title: `${list[lock]?.name} must stay last`, detail: 'Its rebuild tool merges the mods above it.' }); return; }
      ids.splice(from, 1); ids.splice(target, 0, id);
      reorder(m.kind, ids);
    },
    askRemove: (ids) => setRemoveIds(ids),
    askRename: (id) => setRenameId(id),
    reinstall: () => show({ id: 'install' }),
    addTo: (targetId, ids) => void run((a) => a.addModsToProfile(targetId, profile.id, ids)),
    showInFolder: (m) => void call((a) => a.openPath(m.folder), { title: 'Opened in Explorer', detail: m.folder }),
    openConfig: (m, fileName) => {
      const ref = configFiles.data?.find((r) => r.modId === m.id && r.name === fileName);
      setPanel(null);
      go.openConfig(ref?.id ?? fileName);
    },
    attach: (id) => setAttachId(id),
  }), [profile, others, run, call, show, reorder, configFiles.data, go]);


  const setTicks = (ids: string[], on: boolean) => setChecked((s) => { const n = new Set(s); ids.forEach((id) => (on ? n.add(id) : n.delete(id))); return n; });
  const onRowCheck = (id: string, on: boolean, shift: boolean) => {
    const order = visible.map((m) => m.id);
    if (shift && lastCheck.current && order.includes(lastCheck.current)) {
      const [a, b] = [order.indexOf(lastCheck.current), order.indexOf(id)].sort((x, y) => x - y);
      setTicks(order.slice(a, (b ?? 0) + 1), on);
    } else setTicks([id], on);
    lastCheck.current = id;
  };

  const focusRow = (id: string) => requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-mod="${CSS.escape(id)}"]`)?.focus());
  const onRowKey = (m: Mod, e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    const k = e.key.toLowerCase();
    const ctrl = e.ctrlKey || e.metaKey;
    if (k === 'enter') { e.preventDefault(); controller.openPanel(m.id); }
    else if (k === ' ') { e.preventDefault(); if (!m.missing) controller.setEnabled([m.id], !m.enabled); }
    else if (k === 'delete') { e.preventDefault(); controller.askRemove(selected.length > 1 && checked.has(m.id) ? selected.map((x) => x.id) : [m.id]); }
    else if (k === 'f2') { e.preventDefault(); controller.askRename(m.id); }
    else if (k === 'x' && !ctrl) { e.preventDefault(); setTicks([m.id], !checked.has(m.id)); lastCheck.current = m.id; }
    else if (ctrl && (k === 'arrowup' || k === 'arrowdown')) { e.preventDefault(); controller.move(m.id, k === 'arrowup' ? -1 : 1); focusRow(m.id); }
    else if (k === 'arrowup' || k === 'arrowdown') {
      e.preventDefault();
      const i = visible.findIndex((x) => x.id === m.id);
      const next = visible[i + (k === 'arrowup' ? -1 : 1)];
      if (next) focusRow(next.id);
    }
  };

  // Page keys: "/" searches, Ctrl+A ticks everything shown, Esc clears the ticks.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t?.closest('input,textarea,select,[contenteditable="true"]');
      const overlay = !!document.querySelector('[role="dialog"],[role="menu"]');
      if (e.key === '/' && !typing && !overlay) { e.preventDefault(); searchRef.current?.focus(); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a' && !typing && !overlay) { e.preventDefault(); setTicks(visible.map((m) => m.id), true); }
      else if (e.key === 'Escape' && !overlay && hasTicks && !(typing && (t as HTMLInputElement).value)) { setChecked(new Set()); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [visible, hasTicks]);

  const ovh = hasOverhaul(profile);
  const ovhMod = profile.mods.find((m) => m.staysLast && m.setupId);
  const panelMod = panel ? profile.mods.find((m) => m.id === panel.id) : undefined;
  const renameMod = renameId ? profile.mods.find((m) => m.id === renameId) : undefined;
  const attachMod = attachId ? profile.mods.find((m) => m.id === attachId) : undefined;
  const removeMods = removeIds ? profile.mods.filter((m) => removeIds.includes(m.id)) : [];

  const addFolder = async () => {
    const path = await call((a) => a.pickFolder({ title: 'Add a folder that is not loaded' }));
    if (path) show({ id: 'install', path });
  };

  return (
    <ModsCtx.Provider value={controller}>
      <Page className={selected.length ? 'pb-28' : undefined}>
        <PageHeader eyebrow={<>Mods <span aria-hidden>·</span> {game.name}{game.lastPlayed && <><span aria-hidden>·</span> {game.lastPlayed}</>}</>}
          title={profile.name}
          subtitle={<>
            {ovh && profile.merge !== 'needs' && <StatusChip tone="ok" onClick={() => go.openMerge()} title="Open Merge"><GitMerge className="size-3" />Merged game data: up to date</StatusChip>}
            <ManageProfileMenu profile={profile} profileCount={profiles.data?.length ?? 1} onMoveIn={() => setMoveIn(true)} onTakeOver={() => setTakeOver(true)} onRemoveOverhaul={() => setDropOverhaul(true)} />
          </>} />

        <Attention game={game} profile={profile} onWhy={() => go.openMerge()} onMoveIn={() => setMoveIn(true)} onTakeOver={() => setTakeOver(true)}
          onShowMod={(id) => { setFilter('all'); setQuery(''); controller.openPanel(id); }} onReinstall={controller.reinstall} onRemove={(id) => controller.askRemove([id])} />

        <Toolbar>
          <SearchInput ref={searchRef} value={query} onChange={setQuery} hint="/" placeholder="Search mods" aria-label="Search mods" className="w-[260px] max-[820px]:w-auto max-[820px]:min-w-[180px] max-[820px]:flex-1" />
          <Segmented aria-label="Show" value={filter} onChange={setFilter} options={[
            { value: 'all', label: 'All', count: counts.all },
            { value: 'on', label: 'On', count: counts.on },
            { value: 'off', label: 'Off', count: counts.off },
            { value: 'issue', label: 'Issues', count: counts.issue, hot: counts.issue > 0 },
          ]} />
          <span className="flex-1" />
          {build.data && build.data.state !== 'none' && build.data.choices !== false && <Button icon={<Wand2 />} onClick={() => setSuggest(true)} title="Bayle compares what each mod changes and suggests who should win. Nothing changes until you apply.">Suggest who wins</Button>}
          <Button variant="primary" icon={<Download />} onClick={() => show({ id: 'install' })}>Install mod</Button>
          <DropdownMenu align="end" items={[
            item('Add a folder that is not loaded…', () => void addFolder(), { icon: <FolderPlus /> }),
            item('Share setup with friends…', () => setShare(true), { icon: <Upload />, hint: 'versions and fingerprints, no files' }),
            sep,
            item('Edit as text', () => toast({ kind: 'info', title: 'Edit as text', detail: `Opens ${profile.name}.me3 in a text editor view.` }), { icon: <FileCode2 /> }),
          ]} trigger={<Button iconOnly aria-label="More" title="More" icon={<MoreHorizontal />} />} />
        </Toolbar>

        {profile.mods.length === 0 ? (
          <EmptyState title="No mods yet" action={<Button variant="primary" icon={<Download />} onClick={() => show({ id: 'install' })}>Install mod</Button>}>
            Download a mod from Nexus and add it here as the .zip you got. Bayle finds the mod inside, even below a wrapper folder, and tells you what it will do before anything is written.
          </EmptyState>
        ) : visible.length === 0 ? (
          <EmptyState title={`No mod matches${query ? ` “${query}”` : ' this filter'}`} action={<LinkButton onClick={() => { setQuery(''); setFilter('all'); }}>Show all</LinkButton>} />
        ) : (
          <ModsTable visible={visible} checked={checked} activeId={panel?.id ?? null} dragDisabled={filter !== 'all' || !!query}
            onCheck={setTicks} onRowCheck={onRowCheck} onRowKey={onRowKey} onReorder={reorder} />
        )}

        <div className="flex flex-wrap gap-3.5 text-xs text-t3">
          <span>Drag a row's handle to reorder it within its group · Tick rows to act on several · Right-click for more</span>
          <LinkButton className="text-xs" onClick={() => void addFolder()}>Add a folder that is not loaded…</LinkButton>
        </div>
      </Page>

      <BulkBar selected={selected} visibleCount={visible.length} onSelectAll={() => setTicks(visible.map((m) => m.id), true)} onClear={() => setChecked(new Set())} />
      <ModPanel mod={panelMod} tab={panel?.tab ?? 'loading'} onTab={(tab) => panel && setPanel({ ...panel, tab })} onClose={() => { const id = panel?.id; setPanel(null); if (id) focusRow(id); }} />
      {removeMods.length > 0 && <RemoveDialog profile={profile} mods={removeMods} onClose={() => setRemoveIds(null)} onDone={() => { setRemoveIds(null); setTicks(removeMods.map((m) => m.id), false); }} />}
      {renameMod && <RenameModDialog profile={profile} mod={renameMod} onClose={() => setRenameId(null)} />}
      {attachMod && <AttachDialog profile={profile} mod={attachMod} onClose={() => setAttachId(null)} />}
      {profile.outsidePath && <MoveInDialog profile={profile} open={moveIn} onOpenChange={setMoveIn} />}
      <TakeOverDialog profile={profile} open={takeOver} onOpenChange={setTakeOver} />
      <SuggestWinnersDialog profile={profile} open={suggest} onOpenChange={setSuggest} />
      <ShareSetupDialog profile={profile} open={share} onOpenChange={setShare} />
      {ovhMod?.setupId && (
        <ConfirmDialog open={dropOverhaul} onOpenChange={setDropOverhaul} danger confirmLabel={`Remove ${ovhMod.name}`}
          title={`Remove ${ovhMod.name} from ${profile.name}?`} description="Its merged files and folder go too. Your other mods stay. Restore in Activity."
          onConfirm={() => void run((a) => a.removeOverhaul(profile.id, ovhMod.setupId!))} />
      )}
    </ModsCtx.Provider>
  );
}
