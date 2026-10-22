import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useApi } from "@/api/backend";
import { toProblem } from "@/components/toasts";
import { Button } from "@/components/ui/button";
import { savesKey, useSavesOps } from "./ops";
import { SidePanel } from "./SidePanel";
import type { RepairViewData } from "./types";
import { Card, hint, InfoBar, sectionTitle } from "./ui";

/**
 * Check & repair for one save: a character picker, then the findings in cards ("May not load" first). The safe items
 * start ticked; the footer says what the ticked boxes do and the button repairs them after one more confirmation.
 */
export function RepairPanel({ path, slot: first, onClose }: { path: string; slot: number; onClose: () => void }) {
  const api = useApi();
  const ops = useSavesOps();
  const { words, running } = ops.view;
  const [slot, setSlot] = useState(first); // 0-based; -1: the whole file
  const [ticks, setTicks] = useState<string[] | null>(null); // null: the ones ticked by default
  const { data, error } = useQuery({
    queryKey: [...savesKey, "repair", path, slot, ticks],
    queryFn: async () => (await api.post<{ data: RepairViewData }>("/v1/ops/saves.repair_view", { path, slot, ticked: ticks })).data,
    placeholderData: keepPreviousData,
  });
  const current = ticks ?? data?.ticked ?? [];
  const set = (keys: string[], on: boolean) =>
    setTicks(on ? [...new Set([...current, ...keys])] : current.filter((k) => !keys.includes(k)));
  const card = data?.card;

  return (
    <SidePanel
      title={`${words.checkRepair}${card ? `  ·  ${card.file}` : ""}`}
      width={640}
      onClose={onClose}
      closeLabel={words.back ?? ""}
    >
      {error ? <InfoBar severity="error">{toProblem(error).message}</InfoBar> : null}
      {card && card.characters.length > 1 ? (
        <label className="flex flex-col gap-1 text-caption text-text-secondary">
          {words.slot}
          <select
            value={slot}
            onChange={(e) => setSlot(Number(e.target.value))}
            className="h-[var(--control-h)] w-64 rounded-control border border-border-edge bg-surface-input px-2 text-body text-text-primary"
          >
            <option value={-1}>{words.wholeFile}</option>
            {card.characters.map((c) => (
              <option key={c.slot} value={c.slot - 1}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {data?.damaged.map((d) => (
        <InfoBar key={d.title} severity="error">{`${d.title}. ${d.detail} ${words.damagedHint}`}</InfoBar>
      ))}
      {data && data.groups.length === 0 && data.damaged.length === 0 ? <p className={hint}>{words.nothingToFix}</p> : null}
      {data?.groups.map((g) => (
        <Card key={g.id} aria-label={g.title} className="flex flex-col gap-2 p-4">
          <div className="flex items-center gap-2">
            <h3 className={sectionTitle}>{g.title}</h3>
            <Button className="h-6 min-w-0 px-2" onClick={() => set(g.items.filter((i) => i.enabled).map((i) => i.key), true)}>
              {words.all}
            </Button>
            <Button className="h-6 min-w-0 px-2" onClick={() => set(g.items.filter((i) => i.enabled).map((i) => i.key), false)}>
              {words.none}
            </Button>
          </div>
          <p className={hint}>{g.hint}</p>
          {g.items.map((i) => (
            <div key={i.key} className="flex flex-col">
              <label className="flex items-center gap-2 text-body">
                <input
                  type="checkbox"
                  className="size-4 accent-accent"
                  checked={current.includes(i.key)}
                  disabled={!i.enabled}
                  onChange={(e) => set([i.key], e.target.checked)}
                />
                {i.label}
              </label>
              {i.note || i.sub ? (
                <span className={`pl-6 text-caption ${i.note ? "text-status-danger" : "text-text-secondary"}`}>{i.note || i.sub}</span>
              ) : null}
            </div>
          ))}
        </Card>
      ))}
      {data ? <p className={hint}>{data.summary}</p> : null}
      <div className="flex gap-2">
        <Button
          variant="primary"
          disabled={!data || current.length === 0 || running}
          onClick={() => data && ops.repair(path, current.map((k) => data.tuples[k] ?? []))}
        >
          {data?.button ?? words.checkRepair}
        </Button>
        <Button onClick={onClose}>{words.back}</Button>
      </div>
    </SidePanel>
  );
}
