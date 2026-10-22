import type {
  Dependency,
  DragTable,
  Group,
  Leftovers,
  LibraryRows,
  LoadOrderPanel,
  ModsView,
  MoveResult,
  Notice,
  OptionsView,
  Row,
  SettingResult,
  SettingsView,
  Unlisted,
  VersionRow,
} from "@bayle/api";
import type { PromptWords } from "@/api/types";
import type { WordKey } from "./word-keys";

export type { Notice, Dependency, DragTable, Group, Leftovers, LibraryRows, LoadOrderPanel, ModsView, MoveResult, OptionsView, Row, SettingResult, SettingsView, Unlisted, VersionRow };

/** The page's fixed labels and toast templates, by key (ModsView.words): the known keys are strings, a computed key may be missing. */
export type Words = Readonly<Record<WordKey, string>> & Readonly<Record<string, string | undefined>>;
export const fill = (template: string | undefined, values: Record<string, string | number>) =>
  Object.entries(values).reduce((t, [k, v]) => t.replaceAll(`{${k}}`, String(v)), template ?? "");

/** A job as GET /v1/jobs/{id} answers. */
export interface JobDone {
  id: string;
  state: "running" | "done" | "failed" | "cancelled";
  result: Record<string, unknown> | null;
  undo: Record<string, unknown> | null;
  error: { code: string; message: string } | null;
}

export interface Changed {
  note: string;
  name?: string;
}

export type PickWords = Extract<PromptWords, { kind: "pick" }>;
export interface PickOffer {
  label?: string;
  prompt?: PickWords | null;
}

export type LibraryRow = { name: string; size: string; versions: { title: string; size: string; usedBy: string; unused: boolean }[] };

/** The entry dicts of ModsView.entries, as far as the page reads them. */
export interface Entry {
  index: number;
  kind: string;
  name: string;
}

/** What the Install mod dialog (another work package) is asked for. */
export interface InstallRequest {
  /** "file" = an archive or DLL, "folder" = an unpacked mod; absent: the dialog asks. */
  from?: "file" | "folder";
  /** Paths dropped on the page, installed in turn. */
  paths?: string[];
}
