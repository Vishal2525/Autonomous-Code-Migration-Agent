import { useTests } from "../../api/client";
import { formatDuration } from "../../lib/format";

export default function TestsView({ runId }: { runId: string }) {
  const { data: results = [], isLoading } = useTests(runId, true);

  if (isLoading) return <p className="text-slate-400">Loading test results…</p>;
  if (results.length === 0)
    return (
      <div className="card text-sm text-slate-400">
        No test runs recorded yet — the baseline suite runs during indexing.
      </div>
    );

  const latest = results[results.length - 1];

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-slate-900 text-left text-[11px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2">#</th>
              <th className="px-4 py-2">Phase</th>
              <th className="px-4 py-2">Passed</th>
              <th className="px-4 py-2">Failed</th>
              <th className="px-4 py-2">Errors</th>
              <th className="px-4 py-2">Duration</th>
              <th className="px-4 py-2">Exit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/70">
            {results.map((r, i) => (
              <tr key={i} className="bg-slate-950/50 font-mono text-xs">
                <td className="px-4 py-2 text-slate-500">{i + 1}</td>
                <td className="px-4 py-2 text-slate-300">
                  {r.phase}
                  {r.attempt > 0 ? ` (attempt ${r.attempt})` : ""}
                </td>
                <td className="px-4 py-2 text-emerald-400">{r.passed}</td>
                <td className={`px-4 py-2 ${r.failed ? "text-rose-400" : "text-slate-500"}`}>
                  {r.failed}
                </td>
                <td className={`px-4 py-2 ${r.errors ? "text-rose-400" : "text-slate-500"}`}>
                  {r.errors}
                </td>
                <td className="px-4 py-2 text-slate-400">{formatDuration(r.duration_s)}</td>
                <td className="px-4 py-2 text-slate-400">
                  {r.timed_out ? "timeout" : (r.exit_code ?? "—")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {latest.failing_tests.length > 0 && (
        <div className="card">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-rose-400">
            Failing tests (latest run)
          </div>
          <ul className="space-y-1 font-mono text-xs text-rose-300">
            {latest.failing_tests.map((t) => (
              <li key={t}>✗ {t}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="card p-0">
        <div className="border-b border-slate-800 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Latest output
        </div>
        <pre className="max-h-[380px] overflow-auto p-4 font-mono text-[11px] leading-5 text-slate-400">
          {latest.output_tail || "(no output captured)"}
        </pre>
      </div>
    </div>
  );
}
