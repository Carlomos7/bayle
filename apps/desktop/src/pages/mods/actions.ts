import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useApi } from "@/api/backend";
import { ApiError } from "@/api/client";
import type { PlanOffer, PromptWords } from "@/api/types";
import { usePrompts } from "@/components/PromptHost";
import { toProblem } from "@/components/toasts";
import { pickFolder } from "@/lib/native";
import { useModsHost } from "./install-contract";
import { say, sayAction, sayError } from "./notify";
import { fill, type Changed, type DragTable, type JobDone, type ModsView, type MoveResult, type PickOffer, type PickWords, type SettingResult, type Leftovers, type Words } from "./types";

const DECLINED = Symbol("declined");
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const why = (e: unknown) => toProblem(e).message;
const stem = (path: string) => (path.split(/[\\/]/).pop() ?? "").replace(/\.me3$/i, "");

export interface OptionsChosen {
  enabled: boolean;
  id: string;
  loadAfter: { id: string; optional: boolean }[];
  loadBefore: { id: string; optional: boolean }[];
  optional: boolean;
  loadEarly: boolean;
  initKind: number;
  initValue: string;
  finalizer: string;
  overlay: number;
  rebuildFile: string;
}

export type ModsActions = ReturnType<typeof useModsActions>;

/**
 * Everything the Mods page does to a profile: one op each (the Qt adapter's calls, same order and same words). `ui`
 * is what only the page can open (a dialog). Failures say themselves in a toast; nothing here throws to the caller.
 */
