import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type { SettingsState, SettingSpec, ShellState } from "@bayle/api";
import { useApi } from "@/api/backend";
import { pageKey } from "@/api/events";
import { sonnerToasts, toProblem } from "@/components/toasts";
import { Button } from "@/components/ui/button";
import { openFolder, openLink, pickFile, pickFolder } from "@/lib/native";
import { PathButtons, Row, Section, SettingControl, type Value } from "./controls";
import { LayoutSection } from "./LayoutSection";
import { UpdateNotices } from "./UpdateNotices";
import { useSetSetting, useSettingsState } from "./useSettings";
import { FOLDER_KIND, GITHUB, SAID, W } from "./words";

type Me3Facts = { version?: string; latest?: { version?: string }; update?: boolean; error?: string };
const me3Text = (f: Me3Facts | undefined) => {
  if (!f) return W.me3Reading;
  if (f.error) return `me3: ${f.error}`;
  const latest = f.latest?.version;
  let t = f.version ? `me3 ${f.version}` : "me3 version unknown";
  if (f.update && latest) t += `  ·  ${latest} is available`;
  else if (f.version && latest) t += "  ·  up to date";
  return t;
};

/** "Game (*.exe)" -> ["exe"] */
const extensionsOf = (filter: string) => [...filter.matchAll(/\*\.(\w+)/g)].map((m) => m[1] as string);

export function SettingsPage() {
  const { data: state, error, isPending, refetch } = useSettingsState();
  return (
    <section aria-labelledby="page-title" className="flex flex-col gap-4">
      <h1 id="page-title" className="font-semibold text-page text-title">
        Settings
      </h1>
      {isPending ? (
        <p role="status" className="text-text-secondary">
          {W.loading}
        </p>
      ) : error ? (
        <div role="alert" className="flex items-center gap-3 text-status-danger">
          {toProblem(error).message}
          <Button onClick={() => void refetch()}>Retry</Button>
        </div>
      ) : (
        <Loaded state={state} />
      )}
    </section>
  );
}

