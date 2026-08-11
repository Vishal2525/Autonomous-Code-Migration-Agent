import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateRun } from "../api/client";

export default function CreateMigration() {
  const navigate = useNavigate();
  const createRun = useCreateRun();
  const [form, setForm] = useState({
    repository_url: "",
    source_tech: "Flask",
    target_tech: "FastAPI",
    goal: "Migrate the Flask application to FastAPI while preserving existing API behavior.",
    mode: "AUTO" as "AUTO" | "HITL",
  });

  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const run = await createRun.mutateAsync(form);
    navigate(`/runs/${run.run_id}`);
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1 text-lg font-semibold text-slate-100">New Migration</h1>
      <p className="mb-6 text-sm text-slate-500">
        The agent clones the repository into an isolated workspace — your original
        repository is never modified.
      </p>
      <form onSubmit={submit} className="card space-y-4">
        <div>
          <label className="label">GitHub Repository URL (or local path)</label>
          <input
            className="input font-mono"
            placeholder="https://github.com/user/legacy-service  ·  C:\path\to\repo"
            value={form.repository_url}
            onChange={set("repository_url")}
            required
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Source Technology</label>
            <input className="input" value={form.source_tech} onChange={set("source_tech")} required />
          </div>
          <div>
            <label className="label">Target Technology</label>
            <input className="input" value={form.target_tech} onChange={set("target_tech")} required />
          </div>
        </div>
        <div>
          <label className="label">Migration Goal</label>
          <textarea className="input min-h-[80px]" value={form.goal} onChange={set("goal")} required />
        </div>
        <div>
          <label className="label">Execution Mode</label>
          <select className="input" value={form.mode} onChange={set("mode")}>
            <option value="AUTO">AUTO — run end-to-end without approvals</option>
            <option value="HITL">HITL — pause for human approval at key gates</option>
          </select>
        </div>
        {createRun.isError && (
          <div className="rounded-lg border border-rose-800 bg-rose-950/50 p-3 text-sm text-rose-300">
            {(createRun.error as any)?.response?.data?.detail ??
              String(createRun.error)}
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="submit"
            className="btn-primary px-5 py-2"
            disabled={createRun.isPending}
          >
            {createRun.isPending ? "Starting…" : "Start Migration"}
          </button>
        </div>
      </form>
    </div>
  );
}
