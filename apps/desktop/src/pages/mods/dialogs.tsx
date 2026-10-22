import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useApi } from "@/api/backend";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useMods } from "./context";
import { fill, type LibraryRow, type OptionsView, type SettingsView, type Unlisted, type VersionRow } from "./types";
import { CheckRow, inputClass, ModalDialog } from "./ui";

/** A read of the current profile for a dialog; read again when the page is (a write changes what it shows). */
function useRead<T>(op: string, extra: object = {}, enabled = true) {
  const api = useApi();
  const { view } = useMods();
  return useQuery({
    queryKey: ["page", "mods", op, view.profile, extra],
    queryFn: () => api.post<T>(`/v1/ops/${op}`, { profile: view.profile, ...extra }),
    enabled,
  });
}

function Loading({ error }: { error?: unknown }) {
  return <p className="text-caption text-text-tertiary">{error ? String((error as Error).message) : "..."}</p>;
}

// ---------------------------------------------------------------- Mod options
type Deps = Record<string, boolean>; // id -> optional; a key present = listed

export function OptionsDialog({ index, onClose }: { index: number; onClose(): void }) {
  const { words } = useMods();
  const got = useRead<OptionsView>("mods.options", { index });
  const title = fill(words.optionsTitle, { name: got.data?.name ?? "" });
  return (
    <ModalDialog open onClose={onClose} title={title} width={560} footer={null}>
      {got.data ? <OptionsForm data={got.data} onClose={onClose} /> : <Loading error={got.error} />}
    </ModalDialog>
  );
}

