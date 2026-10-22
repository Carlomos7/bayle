import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { pageKey } from "@/api/events";
import { useApi } from "@/api/backend";
import type { ShellState } from "@/api/types";
import { toProblem } from "@/components/toasts";
import { Button } from "@/components/ui/button";
import { onFilesDropped } from "@/lib/native";
import { useModsActions } from "./actions";
import { ModsContext, useMods } from "./context";
import { AddExistingDialog, LibraryDialog, OptionsDialog, RenameDialog, SettingsDialog, UnsavedDialog, VersionsDialog } from "./dialogs";
import { InstallModDialog, type InstallModHandle } from "./install/InstallModDialog";
import { ModsHostContext, useModsHost, type ModsHost } from "./install-contract";
import { handOverBundled } from "@/pages/profile-transfer/bundled";
import { ShellActionsContext } from "@/shell/context";
import { LoadOrderPanel } from "./LoadOrderPanel";
import { ModGroup } from "./ModGroup";
import { ModsHeader } from "./ModsHeader";
import { ParametersCard } from "./ParametersCard";
import { TextEditor, useTextEdit } from "./TextEditor";
import type { ModsView, Notice, Words } from "./types";
import { InfoBar } from "./ui";

type Dialog =
  | { kind: "options"; index: number }
  | { kind: "rename"; index: number }
  | { kind: "add"; entryKind: string }
  | { kind: "settings" | "versions" | "library" };

const NOTICES_SHOWN = 2; // InfoBars at once; the rest wait (ModsPresenter.notices_shown)

/** The Mods page: the profile's rows (packages, natives), InfoBars, Parameters card, Load order panel, Edit as text. */
export function ModsPage() {
  const api = useApi();
  const shell = useQuery({ queryKey: pageKey("shell"), queryFn: () => api.get<ShellState>("/v1/pages/shell") });
  // the profile the top bar picked is the backend's default; the key follows it so a switch reads the page again
  const mods = useQuery({
    queryKey: ["page", "mods", { profile: shell.data?.profile_index ?? null }],
    queryFn: () => api.get<ModsView>("/v1/pages/mods"),
  });
  return (
    <section aria-labelledby="page-title" className="flex flex-col gap-4">
      <h1 id="page-title" className="sr-only">
        Mods
      </h1>
      {mods.data ? (
        <ModsBody view={mods.data} noProfiles={(shell.data?.profiles.length ?? 1) === 0} />
      ) : mods.error ? (
        <p role="alert" className="text-status-danger">
          {toProblem(mods.error).message}
        </p>
      ) : (
        <p aria-busy className="text-text-secondary">
          Loading...
        </p>
      )}
    </section>
  );
}

function ModsBody({ view, noProfiles }: { view: ModsView; noProfiles: boolean }) {
  const navigate = useNavigate();
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const openOptions = useCallback((index: number) => setDialog({ kind: "options", index }), []);
  const openLibrary = useCallback(() => setDialog({ kind: "library" }), []);
  const actions = useModsActions(view, { openOptions, openLibrary });
  const words = useMemo(() => (view.words ?? {}) as Words, [view.words]);
  const value = useMemo(
    () => ({
      view,
      words,
      actions,
      openOptions,
      openRename: (index: number) => setDialog({ kind: "rename", index }),
      openAddExisting: (entryKind: string) => setDialog({ kind: "add", entryKind }),
      // the Mod Configs page selects the mod named in ?select
      openConfigs: (name: string) => void navigate({ to: "/mod-configs", search: { select: name } } as never),
    }),
    [view, words, actions, openOptions, navigate],
  );
  const close = () => setDialog(null);

  // the Install mod dialog lives here; the rest of the page asks for it through ModsHost
  const install = useRef<InstallModHandle>(null);
  const shellActions = use(ShellActionsContext);
  const host = useMemo<ModsHost>(
    () => ({
      openInstall: (request) =>
        request?.paths?.length ? install.current?.openInstall(request.paths) : install.current?.openInstall(undefined, { folder: request?.from === "folder" }),
      newProfile: () => shellActions?.openNewProfile(),
    }),
    [shellActions],
  );
  return (
    <ModsHostContext value={host}>
    <ModsContext value={value}>
      <InstallModDialog
        ref={install}
        profile={view.profile}
        onImportInstead={(h) => {
          // the download ships .me3 profiles: Export / Import takes over its unpacked folder
          handOverBundled({ unpacked: h.unpacked, profiles: h.profiles, staging: h.staging ?? undefined });
          void navigate({ to: "/profile-transfer" });
        }}
      />
      <ModsContent noProfiles={noProfiles} setDialog={setDialog} />
      {dialog?.kind === "options" ? <OptionsDialog index={dialog.index} onClose={close} /> : null}
      {dialog?.kind === "rename" ? <RenameDialog index={dialog.index} onClose={close} /> : null}
      {dialog?.kind === "settings" ? <SettingsDialog onClose={close} /> : null}
      {dialog?.kind === "versions" ? <VersionsDialog onClose={close} /> : null}
      {dialog?.kind === "library" ? <LibraryDialog onClose={close} /> : null}
      {dialog?.kind === "add" ? <AddExistingDialog kind={dialog.entryKind} onClose={close} /> : null}
    </ModsContext>
    </ModsHostContext>
  );
}

