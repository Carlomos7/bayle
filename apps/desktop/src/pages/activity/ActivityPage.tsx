import type { ActivityState, Choice, JobItem } from "@bayle/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, ChevronRight, Copy, FileText, RotateCcw, Share2 } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useApi } from "@/api/backend";
import { pageKey } from "@/api/events";
import { useOp, usePage, usePlanOp } from "@/api/hooks";
import { sonnerToasts, toProblem } from "@/components/toasts";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { openPath } from "@/lib/desktop";

interface LogView {
  rows: { time: string; level: string; text: string }[];
  plain: string;
  note: string;
  missing: boolean;
}

type Item = { kind: "day"; label: string } | { kind: "job"; job: JobItem };

const LEVEL: Record<string, string> = {
  success: "bg-status-success-bg text-status-success",
  warning: "bg-status-warning-bg text-status-warning",
  danger: "bg-status-danger-bg text-status-danger",
  info: "bg-status-info-bg text-status-info",
  muted: "bg-fill-hover text-text-secondary",
};

const select =
  "h-[var(--control-h)] min-w-[var(--picker-game-w)] rounded-control border border-border-edge bg-surface-input px-2 text-body text-text-primary";
const small = "h-[var(--control-small-h)]";

function Pill({ level, children }: { level: string; children: string }) {
  return (
    <span className={cn("rounded-pill px-2 py-0.5 text-caption font-medium whitespace-nowrap", LEVEL[level] ?? LEVEL.muted)}>
      {children}
    </span>
  );
}

