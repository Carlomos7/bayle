import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link2, MoreHorizontal, Plus, Trash2 } from "lucide-react";
import { DropdownMenu, Switch } from "radix-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import { CodeEditor, type EditorProblem } from "@/components/CodeEditor";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { ConfigForm, type FormModel } from "./ConfigForm";
import type { Dialogs } from "./dialogs";
import { failed, message, refuse, say, useModOps } from "./ops";
import { formOf, patchValues, shownValue } from "./overhaul";
import { OverhaulSetup } from "./OverhaulSetup";
import { pickFile } from "@/lib/native";
import { SeamlessPanel } from "./SeamlessPanel";
import type { Candidate, FileRead, FormValues, OverhaulForm, OverhaulView, RawNode, Row, Saved, TreeNode } from "./types";

export type OpenSetup = OverhaulForm & { mod?: Candidate };

export interface FileEditorProps {
  profile: string;
  node: RawNode;
  tree: TreeNode;
  /** The open file's path (null for a new setup, which has no file yet). */
  path: string | null;
  read: FileRead | null;
  ov: OpenSetup | null;
  words: Record<string, string>;
  dialogs: Dialogs;
  /** Read the file again from disk (Reload, Discard, after Save): the edits are dropped. */
  onReload(): void;
  onDirty(dirty: boolean): void;
  /** Ask first when something is unsaved, then run. */
  guard(then: () => void): void;
  /** The tree changed on disk (attach, detach, a saved setup): read it again, and select this node afterwards. */
  onTreeChanged(want: string): void;
  onOverhaulAction(action: "setUp" | "turnOff"): void;
}

const key = (section: string, k: string) => `${section}|${k}`;

