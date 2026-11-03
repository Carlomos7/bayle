import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import type { AppStatus, BayleApi, Runtime } from '@/api';
import type { Gateway } from '@/api/gateway/hub';
import { connectEngine, useEngineReady } from './engine';
import { scopeRoots } from './queryKeys';
import { toast } from '@/state/toasts';
import { useUi } from '@/state/ui';
import { router } from '@/router';

const ApiContext = createContext<BayleApi | null>(null);
const RuntimeContext = createContext<{ mode: Runtime['mode']; gateway: Gateway } | null>(null);
const StatusContext = createContext<AppStatus>({ state: 'ready', text: 'Ready to launch' });

// eslint-disable-next-line react-refresh/only-export-components -- hooks belong with their provider
export function useApi(): BayleApi {
  const api = useContext(ApiContext);
  if (!api) throw new Error('useApi must be used inside <ApiProvider>');
  return api;
}

/** How the app reaches the engine (desktop or preview) and the gateway, for Retry and Stop. */
// eslint-disable-next-line react-refresh/only-export-components -- hooks belong with their provider
export function useRuntime() {
  const r = useContext(RuntimeContext);
  if (!r) throw new Error('useRuntime must be used inside <ApiProvider>');
  return r;
}

/** Live status line (ready, busy, running), pushed by the backend. */
// eslint-disable-next-line react-refresh/only-export-components -- hooks belong with their provider
export function useStatus(): AppStatus {
  return useContext(StatusContext);
}

/** Listens to backend events: keeps the status line current and marks cached data stale. */
function EventBridge({ api, onStatus }: { api: BayleApi; onStatus: (s: AppStatus) => void }) {
  const qc = useQueryClient();
  const ready = useEngineReady();
  // The status line is read once the engine is ready, and again after each restart.
  useEffect(() => { if (ready) void api.getStatus().then(onStatus, () => {}); }, [api, onStatus, ready]);
  useEffect(() => {
    return api.subscribe((e) => {
      switch (e.type) {
        case 'status': onStatus(e.status); break;
        case 'changed': scopeRoots[e.scope].forEach((root) => void qc.invalidateQueries({ queryKey: [root] })); break;
        case 'game-closed': toast({ kind: 'info', title: 'Game closed', detail: e.summary }); break;
        case 'notice': toast({ kind: e.error ? 'error' : 'warn', title: e.text }); break;
        case 'mod-failed':
          useUi.getState().addFailure();
          toast({ kind: 'error', title: `${e.modName} did not start`, detail: e.reason, action: { label: 'Details', run: () => void router.navigate({ to: '/activity' }) } });
          break;
      }
    });
  }, [api, qc, onStatus]);
  return null;
}

/** Follows the engine (status, jobs) for as long as the app is open: one gateway stream, closed on unmount. */
function EngineBridge({ gateway }: { gateway: Gateway }) {
  const qc = useQueryClient();
  useEffect(() => connectEngine(gateway, qc), [gateway, qc]);
  return null;
}

export function ApiProvider({ runtime, children }: { runtime: Runtime; children: ReactNode }) {
  const { api, gateway, mode } = runtime;
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } },
  }));
  const [status, setStatus] = useState<AppStatus>({ state: 'ready', text: 'Ready to launch' });
  const [rt] = useState(() => ({ mode, gateway }));
  return (
    <RuntimeContext.Provider value={rt}>
    <ApiContext.Provider value={api}>
      <QueryClientProvider client={client}>
        <StatusContext.Provider value={status}>
          <EngineBridge gateway={gateway} />
          <EventBridge api={api} onStatus={setStatus} />
          {children}
        </StatusContext.Provider>
      </QueryClientProvider>
    </ApiContext.Provider>
    </RuntimeContext.Provider>
  );
}
