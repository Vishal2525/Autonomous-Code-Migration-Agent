export type RunState =
  | "CREATED"
  | "INDEXING"
  | "INDEXED"
  | "PLANNING"
  | "PLANNED"
  | "EXECUTING"
  | "REPAIRING"
  | "VERIFYING"
  | "WAITING_FOR_APPROVAL"
  | "PAUSED"
  | "FAILED"
  | "CANCELLED"
  | "COMPLETED";

export type Phase = "INDEXING" | "PLANNING" | "EXECUTION" | "REPAIR" | "VERIFICATION";

export type TaskStatus = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "FAILED" | "SKIPPED";

export interface Counters {
  files_indexed: number;
  files_processed: number;
  files_modified: number;
  files_created: number;
  files_deleted: number;
  tests_passed: number;
  tests_failed: number;
  repair_attempts: number;
  git_commits: number;
}

export interface LLMUsage {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface Approval {
  run_id: string;
  gate: string;
  key: string;
  detail: string;
  status: string;
  data?: Record<string, unknown>;
}

export interface Report {
  migration: string;
  goal: string;
  status: string;
  files_analyzed: number;
  files_modified: number;
  files_created: number;
  files_deleted: number;
  tests: { passed: number; failed: number; errors: number; duration_s: number };
  baseline_tests: { passed: number; failed: number; errors: number } | null;
  repair_attempts: number;
  git_commits: number;
  syntax_errors: string[];
  warnings: string[];
  duration_s: number;
}

export interface Run {
  run_id: string;
  repository_url: string;
  goal: string;
  source_tech: string;
  target_tech: string;
  mode: "AUTO" | "HITL";
  status: RunState;
  phase: Phase | null;
  current_task_id: string | null;
  current_file: string | null;
  baseline_sha: string | null;
  head_sha: string | null;
  progress: number;
  counters: Counters;
  llm_usage: LLMUsage;
  error: string | null;
  report: Report | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  pending_approval?: Approval | null;
}

export interface Task {
  run_id: string;
  task_id: string;
  file: string;
  description: string;
  reason: string;
  instructions: string;
  dependencies: string[];
  expected_changes: string[];
  validation: string;
  priority: number;
  status: TaskStatus;
  result_summary: string | null;
  git_sha: string | null;
  error: string | null;
}

export interface Plan {
  run_id: string;
  migration: string;
  overview: string;
  tasks: Task[];
}

export interface EventItem {
  id: string;
  run_id: string;
  event: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface TestRecord {
  run_id: string;
  phase: Phase;
  attempt: number;
  exit_code: number | null;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  duration_s: number;
  failing_tests: string[];
  output_tail: string;
  timed_out: boolean;
  created_at: string;
}

export interface DiffFile {
  status: string;
  path: string;
  old_path?: string;
  patch: string;
}

export interface DiffResponse {
  files: DiffFile[];
  baseline?: string;
  head?: string;
  note?: string;
}
