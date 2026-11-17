"use client";
import { useEffect, useRef, useState } from "react";

import { API_URL, WS_URL } from "./api";

export type Frame = { t: string; stamp?: string | null; replay: boolean; fixture_id?: string;
  name: string[]; position: (number | null)[]; velocity: (number | null)[] };
export type ReadinessTick = { task: string; status: string; summary: string; trace_id: string; at: string };
export type WsState = "connecting" | "open" | "closed";

export const MAX_FRAMES = 300;

/** Append with a hard cap: the browser never holds more than `max` frames. */
export function pushBounded<T>(buf: T[], item: T, max = MAX_FRAMES): T[] {
  const next = buf.length >= max ? buf.slice(buf.length - max + 1) : buf.slice();
  next.push(item);
  return next;
}

export function reconnectDelay(attempt: number): number {
  return Math.min(500 * 2 ** attempt, 10_000);
}

/**
 * Live telemetry over the API's WebSocket, seeded from /telemetry/history, reconnecting with
 * exponential backoff. When the socket is down the UI says so; it never invents frames.
 */
export function useTelemetry() {
  const [frames, setFrames] = useState<Frame[]>([]);
  const [readiness, setReadiness] = useState<ReadinessTick[]>([]);
  const [state, setState] = useState<WsState>("connecting");
  const [lastMessageAt, setLastMessageAt] = useState<number | null>(null);
  const [epoch, setEpoch] = useState(0);
  const attempt = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    fetch(`${API_URL}/api/v1/telemetry/history?limit=${MAX_FRAMES}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => {
        if (!h || disposed) return;
        setFrames(h.frames.slice(-MAX_FRAMES));
        setReadiness(h.readiness.slice(-MAX_FRAMES));
      })
      .catch(() => undefined);

    const open = () => {
      if (disposed) return;
      setState("connecting");
      ws = new WebSocket(WS_URL);
      ws.onopen = () => {
        attempt.current = 0;
        setState("open");
      };
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data);
        setLastMessageAt(Date.now());
        if (m.type === "telemetry") setFrames((f) => pushBounded(f, m.frame as Frame));
        else if (m.type === "readiness" && m.task === "overall") setReadiness((r) => pushBounded(r, m as ReadinessTick));
        else if (m.type === "event" && m.kind === "fixture") setFrames([]);
      };
      ws.onclose = () => {
        if (disposed) return;
        setState("closed");
        timer = setTimeout(open, reconnectDelay(attempt.current++));
      };
      ws.onerror = () => ws?.close();
    };
    open();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, [epoch]);

  return { frames, readiness, state, lastMessageAt, reset: () => setEpoch((e) => e + 1) };
}

export function series(frames: Frame[], joint: string): { t: number; v: number | null }[] {
  return frames.map((f) => {
    const i = f.name.indexOf(joint);
    return { t: new Date(f.t).getTime(), v: i >= 0 ? f.position[i] ?? null : null };
  });
}
