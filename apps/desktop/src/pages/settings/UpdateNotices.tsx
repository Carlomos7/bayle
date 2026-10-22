import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { UpdateNotice } from "@bayle/api";
import { useApi } from "@/api/backend";
import { pageKey } from "@/api/events";
import { sonnerToasts } from "@/components/toasts";
import { Button } from "@/components/ui/button";
import { W } from "./words";

const LEVEL: Record<string, string> = {
  error: "bg-status-danger-bg",
  warning: "bg-status-warning-bg",
  success: "bg-status-success-bg",
};

/** The update flow's notices (offer, download, ready, outcome, advisory, migration): their buttons run the engine's own paths. */
export function UpdateNotices({ notices }: { notices: UpdateNotice[] }) {
  const api = useApi();
  const qc = useQueryClient();
  const done = { onSettled: () => qc.invalidateQueries({ queryKey: pageKey("shell") }), onError: sonnerToasts.error };
  const act = useMutation({
    mutationFn: (v: { notice_id: string; key: string }) => api.post("/v1/ops/shell.update_action", v),
    ...done,
  });
  const dismiss = useMutation({
    mutationFn: (notice_id: string) => api.post("/v1/ops/shell.dismiss_notice", { notice_id }),
    ...done,
  });
  return (
    <>
      {notices.map((n) => (
        <div
          key={n.id}
          role="region"
          aria-label={n.title}
          className={`flex gap-3 rounded-card p-4 ${LEVEL[n.level] ?? "bg-status-info-bg"}`}
        >
          <div className="flex flex-1 flex-col gap-2">
            <strong>{n.title}</strong>
            {n.body ? <p className="whitespace-pre-line text-text-primary">{n.body}</p> : null}
            {n.actions?.length ? (
              <div className="flex flex-wrap gap-2">
                {n.actions.map((a) => (
                  <Button
                    key={a.key}
                    variant={a.primary ? "primary" : "ghost"}
                    title={a.tip}
                    onClick={() => act.mutate({ notice_id: n.id, key: a.key })}
                  >
                    {a.label}
                  </Button>
                ))}
              </div>
            ) : null}
          </div>
          {n.closable ? (
            <Button aria-label={`${W.dismiss}: ${n.title}`} onClick={() => dismiss.mutate(n.id)}>
              {W.dismiss}
            </Button>
          ) : null}
        </div>
      ))}
    </>
  );
}
