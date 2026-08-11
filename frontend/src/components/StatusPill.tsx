import type { RunState, TaskStatus } from "../types";

const RUN_COLORS: Record<string, string> = {
  CREATED: "bg-slate-700 text-slate-200",
  INDEXING: "bg-sky-900 text-sky-300",
  INDEXED: "bg-sky-900 text-sky-300",
  PLANNING: "bg-violet-900 text-violet-300",
  PLANNED: "bg-violet-900 text-violet-300",
  EXECUTING: "bg-amber-900 text-amber-300",
  REPAIRING: "bg-orange-900 text-orange-300",
  VERIFYING: "bg-cyan-900 text-cyan-300",
  WAITING_FOR_APPROVAL: "bg-yellow-800 text-yellow-200",
  PAUSED: "bg-slate-700 text-slate-300",
  FAILED: "bg-rose-900 text-rose-300",
  CANCELLED: "bg-slate-800 text-slate-400",
  COMPLETED: "bg-emerald-900 text-emerald-300",
};

const PULSING = new Set(["INDEXING", "PLANNING", "EXECUTING", "REPAIRING", "VERIFYING"]);

export function StatusPill({ status }: { status: RunState | string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-[11px] font-semibold ${
        RUN_COLORS[status] ?? "bg-slate-700 text-slate-200"
      }`}
    >
      {PULSING.has(status) && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {status}
    </span>
  );
}

const TASK_COLORS: Record<TaskStatus, string> = {
  PENDING: "bg-slate-800 text-slate-400",
  IN_PROGRESS: "bg-amber-900 text-amber-300",
  COMPLETED: "bg-emerald-900 text-emerald-300",
  FAILED: "bg-rose-900 text-rose-300",
  SKIPPED: "bg-slate-700 text-slate-300",
};

export function TaskPill({ status }: { status: TaskStatus }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 font-mono text-[10px] font-semibold ${TASK_COLORS[status]}`}
    >
      {status}
    </span>
  );
}
