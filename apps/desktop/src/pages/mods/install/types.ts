/** The Install dialog's view: views/mod_install.py InstallDraft.view() (a plain dict in the contract). */
export type Level = "error" | "warning" | "muted" | "";

export interface Choice {
  value: string;
  label: string;
}

export interface InstallView {
  title: string;
  what: string;
  variants: string[];
  variant: string;
  name: string;
  id: string;
  nameLabel: string;
  where: string;
  idShown: boolean;
  idNote: string;
  idError: boolean;
  nameError: boolean;
  items: { name: string; what: string; size: string; on: boolean; tip: string }[];
  regulation: {
    shown: boolean;
    about?: string;
    effect?: string;
    effectLevel?: Level;
    places?: string[];
    placeIndex?: number;
    placeShown?: boolean;
    rebuildShown?: boolean;
    rebuildText?: string;
    rebuild?: boolean;
    notes?: string;
  };
  last: { shown: boolean; text?: string; level?: Level; check?: string; on?: boolean };
  note: string;
  noteLevel: Level;
  option: {
    shown: boolean;
    hint?: string;
    ticked?: boolean;
    locked?: boolean;
    text?: string;
    level?: Level;
    badge?: string;
    badgeLevel?: "success" | "warning";
  };
  library: { shown: boolean; text?: string; options?: { key: string; text: string }[]; choice?: string };
  overhaul: { shown: boolean; ready?: boolean; lines?: string[]; notes?: string[]; refusals?: string[] };
  natives: { file: string; load_early?: boolean; after_others?: boolean; initializer?: string | null }[];
  files: { file: string; action: string; target: string; choices: Choice[] }[];
  texts: { file: string; label: string; table: string; choices: Choice[]; chosen: string }[];
  mode: "" | "matched" | "setup";
  profilesInside: boolean;
  canInstall: boolean;
  busy: boolean;
  installText: string;
  error: string;
  words: Record<string, string>;
}

/** mods.install_open / _edit / _replan / _preview */
export interface DraftReply {
  draft_id: string;
  view: InstallView;
  pending: boolean;
}

export interface EditParams {
  field:
    | "name"
    | "id"
    | "variant"
    | "overhaul"
    | "tick"
    | "place_last"
    | "rebuild"
    | "after_last"
    | "library"
    | "native"
    | "table"
    | "file";
  key?: string;
  text?: string;
  on?: boolean;
  kind?: "early" | "after" | "init";
}
