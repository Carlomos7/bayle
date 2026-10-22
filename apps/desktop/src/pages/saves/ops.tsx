import { useQuery, useQueryClient } from "@tanstack/react-query";
import { open as pickFiles } from "@tauri-apps/plugin-dialog";
import { createContext, use, useCallback, useEffect, useMemo, useRef, type ReactNode } from "react";
import { toast } from "sonner";
import { useApi } from "@/api/backend";
import { pageKey } from "@/api/events";
import type { JobState, PlanOffer } from "@/api/types";
import { usePrompts } from "@/components/PromptHost";
import { sonnerToasts } from "@/components/toasts";
import type { CopyEntry, DragSource, DropTarget, Dropped, SavesPageData, SavesView, Written } from "./types";

export const savesKey = pageKey("saves");

export const parentOf = (path: string) => path.replace(/[\\/][^\\/]*$/, "");

/** What the Name dialog is asked for: a copy of a live save, an import, keeping a backup, or a rename. */
export type NameAsk =
  | { mode: "copy" | "import" | "keep"; path: string; start: string }
  | { mode: "rename"; folder: string; id: string; start: string };

/** Everything the page can ask of the backend, in the Qt adapter's terms (ui/pages/saves/adapter.py). */
export interface SavesOps {
  view: SavesView;
  backUp(path: string): void;
  backUpAll(): void;
  postSessionRepair(): void;
  askCopyName(path: string): void;
  pickImport(): void;
  importPaths(paths: string[]): void;
  askName(ask: NameAsk): void;
  saveCopy(path: string, name: string): void;
  importFile(path: string, name: string): void;
  keepAs(backup: string, name: string): void;
  renameCopy(folder: string, id: string, name: string): void;
  letAgeOut(backup: string): void;
  deleteBackup(backup: string): void;
  removeCopy(folder: string, id: string): void;
  finishStranded(folder: string, id: string, restore: boolean): void;
  copyCharacter(source: string, srcSlot: number, target: string, dstSlot: number): void;
  copyFromLibrary(folder: string, id: string, srcSlot: number, target: string, dstSlot: number): void;
  replaceFromLibrary(folder: string, id: string, target: string): void;
  replaceFromFile(target: string): void;
  restoreBackup(backup: string, target: string): void;
  repair(path: string, keys: (string | number)[][]): void;
  copyReport(path: string): void;
  openFolder(which: "saves" | "backups" | "library"): void;
  openSaveFolder(path: string): void;
  drop(source: DragSource, target: DropTarget): void;
  judge(source: DragSource, target: DropTarget): Promise<Dropped>;
  /** Ctrl+C on a character (live or in a Library copy), Ctrl+V on a slot. */
  copyKey(source: DragSource): void;
  pasteInto(target: DropTarget): void;
  refresh(): void;
}

const OpsContext = createContext<SavesOps | null>(null);
export const useSavesOps = () => {
  const ops = use(OpsContext);
  if (!ops) throw new Error("useSavesOps outside SavesProvider");
  return ops;
};

const isWritten = (r: unknown): r is Written =>
  typeof r === "object" && r !== null && "text" in r && "save" in r && "backup" in r && "undo" in r;

/** The wire form of a drag: without the label the ghost shows. */
const wire = (s: DragSource) => Object.fromEntries(Object.entries(s).filter(([k]) => k !== "label"));

