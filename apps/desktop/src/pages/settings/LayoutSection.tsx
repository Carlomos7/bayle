import { useMutation, useQuery, useQueryClient, keepPreviousData, skipToken } from "@tanstack/react-query";
import { useState } from "react";
import type { SettingsState } from "@bayle/api";
import { useApi } from "@/api/backend";
import { jobKey } from "@/api/events";
import type { JobState, PlanOffer } from "@/api/types";
import { usePrompts } from "@/components/PromptHost";
import { sonnerToasts } from "@/components/toasts";
import { Button } from "@/components/ui/button";
import { pickFolder } from "@/lib/native";
import { Row, input } from "./controls";
import { SAID, NAME_FIELDS, W, type NameField } from "./words";

interface LayoutCheck {
  errors: Record<string, string>;
  preview: string;
}

/** The profiles folder, moving profiles in, and the four folder names: each change is a plan (confirm, then a job). */
export function LayoutSection({ state, openKind }: { state: SettingsState; openKind: (kind: string) => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const { offerPlan } = usePrompts();
  const [draft, setDraft] = useState<Partial<Record<NameField, string>>>({});
  const [more, setMore] = useState(false);
  const [moveJob, setMoveJob] = useState("");
  const names = { ...state.layout, ...draft } as Record<NameField, string>;
  const dirty = NAME_FIELDS.some(([k]) => names[k] !== state.layout[k]);

  const job = useQuery<JobState>({ queryKey: moveJob ? jobKey(moveJob) : ["jobs", "none"], queryFn: skipToken, enabled: false });
  const moving = !!moveJob && (job.data === undefined || job.data.state === "running");

  const check = useQuery({
    queryKey: ["op", "settings.layout_check", names],
    queryFn: () => api.post<LayoutCheck>("/v1/ops/settings.layout_check", names),
    placeholderData: keepPreviousData,
  });

  const offer = useMutation({
    mutationFn: ({ op, params }: { op: string; params: object; relocate?: boolean }) => api.post<PlanOffer>(`/v1/ops/${op}`, params),
    onSuccess: (plan, { relocate }) =>
      offerPlan(plan, (done) => {
        const id = (done as { job_id?: string | null })?.job_id;
        if (relocate && id) setMoveJob(id);
        void qc.invalidateQueries({ queryKey: ["page", "settings"] });
      }),
    onError: sonnerToasts.error,
  });
  const cancel = useMutation({ mutationFn: () => api.post(`/v1/jobs/${moveJob}/cancel`), onError: sonnerToasts.error });

  const change = async () => {
    const folder = await pickFolder(SAID.pickProfiles);
    if (folder) offer.mutate({ op: "settings.relocate", params: { folder }, relocate: true });
  };

  const errors = check.data?.errors ?? {};
  const edit = (k: NameField, v: string) => setDraft((d) => ({ ...d, [k]: v }));

  return (
    <>
      <Row title={W.profilesFolder} help={W.profilesFolderHelp}>
        <span className="max-w-80 truncate text-caption text-text-secondary" title={state.profiles_root}>
          {state.profiles_root}
        </span>
        <Button onClick={() => openKind("profiles")}>{W.openFolder}</Button>
        <Button onClick={change} disabled={moving}>
          {W.change}
        </Button>
        {moving ? (
          <>
            <span role="status" className="text-caption text-text-secondary">
              {W.moving}
            </span>
            <Button onClick={() => cancel.mutate()}>{W.cancel}</Button>
          </>
        ) : null}
      </Row>
      <Row title={W.otherProfiles} help={W.moveAllTip}>
        <Button disabled={moving} onClick={() => offer.mutate({ op: "settings.move_all", params: {} })}>
          {W.moveAll}
        </Button>
      </Row>
      <Row title={W.more}>
        <Button aria-expanded={more} onClick={() => setMore(!more)}>
          {W.folderNames}
        </Button>
      </Row>
      {more ? (
        <>
          {NAME_FIELDS.map(([k, label]) => (
            <Row key={k} id={`name-${k}`} errorId={`name-${k}-err`} title={label} help={k === "pattern" ? check.data?.preview : undefined} error={errors[k]}>
              <input
                id={`name-${k}`}
                className={`${input} w-80 max-w-full`}
                value={names[k]}
                aria-invalid={!!errors[k] || undefined}
                aria-describedby={errors[k] ? `name-${k}-err` : undefined}
                onChange={(e) => edit(k, e.target.value)}
              />
            </Row>
          ))}
          <Row title="">
            <Button
              variant="primary"
              disabled={!dirty || Object.keys(errors).length > 0 || moving}
              onClick={() => offer.mutate({ op: "settings.rename_layout", params: names })}
            >
              {W.apply}
            </Button>
          </Row>
        </>
      ) : null}
    </>
  );
}
