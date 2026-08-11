import type { Approval } from "../types";

export function ApprovalBanner({
  approval,
  onApprove,
  onReject,
  onPause,
  busy,
}: {
  approval: Approval;
  onApprove: () => void;
  onReject: () => void;
  onPause: () => void;
  busy: boolean;
}) {
  return (
    <div className="rounded-xl border border-yellow-700 bg-yellow-950/60 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-bold text-yellow-300">
            ⚠ Approval Required — {approval.gate}
          </div>
          <p className="mt-1 text-sm text-yellow-100/80">{approval.detail}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button className="btn-primary" onClick={onApprove} disabled={busy}>
            Approve
          </button>
          <button className="btn-danger" onClick={onReject} disabled={busy}>
            Reject
          </button>
          <button className="btn-secondary" onClick={onPause} disabled={busy}>
            Pause
          </button>
        </div>
      </div>
    </div>
  );
}
