import { useState } from "react";
import { useDiff } from "../../api/client";

const STATUS_COLORS: Record<string, string> = {
  added: "text-emerald-400",
  modified: "text-amber-300",
  deleted: "text-rose-400",
  renamed: "text-sky-300",
};

function DiffLine({ line }: { line: string }) {
  let cls = "text-slate-400";
  if (line.startsWith("+") && !line.startsWith("+++")) cls = "bg-emerald-950/60 text-emerald-300";
  else if (line.startsWith("-") && !line.startsWith("---")) cls = "bg-rose-950/60 text-rose-300";
  else if (line.startsWith("@@")) cls = "text-cyan-400";
  else if (line.startsWith("diff ") || line.startsWith("index ")) cls = "text-slate-600";
  return <div className={`whitespace-pre-wrap break-all px-2 ${cls}`}>{line || " "}</div>;
}

export default function ChangesView({ runId }: { runId: string }) {
  const { data, isLoading } = useDiff(runId, true);
  const [selected, setSelected] = useState<string | null>(null);

  if (isLoading) return <p className="text-slate-400">Loading diff…</p>;
  const files = data?.files ?? [];
  if (files.length === 0)
    return (
      <div className="card text-sm text-slate-400">
        No code changes yet — modifications appear here as execution commits snapshots.
      </div>
    );

  const current = files.find((f) => f.path === selected) ?? files[0];

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      <div className="card max-h-[600px] overflow-y-auto p-2">
        {files.map((f) => (
          <button
            key={f.path}
            onClick={() => setSelected(f.path)}
            className={`block w-full rounded-lg px-2 py-1.5 text-left font-mono text-xs hover:bg-slate-800 ${
              current.path === f.path ? "bg-slate-800" : ""
            }`}
          >
            <span className={`mr-2 ${STATUS_COLORS[f.status] ?? "text-slate-400"}`}>
              {f.status === "added" ? "A" : f.status === "deleted" ? "D" : f.status === "renamed" ? "R" : "M"}
            </span>
            <span className="break-all text-slate-300">{f.path}</span>
          </button>
        ))}
      </div>
      <div className="card max-h-[600px] overflow-y-auto p-0">
        <div className="sticky top-0 border-b border-slate-800 bg-slate-900 px-4 py-2 font-mono text-xs text-slate-300">
          {current.path}{" "}
          <span className={STATUS_COLORS[current.status] ?? ""}>({current.status})</span>
        </div>
        <div className="py-2 font-mono text-[11px] leading-5">
          {current.status === "deleted" ? (
            <p className="px-3 text-rose-300">File deleted by the migration.</p>
          ) : current.patch ? (
            current.patch.split("\n").map((line, i) => <DiffLine key={i} line={line} />)
          ) : (
            <p className="px-3 text-slate-500">No textual diff available.</p>
          )}
        </div>
      </div>
    </div>
  );
}
