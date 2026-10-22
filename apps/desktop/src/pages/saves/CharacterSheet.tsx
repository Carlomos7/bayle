import { useQuery } from "@tanstack/react-query";
import { Tabs } from "radix-ui";
import { useApi } from "@/api/backend";
import { toProblem } from "@/components/toasts";
import { Button } from "@/components/ui/button";
import { savesKey, useSavesOps } from "./ops";
import { SidePanel } from "./SidePanel";
import type { Sheet } from "./types";
import { hint, InfoBar, Pill } from "./ui";

/** The character sheet, read-only: Overview (where, runes, what the slot needs) and Stats (the eight attributes). */
export function CharacterSheet({
  path,
  slot,
  onClose,
  onRepair,
}: {
  path: string;
  slot: number;
  onClose: () => void;
  onRepair: (path: string, slot: number) => void;
}) {
  const api = useApi();
  const { words } = useSavesOps().view;
  const { data, error } = useQuery({
    queryKey: [...savesKey, "sheet", path, slot],
    queryFn: async () => (await api.post<{ data: Sheet | Record<string, never> }>("/v1/ops/saves.sheet", { path, slot })).data,
  });
  const sheet = data && "name" in data ? data : null;
  return (
    <SidePanel title={sheet?.name ?? ""} width={460} onClose={onClose} closeLabel={words.back ?? ""}>
      {error ? <InfoBar severity="error">{toProblem(error).message}</InfoBar> : null}
      {sheet ? (
        <Tabs.Root defaultValue="overview" className="flex flex-col gap-4">
          <Tabs.List aria-label={sheet.name} className="flex gap-1">
            {(["overview", "stats"] as const).map((t) => (
              <Tabs.Trigger
                key={t}
                value={t}
                className="h-8 rounded-control px-3 text-body text-text-secondary hover:bg-fill-ghost-hover data-[state=active]:bg-smear-selected data-[state=active]:text-text-primary"
              >
                {words[t]}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          <p className={hint}>{words.sheetReadOnly}</p>
          <Tabs.Content value="overview" className="flex flex-col gap-2">
            <dl className="grid grid-cols-[130px_1fr] gap-x-3 gap-y-2 text-body">
              {(
                [
                  [words.level, sheet.level],
                  [words.body, sheet.body],
                  [words.where, sheet.where],
                  [words.torrent, sheet.torrent],
                  [words.runesHeld, sheet.runes],
                  [words.runesMemory, sheet.memory],
                  [words.modItems, sheet.mods || words.none],
                ] as const
              ).map(([label, value]) => (
                <div key={label} className="contents">
                  <dt className="text-text-secondary">{label}</dt>
                  <dd className="break-words">{String(value)}</dd>
                </div>
              ))}
            </dl>
            {sheet.findings.map((f) => (
              <div key={f.title} className="flex items-center gap-2">
                <Pill level="warning">{`${f.title}  ·  ${f.count}`}</Pill>
                <Button onClick={() => onRepair(path, slot)}>{words.checkRepair}</Button>
              </div>
            ))}
          </Tabs.Content>
          <Tabs.Content value="stats" className="flex flex-col gap-2">
            {sheet.attributes.map((a) => (
              <div key={a.label} className="flex items-center gap-3 text-body">
                <span className="w-28">{a.label}</span>
                <span className="w-8 text-right tabular-nums">{a.value}</span>
                <span className="h-1.5 w-44 rounded-full bg-fill-identity" aria-hidden>
                  <span className="block h-full rounded-full bg-stat-bar" style={{ width: `${(Math.min(a.value, 99) / 99) * 100}%` }} />
                </span>
              </div>
            ))}
            <p className="pt-2 text-body text-text-secondary">{(words.levelFrom ?? "").replace("{n}", String(sheet.levelFromAttributes))}</p>
            <p className={hint}>{words.atLastSave}</p>
            {sheet.derived.map((d) => (
              <div key={d.label} className="flex gap-3 text-body">
                <span className="w-28 text-text-secondary">{d.label}</span>
                <span className="tabular-nums">{d.value}</span>
              </div>
            ))}
          </Tabs.Content>
        </Tabs.Root>
      ) : null}
    </SidePanel>
  );
}
