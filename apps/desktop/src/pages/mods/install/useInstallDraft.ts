import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "@/api/backend";
import { ApiError } from "@/api/client";
import { jobKey } from "@/api/events";
import type { JobState } from "@/api/types";
import { sonnerToasts, type Toasts } from "@/components/toasts";
import { onFilesDropped, pickSource } from "./sources";
import type { DraftReply, EditParams, InstallView } from "./types";

/** The Qt pause before the replan and the preview are asked for. */
export const REPLAN_PAUSE_MS = 200;

export interface Handoff {
  unpacked: string;
  profiles: string[];
  staging: string | null;
}

interface Options {
  /** The .me3 path of the profile the mod installs into ("" = none picked). */
  profile: string;
  toasts?: Toasts;
}

const baseName = (path: string) => path.split(/[\\/]/).pop() ?? path;

/**
 * The Install mod dialog's session (install_adapter.py): sources go through mods.install_sources and wait in a queue,
 * one draft is open at a time (mods.install_open), edits go to the backend in order, the replan and the preview are
 * asked for after a pause and one at a time (an edit meanwhile asks once more), and Install ends as a job.
 */
export function useInstallDraft({ profile, toasts = sonnerToasts }: Options) {
  const api = useApi();
  const [view, setView] = useState<InstallView | null>(null);
  const [finishing, setFinishing] = useState<string | null>(null);

  const op = useCallback(<T>(name: string, body: object) => api.post<T>(`/v1/ops/${name}`, body), [api]);
  const draft = useRef<string | null>(null);
  const queue = useRef<string[]>([]);
  const planning = useRef(false);
  const refreshing = useRef(false);
  const again = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const edits = useRef<Promise<unknown>>(Promise.resolve());
  const latest = useRef({ profile, jobRunning: false, toasts });

  // the install job we started is over: the next queued mod may open
  const job = useQuery<JobState | null>({
    queryKey: jobKey(finishing ?? ""),
    queryFn: () => null,
    enabled: false,
    staleTime: Infinity,
  });
  const jobRunning = finishing !== null && !(job.data && job.data.state !== "running");
  useEffect(() => {
    latest.current = { profile, jobRunning, toasts };
  });
  const pump = useRef<() => void>(() => {});

  const refresh = useCallback(async () => {
    const mine = draft.current;
    if (mine === null) return;
    if (refreshing.current) {
      again.current = true;
      return;
    }
    refreshing.current = true;
    try {
      do {
        again.current = false;
        try {
          await op("mods.install_replan", { draft_id: mine });
          const got = await op<DraftReply>("mods.install_preview", { draft_id: mine });
          if (draft.current === mine) setView(got.view);
        } catch {
          // the draft is gone, or the preview said why in its refusals
        }
      } while (again.current && draft.current === mine); // an edit came in meanwhile: ask once more
    } finally {
      refreshing.current = false;
    }
  }, [op]);

  const schedule = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      void refresh();
    }, REPLAN_PAUSE_MS);
  }, [refresh]);

  const next = useCallback(async () => {
    const { profile: prof, jobRunning: busy, toasts: t } = latest.current;
    if (draft.current !== null || planning.current || queue.current.length === 0 || busy) return;
    if (!prof) {
      queue.current = [];
      return;
    }
    const src = queue.current.shift() as string;
    planning.current = true;
    try {
      const got = await op<DraftReply>("mods.install_open", { profile: prof, source: src });
      planning.current = false;
      if (latest.current.profile !== prof) {
        // the profile went away while it was unpacked
        void op("mods.install_close", { draft_id: got.draft_id }).catch(() => {});
        return void pump.current();
      }
      draft.current = got.draft_id;
      setView(got.view);
      if (got.pending) void refresh();
    } catch (e) {
      planning.current = false;
      const p = e instanceof ApiError ? e.problem : { code: "", message: String(e) };
      const name = baseName(src);
      if (p.code === "already_listed") t.notice(`Nothing to do: ${p.message} is already installed and listed in the profile.`);
      else if (p.code === "not_installable") t.notice(`${name} is not a mod Bayle can install: ${p.message}`, { error: true });
      else t.notice(`Could not read ${name}: ${p.message}`, { error: true });
      pump.current();
    }
  }, [op, refresh]);
  useEffect(() => {
    pump.current = () => void next();
  });

  useEffect(() => {
    if (!jobRunning) pump.current();
  }, [jobRunning]);

  /** Take paths: the usable ones join the queue, the rest are told in a toast. */
  const add = useCallback(
    async (paths: string[]) => {
      const { profile: prof, jobRunning: busy, toasts: t } = latest.current;
      if (!prof) return t.notice("Pick a profile first.", { error: true });
      if (busy) return t.notice("Wait for the current job to finish.", { error: true });
      try {
        const got = await op<{ usable: string[]; skipped: string[] }>("mods.install_sources", { paths });
        if (got.skipped.length > 0) {
          t.notice(
            `Skipped ${got.skipped.slice(0, 4).map(baseName).join(", ")}: not an archive (.zip, .7z, .rar), a .dll or a folder.`,
          );
        }
        queue.current.push(...got.usable);
        pump.current();
      } catch (e) {
        t.error(e);
      }
    },
    [op],
  );

  /** The Tauri picker (a file or a folder), then add. */
  const pick = useCallback(
    async (folder: boolean) => {
      try {
        const src = await pickSource(folder);
        if (src) await add([src]);
      } catch (e) {
        latest.current.toasts.error(e);
      }
    },
    [add],
  );

  // files dropped on the window
  useEffect(() => {
    let off: (() => void) | undefined;
    let gone = false;
    void onFilesDropped((paths) => void add(paths)).then((f) => (gone ? f() : (off = f)));
    return () => {
      gone = true;
      off?.();
    };
  }, [add]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  /** One edit, in memory on the backend; sent in order. A pending answer asks for the replan after the pause. */
  const edit = useCallback(
    (params: EditParams) => {
      const mine = draft.current;
      if (mine === null) return;
      edits.current = edits.current
        .then(() => op<DraftReply>("mods.install_edit", { key: "", text: "", on: false, kind: "", ...params, draft_id: mine }))
        .then((got) => {
          if (draft.current !== mine) return;
          setView(got.view);
          if (got.pending) schedule();
        })
        .catch(() => {}); // the draft is gone
    },
    [op, schedule],
  );

  /** Install: ends the dialog and starts the job (progress and the result come as toasts). */
  const accept = useCallback(async () => {
    const mine = draft.current;
    if (mine === null || timer.current || !view?.canInstall) return;
    const name = view.name;
    draft.current = null;
    setView(null);
    try {
      const got = await op<{ job_id: string }>("mods.install_finish", { draft_id: mine, name });
      setFinishing(got.job_id);
    } catch (e) {
      toasts.error(e);
      pump.current();
    }
  }, [op, view, toasts]);

  /** Cancel: the unpacked copy is dropped. */
  const cancel = useCallback(() => {
    const mine = draft.current;
    draft.current = null;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    setView(null);
    if (mine !== null) void op("mods.install_close", { draft_id: mine }).catch(() => {});
    pump.current();
  }, [op]);

  /** The download ships .me3 profiles: the Export / Import page takes over its unpacked folder. */
  const importInstead = useCallback(async (): Promise<Handoff | null> => {
    const mine = draft.current;
    if (mine === null || !view?.profilesInside) return null;
    draft.current = null;
    setView(null);
    try {
      return await op<Handoff>("mods.install_import", { draft_id: mine });
    } catch (e) {
      toasts.error(e);
      return null;
    } finally {
      pump.current();
    }
  }, [op, view, toasts]);

  return { view, add, pick, edit, accept, cancel, importInstead };
}
