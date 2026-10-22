/** The Mod Configs operations' shapes (session/ops/mod_configs.py, views/mod_configs.py). The page text, the form rows and the panels come ready from the backend; these types only describe them. */

export interface TreeFile {
  path: string;
  name: string;
  /** seamless | form | markdown | text | readme | overhaul */
  kind: string;
  attached: boolean;
}

export interface TreeNode {
  key: string;
  /** seamless | overhaul | native | package */
  kind: string;
  name: string;
  sub: string;
  disabled: boolean;
  disabledTip: string;
  muted: boolean;
  /** The overhaul entry the mod's menu offers. */
  action: "setUp" | "turnOff" | "";
  files: TreeFile[];
}

/** The services ModNode: what the page needs beyond the words. */
export interface RawNode {
  key: string;
  name: string;
  kind: string;
  target: string | null;
  setup: OverhaulSetup | null;
  files: { path: string; how: string; exists: boolean; kind: string }[];
}

export interface PageState {
  profile: string;
  nodes: RawNode[];
  words: Record<string, string>;
  tree: TreeNode[];
}

export interface Row {
  section: string;
  key: string;
  label: string;
  blurb: string;
  help: string;
  /** bool | choice | int | float | text | password | readonly */
  kind: string;
  value: string;
  choices: { value: string; label: string }[];
  lo: number;
  hi: number;
  tip: string;
  default?: string | null;
  onValue: string;
  offValue: string;
}

export interface Section {
  title: string;
  path?: string;
  rows: Row[];
}

export interface SeamlessView {
  hasPassword: boolean;
  password: string;
  presets: string[];
  presetKeys: string[];
  preset: string;
  scaling: { key: string; label: string; value: number }[];
  scalingHint: string;
  presetValues: Record<string, number[]>;
  languages: { value: string; label: string }[];
  language: string;
  fingerprint: string;
  fingerprintNote: string;
}

export interface FileRead {
  path: string;
  text: string;
  encoding: string;
  crlf: boolean;
  sha: string;
  stamp: [number, number] | null;
  has_form: boolean;
  form_note: string;
  sections: Section[];
  seamless: object | null;
  seamless_view: Partial<SeamlessView>;
}

export interface Saved {
  name: string;
  saved: number;
  missing: string[];
  said: string;
  missing_said: string;
}

export interface NativeSetting {
  file: string;
  load_early?: boolean;
  after_others?: boolean;
  initializer?: string | null;
  [more: string]: unknown;
}

export interface FormValues {
  natives: NativeSetting[];
  files: Record<string, string>;
  tables: Record<string, string>;
  health: Record<string, string>;
  health_touched?: boolean;
}

export interface OverhaulSetup {
  path: string | null;
  sha: string | null;
  verified: boolean;
  level: string;
  folder: string | null;
  config: { id: string; label: string; short_label: string };
}

export interface OverhaulView {
  label: string;
  status: string;
  loadsLast: string;
  note: string;
  sections: Section[];
  steps: string[];
  stepsTitle: string;
  isNew: boolean;
  editable: boolean;
}

export interface OverhaulForm {
  setup: OverhaulSetup;
  choices: Record<string, unknown>;
  values: FormValues;
  new: boolean;
  view: OverhaulView;
}

/** A mod proposed as a new overhaul setup. */
export interface Candidate {
  name: string;
  id: string;
  folder: string;
}
