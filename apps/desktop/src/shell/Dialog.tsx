import { Dialog as D } from "radix-ui";
import type { ReactNode } from "react";

/** A plain modal for the shell's own forms (generic: title, description, body, footer buttons). */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
}: {
  open: boolean;
  onClose(): void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <D.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-fill-scrim" />
        <D.Content className="fixed top-1/2 left-1/2 z-50 flex w-[min(480px,calc(100vw-48px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-overlay border border-border-edge bg-surface-card p-6 shadow-xl">
          <D.Title className="text-section font-semibold text-title">{title}</D.Title>
          <D.Description className={description ? "text-body text-text-secondary" : "sr-only"}>{description ?? title}</D.Description>
          {children}
          {footer ? <div className="mt-2 flex flex-wrap justify-end gap-2">{footer}</div> : null}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