/** Everything the player sees for one open file: the breadcrumb and its tools, the body by kind, and the save bar. */
export function FileEditor(p: FileEditorProps) {
  const { read, words, node, tree, dialogs } = p;
  const ops = useModOps();
  const [pending, setPending] = useState<Record<string, { section: string; key: string; value: string }>>({});
  const [text, setText] = useState(read?.text ?? "");
  const [editText, setEditText] = useState(false);
  const [values, setValues] = useState<FormValues | null>(p.ov?.values ?? null);
  const [busy, setBusy] = useState(false);
  const ov = p.ov;
  const file = tree.files.find((f) => f.path === p.path);
  const isReadme = file?.kind === "readme";

  // ---- what is open
  const kind = ov && !editText ? "overhaul" : !read ? "" : editText ? "text" : read.seamless ? "seamless" : isReadme ? "readme" : read.has_form ? "form" : "text";
  const canEditText = !!read && !(ov && ov.setup.verified) && (!!ov || read.has_form || isReadme);

  // ---- the disk values the edits are compared with
  const disk = useMemo(() => {
    const m: Record<string, string> = {};
    for (const s of read?.sections ?? []) for (const r of s.rows) m[key(r.section, r.key)] = r.value;
    const sv = read?.seamless_view;
    if (sv) {
      if (sv.hasPassword) m[key("PASSWORD", "cooppassword")] = sv.password ?? "";
      for (const x of sv.scaling ?? []) m[key("SCALING", x.key)] = String(x.value);
      m[key("LANGUAGE", "mod_language_override")] = sv.language ?? "";
    }
    return m;
  }, [read]);

  const setValue = useCallback(
    (section: string, k: string, value: string) =>
      setPending((cur) => {
        const next = { ...cur };
        if (disk[key(section, k)] === value) delete next[key(section, k)];
        else next[key(section, k)] = { section, key: k, value };
        return next;
      }),
    [disk],
  );

  // ---- dirty and its words
  const ovDirty = !!ov && !editText && (ov.new || values !== ov.values);
  const dirty = ov && !editText ? ovDirty : kind === "text" ? text !== (read?.text ?? "") : Object.keys(pending).length > 0;
  const changes = ov && !editText ? (ovDirty ? 1 : 0) : kind === "text" ? (dirty ? 1 : 0) : Object.keys(pending).length;
  const changeText = changes === 0 ? (words.noChanges ?? "") : (changes === 1 ? words.changeOne : words.changeMany)?.replace("{n}", String(changes));
  const { onDirty } = p;
  useEffect(() => onDirty(dirty), [dirty, onDirty]);

  // ---- the setup's rows follow the values as edited
  const [settled, setSettled] = useState(values);
  useEffect(() => {
    const id = setTimeout(() => setSettled(values), 200);
    return () => clearTimeout(id);
  }, [values]);
  const { data: viewNow } = useQuery({
    queryKey: ["modConfigsView", p.profile, ov?.mod?.folder ?? "", settled],
    enabled: !!ov && !!settled && settled !== ov.values,
    placeholderData: keepPreviousData,
    queryFn: () =>
      ops.run<{ view: OverhaulView }>("mod_configs.overhaul_view", {
        profile: p.profile,
        ...(ov?.mod ? { folder: ov.mod.folder, name: ov.mod.name, overhaul_id: ov.mod.id } : {}),
        choices: ov?.choices,
        values: settled,
      }),
  });
  const ovView: OverhaulView | undefined = settled && ov && settled !== ov.values ? (viewNow?.view ?? ov.view) : ov?.view;

  // ---- has the file changed under the page?
  const { data: stamp } = useQuery({
    queryKey: ["modConfigsStamp", p.path],
    enabled: !!read?.stamp && !!p.path,
    refetchInterval: 3000,
    queryFn: () => ops.run<{ stamp: [number, number] | null }>("mod_configs.stamp", { path: p.path }),
  });
  const diskChanged = !!stamp?.stamp && JSON.stringify(stamp.stamp) !== JSON.stringify(read?.stamp);

  // ---- the editor's parse check
  const check = useCallback(
    (t: string) => ops.run<EditorProblem>("mod_configs.check_text", { name: p.path ?? "x.toml", text: t }),
    [ops, p.path],
  );

  // ---- saving
  const done = (said: string) => {
    say(said);
    p.onReload();
  };
  async function save() {
    if (busy || !dirty) return;
    setBusy(true);
    try {
      if (ov && !editText) return await saveSetup(ov);
      if (!read) return;
      if (ov) return await saveSetupText();
      const base = { path: read.path, expect: read.sha };
      if (kind === "text") {
        done((await ops.run<Saved>("mod_configs.save", { ...base, kind: "text", text })).said);
        return;
      }
      const edits = Object.values(pending).map((e) => ({ section: e.section, key: e.key, value: e.value }));
      const saved = await ops.run<Saved>("mod_configs.save", { ...base, kind: read.seamless ? "seamless" : "values", edits });
      if (saved.missing.length) refuse(words.notSavedTitle ?? "", saved.missing_said);
      done(saved.said);
    } catch (e) {
      failed(e, words);
    } finally {
      setBusy(false);
    }
  }

  async function saveSetup(o: OpenSetup) {
    if (!values) return;
    if (o.new && o.mod) {
      const offer = await ops.plan("mod_configs.install_setup", { profile: p.profile, folder: o.mod.folder, name: o.mod.name, overhaul_id: o.mod.id, form: formOf(values) });
      dialogs.offerPlan(offer, (ok) => ok && p.onTreeChanged("overhaul"));
      return;
    }
    const saved = await ops.run<{ name: string; overhaul_id: string; said: string }>("mod_configs.save_setup", {
      profile: p.profile,
      path: o.setup.path,
      expect: o.setup.sha,
      form: formOf(values),
    });
    await saveSetupDone(saved);
  }

  async function saveSetupText() {
    const saved = await ops.run<{ name: string; overhaul_id: string; said: string }>("mod_configs.save_setup", {
      profile: p.profile,
      path: read?.path,
      expect: read?.sha,
      text,
    });
    await saveSetupDone(saved);
  }

  async function saveSetupDone(saved: { overhaul_id: string; said: string }) {
    say(saved.said);
    p.onTreeChanged(node.key);
    // the saved setup, installed again in the profiles using it (a job: its toasts follow it)
    try {
      await ops.run("mod_configs.apply_setup", { profile: p.profile, overhaul_id: saved.overhaul_id });
    } catch (e) {
      if ((e as { problem?: { code?: string } }).problem?.code === "busy") refuse("", words.savedNotApplied ?? "");
      else failed(e, words);
    }
  }

  const saveRef = useRef(save);
  useEffect(() => {
    saveRef.current = save;
  });
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.ctrlKey && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void saveRef.current();
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  // ---- the form's model
  const formModel: FormModel | null = read?.has_form
    ? {
        sections: read.sections,
        valueOf: (r) => pending[key(r.section, r.key)]?.value ?? r.value,
        edited: (r) => key(r.section, r.key) in pending,
        onChange: (r, v) => setValue(r.section, r.key, v),
        onReset: (r) => setValue(r.section, r.key, r.default ?? r.value),
        words,
      }
    : null;
  const ovModel: FormModel | null =
    ov && values
      ? {
          sections: [],
          valueOf: (r: Row) => shownValue(values, r.key, r.value),
          edited: () => false,
          onChange: (r, v) => setValues((cur) => (cur ? patchValues(cur, r.key, v) : cur)),
          words,
        }
      : null;

  function resetAll() {
    for (const s of read?.sections ?? []) {
      for (const r of s.rows) if (r.kind !== "readonly" && r.default != null && r.default !== r.value) setValue(r.section, r.key, r.default);
    }
  }

  // ---- Seamless Co-op: sharing with a friend
  const copy = () =>
    ops.run<{ text: string }>("mod_configs.share", { ini: read?.path }).then(
      (r) => navigator.clipboard.writeText(r.text).then(() => say(words.copied ?? ""), (e) => refuse(words.notSavedTitle ?? "", message(e))),
      (e) => failed(e, words),
    );
  const takeShared = (shared: string) =>
    p.guard(() => {
      ops.plan("mod_configs.paste", { ini: read?.path, text: shared }).then(
        (offer) =>
          dialogs.offerPlan(offer, (ok) => {
            if (!ok) return;
            const n = offer.prompt.kind === "confirm" ? offer.prompt.changes.length : 0;
            say((n === 1 ? words.savedOne : words.savedMany)?.replace("{n}", String(n)) ?? "");
            p.onReload();
          }),
        (e) => failed(e, words),
      );
    });
  const paste = () =>
    navigator.clipboard.readText().then(takeShared, (e) => refuse(words.notSettingsTitle ?? "", message(e)));
  const saveAs = () =>
    ops.run<{ text: string }>("mod_configs.share", { ini: read?.path }).then((r) => {
      const url = URL.createObjectURL(new Blob([r.text], { type: "text/plain" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "seamless-coop-settings.ini";
      a.click();
      URL.revokeObjectURL(url);
      say((words.savedFile ?? "").replace("{name}", a.download));
    }, (e) => failed(e, words));

  // ---- attaching a file to a mod
  const canAttach = !!node.target && !ov;
  const attached = !!file?.attached;
  async function attach() {
    const got = await pickFile(words.attach ?? "", "", []);
    if (!got || !node.target) return;
    ops.run("mod_configs.attach", { target: node.target, file: got }).then(() => p.onTreeChanged(node.key), (e) => failed(e, words));
  }
  const detach = () =>
    node.target && p.path
      ? void ops.run("mod_configs.detach", { target: node.target, file: p.path }).then(() => p.onTreeChanged(node.key), (e) => failed(e, words))
      : undefined;

  // ---- the header
  const own = node.kind === "overhaul" ? node.files[0]?.path : undefined;
  const crumb = !p.path || (node.kind === "overhaul" && p.path === own) ? tree.name : `${tree.name} / ${file?.name ?? p.path.split(/[\\/]/).pop()}`;
  const shownPath = p.path ?? ov?.setup.folder ?? "";
  const toggleText = (on: boolean) =>
    p.guard(() => {
      setText(read?.text ?? "");
      setPending({});
      setEditText(on);
    });

  const body = (() => {
    switch (kind) {
      case "form":
        return formModel ? <ConfigForm model={formModel} /> : null;
      case "seamless":
        return (
          <SeamlessPanel
            model={{
              view: read?.seamless_view ?? {},
              get: (s, k, d) => pending[key(s, k)]?.value ?? d,
              set: setValue,
              setPreset: (name) => {
                const keys = (read?.seamless_view.scaling ?? []).map((x) => x.key);
                (read?.seamless_view.presetValues?.[name] ?? []).forEach((v, i) => keys[i] && setValue("SCALING", keys[i], String(v)));
              },
              words,
              copy: () => void copy(),
              paste: () => void paste(),
              load: takeShared,
              saveAs: () => void saveAs(),
            }}
          >
            {formModel && formModel.sections.length > 0 ? (
              <section className="flex flex-col gap-2" aria-label={words.otherSettings}>
                <h3 className="font-semibold text-body">{words.otherSettings}</h3>
                <ConfigForm model={formModel} />
              </section>
            ) : null}
          </SeamlessPanel>
        );
      case "overhaul":
        return ovView && ovModel ? <OverhaulSetup view={ovView} model={ovModel} /> : null;
      case "readme":
        return /\.(md|markdown)$/i.test(p.path ?? "") ? (
          <div data-testid="readmeView" className="flex flex-col gap-2 text-body [&_a]:text-accent [&_code]:font-mono [&_h1]:text-section [&_h2]:text-row [&_li]:ml-5 [&_li]:list-disc">
            <Markdown skipHtml>{read?.text ?? ""}</Markdown>
          </div>
        ) : (
          <pre data-testid="readmeView" className="whitespace-pre-wrap font-mono text-body">{read?.text}</pre>
        );
      case "text":
        return (
          <>
            {read && !read.has_form && read.form_note && !ov ? (
              <p data-testid="formNote" className="mb-2 text-caption text-text-secondary">
                {read.form_note}
              </p>
            ) : null}
            <CodeEditor
              value={text}
              onChange={setText}
              fileName={p.path ?? "x.txt"}
              check={check}
              aria-label={crumb}
              labels={{ wrap: words.wrapLines ?? "Wrap long lines", lineColumn: (l, c) => (words.lineColumn ?? "Line {line}, column {column}").replace("{line}", String(l)).replace("{column}", String(c)) }}
              className="h-[60vh]"
            />
          </>
        );
      default:
        return null;
    }
  })();

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="min-w-0 flex-1 truncate font-semibold text-row text-title">{crumb}</h2>
        {canAttach ? (
          <Button className="h-7 px-2 text-caption" onClick={() => void attach()}>
            <Link2 aria-hidden className="size-4" />
            {words.attach}
          </Button>
        ) : null}
        {attached ? (
          <Button className="h-7 px-2 text-caption" onClick={detach}>
            {words.detach}
          </Button>
        ) : null}
        {canEditText ? (
          <label className="flex items-center gap-2 text-caption text-text-secondary">
            {words.editAsText}
            <Switch.Root
              checked={editText}
              onCheckedChange={toggleText}
              className="h-5 w-10 shrink-0 rounded-pill border border-border-edge bg-fill-input outline-none focus-visible:ring-2 focus-visible:ring-glow-ring data-[state=checked]:border-gold-line data-[state=checked]:bg-gold-fill-top"
            >
              <Switch.Thumb className="block size-3.5 translate-x-0.5 rounded-pill bg-text-secondary transition-transform duration-toggle data-[state=checked]:translate-x-[22px] data-[state=checked]:bg-accent" />
            </Switch.Root>
          </label>
        ) : null}
        {tree.action !== "" && !(ov?.new) ? (
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <Button aria-label={words.more} title={words.more} className="h-7 min-w-0 px-2">
                <MoreHorizontal aria-hidden className="size-4" />
              </Button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content align="end" className="z-50 min-w-56 rounded-card border border-border-edge bg-surface-card p-1 shadow-xl">
                <DropdownMenu.Item
                  className="flex h-[var(--menu-row-h)] cursor-default items-center gap-2 rounded-control px-3 text-body outline-none data-[highlighted]:bg-fill-ghost-hover"
                  onSelect={() => p.onOverhaulAction(tree.action as "setUp" | "turnOff")}
                >
                  {tree.action === "setUp" ? <Plus aria-hidden className="size-4" /> : <Trash2 aria-hidden className="size-4" />}
                  {tree.action === "setUp" ? words.setUpOverhaul : words.turnOffOverhaul}
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        ) : null}
      </div>
      {shownPath ? <p className="truncate text-caption text-text-secondary" title={shownPath}>{shownPath}</p> : null}
      {diskChanged ? (
        <div role="alert" data-testid="diskChangedBar" className="mt-2 flex items-center gap-3 rounded-card border border-status-warning bg-status-warning-bg px-3 py-2 text-caption">
          <span className="flex-1">{words.diskChanged}</span>
          <Button className="h-7 min-w-0 px-2" onClick={p.onReload}>
            {words.reload}
          </Button>
        </div>
      ) : null}
      <div className="mt-3 min-h-0 flex-1 pb-4">{body}</div>
      <div className={cn("sticky bottom-0 -mx-1 flex items-center gap-2 border-t border-border-hairline bg-surface-page px-1 py-3")}>
        <p role="status" className={cn("min-w-0 flex-1 truncate text-caption", dirty ? "text-accent" : "text-text-secondary")}>
          {changeText}
        </p>
        <Button variant="primary" disabled={!dirty || busy} onClick={() => void save()}>
          {words.save}
        </Button>
        <Button disabled={!dirty} onClick={p.onReload}>
          {words.discard}
        </Button>
        {kind === "form" ? <Button onClick={resetAll}>{words.resetAll}</Button> : null}
      </div>
    </div>
  );
}