function Filter({ label, value, choices, onChange }: { label: string; value: string; choices: Choice[]; onChange(v: string): void }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-caption text-text-secondary">
        {label}
      </label>
      <select id={id} className={select} value={value} onChange={(e) => onChange(e.target.value)}>
        {choices.map((c) => (
          <option key={c.key} value={c.key}>
            {c.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** One opened job log: detail toggle, attachment picker, copy (plain / for support), open the file. */
function LogPanel({ job, words }: { job: JobItem; words: Record<string, string> }) {
  const api = useApi();
  const [source, setSource] = useState("");
  const [detail, setDetail] = useState(false);
  const params = { job_id: job.id, source, detail };
  const log = useQuery({
    // under ["page","activity"]: the same events that refresh the list re-read an open log
    queryKey: [...pageKey("activity"), "log", params],
    queryFn: () => api.post<LogView>("/v1/ops/activity.log", params),
  });
  const copy = useOp<{ text: string }, typeof params & { for_support: boolean }>("activity.copy");
  const file = useOp<{ path: string | null }, { job_id: string; source: string }>("activity.log_file");
  const firstSource = job.sources[0]?.key ?? "";
  const text = log.data ? log.data.plain || log.data.rows.map((r) => r.text).join("\n") : "";

  const doCopy = (forSupport: boolean) =>
    copy.mutate(
      { ...params, for_support: forSupport },
      {
        onSuccess: ({ text }) =>
          navigator.clipboard.writeText(text).then(
            () => sonnerToasts.notice((forSupport ? words.copiedSupport : words.copied) ?? "Copied"),
            (e: unknown) => sonnerToasts.error(e),
          ),
      },
    );
  const doOpen = () =>
    file.mutate(
      { job_id: job.id, source },
      {
        onSuccess: ({ path }) => {
          if (path === null) sonnerToasts.notice(words.fileGone ?? "That file is no longer there.", { error: true });
          else openPath(path).catch((e: unknown) => sonnerToasts.error(e));
        },
      },
    );

  return (
    <div className="flex flex-col gap-2 pb-3">
      <div className="flex flex-wrap items-center gap-2">
        {source === "" || source === firstSource ? (
          <label className="flex items-center gap-2 text-body" title={words.showDetailsTip}>
            <input type="checkbox" checked={detail} onChange={(e) => setDetail(e.target.checked)} />
            {words.showDetails}
          </label>
        ) : null}
        {job.sources.length > 1 ? (
          <select
            aria-label="Log source"
            className={cn(select, small, "min-w-0")}
            value={source || firstSource}
            onChange={(e) => setSource(e.target.value)}
          >
            {job.sources.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        ) : null}
        <Button className={small} title={words.copyTip} onClick={() => doCopy(false)}>
          <Copy aria-hidden className="size-4" />
          {words.copy}
        </Button>
        <Button className={small} title={words.copySupportTip} onClick={() => doCopy(true)}>
          <Share2 aria-hidden className="size-4" />
          {words.copySupport}
        </Button>
        <Button className={small} onClick={doOpen}>
          <FileText aria-hidden className="size-4" />
          {words.openFile}
        </Button>
      </div>
      {log.error ? (
        <p role="alert" className="text-caption text-status-danger">
          {toProblem(log.error).message}
        </p>
      ) : null}
      {log.data?.note ? <p className="text-caption text-text-secondary">{log.data.note}</p> : null}
      <pre
        tabIndex={0}
        aria-label="Log text"
        className="max-h-[420px] min-h-[180px] overflow-auto rounded-control bg-surface-input p-3 font-mono text-caption whitespace-pre-wrap"
      >
        {text}
      </pre>
    </div>
  );
}

function JobRow({
  job,
  open,
  words,
  onToggle,
  onUndo,
}: {
  job: JobItem;
  open: boolean;
  words: Record<string, string>;
  onToggle(): void;
  onUndo(): void;
}) {
  const logId = `log-region-${job.id}`;
  return (
    <div className="border-x border-b border-border-hairline bg-surface-card px-[var(--pad-card)]">
      <div className="flex min-h-[60px] items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={open ? logId : undefined}
          title={open ? words.hideLog : words.showLog}
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-control py-2 text-left"
        >
          {open ? <ChevronDown aria-hidden className="size-4 shrink-0" /> : <ChevronRight aria-hidden className="size-4 shrink-0" />}
          <span className="w-11 shrink-0 text-caption text-text-secondary tabular-nums">{job.when}</span>
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="truncate font-semibold text-body">{job.title}</span>
            {job.line || job.meta ? (
              <span className={cn("truncate text-caption", job.failed ? "text-status-danger" : "text-text-secondary")}>
                {job.line || job.meta}
              </span>
            ) : null}
          </span>
          {job.line ? <span className="hidden shrink-0 text-caption text-text-secondary min-[900px]:inline">{job.meta}</span> : null}
        </button>
        <Pill level={job.level}>{job.outcome}</Pill>
        {job.undo_label ? (
          <Button className={small} title={job.undo_tip} onClick={onUndo}>
            <RotateCcw aria-hidden className="size-4" />
            {job.undo_label}
          </Button>
        ) : null}
      </div>
      {open ? (
        <div id={logId} role="region" aria-label={`${job.title} log`}>
          <LogPanel job={job} words={words} />
        </div>
      ) : null}
    </div>
  );
}

export function ActivityPage() {
  const qc = useQueryClient();
  const [game, setGame] = useState("");
  const [group, setGroup] = useState("");
  const [failedOnly, setFailedOnly] = useState(false);
  const [openJob, setOpenJob] = useState("");
  const { data, error, isPending, refetch } = usePage<ActivityState>("activity", { game, group, failed_only: failedOnly });

  // Looking at Activity clears the rail's badge (the shell page carries the count)
  const seen = useOp("activity.mark_seen", { onSuccess: () => void qc.invalidateQueries({ queryKey: pageKey("shell") }) });
  useEffect(() => {
    seen.mutate({});
    // once per visit
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const undo = usePlanOp<{ job_id: string }>("activity.undo", (offer) => {
    if (!offer.plan_id) void qc.invalidateQueries({ queryKey: pageKey("activity") }); // refused: the list may be stale
  });

  const items = useMemo<Item[]>(
    () =>
      (data?.days ?? []).flatMap((d) => [
        { kind: "day" as const, label: d.label },
        ...d.jobs.map((job) => ({ kind: "job" as const, job })),
      ]),
    [data],
  );
  // an open job that is gone from the list closes
  const openId = items.some((i) => i.kind === "job" && i.job.id === openJob) ? openJob : "";

  const listRef = useRef<HTMLDivElement>(null);
  const [margin, setMargin] = useState(0);
  useLayoutEffect(() => {
    const top = listRef.current?.offsetTop ?? 0;
    setMargin(top);
  }, [data]); // the summary and filters above the list change height only with the data
  // TanStack Virtual's functions are not memoizable, which the React Compiler lint flags; this component has nothing memoized on them
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtual = useVirtualizer({
    count: items.length,
    getScrollElement: () => document.getElementById("main"),
    estimateSize: (i) => (items[i]?.kind === "day" ? 40 : 61),
    scrollMargin: margin,
    overscan: 8,
    getItemKey: (i) => {
      const it = items[i];
      return it ? (it.kind === "day" ? `d-${it.label}` : it.job.id) : i;
    },
  });

  const words = data?.words ?? {};
  return (
    <section aria-labelledby="page-title" className="flex flex-col gap-6">
      <h1 id="page-title" className="font-semibold text-page text-title">
        Activity
      </h1>
      {error ? (
        <div role="alert" className="flex items-center gap-3 text-status-danger">
          {toProblem(error).message}
          <Button onClick={() => void refetch()}>Try again</Button>
        </div>
      ) : null}
      {isPending ? (
        <p role="status" className="text-text-secondary">
          Loading...
        </p>
      ) : null}
      {data ? (
        <>
          <div className="grid grid-cols-3 gap-3">
            {data.summary.map((c) => (
              <div key={c.label} className="rounded-card border border-border-hairline bg-surface-card p-3">
                <div className="text-caption text-text-secondary">{c.label}</div>
                <div
                  className={cn(
                    "font-semibold text-body",
                    c.level === "danger" ? "text-status-danger" : c.level === "muted" ? "text-text-secondary" : "text-text-primary",
                  )}
                >
                  {c.value}
                </div>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <Filter label={words.gameFilter ?? "Game"} value={game} choices={data.games ?? []} onChange={setGame} />
            <Filter label={words.kindFilter ?? "Kind"} value={group} choices={data.kinds ?? []} onChange={setGroup} />
            <label className="flex h-[var(--control-h)] items-center gap-2 text-body">
              <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} />
              {words.failedOnly ?? "Failed only"}
            </label>
          </div>
          {data.empty ? <p className="text-text-secondary">{data.empty}</p> : null}
        </>
      ) : null}
      <div ref={listRef} role="list" aria-label="Jobs" style={{ height: virtual.getTotalSize(), position: "relative" }}>
        {virtual.getVirtualItems().map((v) => {
          const it = items[v.index];
          if (!it) return null;
          return (
            <div
              key={v.key}
              ref={virtual.measureElement}
              data-index={v.index}
              role="listitem"
              className="absolute inset-x-0 top-0"
              style={{ transform: `translateY(${v.start - margin}px)` }}
            >
              {it.kind === "day" ? (
                <h2 className="pt-4 pb-2 font-semibold text-section text-title">{it.label}</h2>
              ) : (
                <JobRow
                  job={it.job}
                  open={openId === it.job.id}
                  words={words}
                  onToggle={() => setOpenJob(openId === it.job.id ? "" : it.job.id)}
                  onUndo={() => undo.mutate({ job_id: it.job.id })}
                />
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
