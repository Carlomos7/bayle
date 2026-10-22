import { toast } from "sonner";
import { ApiError, type Problem } from "@/api/client";
import type { Progress } from "@/api/types";

/** What the event router needs from the toast layer; Sonner implements it, tests fake it. */
export interface Toasts {
  progress(jobId: string, title: string, progress: Progress | null): void;
  done(jobId: string, title: string): void;
  failed(jobId: string, title: string, problem: Problem): void;
  cancelled(jobId: string, title: string): void;
  notice(text: string, opts?: { error?: boolean; details?: boolean; onDetails?: () => void }): void;
  error(error: unknown): void;
}

/** Any thrown value as the Problem shape the user sees. */
export function toProblem(error: unknown): Problem {
  if (error instanceof ApiError) return error.problem;
  return { code: "unexpected", message: error instanceof Error ? error.message : String(error), details: {} };
}

function ProgressBody({ progress }: { progress: Progress | null }) {
  const { done, total, label } = progress ?? {};
  const known = typeof done === "number" && typeof total === "number" && total > 0;
  return (
    <div className="mt-1 flex w-full flex-col gap-1">
      {label ? <span>{label}</span> : null}
      <progress aria-label={label || "Progress"} className="h-1 w-full" {...(known ? { value: done, max: total } : {})} />
    </div>
  );
}

export const sonnerToasts: Toasts = {
  // Same id per job: later calls update the one toast in place.
  progress: (jobId, title, progress) =>
    toast.loading(title, { id: jobId, duration: Infinity, description: <ProgressBody progress={progress} /> }),
  done: (jobId, title) => toast.success(title, { id: jobId, description: undefined, duration: 4500 }),
  failed: (jobId, title, p) =>
    toast.error(title, { id: jobId, description: p.message, duration: Infinity, closeButton: true }),
  cancelled: (jobId, title) => toast.info(`${title}: cancelled`, { id: jobId, description: undefined, duration: 4500 }),
  notice: (text, opts) =>
    (opts?.error ? toast.error : toast)(text, {
      duration: opts?.error ? Infinity : 4500,
      closeButton: !!opts?.error,
      action: opts?.details && opts.onDetails ? { label: "Details", onClick: opts.onDetails } : undefined,
    }),
  error: (error) => {
    const p = toProblem(error);
    toast.error(p.message, { description: p.code, duration: Infinity, closeButton: true });
  },
};
