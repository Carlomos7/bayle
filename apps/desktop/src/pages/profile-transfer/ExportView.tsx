import { useMutation, useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "@/api/backend";
import { pageKey } from "@/api/events";
import type { PlanOffer } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { usePrompts } from "@/components/PromptHost";
import { sonnerToasts, toProblem } from "@/components/toasts";
import { bigWarning, doneText, LARGE_EXPORT, LARGE_MOD, progressText, readmeText, sizeText, total } from "./format";
import { detailOf, useJob, useJobResult } from "./jobs";
import { pickFolder } from "./pickers";
import { Bar, Card, Check, Field, inputClass, Segmented } from "./ui";
import { W } from "./words";

interface Listing {
  mods: { key: string; name: string; enabled: boolean; size: number }[];
  save_name?: string;
}
interface ExportResult {
  path: string;
  size: number;
}

const clock = () => performance.now();
const stem = (path: string) => (path.split(/[\\/]/).pop() ?? "").replace(/\.[^.]*$/, "");

/** The checklist of mods; virtualised because a profile can hold hundreds. */
function ModList({
  mods,
  picked,
  disabled,
  onToggle,
}: {
  mods: Listing["mods"];
  picked: Set<string>;
  disabled: boolean;
  onToggle: (key: string, on: boolean) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: mods.length, getScrollElement: () => box.current, estimateSize: () => 36, overscan: 8 });
  return (
    <div ref={box} className="max-h-80 overflow-auto" role="group" aria-label={W.mods}>
      <div className="relative" style={{ height: v.getTotalSize() }}>
        {v.getVirtualItems().map((row) => {
          const m = mods[row.index]!;
          return (
            <div key={m.key} className="absolute inset-x-0 flex h-9 items-center gap-2" style={{ top: row.start }}>
              <Check label={m.name} checked={picked.has(m.key)} disabled={disabled} onChange={(on) => onToggle(m.key, on)} />
              <span
                className={`rounded-tag border px-2 text-caption ${m.size >= LARGE_MOD ? "border-status-warning text-status-warning" : "border-border-tag text-text-secondary"}`}
              >
                {sizeText(m.size)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ExportView({ profile, busy, gameRunning }: { profile: string; busy: boolean; gameRunning: boolean }) {
  const api = useApi();
  const { offerPlan } = usePrompts();
  const listing = useQuery({
    queryKey: [...pageKey("profile_transfer"), { profile }],
    queryFn: () => api.get<Listing>(`/v1/pages/profile_transfer?profile=${encodeURIComponent(profile)}`),
  });
  const mods = listing.data?.mods;
  const saveName = listing.data?.save_name ?? "";

  const [kind, setKind] = useState<"list" | "full">("list");
  const [name, setName] = useState(stem(profile));
  const [version, setVersion] = useState("");
  const [author, setAuthor] = useState("");
  const [readme, setReadme] = useState<string | null>(null); // null: the generated one
  const [changelog, setChangelog] = useState("");
  const [showChangelog, setShowChangelog] = useState(false);
  const [preview, setPreview] = useState(false);
  const [withConfigs, setWithConfigs] = useState(true);
  const [withPassword, setWithPassword] = useState(false);
  const [withSave, setWithSave] = useState(false);
  const [folder, setFolder] = useState("");
  const [off, setOff] = useState<Set<string>>(new Set()); // the unticked mods: everything starts ticked
  const picked = useMemo(() => new Set((mods ?? []).map((m) => m.key).filter((k) => !off.has(k))), [mods, off]);

  const [jobId, setJobId] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [startedAt, setStartedAt] = useState(0);
  const [now, setNow] = useState(0); // ticks while a job runs: the elapsed time and the estimate follow it
  const job = useJob(jobId);
  const result = useJobResult<ExportResult>(jobId, job?.state);
  const running = !!jobId && (!job || job.state === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(clock()), 500);
    return () => clearInterval(t);
  }, [running]);
  const elapsed = Math.max(0, now - startedAt) / 1000;

  const pickedMods = (mods ?? []).filter((m) => picked.has(m.key));
  const size = pickedMods.reduce((n, m) => n + m.size, 0);
  const full = kind === "full";
  const shownReadme = readme ?? readmeText(name, version, author, pickedMods);
  const nameOk = name.trim() !== "";
  const modsOk = pickedMods.length > 0 || !full;
  const reason = busy
    ? W.busy
    : gameRunning
      ? W.gameRunning
      : running
        ? W.exporting
        : !nameOk
          ? W.needName
          : !folder
            ? W.needFolder
            : modsOk
              ? ""
              : W.tickOne;
  const top = [...pickedMods].sort((a, b) => b.size - a.size).slice(0, 3);

  const follow = (id: string | null | undefined) => {
    if (!id) return;
    setStartedAt(clock());
    setNow(clock());
    setCancelling(false);
    setJobId(id);
  };
  const params = () => ({
    profile,
    kind,
    name,
    version,
    author,
    readme: shownReadme,
    changelog,
    chosen: [...picked].sort(),
    folder,
    with_configs: withConfigs,
    with_save: full && withSave && !!saveName,
    password: withConfigs && withPassword,
  });
  const start = useMutation({
    mutationFn: async () => {
      if (full && size >= LARGE_EXPORT) {
        // asked once; answering the plan starts the job
        const offer = await api.post<PlanOffer>("/v1/ops/profile_transfer.confirm_export", { ...params(), size });
        offerPlan(offer, (r) => follow((r as { job_id?: string | null } | undefined)?.job_id));
        return;
      }
      follow((await api.post<{ job_id: string }>("/v1/ops/profile_transfer.export", params())).job_id);
    },
    onError: sonnerToasts.error,
  });
  const cancel = useMutation({
    mutationFn: () => api.post(`/v1/jobs/${jobId}/cancel`),
    onMutate: () => setCancelling(true),
    onError: sonnerToasts.error,
  });

  const d = detailOf(job?.progress ?? null);
  const shown = progressText(
    job?.progress?.done ?? 0,
    job?.progress?.total ?? 0,
    d?.n ?? 0,
    d?.count ?? 0,
    elapsed,
  );
  const phase = running ? "running" : job?.state;

  return (
    <div className="flex flex-col gap-4">
      {running ? (
        <Card>
          <p className="font-semibold text-title" role="status">
            {shown.title || W.exporting}
          </p>
          <Bar value={shown.pct} label={W.exporting} />
          <p className="text-caption text-text-secondary">{job?.progress?.label?.split("/").pop() ?? ""}</p>
          <p className="text-caption text-text-secondary">
            {shown.bytes}  ·  {shown.eta}
          </p>
          <Button disabled={cancelling} className="self-start" onClick={() => cancel.mutate()}>
            {cancelling ? W.cancelling : W.cancelExport}
          </Button>
        </Card>
      ) : null}
      {phase === "done" && result ? (
        <p role="status" className="rounded-control border border-status-success bg-status-success-bg p-3">
          {doneText(result.path, result.size, elapsed)}{" "}
          <span className="break-all text-text-secondary">{result.path}</span>
        </p>
      ) : null}
      {phase === "failed" ? (
        <p role="alert" className="rounded-control border border-status-danger bg-status-danger-bg p-3">
          {`The export did not finish: ${(job?.error?.message ?? "Failed.").replace(/\.$/, "")}. Nothing was written.`}
        </p>
      ) : null}
      {phase === "cancelled" ? (
        <p role="status" className="rounded-control border border-border-edge p-3">
          Export cancelled. Nothing was written.
        </p>
      ) : null}

      <Segmented
        label="Export kind"
        value={kind}
        disabled={running}
        options={[
          { value: "list", label: W.shareList },
          { value: "full", label: pickedMods.length ? `${W.fullExport} (${sizeText(size)})` : W.fullExport },
        ]}
        onChange={setKind}
      />
      <p className="text-text-secondary">{full ? W.fullExportAbout : W.shareListAbout}</p>

      {listing.isPending ? <p role="status">Loading...</p> : null}
      {listing.error ? (
        <p role="alert" className="text-status-danger">
          {toProblem(listing.error).message}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <Field label={W.name} value={name} disabled={running} error={nameOk ? undefined : W.required} onChange={(e) => setName(e.target.value)} />
        <Field label={W.version} value={version} disabled={running} onChange={(e) => setVersion(e.target.value)} />
        <Field label={W.author} value={author} disabled={running} onChange={(e) => setAuthor(e.target.value)} />
      </div>

      {full ? (
        <>
          <Card>
            <h2 className="font-semibold text-title">{W.mods}</h2>
            {mods?.length ? (
              <ModList
                mods={mods}
                picked={picked}
                disabled={running}
                onToggle={(k, on) =>
                  setOff((o) => {
                    const n = new Set(o);
                    if (on) n.delete(k);
                    else n.add(k);
                    return n;
                  })
                }
              />
            ) : null}
            <p className="text-caption text-text-secondary">{total(pickedMods.length, size)}</p>
            {!modsOk ? <p className="text-caption text-status-danger">{W.tickOne}</p> : null}
          </Card>
          <Card>
            <div className="flex items-center gap-3">
              <h2 className="font-semibold text-title">{W.readme}</h2>
              <Button className="h-8 min-w-0" onClick={() => setPreview(!preview)}>
                {preview ? W.readmeEdit : W.readmePreview}
              </Button>
            </div>
            {preview ? (
              <pre aria-label={W.readme} className="max-h-52 overflow-auto whitespace-pre-wrap">
                {shownReadme}
              </pre>
            ) : (
              <textarea
                aria-label={W.readme}
                className={cn(inputClass, "h-52 py-2 font-mono")}
                value={shownReadme}
                disabled={running}
                onChange={(e) => setReadme(e.target.value)}
              />
            )}
            <Button className="h-8 min-w-0 self-start" aria-expanded={showChangelog} onClick={() => setShowChangelog(!showChangelog)}>
              {(showChangelog ? "- " : "+ ") + W.changelog}
            </Button>
            {showChangelog ? (
              <textarea
                aria-label={W.changelog}
                className={cn(inputClass, "h-36 py-2 font-mono")}
                value={changelog}
                disabled={running}
                onChange={(e) => setChangelog(e.target.value)}
              />
            ) : null}
          </Card>
        </>
      ) : null}

      <Card>
        <h2 className="font-semibold text-title">{W.include}</h2>
        {full ? <Check label={W.withProfile} checked disabled /> : null}
        <Check label={W.withConfigs} checked={withConfigs} disabled={running} onChange={setWithConfigs} />
        <Check label={W.withPassword} checked={withPassword} disabled={!withConfigs || running} onChange={setWithPassword} />
        <p className="text-caption text-text-secondary">{W.withPasswordTip}</p>
        {full ? (
          <>
            <Check label={W.withSave + (saveName ? ` (${saveName})` : "")} checked={withSave} disabled={!saveName || running} onChange={setWithSave} />
            <p className="text-caption text-status-warning">{saveName ? W.withSaveWarn : W.noSave}</p>
          </>
        ) : null}
      </Card>

      {full && size >= LARGE_EXPORT ? (
        <p role="note" className="rounded-control border border-status-warning bg-status-warning-bg p-3">
          {bigWarning(top)}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={running} onClick={() => void pickFolder(W.outFolder).then((f) => f && setFolder(f)).catch(sonnerToasts.error)}>
          {W.chooseFolder}
        </Button>
        {folder ? (
          <span className="max-w-64 truncate text-caption text-text-secondary" title={folder}>
            {folder}
          </span>
        ) : null}
        <Button variant="primary" disabled={!!reason || start.isPending} onClick={() => start.mutate()}>
          {running ? W.exporting : W.export}
        </Button>
        {reason && !running ? <span className="text-caption text-text-secondary">{reason}</span> : null}
      </div>
    </div>
  );
}
