import { AlertDialog } from "radix-ui";
import { useId, useRef, useState } from "react";
import type { Answer, PromptWords } from "@/api/types";
import { Button } from "@/components/ui/button";

const NONE: Answer = { ok: false, option: false, choice: "", ticked: [] };

/**
 * The backend's prompt dict as a modal: confirm | pick | choose | refusal. Radix AlertDialog traps focus, restores it,
 * focuses Cancel first and closes on Escape; Escape answers like Cancel. Calls onAnswer exactly once.
 */
export function PromptDialog({ words, onAnswer }: { words: PromptWords; onAnswer: (answer: Answer) => void }) {
  const answered = useRef(false);
  const [option, setOption] = useState(words.kind === "confirm" && !!words.option_checked);
  const [ticked, setTicked] = useState<number[]>(words.kind === "pick" ? (words.ticked ?? []) : []);
  const rowsId = useId();

  const answer = (a: Partial<Answer>) => {
    if (answered.current) return;
    answered.current = true;
    onAnswer({ ...NONE, ...a });
  };
  // the choose prompt's cancel key (the Python side defaults to "cancel")
  const cancelKey = words.kind === "choose" ? (words.choices.find((c) => c.key === "cancel")?.key ?? "cancel") : "";
  const cancel = () => answer({ ok: false, choice: cancelKey });

  return (
    <AlertDialog.Root open onOpenChange={(open) => !open && cancel()}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-40 bg-fill-scrim" />
        <AlertDialog.Content className="fixed top-1/2 left-1/2 z-50 flex w-[min(480px,calc(100vw-48px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-overlay border border-border-edge bg-surface-card p-6 shadow-xl">
          <AlertDialog.Title className="text-section font-semibold text-title">{words.title}</AlertDialog.Title>
          <AlertDialog.Description asChild>
            <div className="flex flex-col gap-3 text-body text-text-secondary">{body()}</div>
          </AlertDialog.Description>
          <div className="mt-2 flex flex-wrap justify-end gap-2">{footer()}</div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );

  function body() {
    switch (words.kind) {
      case "confirm":
        return (
          <>
            {words.changes.length > 0 && (
              <ul className="list-disc pl-5">
                {words.changes.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            )}
            {words.detail ? <p>{words.detail}</p> : null}
            {words.warning ? <p className="text-status-warning">{words.warning}</p> : null}
            {words.safety ? <p>{words.safety}</p> : null}
            {words.option ? (
              <label className="flex items-center gap-2 text-text-primary">
                <input
                  type="checkbox"
                  className="size-4 accent-accent"
                  checked={option}
                  onChange={(e) => setOption(e.target.checked)}
                />
                {words.option}
              </label>
            ) : null}
          </>
        );
      case "pick":
        return (
          <>
            <p>{words.body}</p>
            <ul aria-label={words.title} className="flex max-h-64 flex-col gap-1 overflow-auto">
              {(words.rows ?? []).map((row, i) => (
                <li key={`${rowsId}-${i}`}>
                  <label className="flex items-center gap-2 text-text-primary">
                    <input
                      type="checkbox"
                      className="size-4 accent-accent"
                      checked={ticked.includes(i)}
                      onChange={(e) => setTicked((t) => (e.target.checked ? [...t, i].sort((a, b) => a - b) : t.filter((x) => x !== i)))}
                    />
                    {row}
                  </label>
                </li>
              ))}
            </ul>
          </>
        );
      case "choose":
        return (
          <>
            {words.lines.map((l) => (
              <p key={l}>{l}</p>
            ))}
            {words.warning ? <p className="text-status-warning">{words.warning}</p> : null}
            {words.safety ? <p>{words.safety}</p> : null}
          </>
        );
      case "refusal":
        return <p>{words.body}</p>;
    }
  }

  function footer() {
    switch (words.kind) {
      case "confirm":
        return (
          <>
            <AlertDialog.Cancel asChild>
              <Button onClick={cancel}>Cancel</Button>
            </AlertDialog.Cancel>
            <Button variant="primary" onClick={() => answer({ ok: true, option })}>
              {words.apply}
            </Button>
          </>
        );
      case "pick":
        return (
          <>
            <AlertDialog.Cancel asChild>
              <Button onClick={cancel}>Cancel</Button>
            </AlertDialog.Cancel>
            {words.none ? <Button onClick={() => answer({ ok: true, ticked: [] })}>{words.none}</Button> : null}
            <Button
              variant="primary"
              disabled={!words.none && ticked.length === 0}
              onClick={() => answer({ ok: true, ticked })}
            >
              {words.apply}
            </Button>
          </>
        );
      case "choose":
        return words.choices.map((c) => {
          const button = (
            <Button
              key={c.key}
              variant={c.role === "primary" ? "primary" : c.role === "danger" ? "danger" : "ghost"}
              onClick={() => answer({ ok: c.key !== cancelKey, choice: c.key })}
            >
              {c.label}
            </Button>
          );
          return c.key === cancelKey ? (
            <AlertDialog.Cancel key={c.key} asChild>
              {button}
            </AlertDialog.Cancel>
          ) : (
            button
          );
        });
      case "refusal":
        return (
          <AlertDialog.Cancel asChild>
            <Button variant="primary" onClick={cancel}>
              Close
            </Button>
          </AlertDialog.Cancel>
        );
    }
  }
}
