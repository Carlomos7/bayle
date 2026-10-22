import { Dialog } from "radix-ui";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useSavesOps, type NameAsk } from "./ops";

/** A name for a copy: save a copy of a live save, import a file, keep a backup, or rename a Library copy. */
export function NameDialog({ ask, onClose }: { ask: NameAsk | null; onClose: () => void }) {
  return (
    <Dialog.Root open={ask !== null} onOpenChange={(open) => !open && onClose()}>
      {ask ? <NameForm key={`${ask.mode}:${"path" in ask ? ask.path : ask.id}`} ask={ask} onClose={onClose} /> : null}
    </Dialog.Root>
  );
}

function NameForm({ ask, onClose }: { ask: NameAsk; onClose: () => void }) {
  const ops = useSavesOps();
  const { words } = ops.view;
  const [name, setName] = useState(ask.start);
  const text = {
    rename: [words.rename, "", (words.rename ?? "").replace("...", "")],
    import: [words.importAction, words.importHint, words.importButton],
    keep: [words.keep, words.keepHint, words.save],
    copy: [words.saveCopy, words.saveCopyHint, words.save],
  }[ask.mode];
  const apply = () => {
    const value = name.trim();
    if (!value) return;
    if (ask.mode === "rename") ops.renameCopy(ask.folder, ask.id, value);
    else if (ask.mode === "copy") ops.saveCopy(ask.path, value);
    else if (ask.mode === "import") ops.importFile(ask.path, value);
    else ops.keepAs(ask.path, value);
    onClose();
  };
  const field: ReactNode = (
    <input
      autoFocus
      aria-label={words.name}
      placeholder={words.name}
      maxLength={80}
      value={name}
      onFocus={(e) => e.currentTarget.select()}
      onChange={(e) => setName(e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && apply()}
      className="h-[var(--control-h)] w-full rounded-control border border-border-edge bg-surface-input px-3 text-body text-text-primary"
    />
  );
  return (
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-40 bg-fill-scrim" />
      <Dialog.Content className="fixed top-1/2 left-1/2 z-50 flex w-[min(480px,calc(100vw-48px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-overlay border border-border-edge bg-surface-card p-6 shadow-xl">
        <Dialog.Title className="text-section font-semibold text-title">{text?.[0]}</Dialog.Title>
        <Dialog.Description className="text-body text-text-secondary">{text?.[1]}</Dialog.Description>
        {field}
        <div className="mt-2 flex justify-end gap-2">
          <Dialog.Close asChild>
            <Button>{words.cancel}</Button>
          </Dialog.Close>
          <Button variant="primary" disabled={!name.trim()} onClick={apply}>
            {text?.[2]}
          </Button>
        </div>
      </Dialog.Content>
    </Dialog.Portal>
  );
}
