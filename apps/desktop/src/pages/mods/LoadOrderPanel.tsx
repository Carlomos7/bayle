import { Dialog } from "radix-ui";
import { RefreshCw, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useMods } from "./context";

const SHOWN_CLASHES = 12; // the snapshot carries every clash; the client cuts the list (load_order.SHOWN_CLASHES)

/** The Load order panel, a right-hand side panel: the mod that must stay last, the files two packages both ship, the entries me3 would refuse. */
export function LoadOrderPanel({ open, onClose }: { open: boolean; onClose(): void }) {
  const { view, words, actions } = useMods();
  const [showAll, setShowAll] = useState(false);
  const panel = view.load_order;
  const clashes = showAll ? panel.clashes : panel.clashes.slice(0, SHOWN_CLASHES);
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-fill-scrim" />
        <Dialog.Content className="fixed top-0 right-0 z-50 flex h-full w-[min(460px,100vw)] flex-col gap-4 overflow-auto border-l border-border-edge bg-surface-card p-6 shadow-xl">
          <div className="flex items-center">
            <Dialog.Title className="flex-1 text-section font-semibold text-title">{words.loadOrder}</Dialog.Title>
            <Dialog.Close asChild>
              <Button aria-label={words.close} className="min-w-0 px-2">
                <X aria-hidden className="size-4" />
              </Button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">{panel.title}</Dialog.Description>
          {panel.stays_last ? (
            <section className="flex flex-col gap-2">
              <h3 className="font-semibold text-title">{words.staysLast}</h3>
              <div className="flex items-center gap-2">
                <p className="flex-1 text-body">{panel.stays_last.text}</p>
                <Button disabled={!panel.stays_last.can_fix} onClick={actions.fixOrder}>
                  {words.fixOrder}
                </Button>
              </div>
            </section>
          ) : null}
          <section className="flex flex-col gap-2">
            <div className="flex items-center">
              <h3 className="flex-1 font-semibold text-title">{words.sharedFiles}</h3>
              <Button onClick={actions.refresh}>
                <RefreshCw aria-hidden className="size-4" />
                {words.rescan}
              </Button>
            </div>
            <p className="text-caption text-text-tertiary">{panel.error || panel.clash_note}</p>
            <ul className="flex flex-col">
              {clashes.map((c, i) => (
                <li key={c.path} className={cn("flex flex-col gap-0.5 py-2", i < clashes.length - 1 && "border-b border-border-hairline")}>
                  <span className="break-all">{c.path}</span>
                  <span className={cn("text-caption", c.lost ? "text-status-warning" : "text-text-secondary")}>
                    {c.winner}  {">"}  {c.losers}
                  </span>
                </li>
              ))}
            </ul>
            {panel.clash_total > SHOWN_CLASHES || showAll ? (
              <button type="button" className="self-start text-caption text-accent hover:underline" onClick={() => setShowAll(!showAll)}>
                {showAll ? words.showFewer : `${words.showAll} (${panel.clash_total})`}
              </button>
            ) : null}
          </section>
          <section className="flex flex-col gap-2">
            <h3 className="font-semibold text-title">{words.refused}</h3>
            {panel.refused.length === 0 ? <p className="text-caption text-text-tertiary">{words.nothingRefused}</p> : null}
            {panel.refused.map((r) => (
              <p key={r.name}>
                {r.name}  ·  {r.why}
              </p>
            ))}
          </section>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
