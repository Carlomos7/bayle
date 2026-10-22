import { AlertTriangle, Check, CheckCircle2, Info, X, XCircle, type LucideIcon } from "lucide-react";
import { Dialog, DropdownMenu } from "radix-ui";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

const LEVELS: Record<string, string> = {
  success: "border-status-success/40 bg-status-success-bg text-status-success",
  danger: "border-status-danger/40 bg-status-danger-bg text-status-danger",
  warning: "border-status-warning/40 bg-status-warning-bg text-status-warning",
  info: "border-status-info/40 bg-status-info-bg text-status-info",
  accent: "border-gold-line bg-smear-selected text-gold-text",
  muted: "border-border-tag text-text-secondary",
};
const ICONS: Record<string, LucideIcon> = { Accept: Check, Info, Cancel: X, Warning: AlertTriangle };

/** The presenter's tag / pill: a level and an optional Fluent icon name. */
export function Pill({ level, text, icon, tip, onClick, className }: { level?: string; text: string; icon?: string; tip?: string; onClick?: () => void; className?: string }) {
  const Icon = icon ? ICONS[icon] : undefined;
  const classes = cn(
    "inline-flex shrink-0 items-center gap-1 rounded-tag border px-2 py-0.5 text-tag",
    LEVELS[level ?? "muted"] ?? LEVELS.muted,
    onClick && "cursor-pointer hover:brightness-125",
    className,
  );
  const body = (
    <>
      {Icon ? <Icon aria-hidden className="size-3" /> : null}
      {text}
    </>
  );
  return onClick ? (
    <button type="button" title={tip} className={classes} onClick={onClick}>
      {body}
    </button>
  ) : (
    <span title={tip || undefined} className={classes}>
      {body}
    </span>
  );
}

const SEVERITY: Record<string, { icon: LucideIcon; tone: string }> = {
  success: { icon: CheckCircle2, tone: "border-status-success/40 bg-status-success-bg" },
  warning: { icon: AlertTriangle, tone: "border-status-warning/40 bg-status-warning-bg" },
  error: { icon: XCircle, tone: "border-status-danger/40 bg-status-danger-bg" },
  danger: { icon: XCircle, tone: "border-status-danger/40 bg-status-danger-bg" },
  info: { icon: Info, tone: "border-status-info/40 bg-status-info-bg" },
};

/** An InfoBar: severity, text, an optional action and a close. */
export function InfoBar({ severity, text, action, closable, onAction, onClose, closeLabel }: { severity: string; text: string; action?: string; closable: boolean; onAction(): void; onClose(): void; closeLabel: string }) {
  const { icon: Icon, tone } = SEVERITY[severity] ?? SEVERITY.info!;
  return (
    <div role="status" className={cn("flex items-center gap-3 rounded-card border px-4 py-2", tone)}>
      <Icon aria-hidden className="size-4 shrink-0" />
      <p className="min-w-0 flex-1 text-body text-text-primary">{text}</p>
      {action ? (
        <Button className="h-8 min-w-0" onClick={onAction}>
          {action}
        </Button>
      ) : null}
      {closable ? (
        <button type="button" aria-label={closeLabel} title={closeLabel} onClick={onClose} className="grid size-8 place-items-center rounded-control text-text-icon hover:bg-fill-ghost-hover">
          <X aria-hidden className="size-4" />
        </button>
      ) : null}
    </div>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("rounded-card border border-border-edge bg-surface-card", className)}>{children}</div>;
}

// ---- menus (Radix dropdown: arrow keys, type-ahead, Escape, focus return)
const itemClass =
  "flex h-[var(--menu-row-h)] cursor-default select-none items-center gap-3 rounded-control px-3 text-body text-text-primary outline-none data-[disabled]:text-text-disabled data-[highlighted]:bg-fill-hover";

export function Menu({ trigger, children, label }: { trigger: ReactNode; children: ReactNode; label: string }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content aria-label={label} align="end" sideOffset={4} className="z-50 min-w-52 rounded-overlay border border-border-edge bg-surface-card p-1 shadow-xl">
          {children}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
export function MenuItem({ children, onSelect, disabled, shortcut }: { children: ReactNode; onSelect(): void; disabled?: boolean; shortcut?: string }) {
  return (
    <DropdownMenu.Item className={itemClass} disabled={disabled} onSelect={onSelect}>
      <span className="flex-1">{children}</span>
      {shortcut ? <kbd className="text-caption text-text-tertiary">{shortcut}</kbd> : null}
    </DropdownMenu.Item>
  );
}
export function MenuCheck({ children, checked, onSelect }: { children: ReactNode; checked: boolean; onSelect(): void }) {
  return (
    <DropdownMenu.CheckboxItem className={itemClass} checked={checked} onSelect={onSelect}>
      <span className="flex-1">{children}</span>
      <DropdownMenu.ItemIndicator>
        <Check aria-hidden className="size-4" />
      </DropdownMenu.ItemIndicator>
    </DropdownMenu.CheckboxItem>
  );
}
export const MenuSep = () => <DropdownMenu.Separator className="my-1 h-px bg-border-hairline" />;
export const menuItemClass = itemClass;

// ---- dialogs
/** A modal over Radix Dialog: title, optional subtitle, body, footer buttons. Esc closes. */
export function ModalDialog({ open, onClose, title, subtitle, children, footer, width = 560 }: { open: boolean; onClose(): void; title: string; subtitle?: string; children: ReactNode; footer: ReactNode; width?: number }) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-fill-scrim" />
        <Dialog.Content
          style={{ width: `min(${width}px, calc(100vw - 48px))` }}
          aria-describedby={subtitle ? undefined : undefined}
          className="fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100vh-48px)] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-overlay border border-border-edge bg-surface-card p-6 shadow-xl"
        >
          <Dialog.Title className="text-section font-semibold text-title">{title}</Dialog.Title>
          {subtitle ? <Dialog.Description className="text-body text-text-secondary">{subtitle}</Dialog.Description> : <Dialog.Description className="sr-only">{title}</Dialog.Description>}
          <div className="flex min-h-0 flex-col gap-3 overflow-auto">{children}</div>
          <div className="mt-2 flex flex-wrap justify-end gap-2">{footer}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function CheckRow({ checked, onChange, children, disabled }: { checked: boolean; onChange(v: boolean): void; children: ReactNode; disabled?: boolean }) {
  return (
    <label className={cn("flex items-center gap-2 text-body", disabled ? "text-text-disabled" : "text-text-primary")}>
      <input type="checkbox" className="size-4 accent-accent" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  );
}

export const inputClass =
  "h-[var(--control-h)] rounded-control border border-border-edge bg-surface-input px-3 text-body text-text-primary placeholder:text-text-tertiary disabled:text-text-disabled";
