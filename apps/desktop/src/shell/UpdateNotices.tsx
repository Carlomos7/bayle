import { X } from "lucide-react";
import type { UpdateNotice } from "@bayle/api";
import { Button } from "@/components/ui/button";
import { useShellOp } from "./ops";

const LEVELS: Record<string, string> = {
  error: "border-status-danger bg-status-danger-bg",
  warning: "border-status-warning bg-status-warning-bg",
  ok: "border-status-success bg-status-success-bg",
};

/** The launcher's update notices (offer, download, ready, failed, advisory...): their buttons go back to the backend. */
export function UpdateNotices({ notices }: { notices: readonly UpdateNotice[] }) {
  const op = useShellOp();
  if (notices.length === 0) return null;
  return (
    <section aria-label="Updates" className="flex flex-col gap-2 border-b border-border-hairline bg-surface-page px-4 py-2">
      {notices.map((n) => (
        <div
          key={n.id}
          role={n.level === "error" ? "alert" : "status"}
          className={`flex flex-wrap items-center gap-3 rounded-card border px-3 py-2 ${LEVELS[n.level] ?? "border-border-edge bg-surface-card"}`}
        >
          <div className="min-w-0 flex-1">
            <p className="text-body font-semibold">{n.title}</p>
            <p className="text-caption text-text-secondary">{n.body}</p>
          </div>
          {(n.actions ?? []).map((a) => (
            <Button
              key={a.key}
              variant={a.primary ? "primary" : "ghost"}
              title={a.tip || undefined}
              onClick={() => void op("shell.update_action", { notice_id: n.id, key: a.key })}
            >
              {a.label}
            </Button>
          ))}
          {n.closable ? (
            <button
              type="button"
              aria-label={`Dismiss: ${n.title}`}
              onClick={() => void op("shell.dismiss_notice", { notice_id: n.id })}
              className="grid size-8 place-items-center rounded-control outline-none hover:bg-fill-ghost-hover focus-visible:ring-2 focus-visible:ring-glow-ring"
            >
              <X aria-hidden className="size-4" />
            </button>
          ) : null}
        </div>
      ))}
    </section>
  );
}
