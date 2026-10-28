import { ChevronDown, CircleHelp, Gamepad2, Moon, Play, Plus, Search, Sun } from 'lucide-react';
import type { LaunchMode } from '@/api';
import { Link } from '@tanstack/react-router';
import { useRuntime, useStatus } from '@/data/ApiProvider';
import { cancelJob, useActiveJobs, useJob, useLaunchJob } from '@/data/engine';
import type { JobView } from '@/data/jobState';
import { toast } from '@/state/toasts';
import { useLaunch } from '../useLaunch';
import { modsHint, useBuild, useCall, useCurrent, useGames, useProfiles, useSelectGame, useSettings } from '@/data/hooks';
import { profileHealth } from '@/features/mods/health';
import { useUi } from '@/state/ui';
import { useDialogs } from '@/state/dialogs';
import { DropdownMenu, header, item, sep, type MenuEntry } from '@/components/bayle/menu';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { resolveTheme } from '../theme';

const MODES: { mode: LaunchMode; hint: string }[] = [
  { mode: 'Profile', hint: 'The profile as it is: packages, natives, co-op' },
  { mode: 'Offline', hint: 'Co-op mods off, online play off, the standard save' },
  { mode: 'Vanilla', hint: 'No mods at all. The profile is untouched.' },
];