function ModsContent({ noProfiles, setDialog }: { noProfiles: boolean; setDialog(d: Dialog): void }) {
  const { view, words, actions } = useMods();
  const host = useModsHost();
  const [editText, setEditText] = useState(false);
  const [unsaved, setUnsaved] = useState(false);
  const [loadOrder, setLoadOrder] = useState(false);
  const [dropping, setDropping] = useState(false);

  // F5 rescans
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.key === "F5") {
        e.preventDefault();
        actions.refresh();
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [actions]);

  // files dropped from Explorer: the install flow takes them in turn
  useEffect(() => {
    let off = () => {};
    let gone = false;
    void onFilesDropped((paths, over) => {
      setDropping(over);
      if (paths.length) host.openInstall({ paths });
    }).then((u) => (gone ? u() : (off = u)));
    return () => {
      gone = true;
      off();
    };
  }, [host]);

  const text = useTextEdit(editText);
  const wantEditText = (on: boolean) => {
    if (!on && text.dirty) setUnsaved(true);
    else {
      if (!on) text.reset();
      setEditText(on);
    }
  };

  // the disk hint (the same Separate copy in several profiles) waits for a free bar
  const api = useApi();
  const hint = useQuery({
    queryKey: ["page", "mods", "library-hint", view.profile],
    queryFn: () => api.post<{ notice: Notice | null }>("/v1/ops/mods.library_hint", { profile: view.profile }),
    enabled: view.has_profile,
  });
  const notices = [...view.state.notices];
  if (hint.data?.notice && notices.length < NOTICES_SHOWN) notices.push(hint.data.notice);

  const groups = view.state.groups;
  return (
    <>
      {!editText
        ? notices.map((n) => (
            <InfoBar
              key={n.key}
              severity={n.severity}
              text={n.text}
              action={n.action}
              closable={n.closable}
              closeLabel={words.close}
              onAction={() => actions.noticeAction(n.key)}
              onClose={() => actions.closeNotice(n.key)}
            />
          ))
        : null}
      {view.state.empty ? <p className="text-caption text-text-tertiary">{view.state.empty}</p> : null}
      {noProfiles ? (
        <Button variant="primary" className="self-start" onClick={host.newProfile}>
          {words.createProfile}
        </Button>
      ) : null}
      {view.has_profile ? (
        <>
          <ModsHeader
            editText={editText}
            onEditText={wantEditText}
            onHealth={() => {
              document.getElementById("parameters")?.scrollIntoView?.({ block: "start" });
              setLoadOrder(true);
            }}
            openSettings={() => setDialog({ kind: "settings" })}
            openVersions={() => setDialog({ kind: "versions" })}
            openLibrary={() => setDialog({ kind: "library" })}
          />
          {editText ? (
            <TextEditor edit={text} />
          ) : (
            <>
              {groups.map((g) => (
                <ModGroup key={g.kind} group={g} />
              ))}
              {view.state.parameters.visible ? <ParametersCard onDetails={() => setLoadOrder(true)} /> : null}
            </>
          )}
          <LoadOrderPanel open={loadOrder} onClose={() => setLoadOrder(false)} />
        </>
      ) : null}
      {dropping ? (
        <div aria-hidden className="pointer-events-none fixed inset-3 z-[90] grid place-items-center rounded-card border-2 border-accent bg-accent-soft text-section text-accent">
          {words.dropToInstall}
        </div>
      ) : null}
      {unsaved ? (
        <UnsavedDialog
          canSave={!text.error}
          onSave={() => {
            text.save();
            setUnsaved(false);
            text.reset();
            setEditText(false);
          }}
          onDiscard={() => {
            text.reset();
            setUnsaved(false);
            setEditText(false);
          }}
          onCancel={() => setUnsaved(false)}
        />
      ) : null}
    </>
  );
}
