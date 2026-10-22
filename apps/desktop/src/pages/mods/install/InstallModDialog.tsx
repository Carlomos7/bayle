import { Dialog } from "radix-ui";
import { useEffect, useId, useImperativeHandle, useRef, useState, type ReactNode, type Ref } from "react";
import type { Toasts } from "@/components/toasts";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import type { Choice, InstallView, Level } from "./types";
import { useInstallDraft, type Handoff } from "./useInstallDraft";

/** What the Mods page holds on to: open the dialog for a path, or let the player pick (a file, or a folder). */
export interface InstallModHandle {
  openInstall(source?: string, opts?: { folder?: boolean }): void;
}

const TONE: Record<string, string> = { error: "text-status-danger", warning: "text-status-warning" };
const tone = (level?: Level) => TONE[level ?? ""] ?? "text-text-secondary";
const input =
  "h-[var(--control-h)] w-full rounded-control border border-border-edge bg-surface-page px-2 text-body text-text-primary aria-[invalid=true]:border-status-danger";

function Check({ checked, onChange, children, disabled }: { checked: boolean; onChange: (on: boolean) => void; children: ReactNode; disabled?: boolean }) {
  return (
    <label className={cn("flex items-center gap-2 text-text-primary", disabled && "text-text-disabled")}>
      <input type="checkbox" className="size-4 accent-accent" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  );
}

/** A text box that keeps what is typed while it has focus (the view must not overwrite it) and sends it when asked. */
function Field({ label, value, onText, onCommit, error, describedBy }: { label: string; value: string; onText?: (v: string) => void; onCommit?: (v: string) => void; error?: boolean; describedBy?: string }) {
  const [local, setLocal] = useState(value);
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setLocal(value);
  }, [value]);
  return (
    <input
      aria-label={label}
      aria-invalid={error || undefined}
      aria-describedby={describedBy}
      className={input}
      value={local}
      onFocus={() => (focused.current = true)}
      onChange={(e) => {
        setLocal(e.target.value);
        onText?.(e.target.value);
      }}
      onBlur={(e) => {
        focused.current = false;
        if (e.target.value !== value) onCommit?.(e.target.value);
      }}
      onKeyDown={(e) => e.key === "Enter" && local !== value && onCommit?.(local)}
    />
  );
}

function Select({ label, value, choices, onPick, className }: { label: string; value: string; choices: Choice[]; onPick: (v: string) => void; className?: string }) {
  return (
    <select aria-label={label} className={cn(input, className)} value={value} onChange={(e) => onPick(e.target.value)}>
      {!choices.some((c) => c.value === value) ? <option value={value}>{value}</option> : null}
      {choices.map((c) => (
        <option key={c.value} value={c.value}>
          {c.label}
        </option>
      ))}
    </select>
  );
}

const Hint = ({ level, children }: { level?: Level; children?: ReactNode }) =>
  children ? <p className={cn("text-caption whitespace-pre-line", tone(level))}>{children}</p> : null;

type Edit = ReturnType<typeof useInstallDraft>["edit"];

