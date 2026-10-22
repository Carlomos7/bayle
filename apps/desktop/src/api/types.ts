import type { Problem } from "./client";

// Hand-written mirror of docs/api/openapi.json for what the foundation reads; replaced by the generated types.

export interface Progress {
  done?: number | null;
  total?: number | null;
  label?: string;
}

export type ApiEvent =
  | { seq: number; job_id: string | null; type: "started"; data: { title: string } }
  | { seq: number; job_id: string | null; type: "progress"; data: Progress }
  | { seq: number; job_id: string | null; type: "log"; data: { level: string; text: string } }
  | { seq: number; job_id: string | null; type: "prompt"; data: PromptEventData }
  | { seq: number; job_id: string | null; type: "finished"; data: { result?: unknown; undo?: unknown } }
  | { seq: number; job_id: string | null; type: "failed" | "cancelled"; data: { error: Problem; unexpected?: boolean } }
  | { seq: number; job_id: string | null; type: "resync"; data: { requested: number; oldest: number; seq: number } }
  | { seq: number; job_id: string | null; type: "game.state"; data: { game: string; running: boolean } }
  | { seq: number; job_id: string | null; type: "invalidated"; data: { what: string[] } }
  | { seq: number; job_id: string | null; type: "notice"; data: { text: string; error?: boolean; details?: boolean } }
  | { seq: number; job_id: string | null; type: "navigate"; data: { page: string } };

export interface JobState {
  id: string;
  title: string;
  state: "running" | "done" | "failed" | "cancelled";
  progress: Progress | null;
  log: { level: string; text: string }[];
  error: Problem | null;
}

// ---- prompts: views/common.py (confirm | pick | choose | refusal)
export interface ChoiceOption {
  key: string;
  label: string;
  role?: "primary" | "danger" | "normal";
}

export type PromptWords =
  | {
      kind: "confirm";
      title: string;
      changes: string[];
      apply: string;
      warning?: string;
      safety?: string;
      detail?: string;
      option?: string;
      option_checked?: boolean;
    }
  | {
      kind: "pick";
      title: string;
      body: string;
      apply: string;
      none?: string;
      ticked?: number[];
      /** The row labels. Not in the Python dataclass yet: the backend adds them next to the words. */
      rows?: string[];
    }
  | { kind: "choose"; title: string; lines: string[]; choices: ChoiceOption[]; warning?: string; safety?: string }
  | { kind: "refusal"; title: string; body: string };

/** A prompt event's data: the words plus the id to answer on POST /v1/prompts/{id}. */
export type PromptEventData = PromptWords & { prompt_id: string };

/** PlanAnswer in the contract; a prompt answer only uses `choice`. */
export interface Answer {
  ok: boolean;
  option: boolean;
  choice: string;
  ticked: number[];
}

/** A plan operation's answer (PlanOffer): plan_id null means a refusal. */
export interface PlanOffer {
  plan_id: string | null;
  prompt: PromptWords;
}

export interface ShellState {
  game_name: string;
  game_ready: boolean;
  game_running: boolean;
  profiles: string[];
  profile_index: number;
  status: { text: string; tone: string; busy: boolean; link?: { text: string; action: string } | null };
  pill: { text: string; state: string; can_launch: boolean; mode_text: string };
  unseen: number;
}