export function useModsActions(view: ModsView | undefined, ui: { openOptions(index: number): void; openLibrary(): void }) {
  const api = useApi();
  const qc = useQueryClient();
  const prompts = usePrompts();
  const host = useModsHost();
  const words = (view?.words ?? {}) as Words;
  const profile = view?.profile ?? "";
  // run any action as one mutation: pending state, one error path
  const mutation = useMutation({ mutationFn: (fn: () => Promise<unknown>) => fn(), onError: (e) => sayError(why(e)) });
  const act = mutation.mutate;

  return useMemo(() => {
    const ref = (more: object = {}) => ({ profile, ...more });
    const launch = (more: object = {}) => ref({ kind: view?.kind ?? "me3", source: view?.source ?? "", ...more });
    const refresh = () => {
      void qc.invalidateQueries({ queryKey: ["page", "mods"] });
      void qc.invalidateQueries({ queryKey: ["page", "shell"] });
    };
    const post = <T>(op: string, params: object = {}) => api.post<T>(`/v1/ops/${op}`, params);

    /** An op with the retry convention: needs_confirmation carries the Confirm; on yes it runs again, confirmed. */
    async function run<T>(op: string, params: object, retry?: (option: boolean) => object): Promise<T | typeof DECLINED> {
      try {
        return await post<T>(op, params);
      } catch (e) {
        if (e instanceof ApiError && e.problem.code === "needs_confirmation" && retry) {
          const answer = await prompts.ask(e.problem.details?.prompt as PromptWords);
          if (!answer.ok) return DECLINED;
          return await post<T>(op, { ...params, confirmed: true, ...retry(answer.option) });
        }
        throw e;
      }
    }
    async function follow(jobId: string): Promise<JobDone> {
      for (;;) {
        const job = await api.get<JobDone>(`/v1/jobs/${jobId}`);
        if (job.state !== "running") return job;
        await sleep(250);
      }
    }
    /** A job op: the retry convention, then follow it to its end (its own toasts come from the event stream). */
    async function job(op: string, params: object, retry?: (option: boolean) => object) {
      const started = await run<{ job_id: string }>(op, params, retry);
      return started === DECLINED ? DECLINED : follow(started.job_id);
    }
    /** A plan op: its Confirm opens in the dialog host; `then` gets the job the answer started. */
    async function plan(op: string, params: object, then?: (jobId: string | null) => void) {
      prompts.offerPlan(await post<PlanOffer>(op, params), then && ((r) => then((r as { job_id?: string | null } | undefined)?.job_id ?? null)));
    }
    const failWith = (key: string) => (e: unknown) => sayError(fill(words[key], { why: why(e) }));

    function undoLast() {
      act(async () => {
        try {
          await post("mods.undo_change", ref());
          say(words.toastUndone);
        } catch (e) {
          failWith("failUndo")(e);
        } finally {
          refresh();
        }
      });
    }
    /** A change was written: read the page again and offer Undo. */
    const changed = (toastText: string) => {
      refresh();
      sayAction(toastText, words.undo, undoLast);
    };
    /** pick words -> the ticked indexes, or null when cancelled */
    async function pick(words_: PickWords): Promise<number[] | null> {
      const a = await prompts.ask(words_);
      return a.ok ? a.ticked : null;
    }

    const actions = {
      pending: mutation.isPending,
      refresh,
      post,
      act,

      setEnabled: (index: number, on: boolean, name: string) =>
        act(async () => {
          try {
            const got = await post<Changed>("mods.set_enabled", ref({ index, enabled: on }));
            changed(fill(on ? words.toastOn : words.toastOff, { name: got.name ?? name }));
          } catch (e) {
            failWith("failChange")(e);
            refresh();
          }
        }),

      remove: (index: number, name: string) =>
        act(async () => {
          let asked = false;
          try {
            const done = await job("mods.remove", ref({ index, name }), (delete_folder) => {
              asked = true;
              return { delete_folder };
            });
            if (done === DECLINED) return;
            refresh();
            // a confirm said Undo is in Activity; no confirm: Undo is right here
            const undo = (done.result as { undo?: Record<string, unknown> } | null)?.undo;
            if (done.state === "done" && !asked && undo) {
              sayAction(fill(words.toastRemoved, { name }), words.undo, () =>
                act(async () => {
                  try {
                    await post("mods.undo_removal", { undo });
                    say(words.toastUndone);
                  } catch (e) {
                    failWith("failUndo")(e);
                  } finally {
                    refresh();
                  }
                }),
              );
            }
          } catch (e) {
            sayError(why(e));
            if (e instanceof ApiError && e.problem.code === "stale") refresh();
          }
        }),

      removeHolder: (index: number) =>
        act(() =>
          plan("mods.remove_holder", ref({ index }), (jobId) => {
            if (!jobId) return;
            act(async () => {
              const done = await follow(jobId);
              const r = done.result as Changed | null;
              if (done.state === "done" && r) changed(fill(words.toastHolderOut, { name: r.name ?? "" }));
            });
          }),
        ),

      /** The refusal for every drop spot of this entry (one call per drag). */
      dragTable: (index: number) => post<DragTable>("mods.drag", ref({ index })),

      move: (index: number, to: number) =>
        act(async () => {
          try {
            const got = await post<MoveResult>("mods.move", ref({ index, to }));
            if (got.moved) {
              changed(words.toastMoved);
              return;
            }
            if (got.problem) {
              if ((got.decided_by ?? -1) >= 0) {
                const by = got.decided_by as number;
                sayAction(got.problem, words.editOptions, () => ui.openOptions(by), true);
              } else sayError(got.problem);
            }
            refresh();
          } catch (e) {
            failWith("failMove")(e);
            refresh();
          }
        }),

      rebuild: () =>
        act(async () => {
          try {
            const combine = view?.state.parameters.state === "stacked" ? true : null;
            // a rebuild tool that is not allowed yet is asked about first; the answer allows it
            await job("mods.rebuild", ref({ combine }), () => ({ allow: true }));
          } catch (e) {
            sayError(why(e));
          }
        }),

      allowTool: () =>
        act(() =>
          plan("mods.allow_tool", ref(), () => {
            say(fill(words.toastToolAllowed, { tool: view?.tool_label ?? "" }));
            refresh();
          }),
        ),

      undoRebuild: () => {
        const rec = view?.rebuild_undo;
        if (rec) act(async () => prompts.offerPlan(await post<PlanOffer>("activity.undo", { job_id: rec.id })));
      },

      trimBackups: () =>
        act(() =>
          plan("mods.trim_backups", ref(), (jobId) => {
            if (!jobId) return;
            act(async () => {
              const done = await follow(jobId);
              if (done.state === "done") {
                say(fill(words.toastTrimmed, { n: String((done.result as { moved?: number } | null)?.moved ?? 0) }));
                refresh();
              }
            });
          }),
        ),

      fixOrder: () =>
        act(async () => {
          try {
            await post<Changed>("mods.fix_order", ref());
            changed(words.toastFixed);
          } catch (e) {
            failWith("failOrder")(e);
          }
        }),

      closeNotice: (key: string) =>
        act(async () => {
          await post("mods.close_notice", ref({ key }));
          refresh();
        }),

      // ---- the Library
      share: (index: number) => act(() => plan("mods.share", ref({ index }))),
      separate: (index: number) => act(() => plan("mods.separate", ref({ index }))),
      removeUnused: () => act(() => plan("mods.remove_unused", ref())),
      useInOthers: (index: number, name: string) =>
        act(async () => {
          const offer = await post<PickOffer>("mods.library_use_choices", ref({ index }));
          if (!offer.prompt) return;
          const targets = await pick(offer.prompt);
          if (targets?.length) {
            const done = await job("mods.library_use", ref({ index, targets, name }));
            if (done !== DECLINED) refresh();
          }
        }),

      // ---- InfoBars
      noticeAction: (key: string) => {
        switch (key) {
          case "stale":
            return actions.rebuild();
          case "allow-tool":
            return actions.allowTool();
          case "online":
            return actions.setSetting("start_online", 2); // Online matchmaking off: a Version, with Undo
          case "seamless":
            return actions.seamless();
          case "folder":
            return actions.folderAction();
          case "dll-folders":
            return actions.dllFolders();
          case "outside":
            return actions.moveIn();
          case "library-hint":
            return ui.openLibrary();
        }
      },
      /** Rename the profile's folder to its name, or split a crowded folder. */
      folderAction: () => {
        if (view?.folder_kind === "misnamed") act(async () => void (await job("mods.rename_folder", ref())));
        else if (view?.folder_kind === "crowded") act(() => plan("mods.split_folder", ref()));
      },
      dllFolders: () => act(() => plan("mods.dll_folders", ref())),
      seamless: () => act(() => plan("mods.seamless", launch())),

      // ---- overhauls installed with the launcher
      installOverhaul: () =>
        act(async () => {
          const folder = await pickFolder(words.overhaulFolderTitle);
          if (folder) await plan("mods.overhaul_install", ref({ folder }));
        }),
      removeOverhaul: () => {
        const has = view?.overhaul_info;
        if (!has) return;
        const ask = async (chosen: number[]) =>
          plan("mods.overhaul_remove", ref({ chosen }), () => {
            if (has.legacy) say(`${fill(words.leftoversLaterTitle, { label: has.label })}. ${words.leftoversLaterBody}`);
          });
        act(async () => {
          if (!has.legacy) return ask([]);
          const offer = await post<PickOffer>("mods.overhaul_remove_choices", ref());
          if (!offer.prompt) return ask([]);
          const chosen = await pick(offer.prompt); // what its installer changed is offered unticked
          if (chosen) await ask(chosen);
        });
      },
      /** An overhaul its own installer set up becomes the launcher's: pick what to put back, confirm, then offer to install it again. */
      takeOver: () => {
        const has = view?.overhaul_info;
        if (!has?.takeover) return;
        const ask = (chosen: number[]) =>
          plan("mods.takeover", ref({ chosen }), (jobId) => {
            if (!jobId) return;
            act(async () => {
              const done = await follow(jobId);
              if (done.state !== "done") return;
              const a = await prompts.ask({
                kind: "confirm",
                title: fill(words.reinstallTitle, { label: has.label }),
                changes: [words.reinstallBody],
                apply: words.reinstallApply,
              });
              if (a.ok) host.openInstall({ from: "folder" });
            });
          });
        act(async () => {
          const offer = await post<PickOffer>("mods.takeover_choices", ref());
          if (!offer.prompt) return ask([]);
          const chosen = await pick(offer.prompt);
          if (chosen) await ask(chosen);
        });
      },
      cleanLeftovers: () =>
        act(async () => {
          const left = await post<Leftovers>("mods.leftovers", ref());
          const folders = left.folders ? await pick(left.folders as unknown as PickWords) : [];
          if (folders === null) return;
          const confirmed: number[] = []; // last, and one at a time: the only copy from before the overhaul
          for (const [i, prompt] of left.backups.entries()) {
            if ((await prompts.ask(prompt as unknown as PromptWords)).ok) confirmed.push(i);
          }
          if (folders.length || confirmed.length) await job("mods.leftovers_clean", ref({ folders, backups: confirmed }));
        }),

      // ---- the profile
      deleteProfile: () =>
        act(() =>
          plan("mods.delete_profile", launch(), (jobId) => {
            if (!jobId) return;
            act(async () => {
              const done = await follow(jobId);
              if (done.state === "done") say(fill(words.toastDeleted, { name: stem(profile) }));
              refresh();
            });
          }),
        ),
      moveIn: () => act(() => plan("mods.move_in", launch())),
      duplicate: () =>
        act(async () => {
          // packages can be shared: the session asks, never forces; the check box is the answer
          await job("mods.duplicate_profile", launch(), (share) => ({ share }));
        }),
      renameProfile: async (name: string): Promise<string> => {
        const block = view?.rename_block ?? "";
        if (block) return block;
        const check = await post<{ problem: string }>("mods.profile_name_check", launch({ name }));
        if (check.problem) return check.problem;
        act(async () => void (await job("mods.rename_profile", launch({ name }))));
        return "";
      },
      profileNameCheck: (name: string) => post<{ problem: string }>("mods.profile_name_check", launch({ name })).then((r) => r.problem),

      // ---- entries
      rename: (index: number, name: string) => act(async () => void (await job("mods.rename", ref({ index, name })))),
      saveOptions: (index: number, chosen: OptionsChosen, name: string) =>
        act(async () => {
          try {
            const got = await post<Changed>("mods.save_options", ref({
              index,
              enabled: chosen.enabled,
              id: chosen.id,
              load_after: chosen.loadAfter,
              load_before: chosen.loadBefore,
              optional: chosen.optional,
              load_early: chosen.loadEarly,
              finalizer: chosen.finalizer,
              init_kind: chosen.initKind,
              init_value: chosen.initValue,
              overlay: chosen.overlay,
              rebuild_file: chosen.rebuildFile,
            }));
            changed(fill(words.toastOptionsSaved, { name: got.name ?? name }));
          } catch (e) {
            if (e instanceof ApiError && e.problem.code === "invalid_wait") sayError(e.problem.message);
            else {
              failWith("failOptions")(e);
              refresh();
            }
          }
        }),
      setSetting: (key: string, value: number | string) =>
        act(async () => {
          try {
            const got = await run<SettingResult>("mods.set_setting", ref({ key, value }), () => ({}));
            if (got === DECLINED) return refresh();
            if (got.changed) changed(fill(words.settingChanged, { setting: words[`setting_${key}`] ?? key }));
          } catch (e) {
            failWith("failWrite")(e);
          }
        }),
      restoreVersion: (path: string) =>
        act(async () => {
          try {
            const got = await post<{ before: string | null }>("mods.restore_version", ref({ path }));
            refresh();
            const before = got.before;
            if (before !== null) {
              sayAction(words.toastRestored, words.undo, () =>
                act(async () => {
                  await post("mods.restore_version", ref({ path: before }));
                  refresh();
                }),
              );
            }
          } catch (e) {
            failWith("failRestore")(e);
          }
        }),
      addPaths: (kind: string, paths: string[]) =>
        act(async () => {
          try {
            const got = await post<{ names: string[]; loose_dlls: boolean }>("mods.add_existing", ref({ kind, paths }));
            changed(fill(words.toastAdded, { names: got.names.join(", ") }));
            if (got.loose_dlls) await plan("mods.dll_folders", ref()); // the same move the notice offers, asked right away
          } catch (e) {
            failWith("failAdd")(e);
          }
        }),
      saveText: (text: string, crlf: boolean, saved: () => void) =>
        act(async () => {
          try {
            await post<Changed>("mods.save_text", ref({ text, crlf }));
            saved();
            changed(words.toastTextSaved);
          } catch (e) {
            failWith("failSave")(e);
          }
        }),
    };
    return actions;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, api, qc, prompts, host, act, mutation.isPending]);
}
