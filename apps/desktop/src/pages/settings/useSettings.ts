import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { SettingsState } from "@bayle/api";
import { useApi } from "@/api/backend";
import { ApiError } from "@/api/client";
import { pageKey } from "@/api/events";
import { sonnerToasts, toProblem } from "@/components/toasts";
import { useTheme, type LogoSetting, type ThemeSetting } from "@/theme/ThemeProvider";

export const SETTINGS_KEY = pageKey("settings");

export function useSettingsState() {
  const api = useApi();
  return useQuery({ queryKey: SETTINGS_KEY, queryFn: () => api.get<SettingsState>("/v1/pages/settings") });
}

interface Changed {
  key: string;
  value: boolean | number | string;
  said: string;
}

/** Problems of one value; the sentence belongs under its control, anything else is a toast. */
const INLINE = new Set(["invalid_value", "invalid_choice", "path_problem"]);

/** settings.set for any spec. `errors` holds the refusal sentence of each key until its next save. */
export function useSetSetting() {
  const api = useApi();
  const qc = useQueryClient();
  const { setTheme, setLogo } = useTheme();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const mutation = useMutation({
    mutationFn: (v: { key: string; value: boolean | number | string }) => api.post<Changed>("/v1/ops/settings.set", v),
    onMutate: ({ key, value }) => {
      setErrors((e) => ({ ...e, [key]: "" }));
      if (key === "theme") setTheme(value as ThemeSetting);
      if (key === "logo") setLogo(value as LogoSetting);
    },
    onSuccess: (got) => {
      if (got.said) sonnerToasts.notice(got.said);
    },
    onError: (error, { key }) => {
      if (error instanceof ApiError && INLINE.has(error.problem.code)) setErrors((e) => ({ ...e, [key]: error.problem.message }));
      else sonnerToasts.error(error);
    },
    // a refused change is read again too, so the control shows what is saved
    onSettled: () => qc.invalidateQueries({ queryKey: SETTINGS_KEY }),
  });
  return { set: mutation.mutate, errors };
}

/** Run an op whose answer is not needed; a failure is a toast. */
export function useOp<P extends object>(name: string, onDone?: (got: unknown) => void) {
  const api = useApi();
  return useMutation({
    mutationFn: (p: P | undefined) => api.post<unknown>(`/v1/ops/${name}`, p ?? {}),
    onSuccess: onDone,
    onError: (e) => sonnerToasts.error(toProblem(e)),
  });
}
