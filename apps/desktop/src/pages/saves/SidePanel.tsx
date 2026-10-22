import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import type { ReactNode } from "react";
import { IconButton } from "./ui";

/** A panel that slides in from the right over the page (Esc closes it, focus stays inside). */
export function SidePanel({
  title,
  width,
  onClose,
  closeLabel,
  children,
}: {
  title: string;
  width: number;
  onClose: () => void;
  closeLabel: string;
  children: ReactNode;
}) {
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-fill-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          style={{ width: `min(${width}px, 100vw)` }}
          className="fixed top-0 right-0 z-50 flex h-full flex-col gap-4 overflow-auto border-l border-border-edge bg-surface-card p-6 shadow-xl"
        >
          <div className="flex items-center gap-2">
            <Dialog.Title className="min-w-0 flex-1 truncate text-section font-semibold text-title">{title}</Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label={closeLabel} title={closeLabel} onClick={onClose}>
                <X className="size-4" aria-hidden />
              </IconButton>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