export function SavesProvider({
  view,
  askName,
  children,
}: {
  view: SavesView;
  /** Opens the page's Name dialog. */
  askName: (ask: NameAsk) => void;
  children: ReactNode;
}) {
  const api = useApi();
  const qc = useQueryClient();
  const { offerPlan } = usePrompts();
  const clip = useRef<DragSource | null>(null);
  const told = useRef(new Set<string>());
  const words = view.words;
  const w = useCallback((key: string) => words[key] ?? key, [words]);

  const run = useCallback(<T,>(name: string, body: object = {}) => api.post<T>(`/v1/ops/${name}`, body), [api]);
  const fail = useCallback((e: unknown, title = "") => {
    if (!title) return sonnerToasts.error(e);
    const message = e instanceof Error ? e.message : String(e);
    toast.error(`${title}. ${message}`, { duration: Infinity, closeButton: true });
  }, []);
  const refresh = useCallback(() => void qc.invalidateQueries({ queryKey: savesKey }), [qc]);

  /** A command: its result, or a toast with the backend's own message. */
  const command = useCallback(
    async <T,>(name: string, body: object, title = ""): Promise<T | undefined> => {
      try {
        return await run<T>(name, body);
      } catch (e) {
        fail(e, title);
        return undefined;
      }
    },
    [run, fail],
  );
  /** A job: its progress and its end come through the events (and the Undo toast below). */
  const job = useCallback(
    async (name: string, body: object = {}) => {
      try {
        await run<{ job_id: string }>(name, body);
      } catch (e) {
        fail(e);
      }
    },
    [run, fail],
  );
  /** A plan: the backend's words in the dialog, the answer posted by the host; `done` after an OK. */
  const plan = useCallback(
    async (name: string, body: object, done?: () => void, title = "") => {
      try {
        offerPlan(await run<PlanOffer>(name, body), done);
      } catch (e) {
        fail(e, title);
      }
    },
    [run, offerPlan, fail],
  );

  // A save write ends with its text and, when a backup was taken first, Undo (the Qt page told it after the next read).
  useEffect(() => {
    const undo = (save: string, backup: string) => void job("saves.undo_change", { save, backup });
    return qc.getQueryCache().subscribe((event) => {
      const [kind, id] = event.query.queryKey;
      const state = event.query.state.data as JobState | undefined;
      if (kind !== "jobs" || typeof id !== "string" || state?.state !== "done" || told.current.has(id)) return;
      told.current.add(id);
      void api
        .get<{ result: unknown }>(`/v1/jobs/${id}`)
        .then(({ result }) => {
          if (!isWritten(result) || !result.text) return;
          const { save, backup } = result;
          toast.success(result.text, {
            id,
            description: undefined,
            duration: backup ? 12000 : 4500,
            action: backup && save ? { label: w("undo"), onClick: () => undo(save, backup) } : undefined,
          });
        })
        .catch(() => undefined);
    });
  }, [qc, api, job, w]);

  const ops = useMemo<SavesOps>(() => {
    const hasLibrary = () => {
      if (view.cards.length > 0 || view.library_rows.length > 0) return true;
      toast.error(w("playOnce"));
      return false;
    };
    const pickSaves = async (title: string, multiple: boolean): Promise<string[]> => {
      const got = await pickFiles({
        title,
        multiple,
        directory: false,
        filters: [
          { name: w("saveFiles"), extensions: ["sl2", "co2"] },
          { name: w("allFiles"), extensions: ["*"] },
        ],
      });
      return got === null ? [] : Array.isArray(got) ? got : [got];
    };
    const defaultName = async (path: string) => (await command<{ text: string }>("saves.default_name", { path }))?.text ?? "";

    const importPaths = (paths: string[]) => {
      // one save file asks for a name; several import each under its own; any that are not save files are named
      const good = paths.filter((p) => /\.(sl2|co2)$/i.test(p));
      const skipped = paths.filter((p) => !good.includes(p)).map((p) => p.split(/[\\/]/).pop());
      if (skipped.length) toast.error(w("notSaveFiles").replace("{names}", skipped.join(", ")));
      const only = good[0];
      if (good.length === 1 && only) void defaultName(only).then((start) => askName({ mode: "import", path: only, start }));
      else if (good.length && hasLibrary()) void job("saves.import_files", { files: good });
    };

    const copyCharacter: SavesOps["copyCharacter"] = (source, src_slot, target, dst_slot) =>
      void plan("saves.copy_character", { source, src_slot, target, dst_slot });

    const replaceFromLibrary: SavesOps["replaceFromLibrary"] = (folder, entry_id, target) => {
      const body = { folder, entry_id, target };
      void command<CopyEntry>("saves.copy_entry", { folder, entry_id }, w("copyUnusable")).then((entry) => {
        if (!entry) return;
        // a copy that is not what the launcher stored is asked about first
        if (entry.changed_outside && entry.outside)
          offerPlan({ plan_id: null, prompt: entry.outside }, () => void plan("saves.replace_from_library", body));
        else void plan("saves.replace_from_library", body);
      });
    };

    const copyFromLibrary: SavesOps["copyFromLibrary"] = (folder, entry_id, src_slot, target, dst_slot) =>
      void command<CopyEntry>("saves.copy_entry", { folder, entry_id }, w("copyUnusable")).then(
        (entry) => entry && copyCharacter(entry.path, src_slot, target, dst_slot),
      );

    const restoreBackup: SavesOps["restoreBackup"] = (backup, target) => void plan("saves.restore_backup", { backup, target });
    const backUp = (path: string) => void job("saves.back_up", { paths: [path] });

    const dispatch = (d: Dropped) => {
      const a = d.args;
      switch (d.call) {
        case "copyCharacter":
          return copyCharacter(String(a[0]), Number(a[1]), String(a[2]), Number(a[3]));
        case "copyFromLibrary":
          return copyFromLibrary(String(a[0]), String(a[1]), Number(a[2]), String(a[3]), Number(a[4]));
        case "replaceFromLibrary":
          return replaceFromLibrary(String(a[0]), String(a[1]), String(a[2]));
        case "restoreBackup":
          return restoreBackup(String(a[0]), String(a[1]));
        case "backUpNow":
          return backUp(String(a[0]));
        case "askName":
          return void defaultName(String(a[1])).then((start) => askName({ mode: "copy", path: String(a[1]), start }));
      }
    };
    const judge: SavesOps["judge"] = (source, target) =>
      qc.fetchQuery({
        queryKey: [...savesKey, "drop", source, target],
        queryFn: () => run<Dropped>("saves.drop", { source: wire(source), target }),
        staleTime: 5000,
      });
    const drop: SavesOps["drop"] = (source, target) =>
      void command<Dropped>("saves.drop", { source: wire(source), target }).then((d) => {
        if (!d) return;
        if (d.reason) toast.error(d.reason);
        else dispatch(d);
      });

    return {
      view,
      backUp,
      backUpAll: () => void job("saves.back_up", { everything: true }),
      postSessionRepair: () => void job("saves.post_session_repair"),
      askCopyName: (path) => void defaultName(path).then((start) => askName({ mode: "copy", path, start })),
      pickImport: () => void pickSaves(w("pickImport"), true).then(importPaths),
      importPaths,
      askName,
      saveCopy: (path, name) => void job("saves.save_copy", { path, name }),
      importFile: (path, name) => {
        if (hasLibrary()) void job("saves.import_files", { files: [path], name });
      },
      keepAs: (backup, name) =>
        void command<{ text: string }>("saves.keep_as", { backup, name }, w("couldNotKeep")).then((r) => {
          if (r) toast.success(w("keptAs").replace("{name}", r.text));
          refresh();
        }),
      renameCopy: (folder, entry_id, name) =>
        void command("saves.rename_copy", { folder, entry_id, name }, w("couldNotRename")).then(refresh),
      letAgeOut: (backup) => void command("saves.keep_backup", { backup, keep: false }, w("couldNotChange")).then(refresh),
      deleteBackup: (backup) =>
        void plan(
          "saves.delete_backup",
          { backup },
          () => {
            toast.success(w("backupRemoved"));
            refresh();
          },
          w("couldNotRemove"),
        ),
      removeCopy: (folder, entry_id) => void plan("saves.remove_copy", { folder, entry_id }, refresh, w("couldNotRemove")),
      finishStranded: (folder, entry_id, restore) =>
        void command<{ warning: string }>("saves.finish_stranded", { folder, entry_id, restore }, w("couldNotFinish")).then((r) => {
          if (r?.warning) toast(r.warning);
          refresh();
        }),
      copyCharacter,
      copyFromLibrary,
      replaceFromLibrary,
      replaceFromFile: (target) =>
        void pickSaves(w("pickReplace"), false).then(([source]) => {
          if (source) void plan("saves.replace_from_file", { source, target });
        }),
      restoreBackup,
      repair: (path, keys) => void plan("saves.repair", { path, keys }),
      copyReport: (path) =>
        void command<{ text: string }>("saves.health_report", { path }).then(async (r) => {
          if (!r) return;
          await navigator.clipboard.writeText(r.text);
          toast.success(w("reportCopied"));
        }),
      openFolder: (which) =>
        void command<{ path: string | null }>("saves.folder", { which }).then((f) => {
          if (f?.path) void command("saves.open_folder", { path: f.path });
        }),
      openSaveFolder: (path) => void command("saves.open_folder", { path: parentOf(path) }),
      drop,
      judge,
      copyKey: (source) => {
        clip.current = source;
        toast(w("characterCopied"));
      },
      pasteInto: (target) => {
        if (clip.current) drop(clip.current, target);
        else toast.error(w("copyFirst"));
      },
      refresh: () => void command("saves.adopt_legacy", {}).then(refresh),
    };
  }, [view, w, command, job, plan, run, qc, refresh, offerPlan, askName]);

  return <OpsContext value={ops}>{children}</OpsContext>;
}

/** The page's data, from the first read on. */
export function useSavesPage() {
  const api = useApi();
  return useQuery({ queryKey: savesKey, queryFn: () => api.get<SavesPageData>("/v1/pages/saves") });
}
