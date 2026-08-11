import type { Phase, Run, Task } from "../types";
import { TaskPill } from "./StatusPill";

const PHASES: { key: Phase; label: string }[] = [
  { key: "INDEXING", label: "Indexing" },
  { key: "PLANNING", label: "Planning" },
  { key: "EXECUTION", label: "Execution" },
  { key: "REPAIR", label: "Repair" },
  { key: "VERIFICATION", label: "Verification" },
];

const ORDER: Record<Phase, number> = {
  INDEXING: 0,
  PLANNING: 1,
  EXECUTION: 2,
  REPAIR: 3,
  VERIFICATION: 4,
};

function phaseState(run: Run, phase: Phase): "done" | "active" | "todo" {
  if (run.status === "COMPLETED") return "done";
  const current = run.phase ? ORDER[run.phase] : -1;
  const idx = ORDER[phase];
  if (idx < current) return "done";
  if (idx === current) return "active";
  return "todo";
}

export function PhaseTimeline({ run, tasks }: { run: Run; tasks: Task[] }) {
  return (
    <div className="card">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Timeline
      </div>
      <ol className="space-y-2">
        {PHASES.map(({ key, label }) => {
          const state = phaseState(run, key);
          return (
            <li key={key}>
              <div className="flex items-center gap-2 text-sm">
                <span
                  className={
                    state === "done"
                      ? "text-emerald-400"
                      : state === "active"
                        ? "text-amber-400"
                        : "text-slate-600"
                  }
                >
                  {state === "done" ? "✓" : state === "active" ? "→" : "○"}
                </span>
                <span
                  className={
                    state === "todo" ? "text-slate-500" : "font-medium text-slate-200"
                  }
                >
                  {label}
                </span>
              </div>
              {key === "EXECUTION" && tasks.length > 0 && (
                <ul className="ml-6 mt-1 space-y-1">
                  {tasks.map((t) => (
                    <li
                      key={t.task_id}
                      className="flex items-center justify-between gap-2 text-xs"
                    >
                      <span
                        className={`truncate font-mono ${
                          t.status === "IN_PROGRESS" ? "text-amber-300" : "text-slate-400"
                        }`}
                        title={`${t.task_id} — ${t.file}`}
                      >
                        {t.task_id} · {t.file}
                      </span>
                      <TaskPill status={t.status} />
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
