import type { ErrorData, ProgressData } from "@bayle/api";

/** The backend's error body (application/problem+json) and the error inside failed events. */
export type Problem = ErrorData;
export type { ApiEvent, ShellState } from "@bayle/api";
export type Progress = ProgressData;


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
