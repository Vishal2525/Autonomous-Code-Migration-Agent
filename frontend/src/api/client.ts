import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import type {
  DiffResponse,
  EventItem,
  Plan,
  Report,
  Run,
  Task,
  TestRecord,
} from "../types";

export const api = axios.create({ baseURL: "/api" });

export interface CreateRunPayload {
  repository_url: string;
  goal: string;
  source_tech: string;
  target_tech: string;
  mode: "AUTO" | "HITL";
}

export function useRuns() {
  return useQuery({
    queryKey: ["runs"],
    queryFn: async () => (await api.get<Run[]>("/runs")).data,
    refetchInterval: 4000,
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: async () => (await api.get<Run>(`/runs/${runId}`)).data,
    enabled: !!runId,
    refetchInterval: 3000,
  });
}

export function usePlan(runId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["plan", runId],
    queryFn: async () => (await api.get<Plan>(`/runs/${runId}/plan`)).data,
    enabled: !!runId && enabled,
    retry: false,
    refetchInterval: 5000,
  });
}

export function useTasks(runId: string | undefined) {
  return useQuery({
    queryKey: ["tasks", runId],
    queryFn: async () => (await api.get<Task[]>(`/runs/${runId}/tasks`)).data,
    enabled: !!runId,
    refetchInterval: 4000,
  });
}

export function useDiff(runId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["diff", runId],
    queryFn: async () => (await api.get<DiffResponse>(`/runs/${runId}/diff`)).data,
    enabled: !!runId && enabled,
    refetchInterval: 8000,
  });
}

export function useTests(runId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["tests", runId],
    queryFn: async () => (await api.get<TestRecord[]>(`/runs/${runId}/tests`)).data,
    enabled: !!runId && enabled,
    refetchInterval: 6000,
  });
}

export function useReport(runId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["report", runId],
    queryFn: async () => (await api.get<Report>(`/runs/${runId}/report`)).data,
    enabled: !!runId && enabled,
    retry: false,
    refetchInterval: 8000,
  });
}

export function useEvents(runId: string | undefined) {
  return useQuery({
    queryKey: ["events", runId],
    queryFn: async () =>
      (await api.get<EventItem[]>(`/runs/${runId}/events?limit=500`)).data,
    enabled: !!runId,
  });
}

export function useCreateRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CreateRunPayload) => {
      const run = (await api.post<Run>("/runs", payload)).data;
      await api.post(`/runs/${run.run_id}/start`);
      return run;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useRunAction(runId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (action: "pause" | "resume" | "approve" | "reject" | "cancel") =>
      (await api.post<Run>(`/runs/${runId}/${action}`)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["run", runId] });
      qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}