function Body({ v, edit }: { v: InstallView; edit: Edit }) {
  const w = v.words;
  const ids = { id: useId() };
  const reg = v.regulation;
  const go = (field: Parameters<Edit>[0]["field"], rest: Omit<Parameters<Edit>[0], "field"> = {}) => edit({ field, ...rest });
  return (
    <div className="flex flex-col gap-3">
      {v.variants.length > 1 ? (
        <div className="flex flex-col gap-1">
          <span className="text-caption text-text-secondary">{w.variantLabel}</span>
          <Select label={w.variantLabel ?? ""} value={v.variant} choices={v.variants.map((x) => ({ value: x, label: x }))} onPick={(x) => go("variant", { text: x })} />
        </div>
      ) : null}

      <div className={cn("grid gap-3", v.idShown ? "grid-cols-2" : "grid-cols-1")}>
        <div className="flex flex-col gap-1">
          <span className="font-semibold text-text-primary">{v.nameLabel}</span>
          <Field label={v.nameLabel} value={v.name} error={v.nameError} onText={(t) => go("name", { text: t })} />
          <Hint>{v.where}</Hint>
        </div>
        {v.idShown ? (
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-text-primary">{w.id}</span>
            <Field label={w.id ?? "Id"} value={v.id} error={v.idError} describedBy={ids.id} onText={(t) => go("id", { text: t })} />
            <p id={ids.id} className={cn("text-caption", v.idError ? "text-status-danger" : "text-text-secondary")}>{v.idNote}</p>
          </div>
        ) : null}
      </div>

      {v.items.length > 0 ? (
        <fieldset className="flex flex-col gap-1">
          <legend className="font-semibold text-text-primary">{w.whatToInstall}</legend>
          {v.items.map((it) => (
            <div key={it.name} className="flex items-center justify-between gap-3" title={it.tip || undefined}>
              <Check checked={it.on} onChange={(on) => go("tick", { key: it.name, on })}>{it.name}</Check>
              <span className="text-caption text-text-secondary">{it.what} · {it.size}</span>
            </div>
          ))}
          <Hint>{w.itemsNote}</Hint>
        </fieldset>
      ) : null}

      {reg.shown ? (
        <section className="flex flex-col gap-1" aria-label={w.regulation}>
          <h3 className="font-semibold text-text-primary">{w.regulation}</h3>
          <Hint>{reg.about}</Hint>
          {reg.placeShown ? (
            <Select
              label={w.regulation ?? ""}
              value={String(reg.placeIndex ?? 0)}
              choices={(reg.places ?? []).map((p, i) => ({ value: String(i), label: p }))}
              // the last entry is "Last"; any earlier one is "before the package that must stay last"
              onPick={(i) => go("place_last", { on: Number(i) === (reg.places?.length ?? 1) - 1 })}
            />
          ) : null}
          {reg.rebuildShown ? <Check checked={!!reg.rebuild} onChange={(on) => go("rebuild", { on })}>{reg.rebuildText}</Check> : null}
          <Hint level={reg.effectLevel}>{reg.effect}</Hint>
          <Hint>{reg.notes}</Hint>
        </section>
      ) : null}

      {v.library.shown ? (
        <section className="flex flex-col gap-1">
          <Hint>{v.library.text}</Hint>
          {(v.library.options ?? []).map((o) => (
            <Check key={o.key} checked={v.library.choice === o.key} onChange={() => go("library", { text: o.key })}>{o.text}</Check>
          ))}
        </section>
      ) : null}

      {v.last.shown ? (
        <section className="flex flex-col gap-1">
          <Hint level={v.last.level}>{v.last.text}</Hint>
          <Check checked={!!v.last.on} onChange={(on) => go("after_last", { on })}>{v.last.check}</Check>
        </section>
      ) : null}

      {v.option.shown ? (
        <section className="flex flex-col gap-1 border-t border-border-edge pt-3">
          <Check checked={!!v.option.ticked} disabled={v.option.locked} onChange={(on) => go("overhaul", { on })}>{w.overhaulOption}</Check>
          <div className="flex items-start gap-2 pl-6">
            {v.option.badge ? (
              <span className={cn("rounded-tag border border-border-tag px-2 text-caption", v.option.badgeLevel === "success" ? "text-status-success" : "text-status-warning")}>
                {v.option.badge}
              </span>
            ) : null}
            <Hint level={v.option.level}>{v.option.text}</Hint>
          </div>
        </section>
      ) : null}
      <Hint>{v.option.hint}</Hint>

      {v.overhaul.shown ? (
        <section className="flex flex-col gap-1" aria-label="Overhaul install">
          {!v.overhaul.ready ? <p className="text-caption text-text-secondary">{w.working}</p> : null}
          {(v.overhaul.lines ?? []).map((l) => <p key={l}>{l}</p>)}
          {(v.overhaul.notes ?? []).map((n) => <Hint key={n}>{n}</Hint>)}
          {(v.overhaul.refusals ?? []).map((r) => (
            <p key={r} role="alert" className="rounded-control border border-status-danger bg-status-danger-bg p-2 text-status-danger">{r}</p>
          ))}
        </section>
      ) : null}

      {v.natives.map((n) => (
        <fieldset key={n.file} className="flex flex-col gap-1">
          <legend className="text-text-primary">{n.file}</legend>
          <Check checked={!!n.load_early} onChange={(on) => go("native", { key: n.file, kind: "early", text: String(on) })}>{w.dllEarly}</Check>
          <Check checked={!!n.after_others} onChange={(on) => go("native", { key: n.file, kind: "after", text: String(on) })}>{w.dllAfter}</Check>
          <span className="text-caption text-text-secondary">{w.dllInit}</span>
          <Field label={`${n.file}: ${w.dllInit}`} value={n.initializer ?? ""} onCommit={(t) => go("native", { key: n.file, kind: "init", text: t })} />
        </fieldset>
      ))}

      {v.texts.map((t) => (
        <div key={t.file} className="flex items-center justify-between gap-3">
          <span className="min-w-0 flex-1">{t.label}</span>
          <Select label={t.label} value={t.table} choices={t.choices} onPick={(x) => go("table", { key: t.file, text: x })} className="w-[200px]" />
        </div>
      ))}

      {v.files.map((f) => (
        <div key={f.file} className="flex flex-col gap-1">
          <div className="flex items-center justify-between gap-3">
            <span className="min-w-0 flex-1 break-all">{f.file}</span>
            <Select label={f.file} value={f.action} choices={f.choices} onPick={(x) => go("file", { key: f.file, text: x })} className="w-[200px]" />
          </div>
          {f.action === "place" ? (
            // on its own line: the path is long and the row has no room for it
            <Field label={`${f.file}: game path`} value={f.target} onCommit={(t) => go("file", { key: f.file, text: `place:${t}` })} />
          ) : null}
        </div>
      ))}

      <Hint level={v.noteLevel}>{v.note}</Hint>
    </div>
  );
}

