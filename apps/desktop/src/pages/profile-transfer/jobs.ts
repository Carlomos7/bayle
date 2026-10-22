import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/api/backend";
import { jobKey } from "@/api/events";
import type { JobState } from "@/api/types";

interface JobBody {
  id: string;
  title: string;
  state: JobState["state"];
  progress?: JobState["progress"];
  error?: JobState["error"];
  result?: unknown;
}

/** A job the page follows: the SSE events keep ["jobs", id] current; the first read covers events missed before. */
export function useJob(id: string | null): JobState | undefined {
  const api = useApi();
  const qc = useQueryClient();
  return useQuery({
    queryKey: jobKey(id ?? ""),
    enabled: !!id,
    staleTime: Infinity,
    queryFn: async (): Promise<JobState> => {
      const j = await api.get<JobBody>(`/v1/jobs/${id}`);
      const fresher = qc.getQueryData<JobState>(jobKey(id ?? "")); // events that arrived meanwhile win
      if (fresher) return fresher;
      return { ...j, progress: j.progress ?? null, error: j.error ?? null, log: [] };
    },
  }).data;
}

/** The result of a finished job (the events carry state only). */
export function useJobResult<T>(id: string | null, state: JobState["state"] | undefined): T | undefined {
  const api = useApi();
  return useQuery({
    queryKey: [...jobKey(id ?? ""), "result"],
    enabled: !!id && state === "done",
    staleTime: Infinity,
    queryFn: async () => (await api.get<JobBody>(`/v1/jobs/${id}`)).result as T,
  }).data;
}

/** The detail the transfer jobs add to a progress event (not in the contract's schema). */
export const detailOf = (p: JobState["progress"]) => (p as { detail?: { n?: number; count?: number } } | null)?.detail;
