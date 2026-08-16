import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { Approval, EventItem, Run } from "../types";

interface SocketState {
  connected: boolean;
  events: EventItem[];
  liveRun: Run | null;
  approval: Approval | null;
}

/** Live event stream over WebSocket, with automatic reconnect.
 *  On snapshot/replay the event list is replaced; new events are appended. */
export function useRunSocket(runId: string | undefined): SocketState {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [liveRun, setLiveRun] = useState<Run | null>(null);
  const [approval, setApproval] = useState<Approval | null>(null);
  const retryRef = useRef(0);

  useEffect(() => {
    if (!runId) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let reconnectTimer: number | undefined;

    const connect = () => {
      ws = new WebSocket(`wss://autonomous-code-migration-agent.onrender.com/ws/runs/${runId}`);

      ws.onopen = () => {
        setConnected(true);
        retryRef.current = 0;
      };
      ws.onmessage = (msg) => {
        const payload = JSON.parse(msg.data);
        if (payload.type === "snapshot") {
          setEvents(payload.events ?? []);
          setLiveRun(payload.run ?? null);
          setApproval(payload.pending_approval ?? null);
        } else if (payload.type === "event") {
          setEvents((prev) => [...prev.slice(-499), payload as EventItem]);
          // events signal data changes — refresh the related queries
          qc.invalidateQueries({ queryKey: ["run", runId] });
          const type = String(payload.event ?? "");
          if (type.startsWith("TASK") || type === "PHASE_COMPLETED")
            qc.invalidateQueries({ queryKey: ["tasks", runId] });
          if (type.startsWith("TEST")) qc.invalidateQueries({ queryKey: ["tests", runId] });
          if (type.startsWith("FILE") || type.startsWith("GIT"))
            qc.invalidateQueries({ queryKey: ["diff", runId] });
        } else if (payload.type === "run_update") {
          setLiveRun(payload.run ?? null);
          setApproval(payload.pending_approval ?? null);
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) {
          const delay = Math.min(15000, 1000 * 2 ** retryRef.current);
          retryRef.current += 1;
          reconnectTimer = window.setTimeout(connect, delay);
        }
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [runId, qc]);

  return { connected, events, liveRun, approval };
}
