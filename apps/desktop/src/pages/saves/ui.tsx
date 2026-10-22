import { Ellipsis } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { Level } from "./types";

/** Small primitives of the Saves page (candidates to lift into components/ui once a second page needs them). */
export function Pill({ level, children }: { level?: Level | "accent"; children: ReactNode }) {
  const tone =
    level === "success"
      ? "bg-status-success-bg text-status-success"
      : level === "warning"
        ? "bg-status-warning-bg text-status-warning"
        : level === "danger"
          ? "bg-status-danger-bg text-status-danger"
          : level === "accent"
            ? "bg-accent-soft text-gold-text"
            : "bg-fill-identity text-text-secondary";
  return (
    <span className={cn("inline-flex h-5 shrink-0 items-center rounded-pill px-2 text-tag font-medium", tone)}>
      {children}
    </span>
  );
}

export function Card({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cn("rounded-overlay border border-border-edge bg-surface-card", className)}
      {...props}
    />
  );
}

export const sectionTitle = "text-section font-semibold text-title";
export const hint = "text-caption text-text-secondary";

export function IconButton({ className, ...props }: ComponentProps<"button">) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-control text-text-icon hover:bg-fill-ghost-hover disabled:pointer-events-none disabled:text-text-disabled",
        className,
      )}
      {...props}
    />
  );
}

/** A "more" button with a menu. `label` names the button (it has no text). */
export function Menu({ label, children, disabled }: { label: string; children: ReactNode; disabled?: boolean }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <IconButton aria-label={label} title={label} disabled={disabled}>
          <Ellipsis className="size-4" aria-hidden />
        </IconButton>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" className={menuPanel}>
          {children}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

const menuPanel =
  "z-50 max-h-80 min-w-52 overflow-auto rounded-overlay border border-border-edge bg-surface-card p-1 shadow-xl";
const menuItem =
  "flex h-8 cursor-default items-center gap-2 rounded-control px-2 text-body outline-none data-[disabled]:text-text-disabled data-[highlighted]:bg-fill-ghost-hover";

export function MenuItem({
  onSelect,
  disabled,
  danger,
  children,
}: {
  onSelect: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: ReactNode;
}) {
  return (
    <DropdownMenu.Item
      className={cn(menuItem, danger && "text-status-danger")}
      disabled={disabled}
      onSelect={onSelect}
    >
      {children}
    </DropdownMenu.Item>
  );
}

export function MenuSub({ label, children }: { label: string; children: ReactNode }) {
  return (
    <DropdownMenu.Sub>
      <DropdownMenu.SubTrigger className={menuItem}>{label}</DropdownMenu.SubTrigger>
      <DropdownMenu.Portal>
        <DropdownMenu.SubContent className={menuPanel}>{children}</DropdownMenu.SubContent>
      </DropdownMenu.Portal>
    </DropdownMenu.Sub>
  );
}

export const MenuSeparator = () => <DropdownMenu.Separator className="my-1 h-px bg-border-hairline" />;

/** A warning or error band (the Qt InfoBar). */
export function InfoBar({ severity, children }: { severity: "warning" | "error"; children: ReactNode }) {
  return (
    <div
      role={severity === "error" ? "alert" : "status"}
      className={cn(
        "rounded-control border px-3 py-2 text-body",
        severity === "error"
          ? "border-status-danger bg-status-danger-bg text-status-danger"
          : "border-status-warning bg-status-warning-bg text-status-warning",
      )}
    >
      {children}
    </div>
  );
}
