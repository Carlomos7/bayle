import { useMemo } from "react";
import type { PlanOffer, PromptWords } from "@/api/types";
import { usePrompts } from "@/components/PromptHost";
import { failed } from "./ops";

export interface Dialogs {
  /** Show a plan offer; its answer is posted, then `after` runs (not for a cancel or a refusal, which is only told). */
  offerPlan(offer: PlanOffer, after?: (ok: boolean) => void): void;
  /** Ask a yes/no of the page itself (no backend plan): `then` runs on yes, `otherwise` on no. */
  confirm(words: PromptWords, then: () => void, otherwise?: () => void): void;
  /** A tick list of the page's own: `then` gets the ticked rows. */
  pick(words: PromptWords, then: (ticked: number[]) => void): void;
}

/** The page's questions, all through the shared PromptHost; a refused plan answer is worded by this page (`failed`). */
export function useDialogs(words: Record<string, string>): Dialogs {
  const prompts = usePrompts();
  return useMemo<Dialogs>(
    () => ({
      offerPlan: (offer, after) => prompts.offerPlan(offer, () => after?.(true), (e) => failed(e, words)),
      confirm: (w, then, otherwise) => void prompts.ask(w).then((a) => (a.ok ? then() : otherwise?.())),
      pick: (w, then) => void prompts.ask(w).then((a) => a.ok && then(a.ticked)),
    }),
    [prompts, words],
  );
}
