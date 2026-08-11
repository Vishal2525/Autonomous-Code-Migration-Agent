# Autonomous-Code-Migration-Agent
An agentic system for repository-scale codebase transformation
# Autonomous Code Migration Agent

A long-running agent that migrates a repository from one technology to another
(e.g. **Flask → FastAPI**) by actually doing the work: it clones the repo,
indexes it deterministically with Python AST, plans with an LLM, edits files
through a schema-validated tool layer, runs pytest in an isolated virtualenv,
repairs failures, snapshots every step with Git, checkpoints all progress to
MongoDB — and **resumes from the last checkpoint after a crash** instead of
starting over.

This is a learning project about the two hard problems of long-running agents:

1. **Context-window growth** → solved with tiered / lazy context (the full repo
   is never sent to the LLM; per-task transcripts stay small)
2. **Losing progress on crashes** → solved with MongoDB checkpoints +
   phase-level and task-level resume

```
                    React Frontend
                          |
                          | REST / WebSocket
                          ↓
                    FastAPI Backend
                          |
                          ↓
                    Agent Orchestrator
                          |
          ┌───────────────┼────────────────┐
          ↓               ↓                ↓
      MongoDB          LLM Layer       Git Manager
     Checkpoints      Gemini/Groq       Snapshots
          |               |
          |               ↓
          |          Agent Reasoning
          |               |
          |               ↓
          |           Tool Layer
          |     ┌─────────┼─────────┐
          |     ↓         ↓         ↓
          |   Files      Tests     AST
          |   Tools      Tools    Analyzer
          ↓
      Resume State
```

## The five phases

| Phase | What happens | LLM? | Checkpointed |
|---|---|---|---|
| 1. INDEXING | clone → scan/classify files → AST imports/symbols/routes → dependency graph (forward + reverse) → L1/L2 summaries → baseline test run | optional (one summary-enrichment call) | ✔ phase |
| 2. PLANNING | read-only agent loop inspects the repo, submits a structured task plan (`submit_plan` tool). Cannot modify files. | ✔ | ✔ phase |
| 3. EXECUTION | one agent loop per task: read → targeted edits (syntax-gated) → git snapshot → checkpoint. Failures roll back to the pre-task SHA. | ✔ | ✔ per task |
| 4. REPAIR | run full suite → failure bundle → repair loop (bounded by `MAX_REPAIR_ATTEMPTS`); attempts that make things worse are rolled back | ✔ | ✔ per attempt |
| 5. VERIFICATION | full suite + syntax sweep + dependency sanity → final migration report | ✘ | ✔ phase |

## Repository layout

```
backend/    FastAPI + Motor(MongoDB) + GitPython + AST indexing + agent core
frontend/   Vite + React 18 + TypeScript + Tailwind + React Query
demo/legacy-flask-app/   a real Flask invoice service to migrate (18 pytest tests)
```

## Prerequisites

- Python 3.12+, Node 18+, Git
- MongoDB running locally (`mongodb://localhost:27017`) — a Windows service is fine
- A **Gemini** or **Groq** API key (free tiers work)

## Setup

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env     # then edit .env
```

Edit `backend/.env`:

```ini
LLM_PROVIDER=groq          # or: gemini
GROQ_API_KEY=gsk_...       # from console.groq.com
GEMINI_API_KEY=            # from aistudio.google.com (if LLM_PROVIDER=gemini)
```

The rest of the app never touches Gemini/Groq directly — both sit behind an
`LLMProvider` abstraction (`backend/app/llm/`), selected by `LLM_PROVIDER`.
Rate limits are retried with backoff; hard quota exhaustion fails the run with
a clear message (and the run stays resumable).

Start the API:

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173  (proxies /api and /ws to :8000)
```

### 3. Run a migration

Open http://localhost:5173 → **New Migration** and use the built-in demo target:

- Repository: `<absolute path to>\demo\legacy-flask-app` (or any GitHub URL)
- Source: `Flask` — Target: `FastAPI`
- Goal: *Migrate the Flask application to FastAPI while preserving existing API behavior.*
- Mode: `AUTO` (or `HITL` for approval gates)

The run appears on the dashboard; the details page streams live events over
WebSocket and shows the plan, per-file diffs, test results and the final report.
The original repository is never modified — the agent works on a copy in
`backend/workspace/runs/<run_id>/repository` on its own `migration-<id>` branch.