function OptionsForm({ data, onClose }: { data: OptionsView; onClose(): void }) {
  const { view, words, actions, openConfigs } = useMods();
  const configs = view.configs[data.index] ?? [];
  const toMap = (list: { id: string; optional?: boolean }[]): Deps => Object.fromEntries(list.map((d) => [d.id, !!d.optional]));
  const [enabled, setEnabled] = useState(data.enabled);
  const [id, setId] = useState(data.id);
  const [after, setAfter] = useState<Deps>(toMap(data.load_after));
  const [before, setBefore] = useState<Deps>(toMap(data.load_before));
  const [optional, setOptional] = useState(data.optional);
  const [early, setEarly] = useState(data.load_early);
  const [initKind, setInitKind] = useState(data.init_kind);
  const [initValue, setInitValue] = useState(data.init_value);
  const [finalizer, setFinalizer] = useState(data.finalizer);
  const [last, setLast] = useState(data.overlay === 1);
  const [rebuildFile, setRebuildFile] = useState(data.rebuild_file);
  const list = (m: Deps) => Object.entries(m).map(([k, v]) => ({ id: k, optional: v }));
  const save = () => {
    actions.saveOptions(
      data.index,
      { enabled, id, loadAfter: list(after), loadBefore: list(before), optional, loadEarly: early, initKind, initValue, finalizer, overlay: data.overlay === -1 ? -1 : last ? 1 : 0, rebuildFile },
      data.name,
    );
    onClose();
  };
  const section = (title: string, map: Deps, set: (m: Deps) => void) => (
    <fieldset className="flex flex-col gap-1">
      <legend className="font-semibold text-title">{title}</legend>
      {data.others.length === 0 ? <p className="text-caption text-text-tertiary">{words.noDeps}</p> : null}
      {data.others.map((other) => {
        const listed = other in map;
        return (
          <div key={other} className="flex gap-4">
            <CheckRow
              checked={listed}
              onChange={(on) => {
                const m = { ...map };
                if (on) m[other] = m[other] ?? false;
                else delete m[other];
                set(m);
              }}
            >
              {other}
            </CheckRow>
            <CheckRow checked={listed && map[other] === true} disabled={!listed} onChange={(on) => set({ ...map, [other]: on })}>
              {words.optionalDep}
            </CheckRow>
          </div>
        );
      })}
    </fieldset>
  );
  const field = (label: string, control: React.ReactNode, help?: string) => (
    <label className="flex flex-col gap-1 text-body">
      <span>{label}</span>
      {control}
      {help ? <span className="text-caption text-text-tertiary">{help}</span> : null}
    </label>
  );
  return (
    <>
      <CheckRow checked={enabled} onChange={setEnabled}>
        {words.enabled}
      </CheckRow>
      {data.kind === "package" ? field(words.packageId ?? "", <input className={cn(inputClass, "w-full")} value={id} onChange={(e) => setId(e.target.value)} />) : null}
      {section(words.loadAfter ?? "", after, setAfter)}
      {section(words.loadBefore ?? "", before, setBefore)}
      {data.kind === "native" ? (
        <div className="flex flex-col gap-3">
          <CheckRow checked={optional} onChange={setOptional}>
            {words.optionalNative}
          </CheckRow>
          <div title={`${words.loadEarlyHelp}  (${words.loadEarlyTip})`}>
            <CheckRow checked={early} onChange={setEarly}>
              {words.loadEarly}
            </CheckRow>
          </div>
          {field(
            words.initializer ?? "",
            <div className="flex gap-2">
              <select aria-label={words.initializer} className={cn(inputClass, "w-44")} value={initKind} onChange={(e) => setInitKind(Number(e.target.value))}>
                <option value={0}>{words.initNone}</option>
                <option value={1}>{words.initFunction}</option>
                <option value={2}>{words.initDelay}</option>
              </select>
              {initKind !== 0 ? <input aria-label={initKind === 1 ? words.initFunction : words.initDelay} className={cn(inputClass, "w-40")} value={initValue} onChange={(e) => setInitValue(e.target.value)} /> : null}
            </div>,
            words.initializerHelp,
          )}
          {field(words.finalizer ?? "", <input className={cn(inputClass, "w-full")} value={finalizer} onChange={(e) => setFinalizer(e.target.value)} />)}
        </div>
      ) : null}
      {data.overlay !== -1 ? (
        <div className="flex flex-col gap-2">
          <div title={words.staysLastHelp}>
            <CheckRow checked={last} onChange={setLast}>
              {words.staysLastOption}
            </CheckRow>
          </div>
          {last ? field(words.rebuildFile ?? "", <input className={cn(inputClass, "w-full")} value={rebuildFile} onChange={(e) => setRebuildFile(e.target.value)} />) : null}
        </div>
      ) : null}
      {configs.length > 0 ? (
        <>
          <p className="text-caption text-text-tertiary">
            {words.configFiles}: {configs.join(", ")}
          </p>
          <Button
            className="self-start"
            onClick={() => {
              openConfigs(data.name);
              onClose();
            }}
          >
            {words.openOnModConfigs}
          </Button>
        </>
      ) : null}
      <div className="mt-2 flex justify-end gap-2">
        <Button variant="primary" onClick={save}>
          {words.save}
        </Button>
        <Button onClick={onClose}>{words.cancel}</Button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- Rename
export function RenameDialog({ index, onClose }: { index: number; onClose(): void }) {
  const api = useApi();
  const { view, words, actions } = useMods();
  const current = view.folders[index] ?? "";
  const [name, setName] = useState(current);
  const [debounced, setDebounced] = useState(current);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(name), 300); // the preview reads the profiles: not on every keystroke
    return () => clearTimeout(t);
  }, [name]);
  const preview = useQuery({
    queryKey: ["page", "mods", "rename-preview", view.profile, index, debounced],
    queryFn: () => api.post<{ ok: boolean; lines: string[]; refusals: string[] }>("/v1/ops/mods.rename_preview", { profile: view.profile, index, name: debounced }),
    placeholderData: keepPreviousData,
  });
  const stale = debounced !== name || preview.isFetching;
  const info = preview.data;
  const apply = () => {
    if (stale || !info?.ok) return;
    actions.rename(index, name.trim());
    onClose();
  };
  return (
    <ModalDialog
      open
      onClose={onClose}
      title={fill(words.renameTitle, { name: current })}
      subtitle={words.renameHint}
      width={520}
      footer={
        <>
          <Button variant="primary" disabled={stale || !info?.ok} onClick={apply}>
            {words.renameButton}
          </Button>
          <Button onClick={onClose}>{words.cancel}</Button>
        </>
      }
    >
      <input aria-label={words.renameNew} placeholder={words.renameNew} maxLength={80} autoFocus value={name} onFocus={(e) => e.currentTarget.select()} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && apply()} className={cn(inputClass, "w-full")} />
      {(info?.refusals ?? []).map((r) => (
        <p key={r} role="alert" className="text-caption text-status-danger">
          {r}
        </p>
      ))}
      {info?.ok ? info.lines.map((l) => <p key={l} className="text-caption text-text-tertiary">{l}</p>) : null}
    </ModalDialog>
  );
}