function LaunchButton() {
  const { launch, disabled, mode } = useLaunch();
  const setMode = useUi((s) => s.setLaunchMode);
  const status = useStatus();
  const dim = disabled;
  return (
    <div className={cn('inline-flex h-8 shrink-0 overflow-hidden rounded-sm border',
      dim ? 'border-line2 bg-raise text-t3' : 'border-accent/55 bg-[color-mix(in_srgb,var(--accent)_9%,var(--bg))] text-accent shadow-[0_0_14px_-6px_color-mix(in_srgb,var(--accent)_60%,transparent)]')}>
      <button type="button" onClick={() => void launch()} disabled={disabled} title={status.state === 'running' ? status.text : `Launch ${mode} (Ctrl+L)`}
        className="flex items-center gap-2 px-3 text-ui font-semibold enabled:hover:bg-accent/14 disabled:cursor-not-allowed">
        <Play className="size-4" />Launch
      </button>
      <DropdownMenu
        items={[header('How to launch'), ...MODES.map((m): MenuEntry => item(m.mode, () => setMode(m.mode), { checked: m.mode === mode, hint: m.hint })), sep,
          { type: 'header', label: <span className="block max-w-[280px] text-caption leading-snug font-normal tracking-normal normal-case text-t3">Natives and changed game data can be flagged by the game's online checks. Seamless Co-op uses its own servers.</span> }]}
        trigger={
          <button type="button" aria-label="Launch mode" disabled={disabled}
            className="flex items-center gap-1.5 border-l border-accent/35 px-2.5 text-ui font-medium text-[color-mix(in_srgb,var(--accent)_78%,var(--t2))] enabled:hover:bg-accent/14 disabled:border-line2 disabled:text-t3">
            <span className="max-[560px]:hidden">{mode}</span><ChevronDown className="size-3" />
          </button>
        }
      />
    </div>
  );
}

/**
 * One line next to Launch. While Bayle works it shows what it is doing;
 * otherwise it answers "can I just play?" for the active profile, and
 * clicking it goes to the list of things to fix.
 */
/** A job the engine is running: what it's doing, how far, and Stop. "Stopping…" until the engine says it ended. */
function JobStatus({ job, more }: { job: JobView; more: number }) {
  const { gateway } = useRuntime();
  const p = job.progress;
  const pct = p?.total ? Math.round(((p.done ?? 0) / p.total) * 100) : undefined;
  const stop = () => void cancelJob(gateway, job).catch((e: Error) => toast({ kind: 'error', title: e.message }));
  return (
    <div role="status" aria-live="polite" data-job={job.id} className="flex min-w-0 items-center gap-2 rounded-xs px-1.5 py-1 text-ui text-t2">
      <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-accent" />
      <Link to="/activity" className="min-w-0 truncate hover:text-t1 max-[900px]:hidden" title={`${job.title}${job.message && job.message !== job.title ? `: ${job.message}` : ''} (open Activity)`}>
        {job.cancelRequested ? `${job.title.replace(/…$/, '')}: stopping…` : job.message || job.title}
      </Link>
      {pct !== undefined && !job.cancelRequested && <span className="shrink-0 tabular-nums text-t3">{pct}%</span>}
      {more > 0 && <span className="shrink-0 text-t3">+{more}</span>}
      <Button size="sm" variant="ghost" className="h-6 shrink-0 px-2" disabled={job.cancelRequested} onClick={stop} aria-label={`Stop ${job.title}`}>{job.cancelRequested ? 'Stopping…' : 'Stop'}</Button>
    </div>
  );
}

function StatusLine() {
  const status = useStatus();
  const jobs = useActiveJobs();
  const play = useJob(useLaunchJob((s) => s.ref));
  const { game, profile } = useCurrent();
  const build = useBuild(profile?.id);
  const health = profileHealth(game, profile, build.data);
  const show = useDialogs((s) => s.show);
  // Play is a quiet job (the engine words its ending), so it is looked up by itself, to show what it does and Stop.
  if (play?.phase === 'running') return <JobStatus job={play} more={jobs.length} />;
  if (jobs.length) return <JobStatus job={jobs[jobs.length - 1]!} more={jobs.length - 1} />;
  if (status.state !== 'ready') {
    const dot = { ready: 'bg-ok', busy: 'bg-accent animate-pulse', running: 'bg-info animate-pulse', warn: 'bg-warn' }[status.state];
    return (
      <Link to="/activity" className="flex min-w-0 items-center gap-2 rounded-xs px-1.5 py-1 text-ui text-t2 hover:bg-hover max-[900px]:[&>span:last-child]:hidden" title="Open Activity">
        <span className={cn('size-1.5 shrink-0 rounded-full', dot)} /><span className="truncate">{status.text}</span>
      </Link>
    );
  }
  const worst = health.items.some((i) => i.tone === 'bad') ? 'bad' : health.ok ? 'ok' : 'warn';
  return (
    <button type="button" onClick={() => show({ id: 'health' })} aria-label={health.label} data-health={worst}
      className={cn('flex min-w-0 items-center gap-2 rounded-xs px-1.5 py-1 text-ui hover:bg-hover', health.ok ? 'text-t2' : worst === 'bad' ? 'text-bad' : 'text-warn')}
      title={health.items.length ? `${health.items.map((i) => i.title).join('\n')}\n\nClick for the fixes.` : 'Everything Bayle checks is in order.'}>
      <span className={cn('size-1.5 shrink-0 rounded-full', worst === 'ok' ? 'bg-ok' : worst === 'bad' ? 'bg-bad' : 'bg-warn')} />
      <span className="truncate max-[900px]:hidden">{health.label}</span>
      {/* Narrow windows: just the number, which is the part that matters. */}
      {!health.ok && <span className="hidden font-semibold tabular-nums max-[900px]:inline">{health.items.filter((i) => i.tone !== 'info').length}</span>}
    </button>
  );
}

function Abbr({ text, className }: { text: string; className?: string }) {
  return <span className={cn('grid h-5 min-w-5 place-items-center rounded-xs bg-accent-soft px-1 text-micro font-bold text-accent', className)}>{text}</span>;
}

function GamePicker() {
  const games = useGames();
  const { game } = useCurrent();
  const selectGame = useSelectGame();
  return (
    <DropdownMenu
      items={[header('Games'), ...(games.data ?? []).map((g): MenuEntry => item(g.name, () => void selectGame(g.id), { checked: g.id === game?.id, hint: g.supported ? g.lastPlayed : 'not supported yet' }))]}
      trigger={
        <button type="button" className="flex h-8 w-[168px] items-center gap-2 rounded-sm border border-line2 bg-panel px-2 text-body hover:bg-hover max-[900px]:w-auto" aria-label={`Game: ${game?.name ?? 'none'}`}>
          {game ? <Abbr text={game.abbr} /> : <Gamepad2 className="size-4" />}
          <span className="flex-1 truncate text-left max-[900px]:hidden">{game?.name ?? 'Game'}</span><ChevronDown className="size-3 text-t3" />
        </button>
      }
    />
  );
}

function ProfilePicker() {
  const { game, profile } = useCurrent();
  const profiles = useProfiles(game?.id ?? '');
  const call = useCall();
  const show = useDialogs((s) => s.show);
  if (!game?.supported) return null;
  return (
    <DropdownMenu
      items={[
        header(`Profiles for ${game.name}`),
        ...(profiles.data ?? []).map((p): MenuEntry => item(p.name, () => void call((api) => api.setActiveProfile(game.id, p.id), { title: `Switched to ${p.name}`, detail: modsHint(p) }), { checked: p.id === profile?.id, hint: modsHint(p) })),
        sep,
        item('New profile…', () => show({ id: 'newProfile' }), { icon: <Plus />, kbd: 'Ctrl N' }),
      ]}
      trigger={
        <button type="button" className="flex h-8 w-[264px] min-w-0 items-center gap-2 rounded-sm border border-line2 bg-panel px-2 text-body hover:bg-hover max-[900px]:w-[180px] max-[480px]:w-auto" aria-label={`Profile: ${profile?.name ?? 'none'}`}>
          <Abbr text={profile?.name[0] ?? '·'} /><span className="flex-1 truncate text-left max-[480px]:hidden">{profile?.name ?? 'Profile'}</span><ChevronDown className="size-3 text-t3" />
        </button>
      }
    />
  );
}

function ThemeToggle() {
  const settings = useSettings();
  const call = useCall();
  const current = settings.data ? resolveTheme(settings.data.appearance.theme) : 'dark';
  const next = current === 'light' ? 'dark' : 'light';
  return (
    <Button variant="ghost" iconOnly aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`} icon={current === 'light' ? <Sun /> : <Moon />}
      onClick={() => void call((api) => api.updateSettings({ appearance: { theme: next } }))} />
  );
}

export function TopBar() {
  const openPalette = useUi((s) => s.setCommandOpen);
  const show = useDialogs((s) => s.show);
  return (
    <div className="col-span-full flex min-w-0 items-center gap-2 overflow-hidden bg-side px-4 max-[480px]:gap-1 max-[480px]:px-2 shadow-[inset_0_-1px_0_var(--line)] select-none">
      <LaunchButton />
      <StatusLine />
      <span className="mx-1 h-[18px] w-px bg-line2" />
      <GamePicker />
      <ProfilePicker />
      <span className="flex-1" />
      <Button variant="ghost" iconOnly aria-label="Search (Ctrl+K)" title="Search (Ctrl+K)" icon={<Search />} onClick={() => openPalette(true)} />
      <span className="mx-0.5 h-[18px] w-px bg-line2 max-[480px]:hidden" />
      <span className="contents max-[480px]:hidden"><ThemeToggle /></span>
      <Button variant="ghost" iconOnly aria-label="How to use (F1)" title="How to use (F1)" icon={<CircleHelp />} onClick={() => show({ id: 'setup' })} />
    </div>
  );
}
