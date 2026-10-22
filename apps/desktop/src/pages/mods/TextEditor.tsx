import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useApi } from "@/api/backend";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useMods } from "./context";

/** Edit as text: the raw .me3, the first parse error inline, Save (kept as a Version) / Discard. */
export function useTextEdit(active: boolean) {
  const api = useApi();
  const { view, actions } = useMods();
  const [draft, setDraft] = useState<string | null>(null); // null: untouched
  const [savedNow, setSavedNow] = useState<string | null>(null); // what a save wrote, until the page is read again
  const [debounced, setDebounced] = useState("");
  const read = useQuery({
    queryKey: ["page", "mods", "text", view.profile],
    queryFn: () => api.post<{ text: string; crlf: boolean }>("/v1/ops/mods.text", { profile: view.profile }),
    enabled: active,
    gcTime: 0,
  });
  const saved = savedNow ?? read.data?.text ?? "";
  const text = draft ?? saved;
  useEffect(() => {
    const t = setTimeout(() => setDebounced(text), 250);
    return () => clearTimeout(t);
  }, [text]);
  // the parse gate, asked once per text
  const check = useQuery({
    queryKey: ["page", "mods", "check", debounced],
    queryFn: () => api.post<{ problem: string }>("/v1/ops/mods.check_text", { text: debounced }),
    enabled: active && debounced !== "",
    placeholderData: keepPreviousData,
  });
  return {
    text,
    setText: setDraft,
    dirty: text !== saved,
    error: check.data?.problem ?? "",
    save: () =>
      actions.saveText(text, read.data?.crlf ?? false, () => {
        setSavedNow(text);
      }),
    discard: () => setDraft(null),
    /** Back to the rows: the next time the editor opens it reads the file again. */
    reset: () => {
      setDraft(null);
      setSavedNow(null);
    },
  };
}

export function TextEditor({ edit }: { edit: ReturnType<typeof useTextEdit> }) {
  const { words } = useMods();
  return (
    <div className="flex flex-col gap-2">
      <textarea
        aria-label="me3"
        spellCheck={false}
        value={edit.text}
        onChange={(e) => edit.setText(e.target.value)}
        className="min-h-80 w-full resize-y rounded-card border border-border-edge bg-surface-input p-3 font-mono text-body text-text-primary"
        style={{ height: "max(320px, 60vh)" }}
      />
      {edit.error ? (
        <p role="alert" className="text-caption text-status-danger">
          {edit.error}
        </p>
      ) : null}
      <div className="flex items-center justify-end gap-2">
        <span className={cn("text-caption", edit.dirty ? "text-accent" : "text-text-secondary")}>{edit.dirty ? words.unsaved : words.saved}</span>
        <Button disabled={!edit.dirty} onClick={edit.discard}>
          {words.discard}
        </Button>
        <Button variant="primary" disabled={!edit.dirty || !!edit.error} onClick={edit.save}>
          {words.save}
        </Button>
      </div>
    </div>
  );
}
