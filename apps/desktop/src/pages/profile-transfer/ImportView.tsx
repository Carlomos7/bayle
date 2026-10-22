import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useApi } from "@/api/backend";
import { Button } from "@/components/ui/button";
import { sonnerToasts, toProblem } from "@/components/toasts";
import type { BundledRequest } from "./bundled";
import { Clashes, type Clash } from "./Clashes";
import { useJob, useJobResult } from "./jobs";
import { pickFile } from "@/lib/native";
import { Bar, Card, Check, Field, Notes, Segmented } from "./ui";
import { W } from "./words";

interface Opened {
  resource: string;
  file?: string;
  is_zip?: boolean;
  readme?: string;
  new_profile?: boolean;
  new_name?: string;
  names?: string[];
}
interface FileCard {
  key: string;
  title: string;
  path: string;
  lines: string[];
  leftOut: string[];
  isNew: boolean;
}
interface Preview {
  cards?: FileCard[];
  skipped?: string[];
  notes?: string[];
  refusals?: string[];
  clashes?: Clash[];
  lines?: string[];
  undecided?: boolean;
  ok?: boolean;
}

const OP = "/v1/ops/profile_transfer.";
const base = (p: string) => p.split(/[\\/]/).pop() ?? p;
const stem = (p: string) => base(p).replace(/\.[^.]*$/, "");

/** Import a share list or a full export someone sent, or (with `bundled`) the profile a mod download ships. Leaving
 * the view lets the backend delete what it unpacked. */
