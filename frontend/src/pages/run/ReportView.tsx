import type { Run } from "../../types";
import { StatCard } from "../../components/StatCard";
import { formatDuration } from "../../lib/format";

export default function ReportView({ run }: { run: Run }) {
  const report = run.report;
  if (!report)
    return (
      <div className="card text-sm text-slate-400">
        The final migration report is generated during the verification phase.
      </div>
    );

  const statusColor =
    report.status === "SUCCESS"
      ? "text-emerald-400"
      : report.status === "PARTIAL"
        ? "text-amber-400"
        : "text-rose-400";

  return (
    <div className="space-y-4">
      <div className="card text-center">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Migration Report
        </div>
        <div className="mt-2 font-mono text-xl text-slate-100">{report.migration}</div>
        <div className={`mt-2 font-mono text-3xl font-bold ${statusColor}`}>
          {report.status}
        </div>
        <div className="mt-1 text-xs text-slate-500">{report.goal}</div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Files analyzed" value={report.files_analyzed} />
        <StatCard label="Files modified" value={report.files_modified} />
        <StatCard label="Files created" value={report.files_created} />
        <StatCard label="Files deleted" value={report.files_deleted} />
        <StatCard
          label="Tests"
          value={`${report.tests.passed} ✓ / ${report.tests.failed + report.tests.errors} ✗`}
          sub={
            report.baseline_tests
              ? `baseline: ${report.baseline_tests.passed} ✓ / ${
                  report.baseline_tests.failed + report.baseline_tests.errors
                } ✗`
              : undefined
          }
        />
        <StatCard label="Repair attempts" value={report.repair_attempts} />
        <StatCard label="Git commits" value={report.git_commits} />
        <StatCard label="Duration" value={formatDuration(report.duration_s)} />
      </div>

      {report.syntax_errors.length > 0 && (
        <div className="card border-rose-900">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-rose-400">
            Syntax errors
          </div>
          <ul className="space-y-1 font-mono text-xs text-rose-300">
            {report.syntax_errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}
      {report.warnings.length > 0 && (
        <div className="card border-amber-900">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-400">
            Warnings
          </div>
          <ul className="space-y-1 text-xs text-amber-200/80">
            {report.warnings.map((w, i) => (
              <li key={i}>⚠ {w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