function Loaded({ state }: { state: SettingsState }) {
  const api = useApi();
  const qc = useQueryClient();
  const { set, errors } = useSetSetting();
  const specs = new Map<string, SettingSpec>(state.specs.map((s) => [s.key, s]));
  const shell = useQuery({ queryKey: pageKey("shell"), queryFn: () => api.get<ShellState>("/v1/pages/shell") });
  const updates = shell.data?.updates;

  const run = <T,>(name: string, params: object = {}) => api.post<T>(`/v1/ops/${name}`, params);
  const fail = { onError: sonnerToasts.error };

  // no toast: the line itself says why me3 could not be read (no game yet, for one)
  const me3 = useMutation({ mutationFn: () => run<{ facts: Me3Facts }>("shell.me3") });
  const openKind = useMutation({
    mutationFn: async (kind: string) => {
      const got = await run<{ path: string | null }>("settings.folder", { kind });
      if (got.path === null) sonnerToasts.notice(SAID.folderMissing, { error: true });
      else await openFolder(got.path);
    },
    ...fail,
  });
  const readMe3 = me3.mutate;
  useEffect(() => readMe3(), [readMe3]); // like the Qt page, ask me3 when the page opens
  const clear = useMutation({ mutationFn: () => run("settings.clear_leftovers"), ...fail });
  const check = useMutation({
    mutationFn: () => run("shell.check_updates"),
    onSettled: () => qc.invalidateQueries({ queryKey: pageKey("shell") }),
    ...fail,
  });
  const steam = useMutation({
    mutationFn: () => run<{ changed: string[] }>("shell.steam_shortcuts"),
    onSuccess: ({ changed }) =>
      sonnerToasts.notice(changed.length ? SAID.steamChanged(changed.join(", ")) : SAID.steamNothing),
    ...fail,
  });
  const saveLogs = useMutation({
    mutationFn: async () => {
      const folder = await pickFolder(SAID.pickLogs);
      if (!folder) return;
      const got = await run<{ path: string }>("shell.save_logs", { folder });
      sonnerToasts.notice(SAID.logsSaved(got.path.split(/[\\/]/).pop() ?? got.path));
    },
    ...fail,
  });
  const copy = (text: string) =>
    navigator.clipboard.writeText(text).then(() => sonnerToasts.notice(W.copied), sonnerToasts.error);
  const link = (url: string) => void openLink(url).catch(sonnerToasts.error);

  const valueOf = (key: string): Value => {
    const spec = specs.get(key);
    if (spec?.kind === "switch") return state.switches.find((s) => s.key === key)?.checked ?? false;
    if (spec?.kind === "location") return state.locations.find((l) => l.key === key)?.value ?? "";
    return (state as unknown as Record<string, Value>)[key] ?? "";
  };
  /** One setting, rendered from its spec. */
  const setting = (key: string, label: string, help?: string) => {
    const spec = specs.get(key);
    if (!spec) return null;
    const loc = state.locations.find((l) => l.key === key);
    return (
      <SettingControl
        key={key}
        spec={spec}
        value={valueOf(key)}
        label={label}
        help={help}
        error={errors[key]}
        choices={state.choices[key]}
        placeholder={loc?.placeholder}
        onChange={(value) => set({ key, value })}
        extra={
          loc ? (
            <PathButtons
              hasValue={loc.value !== ""}
              onBrowse={async () => {
                const picked = loc.is_dir
                  ? await pickFolder(SAID.pickFolder)
                  : await pickFile(SAID.pickFile, (loc.filter ?? "").replace(/\s*\(.*$/, "") || "File", extensionsOf(loc.filter ?? ""));
                if (picked) set({ key, value: picked });
              }}
              onClear={() => set({ key, value: "" })}
              onOpen={() => openKind.mutate(FOLDER_KIND[key] ?? "")}
            />
          ) : null
        }
      />
    );
  };
  const switches = (group: string) =>
    state.switches
      .filter((s) => s.group === group && s.shown)
      .map((s) => setting(s.key, s.title, [s.blurb, s.help].filter(Boolean).join(" ")));
  const version = state.launcher_line.split("  ·  ")[0] ?? "";

  return (
    <div className="flex flex-col gap-4">
      <UpdateNotices notices={updates?.notices ?? []} />

      <Section title={W.locations}>
        {state.locations.map((l) => setting(l.key, l.title, l.help))}
        <LayoutSection state={state} openKind={(k) => openKind.mutate(k)} />
        <Row title={me3.error ? `me3: ${toProblem(me3.error).message}` : me3Text(me3.data?.facts)}>
          <Button onClick={() => me3.mutate()}>{W.readMe3}</Button>
        </Row>
        {switches("me3")}
      </Section>

      <Section title={W.launch}>
        <Row title="" help={W.launchHint} />
        {switches("launch")}
        <Row title={W.leftover} help={W.leftoverHelp}>
          <Button onClick={() => clear.mutate()}>{W.clearNow}</Button>
        </Row>
        <Row title={W.offline} help={W.offlineBlurb} />
        {switches("offline")}
        <Row title={W.steam} help={W.steamHelp}>
          <Button onClick={() => void copy(state.steam_target)}>{W.copyTarget}</Button>
          <Button onClick={() => void copy(state.steam_options)}>{W.copyOptions}</Button>
          <Button onClick={() => steam.mutate()}>{W.pointSteam}</Button>
        </Row>
      </Section>

      <Section title={W.backups}>
        <Row title={W.backupsLocation} help={W.backupsLocationHelp}>
          <span className="max-w-80 truncate text-caption text-text-secondary" title={state.backups_location}>
            {state.backups_location}
          </span>
          <Button onClick={() => openKind.mutate("backups")}>{W.openFolder}</Button>
        </Row>
        {setting("backups_keep", W.backupsKeep, W.backupsKeepHelp)}
      </Section>

      <Section title={W.appearance}>
        {setting("theme", W.theme, W.themeHelp)}
        {setting("effects", W.effects, W.effectsHelp)}
        {state.effects === "off" ? null : setting("grain", W.grain, W.grainHelp)}
        {setting("logo", W.logo, W.logoHelp)}
      </Section>

      <Section title={W.updates}>
        <Row title={version} help={updates?.line || state.launcher_line}>
          <Button disabled={updates?.checking} onClick={() => check.mutate()}>
            {W.check}
          </Button>
          <Button onClick={() => link(`${GITHUB}/releases`)}>{W.releases}</Button>
        </Row>
        {setting("launcher_channel", W.channel, W.channelHelp)}
        {switches("updates")}
      </Section>

      <Section title={W.logs}>
        <Row title={W.logsFolder}>
          <Button onClick={() => openKind.mutate("logs")}>{W.openFolder}</Button>
        </Row>
        <Row title={W.saveLogs} help={W.saveLogsHelp}>
          <Button onClick={() => saveLogs.mutate()}>{W.save}</Button>
        </Row>
        <Row title={W.settingsFolder} help={state.data_folder}>
          <Button onClick={() => openKind.mutate("settings")}>{W.openFolder}</Button>
        </Row>
        {setting("log_level", W.logLevel, W.logLevelHelp)}
      </Section>

      <Section title={W.about}>
        <Row title={version} help={W.aboutHelp}>
          <Button onClick={() => link(`${GITHUB}/blob/main/LICENSE`)}>{W.licence}</Button>
          <Button onClick={() => link(`${GITHUB}/blob/main/THIRD_PARTY_NOTICES.md`)}>{W.notices}</Button>
        </Row>
      </Section>
    </div>
  );
}
