import { useMutation, useQuery, useQueryClient, type UseMutationOptions } from "@tanstack/react-query";
import { useApi } from "./backend";
import { jobKey, pageKey } from "./events";
import type { JobState, PlanOffer } from "./types";
import { usePrompts } from "@/components/PromptHost";
import { sonnerToasts } from "@/components/toasts";

/** Filters as the query string of a page route; empty, false and undefined values are left out. */
function search(filters: Record<string, string | number | boolean | undefined> | undefined): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(filters ?? {})) if (v !== undefined && v !== "" && v !== false) q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

/**
 * A backend page (GET /v1/pages/{key}) as a query under ["page", key, filters].
 * `key` is the route's name (snake case, e.g. "mod_configs"). Events invalidate ["page", name] or every page, so the data
 * stays current without the page doing anything. Filters go in the query string; changing them is a new query.
 */
export function usePage<T>(key: string, filters?: Record<string, string | number | boolean | undefined>) {
  const api = useApi();
  return useQuery({
    queryKey: [...pageKey(key), filters ?? {}],
    queryFn: () => api.get<T>(`/v1/pages/${key}${search(filters)}`),
  });
}

/**
 * An operation (POST /v1/ops/{name}) as a mutation: `mutate(params)` resolves with the result (a read or command), `{job_id}`
 * (a job; follow it with useJob, its toasts come from the event stream), or a PlanOffer (use usePlanOp for those).
 * A failure shows the backend's message as a toast unless `onError` is given.
 */
export function useOp<R = unknown, P = Record<string, never>>(
  name: string,
  options: Omit<UseMutationOptions<R, Error, P>, "mutationFn"> = {},
) {
  const api = useApi();
  return useMutation<R, Error, P>({
    onError: (e) => sonnerToasts.error(e),
    ...options,
    mutationFn: (params) => api.post<R>(`/v1/ops/${name}`, params ?? {}),
  });
}

/**
 * A plan operation: the offer opens the confirm/pick dialog (PromptHost posts the answer to /v1/plans/{id}); a refusal
 * (plan_id null) is only told. `onOffered` runs with the offer, e.g. to refresh the page after a refusal.
 */
export function usePlanOp<P = Record<string, never>>(name: string, onOffered?: (offer: PlanOffer) => void) {
  const { offerPlan } = usePrompts();
  return useOp<PlanOffer, P>(name, {
    onSuccess: (offer) => {
      offerPlan(offer);
      onOffered?.(offer);
    },
  });
}

/** A job's live state (title, progress, log, outcome) from ["jobs", id], fed by the event stream; undefined until it starts or for no id. */
export function useJob(id: string | null | undefined): JobState | undefined {
  const qc = useQueryClient();
  return useQuery<JobState | undefined>({
    queryKey: jobKey(id ?? ""),
    queryFn: () => qc.getQueryData<JobState>(jobKey(id ?? "")),
    enabled: false,
    staleTime: Infinity,
  }).data;
}
