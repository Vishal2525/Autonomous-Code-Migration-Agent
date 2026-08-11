import { useEffect, useRef } from "react";
import type { EventItem } from "../../types";
import { timeOnly } from "../../lib/format";

const EVENT_COLORS: Record<string, string> = {
  RUN_FAILED: "text-rose-400",
  TASK_FAILED: "text-rose-400",
  TEST_FAILED: "text-rose-400",
  RUN_COMPLETED: "text-emerald-400",
  TEST_PASSED: "text-emerald-400",
  TASK_COMPLETED: "text-emerald-400",
  PHASE_COMPLETED: "text-emerald-400",
  CHECKPOINT_CREATED: "text-cyan-400",
  GIT_SNAPSHOT: "text-cyan-400",
  GIT_ROLLBACK: "text-orange-400",
  APPROVAL_REQUIRED: "text-yellow-300",
  REPAIR_STARTED: "text-orange-400",
  REPAIR_ATTEMPT: "text-orange-400",
  PHASE_STARTED: "text-sky-400",
  TASK_STARTED: "text-amber-300",
  FILE_MODIFIED: "text-violet-300",
  FILE_CREATED: "text-violet-300",
  FILE_DELETED: "text-rose-300",
};

export default function LogsView({
  events,
  compact = false,
}: {
  events: EventItem[];
  compact?: boolean;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [events.length]);

  return (
    <div className="card p-0">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Agent Log
        </span>
        <span className="font-mono text-[11px] text-slate-600">{events.length} events</span>
      </div>
      <div
        className={`overflow-y-auto p-3 font-mono text-xs leading-5 ${
          compact ? "max-h-[420px]" : "max-h-[620px]"
        }`}
      >
        {events.length === 0 && (
          <p className="text-slate-600">Waiting for events…</p>
        )}
        {events.map((ev) => (
          <div key={ev.id} className="flex gap-2 hover:bg-slate-900/60">
            <span className="shrink-0 text-slate-600">{timeOnly(ev.created_at)}</span>
            <span className={`w-44 shrink-0 truncate ${EVENT_COLORS[ev.event] ?? "text-slate-400"}`}>
              {ev.event}
            </span>
            <span className="whitespace-pre-wrap break-all text-slate-300">{ev.message}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
