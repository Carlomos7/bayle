import { createContext, use, useCallback, useMemo, useState, type ReactNode } from "react";
import type { Answer, PlanOffer, PromptEventData, PromptWords } from "@/api/types";
import { useApi } from "@/api/backend";
import { PromptDialog } from "./PromptDialog";
import { sonnerToasts, type Toasts } from "./toasts";

interface Request {
  words: PromptWords;
  send: (answer: Answer) => Promise<unknown>;
}

interface Host {
  /** Show a backend prompt event; the answer goes to POST /v1/prompts/{prompt_id}. */
  askPrompt(prompt: PromptEventData): void;
  /** Show a plan offer; the answer goes to POST /v1/plans/{plan_id}. A refusal (no plan_id) is only told. */
  offerPlan(offer: PlanOffer): void;
}

const HostContext = createContext<Host | null>(null);

export function usePrompts(): Host {
  const host = use(HostContext);
  if (!host) throw new Error("usePrompts outside PromptHost");
  return host;
}

/** Owns the one open dialog (later prompts queue behind it) and posts the answers. */
export function PromptHost({ children, toasts = sonnerToasts }: { children: ReactNode; toasts?: Toasts }) {
  const api = useApi();
  const [queue, setQueue] = useState<Request[]>([]);
  const push = useCallback((r: Request) => setQueue((q) => [...q, r]), []);

  const host = useMemo<Host>(
    () => ({
      askPrompt: ({ prompt_id, ...words }) =>
        push({
          words: words as PromptWords,
          send: (a) => api.post(`/v1/prompts/${prompt_id}`, { choice: a.choice }),
        }),
      offerPlan: ({ plan_id, prompt }) =>
        push({
          words: prompt,
          send: (a) => (plan_id ? api.post(`/v1/plans/${plan_id}`, a) : Promise.resolve()),
        }),
    }),
    [api, push],
  );

  const head = queue[0];
  return (
    <HostContext value={host}>
      {children}
      {head ? (
        <PromptDialog
          // a new request is a new dialog, with fresh state
          key={queue.length + head.words.title}
          words={head.words}
          onAnswer={(answer) => {
            setQueue((q) => q.slice(1));
            // a cancelled plan is never posted: the offer simply expires
            if (head.words.kind === "refusal" || (head.words.kind !== "choose" && !answer.ok)) return;
            head.send(answer).catch(toasts.error);
          }}
        />
      ) : null}
    </HostContext>
  );
}
