import type { InputHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

export const inputClass =
  "h-[var(--control-h)] rounded-control border border-border-edge bg-surface-input px-3 text-body text-text-primary disabled:text-text-disabled";

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2 rounded-overlay border border-border-edge bg-card-fill p-4", className)}>
      {children}
    </div>
  );
}

export function Field({ label, error, ...props }: { label: string; error?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="flex flex-col gap-1 text-caption text-text-secondary">
      <span className="flex gap-2">
        {label}
        {error ? <span className="text-status-danger">{error}</span> : null}
      </span>
      <input {...props} aria-invalid={error ? true : undefined} className={inputClass} />
    </label>
  );
}

export function Check({
  label,
  checked,
  onChange,
  disabled,
  children,
}: {
  label: ReactNode;
  checked: boolean;
  onChange?: (on: boolean) => void;
  disabled?: boolean;
  children?: ReactNode;
}) {
  return (
    <label className="flex items-center gap-2 text-body text-text-primary">
      <input
        type="checkbox"
        className="size-4 accent-accent"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange?.(e.target.checked)}
      />
      {label}
      {children}
    </label>
  );
}

/** A two-or-three way switch (native radios: arrow keys move, Tab leaves). */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: T | "";
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1">
      {options.map((o) => (
        <label
          key={o.value}
          className={cn(
            "inline-flex h-[var(--control-h)] cursor-pointer items-center rounded-control border px-4 text-body has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
            value === o.value
              ? "border-gold-line bg-gold-fill-top text-gold-text"
              : "border-border-edge text-text-primary hover:bg-fill-ghost-hover",
            disabled && "pointer-events-none text-text-disabled",
          )}
        >
          <input
            type="radio"
            className="sr-only"
            name={label}
            value={o.value}
            checked={value === o.value}
            disabled={disabled}
            onChange={() => onChange(o.value)}
          />
          {o.label}
        </label>
      ))}
    </div>
  );
}

export function Notes({ title, lines, danger }: { title?: string; lines: string[]; danger?: boolean }) {
  if (!lines.length) return null;
  return (
    <div className="flex flex-col gap-1" role={danger ? "alert" : undefined}>
      {title ? <h3 className="font-semibold text-body text-title">{title}</h3> : null}
      {lines.map((l, i) => (
        <p key={i} className={cn("text-body", danger ? "text-status-danger" : "text-text-secondary")}>
          {l}
        </p>
      ))}
    </div>
  );
}

export function Bar({ value, label }: { value: number; label: string }) {
  return <progress aria-label={label} className="h-2 w-full" value={value} max={100} />;
}
