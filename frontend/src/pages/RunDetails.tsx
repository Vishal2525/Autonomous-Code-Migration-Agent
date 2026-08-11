import { useState } from "react";
import { useParams } from "react-router-dom";
import { useRun, useRunAction, useTasks } from "../api/client";
import { useRunSocket } from "../api/useRunSocket";
import { ApprovalBanner } from "../components/ApprovalBanner";
import { PhaseTimeline } from "../components/PhaseTimeline";
import { ProgressBar } from "../components/ProgressBar";
import { StatCard } from "../components/StatCard";
import { StatusPill } from "../components/StatusPill";
import { elapsedSince, formatTokens, repoShortName, shortSha } from "../lib/format";
import ChangesView from "./run/ChangesView";
import LogsView from "./run/LogsView";
import PlanView from "./run/PlanView";
import ReportView from "./run/ReportView";
import TestsView from "./run/TestsView";

const TABS = ["Overview", "Plan", "Live Logs", "Code Changes", "Tests", "Report"] as const;
type Tab = (typeof TABS)[number];

export default function RunDetails() {
  const { runId } = useParams<{ runId: string }>();
  const { data: fetchedRun, isLoading } = useRun(runId);
  const { data: tasks = [] } = useTasks(runId);
  const socket = useRunSocket(runId);
  const action = useRunAction(runId);
  const [tab, setTab] = useState<Tab>("Overview");

  const run = socket.liveRun ?? fetchedRun;
  if (isLoading && !run) return <p className="text-slate-400">Loading run…</p>;
  if (!run) return <p className="text-rose-400">Run not found.</p>;

  const approval = socket.approval ?? run.pending_approval ?? null;
  const active = ["INDEXING", "INDEXED", "PLANNING", "PLANNED", "EXECUTING", "REPAIRING", "VERIFYING"].includes(run.status);
  const canResume = ["PAUSED", "FAILED"].includes(run.status) || (active && !socket.connected);

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="font-mono text-lg text-slate-100">{run.run_id}</h1>
              <StatusPill status={run.status} />
              <span
                className={`text-[11px] font-mono ${socket.connected ? "text-emerald-500" : "text-slate-600"}`}
                title="WebSocket live stream"
              >
                {socket.connected ? "● live" : "○ polling"}
              </span>
            </div>
            <div className="mt-1 text-sm text-slate-400">
              {repoShortName(run.repository_url)} ·{" "}
              <span className="font-mono">
                {run.source_tech} → {run.target_tech}
              </span>{" "}
              · mode {run.mode}
            </div>
            <div className="mt-1 max-w-2xl text-xs text-slate-500">{run.goal}</div>
          </div>
          <div className="flex gap-2">
            {active && (
              <button className="btn-warn" onClick={() => action.mutate("pause")} disabled={action.isPending}>
                Pause
              </button>
            )}
            {canResume && (
              <button className="btn-primary" onClick={() => action.mutate("resume")} disabled={action.isPending}>
                Resume
              </button>
            )}
            {!["COMPLETED", "CANCELLED"].includes(run.status) && (
              <button className="btn-danger" onClick={() => action.mutate("cancel")} disabled={action.isPending}>
                Cancel
              </button>
            )}
          </div>
        </div>
        <div className="mt-4">
          <ProgressBar value={run.progress} />
        </div>
        {run.error && (
          <div className="mt-3 rounded-lg border border-rose-900 bg-rose-950/40 p-3 font-mono text-xs text-rose-300 whitespace-pre-wrap">
            {run.error}
          </div>
        )}
        {(action.error as any) && (
          <div className="mt-3 text-xs text-rose-400">
            {(action.error as any)?.response?.data?.detail ?? String(action.error)}
          </div>
        )}
      </div>

      {approval && approval.status === "pending" && (
        <ApprovalBanner
          approval={approval}
          onApprove={() => action.mutate("approve")}
          onReject={() => action.mutate("reject")}
          onPause={() => action.mutate("pause")}
          busy={action.isPending}
        />
      )}

      {/* stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
        <StatCard label="Phase" value={run.phase ?? "—"} />
        <StatCard label="Current Task" value={run.current_task_id ?? "—"} sub={run.current_file ?? undefined} />
        <StatCard label="Files Indexed" value={run.counters.files_indexed} />
        <StatCard
          label="Files Changed"
          value={run.counters.files_modified + run.counters.files_created}
          sub={`+${run.counters.files_created} new · -${run.counters.files_deleted} deleted`}
        />
        <StatCard
          label="Tests"
          value={`${run.counters.tests_passed} ✓ / ${run.counters.tests_failed} ✗`}
          sub={`${run.counters.repair_attempts} repair attempts`}
        />
        <StatCard
          label="LLM Usage"
          value={`${run.llm_usage.calls} calls`}
          sub={`${formatTokens(run.llm_usage.total_tokens)} tokens`}
        />
        <StatCard label="Elapsed" value={elapsedSince(run.started_at, run.finished_at)} />
        <StatCard
          label="Git HEAD"
          value={shortSha(run.head_sha)}
          sub={`${run.counters.git_commits} commits`}
        />
      </div>

      {/* tabs */}
      <div className="flex gap-1 overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60 p-1">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              tab === t ? "bg-slate-700 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Overview" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <PhaseTimeline run={run} tasks={tasks} />
          <LogsView events={socket.events} compact />
        </div>
      )}
      {tab === "Plan" && <PlanView runId={run.run_id} />}
      {tab === "Live Logs" && <LogsView events={socket.events} />}
      {tab === "Code Changes" && <ChangesView runId={run.run_id} />}
      {tab === "Tests" && <TestsView runId={run.run_id} />}
      {tab === "Report" && <ReportView run={run} />}
    </div>
  );
}
