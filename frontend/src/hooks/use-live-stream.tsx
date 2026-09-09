'use client';

import { useQueryClient } from '@tanstack/react-query';
import * as React from 'react';

import { websocketUrl } from '@/lib/api-client';
import { qk } from '@/lib/query-keys';
import type { DashboardSummary, WsFrame } from '@/lib/types';

export type StreamStatus = 'connecting' | 'live' | 'reconnecting' | 'offline';

export interface StreamEvent {
  id: number;
  topic: string;
  event: string;
  payload: Record<string, unknown>;
  ts: string;
}

interface LiveStreamValue {
  status: StreamStatus;
  topics: string[];
  backend: string | null;
  lastFrameAt: string | null;
  snapshot: DashboardSummary | null;
  events: StreamEvent[];
  attempts: number;
  clearEvents: () => void;
  reconnect: () => void;
}

const LiveStreamContext = React.createContext<LiveStreamValue | null>(null);

/** Query keys refreshed when a topic pushes an event. */
const TOPIC_INVALIDATIONS: Record<string, readonly unknown[][]> = {
  vitals: [[...qk.dashboard], ['personnel']],
  alerts: [[...qk.alertSummary], ['alerts'], [...qk.dashboard]],
  drones: [[...qk.drones], [...qk.droneEvents]],
  security: [['security']],
  simulation: [[...qk.simulationStatus]],
  dashboard: [[...qk.dashboard]],
};

const MAX_EVENTS = 120;
const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000, 30000];

/**
 * Single WebSocket connection shared by the whole console.
 *
 * Reconnection uses capped exponential backoff and, on every successful
 * (re)connect, asks the server for a fresh snapshot so a client that was
 * offline for a while cannot keep showing stale numbers.
 */
export function LiveStreamProvider({
  enabled,
  children,
}: {
  enabled: boolean;
  children: React.ReactNode;
}) {
  const queryClient = useQueryClient();
  const [status, setStatus] = React.useState<StreamStatus>('offline');
  const [topics, setTopics] = React.useState<string[]>([]);
  const [backend, setBackend] = React.useState<string | null>(null);
  const [lastFrameAt, setLastFrameAt] = React.useState<string | null>(null);
  const [snapshot, setSnapshot] = React.useState<DashboardSummary | null>(null);
  const [events, setEvents] = React.useState<StreamEvent[]>([]);
  const [attempts, setAttempts] = React.useState(0);
  const [generation, setGeneration] = React.useState(0);

  const socketRef = React.useRef<WebSocket | null>(null);
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = React.useRef(0);
  const eventSeq = React.useRef(0);
  const closedByUs = React.useRef(false);

  const handleFrame = React.useCallback(
    (frame: WsFrame) => {
      setLastFrameAt(new Date().toISOString());
      switch (frame.type) {
        case 'connection.ready':
          setTopics(frame.topics);
          setBackend(frame.backend);
          setStatus('live');
          attemptRef.current = 0;
          setAttempts(0);
          break;
        case 'snapshot':
          setSnapshot(frame.payload);
          queryClient.setQueryData([...qk.dashboard], frame.payload);
          break;
        case 'event': {
          eventSeq.current += 1;
          const entry: StreamEvent = {
            id: eventSeq.current,
            topic: frame.topic,
            event: frame.event,
            payload: frame.payload,
            ts: frame.ts,
          };
          setEvents((previous) => [entry, ...previous].slice(0, MAX_EVENTS));
          for (const key of TOPIC_INVALIDATIONS[frame.topic] ?? []) {
            void queryClient.invalidateQueries({ queryKey: key });
          }
          break;
        }
        case 'subscribed':
          setTopics(frame.topics);
          break;
        default:
          break;
      }
    },
    [queryClient],
  );

  React.useEffect(() => {
    if (!enabled || typeof window === 'undefined') {
      setStatus('offline');
      return;
    }

    let disposed = false;
    closedByUs.current = false;

    const connect = () => {
      if (disposed) return;
      const url = websocketUrl();
      if (!url) {
        setStatus('offline');
        return;
      }
      setStatus(attemptRef.current === 0 ? 'connecting' : 'reconnecting');

      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        // Ask for a snapshot explicitly: it makes the reconnect path identical
        // to the first-connect path.
        socket.send(JSON.stringify({ action: 'snapshot' }));
      };

      socket.onmessage = (message) => {
        try {
          handleFrame(JSON.parse(message.data as string) as WsFrame);
        } catch {
          /* ignore frames we cannot parse */
        }
      };

      socket.onerror = () => {
        /* the close handler owns the retry */
      };

      socket.onclose = () => {
        socketRef.current = null;
        if (disposed || closedByUs.current) return;
        const delay = BACKOFF_MS[Math.min(attemptRef.current, BACKOFF_MS.length - 1)];
        attemptRef.current += 1;
        setAttempts(attemptRef.current);
        setStatus('reconnecting');
        timerRef.current = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      disposed = true;
      closedByUs.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
      setStatus('offline');
    };
  }, [enabled, handleFrame, generation]);

  const value = React.useMemo<LiveStreamValue>(
    () => ({
      status,
      topics,
      backend,
      lastFrameAt,
      snapshot,
      events,
      attempts,
      clearEvents: () => setEvents([]),
      reconnect: () => {
        attemptRef.current = 0;
        setGeneration((g) => g + 1);
      },
    }),
    [status, topics, backend, lastFrameAt, snapshot, events, attempts],
  );

  return <LiveStreamContext.Provider value={value}>{children}</LiveStreamContext.Provider>;
}

export function useLiveStream(): LiveStreamValue {
  const context = React.useContext(LiveStreamContext);
  if (!context) throw new Error('useLiveStream must be used inside <LiveStreamProvider>.');
  return context;
}
