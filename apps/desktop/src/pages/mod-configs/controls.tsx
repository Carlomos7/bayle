import { Switch } from "radix-ui";
import { useId, type ReactNode } from "react";
import { cn } from "@/lib/cn";

const field =
  "h-[var(--control-h)] rounded-control border border-border-edge bg-surface-input px-2 text-body text-text-primary outline-none focus-visible:border-accent disabled:text-text-disabled";

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("overflow-hidden rounded-card border border-border-edge bg-surface-card", className)}>{children}</div>;
}

/** One setting: its name and help line on the left, the control on the right; the id ties the label to the control. */
export function FormRow({
  title,
  help,
  divider = true,
  testId,
  children,
}: {
  title: string;
  help?: string;
  divider?: boolean;
  testId?: string;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div data-testid={testId} className={cn("flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3", divider && "border-b border-border-hairline last:border-b-0")}>
      <div className="min-w-48 flex-1">
        <label htmlFor={id} className="block text-body text-text-primary">
          {title}
        </label>
        {help ? <p className="text-caption text-text-secondary">{help}</p> : null}
      </div>
      <div className="flex items-center gap-2">{children(id)}</div>
    </div>
  );
}

export function Toggle({ id, checked, onChange, label }: { id?: string; checked: boolean; onChange: (on: boolean) => void; label?: string }) {
  return (
    <Switch.Root
      id={id}
      aria-label={label}
      checked={checked}
      onCheckedChange={onChange}
      className="h-5 w-10 shrink-0 rounded-pill border border-border-edge bg-fill-input outline-none transition-colors duration-toggle focus-visible:ring-2 focus-visible:ring-glow-ring data-[state=checked]:border-gold-line data-[state=checked]:bg-gold-fill-top"
    >
      <Switch.Thumb className="block size-3.5 translate-x-0.5 rounded-pill bg-text-secondary transition-transform duration-toggle data-[state=checked]:translate-x-[22px] data-[state=checked]:bg-accent" />
    </Switch.Root>
  );
}

export function Choice({
  id,
  value,
  choices,
  onChange,
  label,
}: {
  id?: string;
  value: string;
  choices: { value: string; label: string }[];
  onChange: (value: string) => void;
  label?: string;
}) {
  // a value the list does not have stays choosable as it is
  const all = choices.some((c) => c.value === value) ? choices : [{ value, label: value }, ...choices];
  return (
    <select id={id} aria-label={label} className={cn(field, "w-52")} value={value} onChange={(e) => onChange(e.target.value)}>
      {all.map((c) => (
        <option key={c.value} value={c.value}>
          {c.label}
        </option>
      ))}
    </select>
  );
}

export function Spin({ id, value, lo, hi, onChange, label }: { id?: string; value: number; lo: number; hi: number; onChange: (value: number) => void; label?: string }) {
  return (
    <input
      id={id}
      aria-label={label}
      type="number"
      className={cn(field, "w-28")}
      min={lo}
      max={hi}
      value={Number.isFinite(value) ? value : 0}
      onChange={(e) => onChange(Math.min(hi, Math.max(lo, Number.parseInt(e.target.value, 10) || 0)))}
    />
  );
}

export function TextField({
  id,
  value,
  onChange,
  type = "text",
  label,
  className,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "password";
  label?: string;
  className?: string;
}) {
  return (
    <input
      id={id}
      aria-label={label}
      type={type}
      autoComplete="off"
      spellCheck={false}
      className={cn(field, "w-64", className)}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
