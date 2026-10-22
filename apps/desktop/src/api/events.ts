import type { QueryClient } from "@tanstack/react-query";
import type { Toasts } from "@/components/toasts";
import type { ApiEvent, JobState, PromptEventData } from "./types";

export const jobKey = (id: string) => ["jobs", id] as const;
export const pageKey = (name: string) => ["page", name] as const;
const LOG_CAP = 500;

export interface EventDeps {
  queryClient: QueryClient;
  toasts: Toasts;
  /** Open a backend prompt in the dialog host. */
  ask(prompt: PromptEventData): void;
  /** Go to a backend page name (mods, modConfigs, saves, ...). */
  navigate(page: string): void;
}

/** Route one event to the query cache, the toasts, the dialog host or the router. */
export function handleEvent(e: ApiEvent, { queryClient: qc, toasts, ask, navigate }: EventDeps): void {
  const id = e.job_id ?? null;
  const update = (patch: (j: JobState) => Partial<JobState>) => {
    if (id === null) return undefined;
    const old = qc.getQueryData<JobState>(jobKey(id)) ?? {
      id,
      title: "",
      state: "running" as const,
      progress: null,
      log: [],
      error: null,
    };
    const next = { ...old, ...patch(old) };
    qc.setQueryData(jobKey(id), next);
    return next;
  };

  switch (e.type) {
    case "started": {
      const job = update(() => ({ title: e.data.title, state: "running", progress: null, log: [], error: null }));
      if (job) toasts.progress(job.id, job.title, null);
      break;
    }
    case "progress": {
      const job = update(() => ({ progress: e.data }));
      if (job) toasts.progress(job.id, job.title, job.progress);
      break;
    }
    case "log":
      update((j) => ({ log: [...j.log, e.data].slice(-LOG_CAP) }));
      break;
    case "finished": {
      const job = update(() => ({ state: "done" }));
      if (job) toasts.done(job.id, job.title);
      void qc.invalidateQueries({ queryKey: ["page"] });
      break;
    }
    case "failed":
    case "cancelled": {
      const job = update(() => ({ state: e.type === "failed" ? "failed" : "cancelled", error: e.data.error }));
      if (job) {
        if (e.type === "failed") toasts.failed(job.id, job.title, e.data.error);
        else toasts.cancelled(job.id, job.title);
      }
      void qc.invalidateQueries({ queryKey: ["page"] });
      break;
    }
    case "prompt":
      ask(e.data as unknown as PromptEventData);
      break;
    case "invalidated":
      // shell | pages | updates | game: "pages" means every page; a name means that page
      for (const what of e.data.what) {
        void qc.invalidateQueries({ queryKey: what === "pages" ? ["page"] : pageKey(what) });
      }
      break;
    case "game.state":
      qc.setQueryData(["game", "state"], e.data);
      void qc.invalidateQueries({ queryKey: pageKey("shell") });
      break;
    case "notice":
      toasts.notice(e.data.text, { error: e.data.error, details: e.data.details, onDetails: () => navigate("activity") });
      break;
    case "navigate":
      navigate(e.data.page);
      break;
    case "resync":
      // the stream lost events: everything cached may be stale
      void qc.invalidateQueries();
      break;
  }
}
