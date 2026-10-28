import { useRuntime } from '@/data/ApiProvider';
import { Copy, Download, FileUp, FolderOpen, Info, LogOut, Minus, PenLine, Plus, RefreshCw, Save, Search, Square, Trash2, X, BookOpen, Sparkles } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useApi } from '@/data/ApiProvider';
import { useAction, useAppInfo, useCall, useCurrent, useGames, useProfiles, useSelectGame, useSettings } from '@/data/hooks';
import { useUi } from '@/state/ui';
import { useGo, type PageId } from '@/app/nav';
import { useDialogs } from '@/state/dialogs';
import { DropdownMenu, header, item, sep, sub, type MenuEntry } from '@/components/bayle/menu';
import { LogoMark } from '@/components/bayle/layout';
import type { ThemeName } from '@/api';
import { cn } from '@/lib/utils';
import { toast } from '@/state/toasts';

const PAGES: { id: PageId; label: string; kbd: string }[] = [
  { id: 'mods', label: 'Mods', kbd: 'Ctrl 1' },
  { id: 'saves', label: 'Saves', kbd: 'Ctrl 2' },
  { id: 'merge', label: 'Merge', kbd: 'Ctrl 3' },
  { id: 'configs', label: 'Mod Configs', kbd: 'Ctrl 4' },
  { id: 'activity', label: 'Activity', kbd: 'Ctrl 5' },
  { id: 'settings', label: 'Settings', kbd: 'Ctrl 6' },
];

function MenuButton({ label, items }: { label: string; items: MenuEntry[] }) {
  return (
    <DropdownMenu items={items} trigger={
      <button type="button" className="h-6 rounded-xs px-2.5 text-xs text-t2 hover:bg-hover hover:text-t1 data-[state=open]:bg-hover data-[state=open]:text-t1">{label}</button>
    } />
  );
}

