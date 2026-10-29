import { useEffect, useState, type ReactNode } from 'react';
import { Bug, Copy, Download, FolderOpen, LoaderCircle, MonitorSmartphone, PlugZap, RefreshCw, TriangleAlert } from 'lucide-react';
import type { AppUpdate, EngineStatus } from '@/api/gateway/protocol';
import { Button } from '@/components/ui/button';
import { Wordmark } from '@/components/bayle/layout';
import { useRuntime } from '@/data/ApiProvider';
import { useEngine } from '@/data/engine';
import { toast } from '@/state/toasts';
import { cn } from '@/lib/utils';
import { uiReady } from '@/api';

/**
 * What the window shows about Bayle's engine (the Python process Rust runs):
 * - before it has ever been ready: a start screen, or what went wrong with Retry;
 * - after: the app stays, and a banner says it is reconnecting or stopped;
 * - an engine this app can't talk to: a screen that says so (Retry won't help).
 * No timers decide anything here: every change comes from the gateway's status.
 */

function Screen({ icon, title, children, actions, tone = 'info' }: { icon: ReactNode; title: string; children?: ReactNode; actions?: ReactNode; tone?: 'info' | 'bad' }) {
  return (
    <div role={tone === 'bad' ? 'alert' : 'status'} aria-live="polite" data-engine-screen className="grid h-full place-items-center bg-bg px-6 py-10">
      <div className="flex w-full max-w-[460px] flex-col items-start gap-5">
        <Wordmark width={200} />
        <div className="flex items-start gap-3">
          <span className={cn('mt-1 [&_svg]:size-5', tone === 'bad' ? 'text-bad' : 'text-accent')}>{icon}</span>
          <div className="flex min-w-0 flex-col gap-1.5">
            <h1 className="m-0 font-serif text-title leading-tight font-semibold">{title}</h1>
            {children && <div className="text-body leading-relaxed text-t2">{children}</div>}
          </div>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2 pl-8">{actions}</div>}
      </div>
    </div>
  );
}

/** Plain facts for a bug report: state, codes, versions. The gateway never puts ports, tokens or paths in a status. */
function copyDetails(s: EngineStatus) {
  const text = JSON.stringify({ state: s.state, epoch: s.epoch, problem: s.problem, engineVersion: s.engineVersion, contract: s.contract, expectedContract: s.expectedContract }, null, 2);
  void navigator.clipboard?.writeText(text).then(() => toast({ kind: 'success', title: 'Details copied' }), () => {});
}

function useRetry() {
  const { gateway } = useRuntime();
  const [busy, setBusy] = useState(false);
  const retry = async () => {
    setBusy(true);
    try { await gateway.restart(); } catch (e) { toast({ kind: 'error', title: (e as Error).message }); } finally { setBusy(false); }
  };
  return { retry, busy };
}

/**
 * What the app can still do with the engine down (decision 0016): look for a fixed version and install it, open the
 * logs, report the problem. Rust does these on its own, so they work whatever state the engine is in.
 */
function AppActions({ size }: { size?: 'sm' }) {
  const { gateway } = useRuntime();
  const app = gateway.app;
  const [update, setUpdate] = useState<AppUpdate | null>(null);
  const [busy, setBusy] = useState<'check' | 'install' | null>(null);
  if (!app) return null;
  const run = async (what: 'check' | 'install', f: () => Promise<void>) => {
    setBusy(what);
    try { await f(); } catch (e) { toast({ kind: 'error', title: (e as Error).message }); } finally { setBusy(null); }
  };
  const check = () => run('check', async () => {
    const found = await app.checkUpdate();
    setUpdate(found);
    if (!found) toast({ kind: 'success', title: 'Bayle is up to date' });
  });
  const install = () => run('install', () => app.installUpdate()); // the app restarts when it is done
  const quiet = (f: () => Promise<void>) => () => void f().catch((e: Error) => toast({ kind: 'error', title: e.message }));
  return (
    <>
      {update
        ? <Button size={size} variant="primary" icon={<Download />} disabled={!!busy} onClick={() => void install()}>Install Bayle {update.version}</Button>
        : <Button size={size} variant="default" icon={<Download />} disabled={!!busy} onClick={() => void check()}>Check for updates</Button>}
      <Button size={size} variant="ghost" icon={<FolderOpen />} onClick={quiet(app.openLogs)}>Open logs</Button>
      <Button size={size} variant="ghost" icon={<Bug />} onClick={quiet(app.reportIssue)}>Report issue</Button>
    </>
  );
}

