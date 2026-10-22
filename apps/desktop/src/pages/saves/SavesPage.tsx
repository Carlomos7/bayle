import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useApi } from "@/api/backend";
import { toProblem } from "@/components/toasts";
import { Button } from "@/components/ui/button";
import { CharacterSheet } from "./CharacterSheet";
import { DragProvider } from "./drag";
import { LiveSaveCard } from "./LiveSaveCard";
import { NameDialog } from "./NameDialog";
import { SavesProvider, savesKey, useSavesOps, useSavesPage, type NameAsk } from "./ops";
import { RepairPanel } from "./RepairPanel";
import { SavedCopies } from "./SavedCopies";
import { hint, InfoBar, Menu, MenuItem, MenuSeparator } from "./ui";

/**
 * Saves: the two live saves (Standard first) with their characters, and below them the saved copies (Library and
 * Backups). Copy a character, replace a live save with a file, save a copy, back up, import; Check & repair and the
 * character sheet open beside the page. Nothing is written while the game runs. Every word comes from the backend.
 */
export function SavesPage() {
  const api = useApi();
  const qc = useQueryClient();
  const { data, error, isPending, refetch } = useSavesPage();
  const [name, setName] = useState<NameAsk | null>(null);

  // Showing the page also takes in older tools' backup folders (the Qt page's Refresh does the same)
  useEffect(() => {
    api
      .post("/v1/ops/saves.adopt_legacy", {})
      .catch(() => undefined)
      .finally(() => void qc.invalidateQueries({ queryKey: savesKey }));
  }, [api, qc]);

  return (
    <section aria-labelledby="page-title" className="flex flex-col gap-4">
      <h1 id="page-title" className="font-semibold text-page text-title">
        {data?.view.words.title ?? "Saves"}
      </h1>
      {error ? (
        <div className="flex flex-col items-start gap-2">
          <InfoBar severity="error">{toProblem(error).message}</InfoBar>
          <Button onClick={() => void refetch()}>Retry</Button>
        </div>
      ) : isPending ? (
        <p role="status" className={hint}>
          Reading saves...
        </p>
      ) : (
        <SavesProvider view={data.view} askName={setName}>
          <DragProvider>
            <Body />
            <NameDialog ask={name} onClose={() => setName(null)} />
          </DragProvider>
        </SavesProvider>
      )}
    </section>
  );
}

function Body() {
  const ops = useSavesOps();
  const { words, running, running_bar, encrypted, cards } = ops.view;
  const [sheet, setSheet] = useState<{ path: string; slot: number } | null>(null);
  const [repair, setRepair] = useState<{ path: string; slot: number } | null>(null);
  const [filesOver, setFilesOver] = useState(false);
  const opsRef = useRef(ops);
  useEffect(() => {
    opsRef.current = ops;
  });

  // Files dropped from Explorer are imported into the Library (the window hands over their paths)
  useEffect(() => {
    let off: (() => void) | undefined;
    let gone = false;
    void import("@tauri-apps/api/webview")
      .then(({ getCurrentWebview }) =>
        getCurrentWebview().onDragDropEvent((e) => {
          if (e.payload.type === "drop") {
            setFilesOver(false);
            opsRef.current.importPaths(e.payload.paths);
          } else setFilesOver(e.payload.type !== "leave");
        }),
      )
      .then((un) => (gone ? un() : (off = un)))
      .catch(() => undefined); // outside the desktop window there is no file drop
    return () => {
      gone = true;
      off?.();
    };
  }, []);

  return (
    <div className="@container flex flex-col gap-4">
      {running ? <InfoBar severity="warning">{running_bar}</InfoBar> : null}
      {filesOver ? <InfoBar severity="warning">{words.dropImport}</InfoBar> : null}
      <div className="flex min-h-[var(--control-h)] items-center gap-3">
        <p className={`${hint} min-w-0 flex-1`}>{encrypted ? words.nightreign : ""}</p>
        <Button onClick={ops.refresh}>{words.refresh}</Button>
        <Menu label={words.operations ?? ""}>
          <MenuItem onSelect={ops.pickImport}>{words.importAction}</MenuItem>
          <MenuItem disabled={running} onSelect={ops.backUpAll}>
            {words.backUpAll}
          </MenuItem>
          <MenuItem disabled={running} onSelect={ops.postSessionRepair}>
            {words.postSession}
          </MenuItem>
          <MenuSeparator />
          <MenuItem onSelect={() => ops.openFolder("saves")}>{words.openSaves}</MenuItem>
          <MenuItem onSelect={() => ops.openFolder("library")}>{`${words.openFolder} (${words.library})`}</MenuItem>
          <MenuItem onSelect={() => ops.openFolder("backups")}>{`${words.openFolder} (${words.backups})`}</MenuItem>
        </Menu>
      </div>
      {cards.length === 0 ? (
        <p className={hint}>{words.noSaves}</p>
      ) : (
        <div className="grid grid-cols-1 gap-5 @[900px]:grid-cols-2">
          {cards.map((c) => (
            <LiveSaveCard key={c.path} card={c} onSheet={(path, slot) => setSheet({ path, slot })} onRepair={(path) => setRepair({ path, slot: -1 })} />
          ))}
        </div>
      )}
      {cards.length > 0 ? <SavedCopies /> : null}
      {sheet ? (
        <CharacterSheet
          path={sheet.path}
          slot={sheet.slot}
          onClose={() => setSheet(null)}
          onRepair={(path, slot) => {
            setSheet(null);
            setRepair({ path, slot: slot - 1 });
          }}
        />
      ) : null}
      {repair ? <RepairPanel key={`${repair.path}:${repair.slot}`} path={repair.path} slot={repair.slot} onClose={() => setRepair(null)} /> : null}
    </div>
  );
}
