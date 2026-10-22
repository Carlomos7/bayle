import { useCallback, useState, type ReactNode } from "react";
import type { Answer, PlanOffer, PromptWords } from "@/api/types";
import { PromptDialog } from "@/components/PromptDialog";
import { failed, useModOps } from "./ops";

interface Open {
  words: PromptWords;
  done: (answer: Answer) => void;
}

export interface Dialogs {
  /** Show a plan offer; its answer is posted, then `after(ok)` runs (not for a refusal, which is only told). */
  offerPlan(offer: PlanOffer, after?: (ok: boolean) => void): void;
  /** Ask a yes/no of the page itself (no backend plan): `then` runs on yes, `otherwise` on no. */
  confirm(words: PromptWords, then: () => void, otherwise?: () => void): void;
  /** A tick list of the page's own: `then` gets the ticked rows. */
  pick(words: PromptWords, then: (ticked: number[]) => void): void;
  /** Render this once, next to the page. */
  node: ReactNode;
}

/**
 * The page's one open dialog. Plans from this page are answered here (not through PromptHost) because the page acts on
 * the answer: it selects the new overhaul, or re-reads the Seamless Co-op file once the pasted settings are written.
 */
export function useDialogs(words: Record<string, string>): Dialogs {
  const ops = useModOps();
  const [open, setOpen] = useState<Open | null>(null);

  const offerPlan = useCallback<Dialogs["offerPlan"]>(
    (offer, after) =>
      setOpen({
        words: offer.prompt,
        done: (a) => {
          if (offer.prompt.kind === "refusal" || !offer.plan_id) return;
          if (!a.ok) return after?.(false);
          ops.answer(offer.plan_id, a).then(
            () => after?.(true),
            (e) => failed(e, words),
          );
        },
      }),
    [ops, words],
  );
  const confirm = useCallback<Dialogs["confirm"]>(
    (w, then, otherwise) => setOpen({ words: w, done: (a) => (a.ok ? then() : otherwise?.()) }),
    [],
  );
  const pick = useCallback<Dialogs["pick"]>((w, then) => setOpen({ words: w, done: (a) => a.ok && then(a.ticked) }), []);

  const node = open ? (
    <PromptDialog
      key={open.words.title}
      words={open.words}
      onAnswer={(a) => {
        setOpen(null);
        open.done(a);
      }}
    />
  ) : null;
  return { offerPlan, confirm, pick, node };
}
