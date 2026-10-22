import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { DragHandle, useDropSpot } from "./drag";
import { useSavesOps } from "./ops";
import type { Card as CardData, SlotRow } from "./types";
import { Card, hint, Menu, MenuItem, MenuSeparator, MenuSub, Pill, sectionTitle } from "./ui";

/**
 * One live save (Standard or Seamless Co-op): kind and file, one health pill, all ten slots (empty ones are where a
 * character can be dropped or copied to) and the footer. Everything shown comes from the backend (views.saves.card).
 */
export function LiveSaveCard({
  card,
  onSheet,
  onRepair,
}: {
  card: CardData;
  onSheet: (path: string, slot: number) => void;
  onRepair: (path: string) => void;
}) {
  const ops = useSavesOps();
  const { words, running } = ops.view;
  const spot = useDropSpot({ type: "card", path: card.path, free: card.freeSlots });
  const note = card.error || card.contents;
  return (
    <Card aria-label={`${card.kind} ${card.file}`} className={cn("flex flex-col", spot.className)} {...spot.props}>
      <div className="flex items-center gap-3 px-4 py-3">
        <DragHandle source={{ type: "live", path: card.path, label: `${card.kind}  ·  ${card.file}` }} />
        <div className="min-w-0 flex-1">
          <h2 className={sectionTitle}>{card.kind}</h2>
          <p className={cn(hint, "truncate")}>
            {[card.file, card.modified, card.role].filter(Boolean).join("  ·  ")}
          </p>
        </div>
        <Pill level={card.healthLevel}>{card.health}</Pill>
      </div>
      {note ? <p className={cn(hint, "px-4 pb-2")}>{note}</p> : null}
      <ul aria-label={card.kind} className="max-h-[272px] overflow-auto border-t border-border-hairline">
        {card.slots.map((s) => (
          <Slot key={s.slot} card={card} row={s} onSheet={onSheet} />
        ))}
      </ul>
      <div className="flex items-center gap-2 px-4 py-3">
        <Button variant={card.canRepair ? "primary" : "ghost"} onClick={() => onRepair(card.path)}>
          {words.checkRepair}
        </Button>
        <Menu label={`${words.operations} (${card.file})`}>
          <MenuItem disabled={running} onSelect={() => ops.backUp(card.path)}>
            {words.backUpNow}
          </MenuItem>
          {/* only reads the live save: allowed while the game runs */}
          <MenuItem onSelect={() => ops.askCopyName(card.path)}>{words.saveCopy}</MenuItem>
          <MenuItem disabled={running} onSelect={() => ops.replaceFromFile(card.path)}>
            {words.replaceWith}
          </MenuItem>
          <MenuSub label={words.replaceLibrary ?? ""}>
            {ops.view.library_rows.slice(0, 8).map((r) => (
              <MenuItem
                key={`${r.folder}/${r.id}`}
                disabled={running || r.missing || r.stranded}
                onSelect={() => ops.replaceFromLibrary(r.folder, r.id, card.path)}
              >
                {r.name}
              </MenuItem>
            ))}
          </MenuSub>
          <MenuSeparator />
          <MenuItem onSelect={() => ops.copyReport(card.path)}>{words.copyReport}</MenuItem>
          <MenuItem onSelect={() => ops.openSaveFolder(card.path)}>{words.openFolder}</MenuItem>
        </Menu>
      </div>
    </Card>
  );
}

function Slot({ card, row, onSheet }: { card: CardData; row: SlotRow; onSheet: (path: string, slot: number) => void }) {
  const ops = useSavesOps();
  const { words, running, copy_targets } = ops.view;
  const spot = useDropSpot({ type: "slot", path: card.path, slot: row.slot });
  const copyable = !row.empty && !running && card.canCopyCharacters && row.runes !== "";
  const source = { type: "character", path: card.path, slot: row.slot, label: `${row.name}  ·  ${row.levelText}` } as const;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    if (e.key === "c" && copyable) {
      ops.copyKey(source);
      e.preventDefault();
    } else if (e.key === "v") {
      ops.pasteInto({ type: "slot", path: card.path, slot: row.slot });
      e.preventDefault();
    }
  };

  return (
    <li className={cn("flex items-center gap-1 border-b border-border-hairline px-2", row.empty ? "h-8" : "h-12", spot.className)} {...spot.props}>
      {copyable ? <DragHandle source={source} /> : <span className="size-6 shrink-0" />}
      <button
        type="button"
        aria-disabled={row.empty}
        onKeyDown={onKeyDown}
        onClick={() => !row.empty && onSheet(card.path, row.slot)}
        className={cn(
          "flex h-full min-w-0 flex-1 items-center gap-2 rounded-control px-1 text-left",
          row.empty ? "cursor-default" : "hover:bg-fill-ghost-hover",
        )}
      >
        <span className="w-5 shrink-0 text-caption text-text-secondary">{row.slot}</span>
        <span className={cn("min-w-0 flex-1 truncate", row.empty ? "text-caption text-text-secondary" : "text-row text-text-primary")}>
          {row.name}
        </span>
        {row.mark ? <Pill level="warning">{row.mark}</Pill> : null}
        <span className="shrink-0 text-caption text-text-secondary">
          {row.levelText}
          {row.runes ? `  ·  ${row.runes}` : ""}
        </span>
      </button>
      {!row.empty ? (
        <Menu label={`${words.copyTo} (${row.name})`} disabled={!copyable}>
          {copyable
            ? copy_targets
                .filter((t) => !(t.path === card.path && t.slot === row.slot))
                .map((t) => (
                  <MenuItem
                    key={`${t.path}:${t.slot}`}
                    danger={t.danger}
                    onSelect={() => ops.copyCharacter(card.path, row.slot, t.path, t.slot)}
                  >
                    {t.label}
                  </MenuItem>
                ))
            : null}
        </Menu>
      ) : (
        <span className="size-8 shrink-0" />
      )}
    </li>
  );
}
