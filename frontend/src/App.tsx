import { Link, Route, Routes } from "react-router-dom";
import CreateMigration from "./pages/CreateMigration";
import Dashboard from "./pages/Dashboard";
import RunDetails from "./pages/RunDetails";

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-600 font-mono text-sm font-bold text-white">
              MA
            </span>
            <div>
              <div className="text-sm font-semibold text-slate-100">
                Autonomous Code Migration Agent
              </div>
              <div className="text-[11px] text-slate-500">
                index → plan → execute → repair → verify
              </div>
            </div>
          </Link>
          <Link to="/new" className="btn-primary">
            + New Migration
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<CreateMigration />} />
          <Route path="/runs/:runId" element={<RunDetails />} />
        </Routes>
      </main>
    </div>
  );
}
