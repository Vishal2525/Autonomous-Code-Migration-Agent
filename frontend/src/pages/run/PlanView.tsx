import { usePlan } from "../../api/client";
import { TaskPill } from "../../components/StatusPill";
import { shortSha } from "../../lib/format";

export default function PlanView({ runId }: { runId: string }) {
  const { data: plan, isLoading, error } = usePlan(runId, true);

  if (isLoading) return <p className="text-slate-400">Loading plan…</p>;
  if (error || !plan)
    return (
      <div className="card text-sm text-slate-400">
        The migration plan has not been created yet — it appears once the planning
        phase completes.
      </div>
    );

  return (
    <div className="space-y-3">
      <div className="card">
        <div className="font-mono text-sm text-emerald-400">{plan.migration}</div>
        {plan.overview && <p className="mt-1 text-sm text-slate-400">{plan.overview}</p>}
        <p className="mt-1 text-xs text-slate-500">{plan.tasks.length} tasks</p>
      </div>
      {plan.tasks.map((task) => (
        <div key={task.task_id} className="card">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm font-semibold text-slate-100">
                {task.task_id}
              </span>
              <span className="font-mono text-xs text-sky-300">{task.file}</span>
            </div>
            <div className="flex items-center gap-2">
              {task.git_sha && (
                <span className="font-mono text-[10px] text-slate-500">
                  {shortSha(task.git_sha)}
                </span>
              )}
              <TaskPill status={task.status} />
            </div>
          </div>
          <p className="mt-2 text-sm text-slate-300">{task.description}</p>
          {task.reason && <p className="mt-1 text-xs text-slate-500">Why: {task.reason}</p>}
          <details className="mt-2">
            <summary className="cursor-pointer text-xs font-medium text-slate-400 hover:text-slate-200">
              Instructions & validation
            </summary>
            <div className="mt-2 space-y-2 rounded-lg bg-slate-950/70 p-3 text-xs text-slate-400">
              <p className="whitespace-pre-wrap">{task.instructions}</p>
              {task.expected_changes.length > 0 && (
                <div>
                  <span className="font-semibold text-slate-300">Expected changes:</span>
                  <ul className="ml-4 list-disc">
                    {task.expected_changes.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </div>
              )}
              {task.validation && (
                <p>
                  <span className="font-semibold text-slate-300">Validation:</span>{" "}
                  {task.validation}
                </p>
              )}
              {task.dependencies.length > 0 && (
                <p className="font-mono">
                  <span className="font-semibold text-slate-300">Depends on:</span>{" "}
                  {task.dependencies.join(", ")}
                </p>
              )}
            </div>
          </details>
          {task.result_summary && (
            <p className="mt-2 border-l-2 border-emerald-700 pl-2 text-xs text-emerald-300/80">
              {task.result_summary}
            </p>
          )}
          {task.error && (
            <p className="mt-2 border-l-2 border-rose-700 pl-2 font-mono text-xs text-rose-300">
              {task.error}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
