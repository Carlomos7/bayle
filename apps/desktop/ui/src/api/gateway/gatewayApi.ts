/**
 * BayleApi over the Rust gateway: the production adapter. Pages keep calling
 * BayleApi exactly as they do against the mock; this file decides which engine
 * operation answers each method.
 *
 * Wired so far (the first integration slice): getStatus, listActivity,
 * getLog and the event stream. Every other method rejects with not_wired, a
 * plain sentence the page shows as an error. That is deliberate: production
 * must never fall back to mock data. Wire methods one at a time as the engine
 * contract for each page settles.
 */
import type { BayleApi } from '../BayleApi';
import type { ActivityEntry, ActivityKind, AppStatus, BackendEvent } from '../types';
import type { Gateway } from './hub';
import { OPERATIONS, type EngineEvent } from './protocol';
import { settingsAdapter } from './adapters/settings';
import { GatewayError } from './transport';

/* ------------------------------------------------------------------ activity (provisional mapping) */

/**
 * One record of GET /v1/activity → ActivityJobs.jobs. The engine types these as
 * dict[str, Any]; the fields below are what adapters/system/logging.py `_record`
 * writes today. PROVISIONAL until the engine declares the model in OpenAPI.
 */
export interface EngineActivityRecord {
  id: string;
  title?: string;
  kind?: string;
  game?: string;
  profile?: string;
  start?: string;
  end?: string | null;
  seconds?: number | null;
  outcome?: string;
  summary?: string;
  problem?: string;
  log?: string | null;
  undo?: Record<string, unknown> | null;
  undone?: boolean;
}

const KINDS: Record<string, ActivityKind> = { launch: 'launch', install: 'install', rebuild: 'rebuild', merge: 'rebuild', save: 'save', saves: 'save', profile: 'profile', mods: 'profile' };

function dayOf(iso: string | undefined, now: Date): string {
  if (!iso) return 'Earlier';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'Earlier';
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((start(now) - start(d)) / 86_400_000);
  return diff === 0 ? 'Today' : diff === 1 ? 'Yesterday' : d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

function durationOf(seconds: number | null | undefined, outcome: string | undefined): string {
  if (outcome === 'running') return 'running';
  if (seconds == null) return '';
  const s = Math.round(seconds);
  return s < 1 ? 'under a second' : s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}

export function toActivityEntry(r: EngineActivityRecord, now = new Date()): ActivityEntry {
  const outcome = r.outcome ?? 'done';
  const t = r.start ? new Date(r.start) : undefined;
  return {
    id: r.id,
    gameId: r.game ?? '',
    kind: KINDS[r.kind ?? ''] ?? 'profile',
    ok: outcome !== 'failed' && outcome !== 'interrupted',
    title: r.title ?? 'Job',
    detail: (outcome === 'failed' ? r.problem : r.summary) || r.profile || '',
    day: dayOf(r.start, now),
    time: t && !Number.isNaN(t.getTime()) ? t.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }) : '',
    duration: durationOf(r.seconds, outcome),
    hasLog: !!r.log,
    undoable: !!r.undo && !r.undone,
    undone: !!r.undone,
    // Undo through the engine (activity_undo with the confirmed record) is not wired yet.
  };
}

/* ------------------------------------------------------------------ events */

/** What the engine's `invalidated.what` names → the UI's cache scopes. PROVISIONAL: the engine's names follow its Qt pages. */
const INVALIDATES: Record<string, Extract<BackendEvent, { type: 'changed' }>['scope'][]> = {
  shell: ['profiles', 'settings'],
  pages: ['profiles', 'saves', 'configs', 'activity'],
  game: ['profiles', 'saves'],
  updates: ['settings'],
};

export function toBackendEvents(e: EngineEvent): BackendEvent[] {
  switch (e.type) {
    case 'invalidated': return [...new Set(e.data.what.flatMap((w) => INVALIDATES[w] ?? []))].map((scope) => ({ type: 'changed', scope }));
    case 'game.state': return [{ type: 'status', status: e.data.running ? { state: 'running', text: `${e.data.game} is running` } : { state: 'ready', text: 'Ready to launch' } }];
    case 'notice': return [{ type: 'notice', text: e.data.text, error: !!e.data.error }];
    // Any job ending can change what Activity lists.
    case 'finished': case 'failed': case 'cancelled': return [{ type: 'changed', scope: 'activity' }];
    default: return [];
  }
}

/* ------------------------------------------------------------------ the adapter */

const notWired = (method: string) => new GatewayError({ code: 'not_wired', message: `This part of Bayle isn't connected to the engine yet (${method}).` });

export function createGatewayApi(gateway: Gateway): BayleApi {
  const wired: Partial<BayleApi> = {
    ...settingsAdapter(gateway),
    async getStatus(): Promise<AppStatus> {
      const s = gateway.current();
      return s?.state === 'ready' ? { state: 'ready', text: 'Ready to launch' } : { state: 'warn', text: "Bayle's engine isn't ready" };
    },
    async listActivity() {
      const page = await gateway.call<{ jobs: EngineActivityRecord[] }>(OPERATIONS.activity);
      return page.jobs.map((r) => toActivityEntry(r));
    },
    async getLog(entryId) {
      const v = await gateway.call<{ text: string; missing: boolean }>(OPERATIONS.activityLog, { job_id: entryId });
      return v.missing ? ['This job left no log.'] : v.text.split('\n');
    },
    subscribe(listener) {
      return gateway.on((m) => { if (m.kind === 'event') toBackendEvents(m.event).forEach(listener); });
    },
    // Links open through Rust (https only); the webview opens nothing itself.
    async openUrl(url) {
      if (!gateway.app) throw notWired('openUrl');
      await gateway.app.openUrl(url);
    },
  };
  return new Proxy(wired as BayleApi, {
    get(target, prop) {
      if (typeof prop !== 'string' || prop === 'then') return undefined;
      const own = (target as unknown as Record<string, unknown>)[prop];
      return own ?? (() => Promise.reject(notWired(prop)));
    },
  });
}
