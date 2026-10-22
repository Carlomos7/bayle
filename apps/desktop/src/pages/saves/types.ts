import type { PromptWords } from "@/api/types";

/** The Saves page's data: GET /v1/pages/saves `view` is views.saves worded by the backend (src/bayle/session/ops/saves.py). */
export type Level = "success" | "warning" | "danger";

export interface SlotRow {
  slot: number;
  name: string;
  level: number;
  levelText: string;
  runes: string;
  mark: string;
  body: string;
  empty: boolean;
}

export interface Card {
  path: string;
  kind: string;
  file: string;
  modified: string;
  role: string;
  health: string;
  healthLevel: Level;
  characters: SlotRow[];
  freeSlots: number[];
  slots: SlotRow[];
  canRepair: boolean;
  canCopyCharacters: boolean;
  contents: string;
  error: string;
}

export interface LibraryRow {
  id: string;
  folder: string;
  name: string;
  when: string;
  tag: string;
  who: string;
  missing: boolean;
  stranded: boolean;
  characters: { slot: number; name: string; levelText: string }[];
  note: string;
}

export interface BackupRow {
  path: string;
  name: string;
  time: string;
  trigger: string;
  action: string;
  kept: boolean;
  unreadable: boolean;
  size: string;
}

export interface CopyTarget {
  path: string;
  slot: number;
  danger: boolean;
  label: string;
}

export interface SavesView {
  words: Record<string, string>;
  game_name: string;
  running: boolean;
  encrypted: boolean;
  running_bar: string;
  cards: Card[];
  copy_targets: CopyTarget[];
  library_rows: LibraryRow[];
  library_problems: string[];
  backup_days: { day: string; rows: BackupRow[] }[];
  retention: string;
}

export interface SavesPageData {
  view: SavesView;
}

export interface Sheet {
  slot: number;
  name: string;
  level: number;
  body: string;
  where: string;
  torrent: string;
  runes: string;
  memory: string;
  attributes: { label: string; value: number }[];
  levelFromAttributes: number;
  derived: { label: string; value: string }[];
  mods: string;
  findings: { title: string; count: number }[];
}

export interface RepairItem {
  key: string;
  label: string;
  sub: string;
  checked: boolean;
  enabled: boolean;
  note: string;
}

export interface RepairGroup {
  id: string;
  title: string;
  hint: string;
  items: RepairItem[];
}

export interface RepairViewData {
  card: Card;
  groups: RepairGroup[];
  damaged: { title: string; detail: string }[];
  tuples: Record<string, (string | number)[]>;
  ticked: string[];
  summary: string;
  button: string;
}

export interface Written {
  text: string;
  save: string | null;
  backup: string | null;
  undo: Record<string, unknown> | null;
}

export interface CopyEntry {
  name: string;
  path: string;
  changed_outside: boolean;
  outside: PromptWords | null;
}

/** What a drag carries (views.saves.drop); `label` is only for the ghost and is not sent. */
export type DragSource =
  | { type: "character"; path: string; slot: number; label: string }
  | { type: "live"; path: string; label: string }
  | { type: "copy"; folder: string; id: string; missing: boolean; label: string }
  | { type: "copychar"; folder: string; id: string; slot: number; label: string }
  | { type: "backup"; path: string; label: string };

/** Where it can land. */
export type DropTarget =
  | { type: "slot"; path: string; slot: number }
  | { type: "card"; path: string; free: number[] }
  | { type: "library" }
  | { type: "backups" };

export interface Dropped {
  reason: string;
  call: string;
  args: (string | number)[];
}
