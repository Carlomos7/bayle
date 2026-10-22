import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { pageKey } from "@/api/events";
import { useApi } from "@/api/backend";
import { sonnerToasts, toProblem } from "@/components/toasts";

/**
 * Run a shell operation (POST /v1/ops/{name}). A refusal (cannot_launch, busy, folder_unknown...) is told with the
 * backend's own words and gives undefined; the page of the shell is read again either way.
 */
export function useShellOp() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useCallback(
    async <T = unknown>(name: string, params: object = {}): Promise<T | undefined> => {
      try {
        return await api.post<T>(`/v1/ops/${name}`, params);
      } catch (e) {
        sonnerToasts.notice(toProblem(e).message, { error: true });
        return undefined;
      } finally {
        void queryClient.invalidateQueries({ queryKey: pageKey("shell") });
      }
    },
    [api, queryClient],
  );
}
