import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useBlocker, useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import { ContextMenu } from "radix-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "@/api/backend";
import { toProblem } from "@/components/toasts";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useDialogs } from "./dialogs";
import { FileEditor, type OpenSetup } from "./FileEditor";
import { failed, refuse, useModOps } from "./ops";
import type { Candidate, FileRead, OverhaulForm, PageState, RawNode, TreeNode } from "./types";

const NEW_KEY = "overhaul:new";

/** Under 640 px the tree and the file take turns (the Qt page's narrow layout). */
function useNarrow() {
  const query = "(max-width: 639.98px)";
  const [narrow, setNarrow] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
}

const stem = (path: string) => (path.split(/[\\/]/).pop() ?? "").replace(/\.me3$/i, "");

/** Mod Configs: the profile's mods with settings files on the left; the open file, as the form, panel or text its kind asks for, on the right. */
export function ModConfigsPage() {
  const api = useApi();
  const qc = useQueryClient();
  const ops = useModOps();
  const navigate = useNavigate();
  const narrow = useNarrow();
  const [showFile, setShowFile] = useState(false);
  const [sel, setSel] = useState<{ node: string; path: string } | null>(null);
  const [want, setWant] = useState("");
  const [nonce, setNonce] = useState(0);
  const [newSetup, setNewSetup] = useState<OpenSetup | null>(null);
  const dirtyRef = useRef(false);
  const setDirty = useCallback((d: boolean) => {
    dirtyRef.current = d;
  }, []);

  const page = useQuery({ queryKey: ["page", "mod_configs"], queryFn: () => api.get<PageState>("/v1/pages/mod_configs") });
  const state = page.data;
  const words = useMemo(() => state?.words ?? {}, [state?.words]);
  const dialogs = useDialogs(words);

  // Mods sends the player here with ?select=<mod name>: that mod is selected once the page has read it, then the link is cleaned
  const { select: selectName } = useSearch({ strict: false }) as { select?: string };
  const [handled, setHandled] = useState("");
  const named = selectName ? state?.nodes.find((n) => n.name === selectName) : undefined;
  if (selectName && named && handled !== selectName) {
    setHandled(selectName);
    setWant(named.key);
  } else if (!selectName && handled) setHandled("");
  useEffect(() => {
    if (selectName && handled === selectName) void navigate({ to: "/mod-configs", search: {}, replace: true } as never);
  }, [selectName, handled, navigate]);

  // ---- which file is open: the one picked, else the first mod's first file
  const nodes = state?.nodes;
  const first = nodes?.find((n) => n.files.length > 0);
  const picked = sel && nodes?.find((n) => n.key === sel.node && n.files.some((f) => f.path === sel.path));
  const open = newSetup ? null : picked ? sel : first ? { node: first.key, path: first.files[0]!.path } : null;

  // A mod to select once the tree is read again (after attach, a saved setup, an install): adjusted while rendering.
  const wanted = want ? nodes?.find((n) => n.key === want) : undefined;
  if (wanted) {
    setWant("");
    setNewSetup(null);
    if (!(sel?.node === wanted.key && wanted.files.some((f) => f.path === sel.path)) && wanted.files[0]) setSel({ node: wanted.key, path: wanted.files[0].path });
  }

  const node = newSetup ? undefined : nodes?.find((n) => n.key === open?.node);
  const tree = newSetup ? newTree(newSetup) : state?.tree.find((t) => t.key === open?.node);
  const rawNode: RawNode | undefined = newSetup ? newRaw(newSetup) : node;

  const profile = state?.profile ?? "";
  const file = useQuery({
    queryKey: ["modConfigsFile", profile, open?.path, nonce],
    enabled: !!open && !!rawNode && !newSetup,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[2] === open?.path ? prev : undefined),
    queryFn: async () => {
      const setupFile = rawNode?.kind === "overhaul" && !!rawNode.setup && rawNode.files[0]?.path === open?.path;
      const read = await ops.run<FileRead>("mod_configs.open", {
        path: open?.path,
        seamless: rawNode?.kind === "seamless",
        profile,
        form: !setupFile,
      });
      const form = setupFile ? await ops.run<OverhaulForm>("mod_configs.overhaul_form", { profile }) : null;
      return { read, form };
    },
  });

  // ---- asking before something unsaved is dropped
  const guard = useCallback(
    (then: () => void) => {
      if (!dirtyRef.current) return then();
      dialogs.confirm({ kind: "confirm", title: words.unsavedTitle ?? "", changes: [words.unsavedBody ?? ""], apply: words.discard ?? "" }, then);
    },
    [dialogs, words],
  );
  const blocker = useBlocker({ shouldBlockFn: () => dirtyRef.current, enableBeforeUnload: () => dirtyRef.current, withResolver: true });
  useEffect(() => {
    if (blocker.status !== "blocked") return;
    dialogs.confirm(
      { kind: "confirm", title: words.unsavedTitle ?? "", changes: [words.unsavedBody ?? ""], apply: words.discard ?? "" },
      blocker.proceed,
      blocker.reset,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blocker.status]);

  const refreshTree = () => void qc.invalidateQueries({ queryKey: ["page"] });
  const onTreeChanged = useCallback(
    (key: string) => {
      setWant(key);
      setNonce((n) => n + 1); // the file's fingerprint changed too
      void qc.invalidateQueries({ queryKey: ["page"] });
    },
    [qc],
  );
  const reload = useCallback(() => {
    if (newSetup?.mod) return void startNew(newSetup.mod);
    setNonce((n) => n + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newSetup]);

  // ---- the overhaul setup: set a mod up, turn it off
  async function startNew(mod: Candidate) {
    try {
      const form = await ops.run<OverhaulForm>("mod_configs.overhaul_form", { profile, folder: mod.folder, name: mod.name, overhaul_id: mod.id });
      setNewSetup({ ...form, mod });
      setNonce((n) => n + 1);
      setShowFile(true);
    } catch (e) {
      failed(e, words);
    }
  }
  async function setUp(key: string) {
    try {
      const { mods } = await ops.run<{ mods: Candidate[] }>("mod_configs.setup_candidates", { profile });
      const named = key ? state?.nodes.find((n) => n.key === key)?.name : undefined;
      const chosen = mods.find((m) => m.name === named);
      if (chosen) return guard(() => void startNew(chosen));
      if (mods.length === 0) return refuse(words.nothingToSetUp ?? "", words.noMods ?? "");
      dialogs.pick(
        { kind: "pick", title: words.pickOverhaulTitle ?? "", body: words.pickOverhaulBody ?? "", apply: words.pickOverhaulApply ?? "", none: "", rows: mods.map((m) => m.name) },
        (ticked) => {
          const m = ticked[0] !== undefined ? mods[ticked[0]] : undefined;
          if (m) guard(() => void startNew(m));
        },
      );
    } catch (e) {
      failed(e, words);
    }
  }
  async function turnOff() {
    const setup = node?.setup ?? null;
    if (!setup || setup.verified) return;
    try {
      dialogs.offerPlan(await ops.plan("mod_configs.turn_off", { profile }), (ok) => ok && refreshTree());
    } catch (e) {
      failed(e, words);
    }
  }
  const overhaulAction = (key: string, action: "setUp" | "turnOff") => (action === "setUp" ? void setUp(key) : void turnOff());

  function select(nodeKey: string, path: string) {
    guard(() => {
      setNewSetup(null);
      setSel({ node: nodeKey, path });
      setShowFile(true);
    });
  }

  // ---- the page
  const empty = !!state?.profile && state.nodes.length === 0 && !page.isFetching;
  const loaded = file.data;
  return (
    <section aria-labelledby="page-title" className="flex min-h-[70vh] flex-col gap-3">
      <header className="flex items-baseline gap-3">
        <h1 id="page-title" className="font-semibold text-page text-title">
          {words.title ?? "Mod Configs"}
        </h1>
        <span className="truncate text-row text-accent">{state ? (state.profile ? stem(state.profile) : words.noProfile) : ""}</span>
      </header>
      {page.error ? (
        <p role="alert" className="text-status-danger">
          {toProblem(page.error).message}
        </p>
      ) : null}
      {page.isPending ? <p className="text-text-secondary">…</p> : null}
      {state && !state.profile ? <p className="text-text-secondary">{words.noProfile}</p> : null}
      {empty ? (
        <div className="m-auto flex max-w-sm flex-col items-center gap-2 text-center">
          <h2 className="font-semibold text-row">{words.emptyNoFilesTitle}</h2>
          <p className="text-caption text-text-secondary">{words.emptyNoFilesBody}</p>
          <Button variant="primary" onClick={() => void navigate({ to: "/mods" })}>
            {words.goToMods}
          </Button>
          <Button onClick={() => void setUp("")}>{words.setUpModLink}</Button>
        </div>
      ) : null}
      {state && state.nodes.length > 0 ? (
        <div className="flex min-w-0 flex-1 gap-0">
          <nav
            aria-label={words.title}
            className={cn("flex w-[300px] shrink-0 flex-col gap-3 self-start border-r border-border-hairline pr-4 max-[900px]:w-[220px]", narrow && (showFile ? "hidden" : "w-full border-r-0 pr-0"))}
          >
            {narrow ? <p className="text-caption text-text-secondary">{words.pickFile}</p> : null}
            {state.tree.map((t) => (
              <TreeBlock key={t.key} node={t} selected={open?.node === t.key ? (newSetup ? "" : open.path) : ""} words={words} onSelect={select} onAction={overhaulAction} />
            ))}
          </nav>
          <div className={cn("flex min-w-0 flex-1 flex-col pl-4", narrow && !showFile && "hidden", narrow && "pl-0")}>
            {narrow ? (
              <Button className="mb-2 self-start" onClick={() => setShowFile(false)}>
                <ArrowLeft aria-hidden className="size-4" />
                {words.back}
              </Button>
            ) : null}
            {!newSetup && file.error ? (
              <div role="alert" className="rounded-card border border-status-danger bg-status-danger-bg px-3 py-2">
                <p className="font-semibold">{(words.cantOpen ?? "{name}").replace("{name}", (open?.path ?? "").split(/[\\/]/).pop() ?? "")}</p>
                <p className="text-caption">{toProblem(file.error).message}</p>
              </div>
            ) : null}
            {(newSetup || (loaded && rawNode && tree)) && rawNode && tree ? (
              <FileEditor
                key={newSetup ? `new-${nonce}` : `${open?.path}-${file.dataUpdatedAt}`}
                profile={profile}
                node={rawNode}
                tree={tree}
                path={newSetup ? null : (open?.path ?? null)}
                read={newSetup ? null : (loaded?.read ?? null)}
                ov={newSetup ?? (loaded?.form ? { ...loaded.form } : null)}
                words={words}
                dialogs={dialogs}
                onReload={reload}
                onDirty={setDirty}
                guard={guard}
                onTreeChanged={onTreeChanged}
                onOverhaulAction={(a) => overhaulAction(rawNode.key, a)}
              />
            ) : !file.error && open ? (
              <p className="text-text-secondary">…</p>
            ) : !file.error ? (
              <div className="m-auto flex max-w-sm flex-col items-center gap-2 text-center">
                <h2 className="font-semibold text-row">{words.emptyPickTitle}</h2>
                <p className="text-caption text-text-secondary">{words.emptyPickBody}</p>
                <Button onClick={() => void setUp("")}>{words.setUpModLink}</Button>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

/** A mod: its name (with the Disabled tag), the line under it, and its files. Right-click, or the Menu key, offers the overhaul entry. */
function TreeBlock({
  node,
  selected,
  words,
  onSelect,
  onAction,
}: {
  node: TreeNode;
  selected: string;
  words: Record<string, string>;
  onSelect: (node: string, path: string) => void;
  onAction: (node: string, action: "setUp" | "turnOff") => void;
}) {
  const block = (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-2">
        <span className={cn("truncate font-semibold text-body", node.muted ? "text-text-secondary" : "text-text-primary")}>{node.name}</span>
        {node.disabled ? (
          <span title={node.disabledTip || undefined} className="rounded-tag border border-border-tag px-1.5 text-tag text-text-secondary">
            {words.disabled}
          </span>
        ) : null}
      </div>
      {node.sub ? <p className="text-caption text-text-secondary">{node.sub}</p> : null}
      <ul aria-label={node.name} className="flex flex-col">
        {node.files.map((f) => (
          <li key={f.path}>
            <button
              type="button"
              data-testid={`file_${f.name}`}
              aria-current={f.path === selected ? "true" : undefined}
              onClick={() => onSelect(node.key, f.path)}
              className={cn(
                "h-8 w-full truncate rounded-control px-4 text-left text-body outline-none hover:bg-fill-ghost-hover focus-visible:ring-2 focus-visible:ring-glow-ring",
                f.path === selected && "bg-accent-soft",
              )}
            >
              {f.name}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
  if (node.action === "") return block;
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild>{block}</ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content className="z-50 min-w-56 rounded-card border border-border-edge bg-surface-card p-1 shadow-xl">
          <ContextMenu.Item
            className="flex h-[var(--menu-row-h)] cursor-default items-center gap-2 rounded-control px-3 text-body outline-none data-[highlighted]:bg-fill-ghost-hover"
            onSelect={() => onAction(node.key, node.action as "setUp" | "turnOff")}
          >
            {node.action === "setUp" ? <Plus aria-hidden className="size-4" /> : <Trash2 aria-hidden className="size-4" />}
            {node.action === "setUp" ? words.setUpOverhaul : words.turnOffOverhaul}
          </ContextMenu.Item>
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}

// A mod set up as a new overhaul has no file yet: the page shows the proposal under a node of its own.
function newTree(o: OpenSetup): TreeNode {
  return { key: NEW_KEY, kind: "overhaul", name: o.setup.config.label, sub: "", disabled: false, disabledTip: "", muted: false, action: "", files: [] };
}
function newRaw(o: OpenSetup): RawNode {
  return { key: NEW_KEY, name: o.setup.config.label, kind: "overhaul", target: null, setup: o.setup, files: [] };
}
