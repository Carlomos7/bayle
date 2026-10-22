import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useApi } from "@/api/backend";
import { pageKey } from "@/api/events";
import type { ShellState } from "@/api/types";
import { onBundled, takeBundled, type BundledRequest } from "./bundled";
import { ExportView } from "./ExportView";
import { ImportView } from "./ImportView";
import { Segmented } from "./ui";
import { W } from "./words";

type Mode = "export" | "import";

/** The page body. The route supplies the shell's facts; tests supply them directly. */
export function ProfileTransfer({
  profilePath,
  profileName,
  busy,
  gameRunning,
  onLeave,
}: {
  profilePath: string;
  profileName: string;
  busy: boolean;
  gameRunning: boolean;
  onLeave: () => void;
}) {
  const [mode, setMode] = useState<Mode>("export");
  const [bundled, setBundled] = useState<BundledRequest | null>(takeBundled);
  useEffect(() => onBundled(() => setBundled(takeBundled())), []);

  const importing = mode === "import" || !!bundled;
  return (
    <section aria-labelledby="page-title" className="flex flex-col gap-4">
      <h1 id="page-title" className="font-semibold text-page text-title">
        Profile transfer
      </h1>
      {!profilePath ? (
        <p className="text-text-secondary">{W.noProfile}</p>
      ) : (
        <>
          {bundled ? null : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-title">
                {importing ? W.importingInto : W.exportingProfile} <strong className="text-accent">{profileName}</strong>
              </p>
              <Segmented<Mode>
                label="Mode"
                value={mode}
                options={[
                  { value: "export", label: W.tabExport },
                  { value: "import", label: W.tabImport },
                ]}
                onChange={setMode}
              />
            </div>
          )}
          <div hidden={importing}>
            <ExportView key={profilePath} profile={profilePath} busy={busy} gameRunning={gameRunning} />
          </div>
          {importing ? (
            <ImportView
              // each handed-over download is a new view
              key={bundled ? `bundled:${bundled.unpacked}` : "import"}
              profile={profilePath}
              busy={busy}
              bundled={bundled ?? undefined}
              onLeave={() => {
                setBundled(null);
                onLeave();
              }}
              onImported={() => {
                if (bundled) {
                  setBundled(null);
                  setMode("import");
                }
              }}
            />
          ) : null}
        </>
      )}
    </section>
  );
}

export function ProfileTransferPage() {
  const api = useApi();
  const navigate = useNavigate();
  const { data: shell } = useQuery({
    queryKey: pageKey("shell"),
    queryFn: () => api.get<ShellState>("/v1/pages/shell"),
  });
  return (
    <ProfileTransfer
      profilePath={shell?.profile_path ?? ""}
      profileName={shell?.profiles[shell.profile_index] ?? ""}
      busy={!!shell?.status.busy}
      gameRunning={!!shell?.game_running}
      onLeave={() => void navigate({ to: "/mods" })}
    />
  );
}
