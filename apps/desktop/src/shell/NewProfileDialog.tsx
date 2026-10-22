import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "./Dialog";
import { useShellOp } from "./ops";

export interface NewProfileOffer {
  name: string;
  seamless: boolean;
}

/** New profile (NewProfileDialog.qml): a name, and Seamless Co-op moved in from the game folder when it is there. */
export function NewProfileDialog({ offer, onClose }: { offer: NewProfileOffer | null; onClose(): void }) {
  return offer ? <Form offer={offer} onClose={onClose} /> : null;
}

function Form({ offer, onClose }: { offer: NewProfileOffer; onClose(): void }) {
  const op = useShellOp();
  const [name, setName] = useState(offer.name);
  const [include, setInclude] = useState(offer.seamless);
  const create = async () => {
    onClose();
    await op("shell.new_profile", { name: name.trim(), include_seamless: offer.seamless && include });
  };
  return (
    <Modal
      open
      onClose={onClose}
      title="New profile"
      description="A new profile for this game. Add mods to it from the Mods page."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!name.trim()} onClick={() => void create()}>
            Create
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) void create();
        }}
      >
        <input
          aria-label="Profile name"
          autoFocus
          maxLength={80}
          placeholder="Profile name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-[var(--control-h)] rounded-control border border-border-edge bg-surface-input px-3 text-body outline-none focus-visible:ring-2 focus-visible:ring-glow-ring"
        />
        {offer.seamless ? (
          <>
            <label className="flex items-center gap-2 text-body">
              <input type="checkbox" className="size-4 accent-accent" checked={include} onChange={(e) => setInclude(e.target.checked)} />
              Include Seamless Co-op from the game folder (moved into the new profile)
            </label>
            {include ? (
              <p className="text-caption text-status-warning">
                Seamless Co-op's own launcher goes to the Recycle Bin: start the game from here instead.
              </p>
            ) : null}
          </>
        ) : null}
      </form>
    </Modal>
  );
}