/** Seconds this screen has been showing, for wording only ("this can take a moment"). Remount (key) to restart it. */
function useSecondsShown() {
  const [secs, setSecs] = useState(0);
  useEffect(() => { const t = setInterval(() => setSecs((n) => n + 1), 1000); return () => clearInterval(t); }, []);
  return secs;
}

function Starting() {
  const secs = useSecondsShown();
  return (
    <Screen icon={<LoaderCircle className="animate-spin" />} title="Starting Bayle…">
      <p className="m-0">Getting the engine ready: your profiles, mods and saves.</p>
      {secs >= 6 && <p className="m-0 mt-1 text-t3">The first start after installing or updating can take a little longer.</p>}
    </Screen>
  );
}

function Failed({ status }: { status: EngineStatus }) {
  const { retry, busy } = useRetry();
  return (
    <Screen tone="bad" icon={<PlugZap />} title={status.state === 'unavailable' ? "Can't reach Bayle's engine" : "Bayle's engine didn't start"}
      actions={<>
        <Button variant="primary" icon={<RefreshCw />} disabled={busy} onClick={() => void retry()}>Try again</Button>
        <Button variant="ghost" icon={<Copy />} onClick={() => copyDetails(status)}>Copy details</Button>
        <AppActions />
      </>}>
      <p className="m-0">{status.problem?.message ?? 'It stopped before it was ready.'}</p>
      <p className="m-0 mt-1 text-t3">If it keeps happening, check for an update that fixes it, or Copy details and report the issue.</p>
    </Screen>
  );
}

function Incompatible({ status }: { status: EngineStatus }) {
  return (
    <Screen tone="bad" icon={<TriangleAlert />} title="This engine doesn't match this app"
      actions={<>
        <Button variant="ghost" icon={<Copy />} onClick={() => copyDetails(status)}>Copy details</Button>
        <AppActions />
      </>}>
      <p className="m-0">{status.problem?.message ?? 'The app and its engine come from different versions of Bayle.'}</p>
      <p className="m-0 mt-1 text-t3">Install Bayle again, or its latest update, so both parts match. Retrying won't help.</p>
    </Screen>
  );
}

/** Shows the app once the engine is ready, and a screen until then. After the first ready, outages are a banner (EngineBanner). */
export function EngineGate({ children }: { children: ReactNode }) {
  const status = useEngine((s) => s.status);
  const everReady = useEngine((s) => s.everReady);
  if (status.state === 'incompatible') return <Incompatible status={status} />;
  if (everReady) return <>{children}</>;
  if (status.state === 'failed' || status.state === 'unavailable') return <Failed status={status} />;
  if (status.state === 'ready') return <>{children}</>;
  return <Starting key={`${status.epoch}:${status.state}`} />;
}

/** One line above the page while the engine is away after having been ready. Pages stay readable; changes wait. */
export function EngineBanner() {
  const status = useEngine((s) => s.status);
  const everReady = useEngine((s) => s.everReady);
  const { retry, busy } = useRetry();
  if (!everReady || status.state === 'ready' || status.state === 'incompatible') return null;
  const stopped = status.state === 'failed';
  return (
    <div role={stopped ? 'alert' : 'status'} aria-live="polite" data-engine-banner={status.state}
      className={cn('flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line px-4 py-2 text-ui', stopped ? 'bg-bad-bg/40' : 'bg-warn-bg/40')}>
      {stopped ? <PlugZap className="size-4 shrink-0 text-bad" /> : <LoaderCircle className="size-4 shrink-0 animate-spin text-warn" />}
      <span className="min-w-0 flex-1">
        <b className="font-semibold">{stopped ? (status.problem?.message ?? "Bayle's engine stopped.") : status.state === 'unavailable' ? "Lost touch with Bayle's engine. Reconnecting…" : "Bayle's engine is restarting…"}</b>
        <span className="text-t2"> What you see may be out of date, and changes wait until it's back.</span>
      </span>
      {(stopped || status.state === 'unavailable') && <Button size="sm" variant={stopped ? 'primary' : 'default'} icon={<RefreshCw />} disabled={busy} onClick={() => void retry()}>{stopped ? 'Try again' : 'Retry now'}</Button>}
      {stopped && <AppActions size="sm" />}
    </div>
  );
}

/** A production build opened in a plain browser: there is no engine to reach from here, and no mock to fall back to. */
export function OutsideDesktop() {
  return (
    <Screen icon={<MonitorSmartphone />} title="Open Bayle from its desktop app">
      <p className="m-0">This page is Bayle's interface without its engine. It only works inside the Bayle app, which runs the engine for it.</p>
    </Screen>
  );
}

/** Tells the shell the window is drawn, once the tree has rendered (a render that throws never gets here). */
export function Drawn() {
  useEffect(uiReady, []);
  return null;
}
