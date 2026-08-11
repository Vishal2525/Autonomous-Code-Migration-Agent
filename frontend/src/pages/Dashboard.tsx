import { Link } from "react-router-dom";
import { useRuns } from "../api/client";
import { ProgressBar } from "../components/ProgressBar";
import { StatusPill } from "../components/StatusPill";
import { elapsedSince, repoShortName } from "../lib/format";

export default function Dashboard() {
  const { data: runs, isLoading, error } = useRuns();

  if (isLoading) return <p className="text-slate-400">Loading runs…</p>;
  if (error)
    return (
      <div className="card border-rose-800 text-rose-300">
        Backend unreachable — is the FastAPI server running on port 8000?
      </div>
    );

  if (!runs || runs.length === 0)
    return (
      <div className="card py-16 text-center">
        <p className="text-lg font-medium text-slate-300">No migration runs yet</p>
        <p className="mt-1 text-sm text-slate-500">
          Start by pointing the agent at a repository.
        </p>
        <Link to="/new" className="btn-primary mt-6 inline-block">
          + New Migration
        </Link>
      </div>
    );

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold text-slate-100">Migration Runs</h1>
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full min-w-[760px] text-sm">
          <thead className="bg-slate-900 text-left text-[11px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2.5">Run</th>
              <th className="px-4 py-2.5">Repository</th>
              <th className="px-4 py-2.5">Migration</th>
              <th className="px-4 py-2.5">Status</th>
              <th className="px-4 py-2.5">Phase</th>
              <th className="px-4 py-2.5 w-48">Progress</th>
              <th className="px-4 py-2.5">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/70">
            {runs.map((run) => (
              <tr key={run.run_id} className="bg-slate-950/50 hover:bg-slate-900/70">
                <td className="px-4 py-3">
                  <Link
                    to={`/runs/${run.run_id}`}
                    className="font-mono text-emerald-400 hover:underline"
                  >
                    {run.run_id}
                  </Link>
                </td>
                <td className="max-w-[220px] truncate px-4 py-3 text-slate-300">
                  {repoShortName(run.repository_url)}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-300">
                  {run.source_tech} → {run.target_tech}
                </td>
                <td className="px-4 py-3">
                  <StatusPill status={run.status} />
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-400">
                  {run.phase ?? "—"}
                </td>
                <td className="px-4 py-3">
                  <ProgressBar value={run.progress} />
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-400">
                  {elapsedSince(run.started_at, run.finished_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