export function ImportView({
  profile,
  busy,
  bundled,
  onLeave,
  onImported,
}: {
  profile: string;
  busy: boolean;
  bundled?: BundledRequest;
  onLeave: () => void;
  onImported: (name: string) => void;
}) {
  const api = useApi();
  const [opened, setOpened] = useState<Opened | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [newProfile, setNewProfile] = useState(true);
  const [newName, setNewName] = useState("");
  const [names, setNames] = useState<string[]>([]);
  const [which, setWhich] = useState(0);
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);

  const res = useRef(""); // the backend resource this view holds
  const previewRef = useRef<Preview | null>(null);
  const job = useJob(jobId);
  const result = useJobResult<{ name: string }>(jobId, job?.state);
  const importing = !!jobId && (!job || job.state === "running");
  const isBundled = !!bundled;

  const discard = (id: string) => void api.post(`${OP}discard`, { resource: id }).catch(() => undefined);
  useEffect(
    () => () => {
      if (res.current) discard(res.current); // leaving the page lets go of the unpacked zip
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const previewM = useMutation({
    mutationFn: (p: Record<string, unknown>) => api.post<Preview>(`${OP}preview`, p),
    onSuccess: (prev, vars) => {
      if (vars.resource !== res.current) return; // the player left that file
      const before = previewRef.current?.cards ? new Set(previewRef.current.cards.map((c) => c.key)) : null;
      previewRef.current = prev;
      setError("");
      setPreview(prev);
      // a new look after a choice keeps what was unticked
      setTicked((t) => new Set((prev.cards ?? []).map((c) => c.key).filter((k) => !before || !before.has(k) || t.has(k))));
    },
    onError: (e, vars) => {
      if (vars.resource !== res.current) return;
      previewRef.current = null;
      setPreview(null);
      setError(toProblem(e).message);
    },
  });
  const runPreview = (o: Partial<{ newProfile: boolean; newName: string; choices: Record<string, string>; which: number }> = {}) =>
    res.current &&
    previewM.mutate({
      resource: res.current,
      profile,
      new_profile: o.newProfile ?? newProfile,
      new_name: o.newName ?? newName,
      choices: o.choices ?? choices,
      which: o.which ?? which,
    });

  const reset = () => {
    res.current = "";
    previewRef.current = null;
    setOpened(null);
    setPreview(null);
    setTicked(new Set());
    setChoices({});
    setError("");
  };

  const openM = useMutation({
    mutationFn: (path: string) => api.post<Opened>(`${OP}open_file`, { path }),
    onSuccess: (o) => {
      res.current = o.resource;
      setOpened(o);
      setNewProfile(o.new_profile ?? true);
      setNewName(o.new_name ?? "");
      runPreview({ newProfile: o.new_profile ?? true, newName: o.new_name ?? "" });
    },
    onError: (e) => setError(`Can't use that file. ${toProblem(e).message}`),
  });
  const chooseFile = async () => {
    const path = await pickFile(W.openFile, "Profile files", ["json", "zip"]).catch((e: unknown) => (sonnerToasts.error(e), null));
    if (!path || openM.isPending) return;
    if (res.current) discard(res.current);
    reset();
    openM.mutate(path);
  };

  // the bundled profile: the shell's hand-over opens a resource of the unpacked download
  const taken = useRef<BundledRequest | null>(null);
  const bundledM = useMutation({
    mutationFn: (b: BundledRequest) =>
      api.post<Opened>(`${OP}open_bundled`, { unpacked: b.unpacked, profiles: b.profiles, staging: b.staging ?? "" }),
    onSuccess: (o, b) => {
      res.current = o.resource;
      setNames(o.names ?? b.profiles);
      setNewName(o.new_name ?? "");
      setNewProfile(true);
      runPreview({ newProfile: true, newName: o.new_name ?? "", which: 0 });
    },
    onError: (e) => setError(toProblem(e).message),
  });
  useEffect(() => {
    if (bundled && taken.current !== bundled) {
      taken.current = bundled;
      bundledM.mutate(bundled);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bundled]);

  // the top bar's profile may change under an open file
  useEffect(() => {
    if (res.current) runPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile]);

  const importM = useMutation({
    mutationFn: () =>
      api.post<{ job_id: string }>(`${OP}import`, {
        resource: res.current,
        skip: (preview?.cards ?? []).map((c) => c.key).filter((k) => !ticked.has(k)),
      }),
    onSuccess: (r) => setJobId(r.job_id),
    onError: sonnerToasts.error,
  });
  const imported = useRef("");
  useEffect(() => {
    if (!result || imported.current === jobId) return;
    imported.current = jobId ?? "";
    sonnerToasts.notice(`Imported into ${result.name}. Undo it from Activity.`);
    res.current = ""; // the backend let go of it when the import worked
    reset();
    onImported(result.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  const working = openM.isPending || previewM.isPending || bundledM.isPending || importing;
  const cards = preview?.cards ?? [];
  const canImport = isBundled
    ? !!preview?.ok && !preview.undecided
    : !!preview && !(preview.refusals?.length ?? 0) && cards.some((c) => ticked.has(c.key)) && !preview.undecided;
  const target = isBundled || opened?.is_zip;

  const importNow = () => {
    if (busy) return sonnerToasts.notice(W.waitJob, { error: true });
    importM.mutate();
  };
  const rename = () => runPreview();

  return (
    <div className="flex flex-col gap-4">
      {isBundled ? (
        <>
          <h2 className="font-semibold text-section text-title">{W.bundledTitle}</h2>
          <p className="text-text-secondary">{W.bundledAbout}</p>
          {names.length > 1 ? (
            <label className="flex flex-col gap-1 text-caption text-text-secondary">
              {W.whichProfile}
              <select
                className="h-[var(--control-h)] rounded-control border border-border-edge bg-surface-input px-3 text-body text-text-primary"
                value={which}
                disabled={working}
                onChange={(e) => {
                  const i = Number(e.target.value);
                  const n = stem(names[i] ?? "");
                  setWhich(i);
                  setNewName(n);
                  runPreview({ which: i, newName: n });
                }}
              >
                {names.map((n, i) => (
                  <option key={n} value={i}>
                    {base(n)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </>
      ) : (
        <>
          <p className="text-text-secondary">{W.importAbout}</p>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" disabled={working} onClick={() => void chooseFile()}>
              {W.openFile}
            </Button>
            <strong className="text-title">{opened?.file ?? ""}</strong>
          </div>
        </>
      )}

      {working && !importing ? (
        <p role="status" className="text-caption text-text-secondary">
          {W.reading}
        </p>
      ) : null}
      {importing ? <Bar label={W.importing} value={Math.floor((100 * (job?.progress?.done ?? 0)) / (job?.progress?.total || 1))} /> : null}
      {error ? (
        <p role="alert" className="text-status-danger">
          {error}
        </p>
      ) : null}

      {opened?.readme ? (
        <Card>
          <h2 className="font-semibold text-title">{W.readmeFirst}</h2>
          <pre className="whitespace-pre-wrap font-sans">{opened.readme}</pre>
        </Card>
      ) : null}

      {target ? (
        <div className="flex flex-col gap-2">
          <Segmented
            label="Import target"
            value={newProfile ? "new" : "current"}
            disabled={working}
            options={[
              { value: "new", label: W.newProfile },
              { value: "current", label: W.currentProfile },
            ]}
            onChange={(v) => {
              setNewProfile(v === "new");
              runPreview({ newProfile: v === "new" });
            }}
          />
          {newProfile ? (
            <Field
              label={W.newName}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onBlur={rename}
              onKeyDown={(e) => e.key === "Enter" && rename()}
            />
          ) : null}
        </div>
      ) : null}

      <Clashes
        clashes={preview?.clashes ?? []}
        disabled={working}
        onPick={(key, c) => {
          const next = { ...choices, [key.toLowerCase()]: c };
          setChoices(next);
          runPreview({ choices: next });
        }}
      />

      {cards.map((c) => (
        <Card key={c.key}>
          <Check
            label={c.title + (c.isNew ? `  ·  ${W.newFile}` : "")}
            checked={ticked.has(c.key)}
            disabled={working}
            onChange={(on) =>
              setTicked((t) => {
                const n = new Set(t);
                if (on) n.add(c.key);
                else n.delete(c.key);
                return n;
              })
            }
          />
          <p className="break-all text-caption text-text-secondary">{c.path}</p>
          {c.lines.map((l, i) => (
            <p key={i}>{l}</p>
          ))}
          {c.leftOut.map((l, i) => (
            <p key={i} className="text-text-secondary">
              {l}
            </p>
          ))}
        </Card>
      ))}

      {(preview?.lines?.length ?? 0) > 0 ? (
        <Card>
          {preview?.lines?.map((l, i) => (
            <p key={i}>{l}</p>
          ))}
        </Card>
      ) : null}
      <Notes lines={preview?.refusals ?? []} danger />
      <Notes title={W.left} lines={preview?.skipped ?? []} />
      <Notes title={W.notes} lines={preview?.notes ?? []} />
      {!isBundled && opened && preview && !cards.length && !(preview.refusals?.length ?? 0) && !working ? (
        <p className="text-text-secondary">{W.nothing}</p>
      ) : null}

      {opened || isBundled ? (
        <div className="flex flex-wrap gap-3">
          <Button variant="primary" disabled={!canImport || working} onClick={importNow}>
            {importing ? W.importing : W.importButton}
          </Button>
          <Button
            onClick={() => {
              if (res.current) discard(res.current);
              reset();
              if (isBundled) onLeave();
            }}
          >
            {W.cancel}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