/** The window's own menu row: icon, menus, centred title, window buttons. */
export function MenuBar() {
  const api = useApi();
  const qc = useQueryClient();
  const call = useCall();
  const { run } = useAction();
  const { game, profile } = useCurrent();
  const games = useGames();
  const profiles = useProfiles(game?.id ?? '');
  const { mode } = useRuntime();
  const info = useAppInfo();
  const settings = useSettings();
  const go = useGo();
  const setPage = go.page;
  const selectGame = useSelectGame();
  const openPalette = useUi((s) => s.setCommandOpen);
  const show = useDialogs((s) => s.show);
  const supported = !!game?.supported;
  const theme = settings.data?.appearance.theme;

  const file: MenuEntry[] = [
    item('Install mod…', () => show({ id: 'install' }), { icon: <Download />, kbd: 'Ctrl O', disabled: !supported, why: `${game?.name} is not supported yet` }),
    item('Import a save file…', () => { setPage('saves'); void (async () => { const p = await api.pickFile({ title: 'Import a save file' }); if (p && game) await run((a) => a.importSave(game.id, p)); })(); }, { icon: <FileUp />, disabled: !supported }),
    sep,
    item('New profile…', () => show({ id: 'newProfile' }), { icon: <Plus />, kbd: 'Ctrl N', disabled: !supported }),
    item('Open profiles folder', () => void call(async (a) => { const s = await a.getSettings(); await a.openPath(s.paths.profiles); }), { icon: <FolderOpen /> }),
    sep,
    item('Exit', () => void api.windowControl('close'), { icon: <LogOut />, kbd: 'Alt F4' }),
  ];
  const profileMenu: MenuEntry[] = [
    header(profile?.name ?? 'Profile'),
    ...(profiles.data ?? []).map((p): MenuEntry => item(p.name, () => game && void call((a) => a.setActiveProfile(game.id, p.id), { title: `Switched to ${p.name}` }), { checked: p.id === profile?.id })),
    sep,
    item('New profile…', () => show({ id: 'newProfile' }), { icon: <Plus />, kbd: 'Ctrl N', disabled: !supported }),
    item('Duplicate…', () => profile && show({ id: 'newProfile', copyFrom: profile.id }), { icon: <Copy />, disabled: !profile }),
    item('Rename…', () => profile && show({ id: 'renameProfile', profileId: profile.id }), { icon: <PenLine />, kbd: 'F2', disabled: !profile }),
    sep,
    item('Delete profile…', () => profile && show({ id: 'deleteProfile', profileId: profile.id }), { icon: <Trash2 />, danger: true, disabled: !profile || (profiles.data?.length ?? 0) < 2, why: 'A game needs at least one profile' }),
  ];
  const gameMenu: MenuEntry[] = [
    header('Games'),
    ...(games.data ?? []).map((g): MenuEntry => item(g.name, () => void selectGame(g.id), { checked: g.id === game?.id, hint: g.supported ? (g.build ? `build ${g.build}` : undefined) : 'not supported yet' })),
    sep,
    item('Rescan mods and saves', () => void qc.invalidateQueries(), { icon: <RefreshCw />, kbd: 'F5' }),
  ];
  const savesMenu: MenuEntry[] = [
    item('Back up now', () => game && void run((a) => a.backupNow(game.id)), { icon: <Save />, disabled: !supported }),
    item('Import a save file…', () => file[1]?.type === 'item' && file[1].onSelect(), { icon: <FileUp />, disabled: !supported }),
    item('Open saves page', () => setPage('saves'), { kbd: 'Ctrl 2' }),
  ];
  const themes: [ThemeName, string][] = [['dark', 'Dark'], ['bayle', 'Bayle'], ['tarnished', 'Tarnished'], ['light', 'Light'], ['system', 'Match Windows']];
  const view: MenuEntry[] = [
    ...PAGES.map((p) => item(p.label, () => setPage(p.id), { kbd: p.kbd })),
    sep,
    sub('Theme', themes.map(([t, l]) => item(l, () => void call((a) => a.updateSettings({ appearance: { theme: t } })), { checked: theme === t }))),
    item('Search', () => openPalette(true), { icon: <Search />, kbd: 'Ctrl K' }),
    item('Rescan', () => void qc.invalidateQueries(), { icon: <RefreshCw />, kbd: 'F5' }),
  ];
  const help: MenuEntry[] = [
    item('How to use', () => show({ id: 'setup' }), { kbd: 'F1' }),
    item('Welcome tour', () => show({ id: 'welcome' }), { icon: <Sparkles /> }),
    item('Words Bayle uses', () => show({ id: 'glossary' }), { icon: <BookOpen /> }),
    sep,
    item('Check for updates', () => show({ id: 'updates' }), { icon: <RefreshCw /> }),
    item('Save logs for support…', () => void call(async (a) => { const path = await a.saveSupportLogs(); if (path) toast({ kind: 'info', title: 'Logs saved for support', detail: path }); }), { icon: <Save /> }),
    item('Open logs folder', () => void call(async (a) => { const s = await a.getSettings(); await a.openPath(s.paths.logs); }), { icon: <FolderOpen /> }),
    sep,
    item('About Bayle', () => show({ id: 'about' }), { icon: <Info /> }),
  ];

  return (
    // data-tauri-drag-region: the window moves by its empty area (double-click maximises); buttons and menus are their own targets.
    <div role="menubar" aria-label="Application" data-tauri-drag-region className="relative col-span-full flex min-w-0 items-center gap-0.5 overflow-hidden bg-side pl-4 max-[480px]:pl-2 shadow-[inset_0_-1px_0_var(--line)] select-none">
      <LogoMark size={18} className="mr-2 [[data-theme=bayle]_&]:drop-shadow-[0_0_6px_rgb(217_59_59/.45)]" />
      <MenuButton label="File" items={file} />
      <MenuButton label="Profile" items={profileMenu} />
      <MenuButton label="Game" items={gameMenu} />
      <span className="contents max-[480px]:hidden"><MenuButton label="Saves" items={savesMenu} />
      <MenuButton label="View" items={view} /></span>
      <MenuButton label="Help" items={help} />
      <div aria-hidden className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-xs font-medium whitespace-nowrap text-t2 max-[880px]:hidden">
        Bayle <span className="ml-1 tabular-nums text-t4">{info.data?.version}</span>
        {mode === 'preview' && <span data-preview className="ml-2 rounded-xs border border-line2 px-1.5 py-px text-tag tracking-wide text-t3 uppercase" title="No engine: this preview runs on made-up data">Preview data</span>}
      </div>
      <span data-tauri-drag-region className="flex-1 self-stretch" />
      <div className="flex h-full shrink-0">
        {([['minimize', <Minus key="m" />, 'Minimise'], ['maximize', <Square key="s" className="size-3!" />, 'Maximise'], ['close', <X key="x" />, 'Close']] as const).map(([a, icon, label]) => (
          <button key={a} type="button" aria-label={label} title={label} onClick={() => void api.windowControl(a)}
            className={cn('grid h-full w-10 place-items-center text-t3 [&_svg]:size-3.5', a === 'close' ? 'hover:bg-win-close hover:text-white' : 'hover:bg-hover hover:text-t1')}>{icon}</button>
        ))}
      </div>
    </div>
  );
}