// ---------------------------------------------------------------- Profile settings
export function SettingsDialog({ onClose }: { onClose(): void }) {
  const { words, actions } = useMods();
  const got = useRead<SettingsView>("mods.settings");
  const v = got.data;
  const [save, setSave] = useState<string | null>(null);
  const [heap, setHeap] = useState<string | null>(null);
  const tri = ["start_online", "disable_arxan", "mem_patch"] as const;
  const row = (key: string, control: React.ReactNode) => (
    <div className="flex flex-col gap-1 border-b border-border-hairline py-3 last:border-b-0">
      <div className="flex items-center justify-between gap-4">
        <span id={`s-${key}`} className="text-body" title={words[`setting_${key}_tip`]}>
          {words[`setting_${key}`]}
        </span>
        {control}
      </div>
      <p className="text-caption text-text-tertiary">{words[`setting_${key}_help`]}</p>
    </div>
  );
  return (
    <ModalDialog open onClose={onClose} title={words.settingsTitle ?? ""} footer={<Button onClick={onClose}>{words.close}</Button>}>
      {!v ? (
        <Loading error={got.error} />
      ) : (
        <div className="flex flex-col">
          {row(
            "savefile",
            <input aria-labelledby="s-savefile" className={cn(inputClass, "w-60")} value={save ?? v.savefile} onChange={(e) => setSave(e.target.value)} onBlur={() => save !== null && save !== v.savefile && actions.setSetting("savefile", save)} />,
          )}
          {tri.map((key) =>
            row(
              key,
              <select aria-labelledby={`s-${key}`} className={cn(inputClass, "w-44")} value={v[key]} onChange={(e) => actions.setSetting(key, Number(e.target.value))}>
                <option value={0}>{words.meDefault}</option>
                <option value={1}>{words.on}</option>
                <option value={2}>{words.off}</option>
              </select>,
            ),
          )}
          {row(
            "mem_patch_heap_size",
            <input
              aria-labelledby="s-mem_patch_heap_size"
              type="number"
              min={0}
              max={65536}
              disabled={!v.heap_applies}
              className={cn(inputClass, "w-32")}
              value={heap ?? v.mem_patch_heap_size}
              onChange={(e) => setHeap(e.target.value)}
              onBlur={() => heap !== null && Number(heap) !== v.mem_patch_heap_size && actions.setSetting("mem_patch_heap_size", Number(heap))}
            />,
          )}
        </div>
      )}
    </ModalDialog>
  );
}