/**
 * The Install mod dialog (InstallModDialog.qml). The Mods page renders it once and calls ref.openInstall(source?):
 * with a path it installs that; without one it opens the Tauri picker. Files dropped on the window are taken too.
 * Several sources open one dialog after another.
 */
export function InstallModDialog({ profile, ref, toasts, onImportInstead }: {
  profile: string;
  ref?: Ref<InstallModHandle>;
  toasts?: Toasts;
  /** The download ships .me3 profiles: the Export / Import page takes over this unpacked folder. */
  onImportInstead?: (handoff: Handoff) => void;
}) {
  const s = useInstallDraft({ profile, toasts });
  useImperativeHandle(ref, () => ({ openInstall: (source, opts) => (source ? void s.add([source]) : void s.pick(!!opts?.folder)) }), [s.add, s.pick]); // eslint-disable-line react-hooks/exhaustive-deps
  const v = s.view;
  if (!v) return null;
  const w = v.words;
  return (
    <Dialog.Root open onOpenChange={(open) => !open && s.cancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-fill-scrim" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100vh-48px)] w-[min(640px,calc(100vw-48px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-overlay border border-border-edge bg-surface-card p-6 shadow-xl">
          <Dialog.Title className="text-section font-semibold text-title">{v.title}</Dialog.Title>
          <Dialog.Description className="text-body whitespace-pre-line text-text-secondary">{v.what}</Dialog.Description>
          <div className="min-h-0 flex-1 overflow-auto pr-1"><Body v={v} edit={s.edit} /></div>
          <div className="mt-2 flex flex-wrap justify-end gap-2">
            <Button variant="primary" disabled={!v.canInstall} onClick={() => void s.accept()}>
              {v.busy ? w.working : v.installText || w.install}
            </Button>
            {v.profilesInside && onImportInstead ? (
              <Button onClick={() => void s.importInstead().then((h) => h && onImportInstead(h))}>{w.importInstead}</Button>
            ) : null}
            <Dialog.Close asChild>
              <Button>{w.cancel}</Button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
