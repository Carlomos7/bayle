import { useMemo } from "react";
import { useApi } from "@/api/backend";
import { ApiError } from "@/api/client";
import { sonnerToasts } from "@/components/toasts";
import type { PlanOffer } from "@/api/types";

/** The Mod Configs operations: one POST each (session/ops/mod_configs.py). */
export function useModOps() {
  const api = useApi();
  return useMemo(
    () => ({
      run: <T>(name: string, params: object = {}) => api.post<T>(`/v1/ops/${name}`, params),
      plan: (name: string, params: object) => api.post<PlanOffer>(`/v1/ops/${name}`, params),
      answer: (planId: string, answer: object) => api.post<{ job_id?: string | null }>(`/v1/plans/${planId}`, answer),
    }),
    [api],
  );
}

export const code = (e: unknown) => (e instanceof ApiError ? e.problem.code : "");
export const message = (e: unknown) => (e instanceof ApiError ? e.problem.message : e instanceof Error ? e.message : String(e));

/** A refusal in a toast, the way the Qt page says it: "Title. Words." */
export function refuse(title: string, body: string) {
  sonnerToasts.notice(`${title}. ${body}`, { error: true });
}

export const say = (text: string) => sonnerToasts.notice(text);

/**
 * An operation said no: the code says why. Same cases as the Qt adapter (_failed).
 */
export function failed(e: unknown, words: Record<string, string>) {
  const text = message(e);
  switch (code(e)) {
    case "password_empty":
      return refuse(words.emptyPasswordTitle ?? "", words.emptyPasswordBody ?? text);
    case "cannot_set_up":
      return refuse(words.cantSetUp ?? "", text);
    case "cannot_turn_off":
      return refuse(words.cantTurnOff ?? "", text);
    case "not_settings":
      return refuse(words.notSettingsTitle ?? "", (words.notSettingsBody ?? "{why}").replace("{why}", text));
    case "nothing_to_change":
      return say(text);
    case "busy":
    case "plan_stale":
    case "plan_expired":
    case "unknown_plan":
      return sonnerToasts.notice(text, { error: true });
    default:
      return refuse(words.notSavedTitle ?? "", text);
  }
}
