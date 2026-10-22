import { useId, useState, type ReactNode } from "react";
import type { SettingSpec } from "@bayle/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { W } from "./words";

export const input =
  "h-[var(--control-h)] rounded-control border border-border-edge bg-surface-input px-2 text-body text-text-primary disabled:text-text-disabled";

export function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col rounded-card border border-border-edge bg-surface-card">
      <h2 id={id} className="border-b border-border-edge px-4 py-3 font-semibold text-row text-title">
        {title}
      </h2>
      <div className="flex flex-col divide-y divide-border-edge">{children}</div>
    </section>
  );
}

/** A labelled row: the title and its help on the left, the control (and a refusal sentence) on the right. */
export function Row({
  id,
  errorId,
  title,
  help,
  error,
  children,
}: {
  id?: string;
  errorId?: string;
  title: string;
  help?: string;
  error?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start gap-x-6 gap-y-2 px-4 py-3">
      <div className="min-w-56 flex-1">
        <label htmlFor={id} className="text-body text-text-primary">
          {title}
        </label>
        {help ? <p className="text-caption text-text-secondary">{help}</p> : null}
        {error ? (
          <p id={errorId} role="alert" className="text-caption text-status-danger">
            {error}
          </p>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

export type Value = boolean | number | string;

/** Any setting by its spec: the kind decides the control. `choices` carries the labels of a choice. */
export function SettingControl({
  spec,
  value,
  label,
  help,
  error,
  choices,
  placeholder,
  disabled,
  onChange,
  extra,
}: {
  spec: SettingSpec;
  value: Value;
  label: string;
  help?: string;
  error?: string;
  choices?: { key: string; label: string }[];
  placeholder?: string;
  disabled?: boolean;
  onChange: (value: Value) => void;
  extra?: ReactNode;
}) {
  const id = useId();
  const describedBy = error ? `${id}-err` : undefined;
  let control: ReactNode;
  if (spec.kind === "switch")
    control = (
      <input
        id={id}
        type="checkbox"
        role="switch"
        className="size-5 accent-gold-line"
        checked={value === true}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  else if (spec.kind === "choice")
    control = (
      <select id={id} className={input} value={String(value)} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {(choices ?? spec.choices?.map((c) => ({ key: c, label: c })) ?? []).map((c) => (
          <option key={c.key} value={c.key}>
            {c.label}
          </option>
        ))}
      </select>
    );
  else
    control = (
      <DraftControl id={id} spec={spec} value={value} placeholder={placeholder} disabled={disabled} invalid={!!error} describedBy={describedBy} onChange={onChange} />
    );
  return (
    <Row id={id} errorId={describedBy} title={label} help={help} error={error}>
      {control}
      {extra}
    </Row>
  );
}

/** Number and location: typed text saved on Enter or leaving the field (a half-typed path is never sent). */
function DraftControl({
  id,
  spec,
  value,
  placeholder,
  disabled,
  invalid,
  describedBy,
  onChange,
}: {
  id: string;
  spec: SettingSpec;
  value: Value;
  placeholder?: string;
  disabled?: boolean;
  invalid: boolean;
  describedBy?: string;
  onChange: (value: Value) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? String(value);
  const commit = () => {
    if (draft === null) return;
    setDraft(null);
    if (draft === String(value)) return;
    onChange(spec.kind === "number" ? Number(draft) : draft);
  };
  return (
    <input
        id={id}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        className={cn(input, spec.kind === "number" ? "w-24" : "w-80 max-w-full")}
        type={spec.kind === "number" ? "number" : "text"}
        min={spec.low ?? undefined}
        max={spec.high ?? undefined}
        value={shown}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") setDraft(null);
        }}
      />
  );
}

export function PathButtons({
  onBrowse,
  onClear,
  onOpen,
  hasValue,
}: {
  onBrowse: () => void;
  onClear: () => void;
  onOpen: () => void;
  hasValue: boolean;
}) {
  return (
    <>
      <Button onClick={onBrowse}>{W.browse}</Button>
      <Button onClick={onClear} disabled={!hasValue}>
        {W.clear}
      </Button>
      <Button onClick={onOpen}>{W.openFolder}</Button>
    </>
  );
}
