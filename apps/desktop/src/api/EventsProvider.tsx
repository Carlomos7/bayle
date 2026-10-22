import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type ReactNode } from "react";
import { useApi } from "./backend";
import { handleEvent, type EventDeps } from "./events";
import { readFrames } from "./sse";
import type { ApiEvent } from "./types";

const BACKOFF_MS = [250, 500, 1000, 2000, 5000];

/** One SSE connection for the whole app; reconnects with Last-Event-ID (the engine can restart). */
export function EventsProvider({ deps, children }: { deps: Omit<EventDeps, "queryClient">; children: ReactNode }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const depsRef = useRef(deps);
  useEffect(() => {
    depsRef.current = deps;
  });

  useEffect(() => {
    const abort = new AbortController();
    let last: number | null = null;
    void (async () => {
      for (let attempt = 0; !abort.signal.aborted; attempt++) {
        try {
          const response = await api.stream(last, abort.signal);
          if (!response.ok || !response.body) throw new Error(`events: HTTP ${response.status}`);
          for await (const frame of readFrames(response.body)) {
            attempt = 0;
            const event = JSON.parse(frame.data) as ApiEvent;
            last = event.seq;
            handleEvent(event, { ...depsRef.current, queryClient });
          }
        } catch {
          if (abort.signal.aborted) return;
        }
        const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 5000;
        await new Promise((r) => setTimeout(r, wait));
      }
    })();
    return () => abort.abort();
  }, [api, queryClient]);

  return children;
}