// ---------------------------------------------------------------- Versions
const when = (iso: string) => {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return Number.isNaN(d.getTime()) ? iso : `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

export function VersionsDialog({ onClose }: { onClose(): void }) {
  const { words, actions } = useMods();
  const got = useRead<{ versions: VersionRow[] }>("mods.versions");
  const rows = got.data?.versions;
  return (
    <ModalDialog open onClose={onClose} title={words.versionsTitle ?? ""} subtitle={words.versionsBody} footer={<Button onClick={onClose}>{words.close}</Button>}>
      {!rows ? <Loading error={got.error} /> : null}
      {rows?.length === 0 ? <p className="text-caption text-text-tertiary">{words.noVersions}</p> : null}
      <ul>
        {rows?.map((r, i) => (
          <li key={r.path} className={cn("flex items-center gap-3 py-2", i < rows.length - 1 && "border-b border-border-hairline")}>
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="tabular-nums">{when(r.when)}</span>
              <span className="truncate text-caption text-text-secondary">{r.why}</span>
            </div>
            <Button
              aria-label={`${words.restore}: ${when(r.when)}`}
              onClick={() => {
                actions.restoreVersion(r.path);
                onClose();
              }}
            >
              {words.restore}
            </Button>
          </li>
        ))}
      </ul>
    </ModalDialog>
  );
}

// ---------------------------------------------------------------- Library
export function LibraryDialog({ onClose }: { onClose(): void }) {
  const { words, actions } = useMods();
  const got = useRead<{ rows: LibraryRow[] }>("mods.library");
  const rows = got.data?.rows;
  return (
    <ModalDialog
      open
      onClose={onClose}
      title={words.libraryTitle ?? ""}
      subtitle={words.libraryBody}
      width={600}
      footer={
        <>
          {rows?.length ? (
            <Button
              onClick={() => {
                onClose();
                actions.removeUnused();
              }}
            >
              {words.removeUnused}
            </Button>
          ) : null}
          <Button onClick={onClose}>{words.close}</Button>
        </>
      }
    >
      {!rows ? <Loading error={got.error} /> : null}
      {rows?.length === 0 ? <p className="text-caption text-text-tertiary">{words.libraryEmpty}</p> : null}
      {rows?.map((m) => (
        <div key={m.name} className="flex flex-col gap-0.5">
          <div className="flex items-baseline gap-2">
            <span className="text-row font-medium text-title">{m.name}</span>
            <span className="text-caption text-text-secondary">{m.size}</span>
          </div>
          {m.versions.map((v) => (
            <div key={v.title + v.usedBy} className="flex gap-2 text-caption">
              <span className="text-text-secondary">
                {v.title}  ·  {v.size}
              </span>
              <span className={v.unused ? "text-status-warning" : "text-text-secondary"}>{v.usedBy}</span>
            </div>
          ))}
        </div>
      ))}
    </ModalDialog>
  );
}

// ---------------------------------------------------------------- Add existing
export function AddExistingDialog({ kind, onClose }: { kind: string; onClose(): void }) {
  const { words, actions } = useMods();
  const got = useRead<Unlisted>("mods.unlisted", { kind });
  const rows = got.data?.folders;
  const [picked, setPicked] = useState<string[]>([]);
  return (
    <ModalDialog
      open
      onClose={onClose}
      title={(kind === "package" ? words.addPackagesTitle : words.addNativesTitle) ?? ""}
      subtitle={words.addBody}
      width={520}
      footer={
        <>
          <Button
            variant="primary"
            disabled={picked.length === 0}
            onClick={() => {
              actions.addPaths(kind, picked);
              onClose();
            }}
          >
            {words.add}
          </Button>
          <Button onClick={onClose}>{rows?.length === 0 ? words.close : words.cancel}</Button>
        </>
      }
    >
      {!rows ? <Loading error={got.error} /> : null}
      {rows?.length === 0 ? <p className="text-caption text-text-tertiary">{words.nothingToAdd}</p> : null}
      {rows?.map((r) => (
        <CheckRow key={r.path} checked={picked.includes(r.path!)} onChange={(on) => setPicked(on ? [...picked, r.path!] : picked.filter((p) => p !== r.path))}>
          {r.label}
        </CheckRow>
      ))}
    </ModalDialog>
  );
}

// ---------------------------------------------------------------- unsaved text
export function UnsavedDialog({ canSave, onSave, onDiscard, onCancel }: { canSave: boolean; onSave(): void; onDiscard(): void; onCancel(): void }) {
  const { words } = useMods();
  return (
    <ModalDialog
      open
      onClose={onCancel}
      title={words.unsavedTitle ?? ""}
      subtitle={words.unsavedBody}
      width={460}
      footer={
        <>
          <Button variant="primary" disabled={!canSave} onClick={onSave}>
            {words.save}
          </Button>
          <Button variant="danger" onClick={onDiscard}>
            {words.discard}
          </Button>
          <Button onClick={onCancel}>{words.cancel}</Button>
        </>
      }
    >
      {null}
    </ModalDialog>
  );
}