## Proving the resume system (crash simulation)

1. In `backend/.env` set:

   ```ini
   CRASH_AFTER_TASK=TASK-003
   ```

2. Restart the backend and start a migration. The worker dies immediately
   after TASK-003's checkpoint is written — the run is left mid-flight exactly
   like a real crash. (Restarting the backend instead also works: on startup,
   orphaned active runs are marked FAILED-but-resumable.)

3. Remove `CRASH_AFTER_TASK`, restart the backend, and click **Resume**
   (or `POST /api/runs/{run_id}/resume`).

4. Watch the events: the run logs `RUN_RESUMED`, skips indexing and planning
   (their checkpoints exist), skips TASK-001…TASK-003 (task checkpoints exist),
   verifies the Git HEAD matches the last checkpoint SHA (rolling back
   half-applied edits if needed), and continues at **TASK-004** — not from the
   beginning.

The same machinery powers every recovery path: pause/resume, approval gates,
LLM quota failures, backend restarts.

## Human-in-the-loop (HITL)

In `HITL` mode the run parks in `WAITING_FOR_APPROVAL` (Approve / Reject /
Pause in the UI) at these gates:

- before the migration starts, after indexing, after planning
- before any file deletion, before dependency-file changes
- before finalizing the migration

One gate fires **even in AUTO mode**: repair-attempt exhaustion
(`MAX_REPAIR_ATTEMPTS`, default 5). Approving grants another repair cycle.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/runs` / `GET /api/runs` / `GET /api/runs/{id}` | create / list / inspect |
| `POST /api/runs/{id}/start · pause · resume · approve · reject · cancel` | lifecycle |
| `GET /api/runs/{id}/events · tasks · plan · report · diff · files · tests · checkpoints` | run data |
| `WS /ws/runs/{id}` | live event stream (snapshot replay on connect) |

## MongoDB collections

`runs`, `repository_indexes`, `files`, `dependencies`, `plans`, `tasks`,
`checkpoints`, `events`, `test_results`, `approvals` — every important
operation writes a checkpoint/event, so Python memory is never the only copy
of progress.

## Tests

```powershell
cd backend
.\.venv\Scripts\python -m pytest      # 44 unit tests
```

Covers: AST import/route extraction, dependency graphs, state-machine
transition rules, file-tool sandboxing + syntax gates, git snapshot/rollback,
tool-registry validation, and the MongoDB checkpoint → resume-point logic.

## Safety model (and honest limitations)

- All file tools are sandboxed to the run's repository copy (no `..`, no
  absolute paths, no `.git` access); Python writes are rejected unless they parse.
- `run_command` is allowlisted (`pip` / `pytest` / `python` in the run's venv,
  cwd-locked, timed out) — nothing from the frontend reaches a shell.
- Planning runs with mutations disabled at the registry level.
- **Limitation:** running a repository's test suite executes that repository's
  code on your machine (inherent to any CI-like system). Only point the agent
  at repositories you trust.
- The worker is an in-process asyncio task; its only input is `run_id` + Mongo
  state, so it can be moved to Celery/RQ/Temporal without changing the agent.



## Run the Full Migration Locally

### 1. Configure the LLM Provider

Add your API key to `backend/.env`.

**Option 1 — Groq:**

```env
GROQ_API_KEY=your_groq_api_key
```

**Option 2 — Gemini:**

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
```

### 2. Start the Backend

From the project root:

```bash
cd backend
..\venv\Scripts\python -m uvicorn app.main:app --port 8000
```

The backend will run on:

```text
http://localhost:8000
```

### 3. Start the Frontend

Open a new terminal:

```bash
cd frontend
npm run dev
```

Then open:

```text
http://localhost:5173
```

Point the migration agent to:

```text
demo/legacy-flask-app
```

### 4. Test Crash Recovery

To verify that checkpoint-based recovery works:

**Step 1 — Configure the crash point**

Add to `backend/.env`:

```env
CRASH_AFTER_TASK=TASK-003
```

**Step 2 — Start a migration run**

The agent should intentionally crash after `TASK-003`.

**Step 3 — Clear the crash variable**

Remove or disable:

```env
CRASH_AFTER_TASK=TASK-003
```

**Step 4 — Resume the migration**

Click **Resume**.

The agent should load the latest checkpoint and continue from:

```text
TASK-004
```

rather than restarting the migration from the beginning.
