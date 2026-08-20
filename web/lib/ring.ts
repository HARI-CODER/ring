"use client";

import { useEffect, useRef, useState } from "react";

export const WS_URL = process.env.NEXT_PUBLIC_RING_WS ?? "ws://127.0.0.1:8765";

export type Mode = "hr" | "motion" | "gesture";

type Base = { t: number };
export type Battery = Base & { type: "battery"; percent: number; charging: boolean };
export type Hr = Base & { type: "hr"; bpm: number };
export type Spo2 = Base & { type: "spo2"; percent: number };
export type Accel = Base & { type: "accel"; x: number; y: number; z: number; g: number };
export type Ppg = Base & { type: "ppg"; channel: "a" | "b"; value: number; saturated: boolean };
export type Activity = Base & {
  type: "activity";
  steps: number;
  distance_cm: number;
  calories: number;
};
export type ModeMsg = Base & { type: "mode"; mode: Mode; pinned: boolean };
export type GestureItem = { name: string; examples: number; threshold: number };
export type Ranked = { name: string; distance: number; threshold: number };
export type Gestures = Base & { type: "gestures"; items: GestureItem[] };
export type GestureState = Base & {
  type: "gesture_state";
  capturing: boolean;
  arming: string | null;
};
export type GestureSignal = Base & { type: "gesture_signal"; sample_hz: number; fresh_hz: number };
export type GestureSaved = Base & {
  type: "gesture_saved";
  name: string;
  examples: number;
  samples: number;
  /** Distance to the nearest existing example; null for the first one. */
  agreement: number | null;
  outlier: boolean;
};
export type GestureHit = Base & {
  type: "gesture";
  name: string | null;
  distance: number | null;
  reason: string | null;
  samples: number;
  ranking: Ranked[];
};

export type Message =
  | Battery
  | Hr
  | Spo2
  | Accel
  | Ppg
  | Activity
  | ModeMsg
  | Gestures
  | GestureState
  | GestureSignal
  | GestureSaved
  | GestureHit;

const HISTORY = 120;

export type RingState = {
  connected: boolean;
  mode: Mode | null;
  pinned: boolean;
  battery: Battery | null;
  hr: Hr | null;
  spo2: Spo2 | null;
  accel: Accel | null;
  activity: Activity | null;
  /** Most recent first-in-last-out buffers for the charts. */
  hrHistory: { t: number; bpm: number }[];
  accelHistory: Accel[];
  ppgHistory: { t: number; a: number | null; b: number | null }[];
  /** Steps/min estimated from consecutive activity frames. */
  cadence: number;
  gestures: GestureItem[];
  gestureState: { capturing: boolean; arming: string | null };
  gestureSignal: GestureSignal | null;
  lastHit: GestureHit | null;
  lastSaved: GestureSaved | null;
  setMode: (mode: Mode | "auto") => void;
  recordGesture: (name: string) => void;
  cancelGesture: () => void;
  deleteGesture: (name: string) => void;
};

function push<T>(list: T[], item: T): T[] {
  const next = [...list, item];
  return next.length > HISTORY ? next.slice(next.length - HISTORY) : next;
}

export function useRing(): RingState {
  const [connected, setConnected] = useState(false);
  const [mode, setModeState] = useState<Mode | null>(null);
  const [pinned, setPinned] = useState(false);
  const [battery, setBattery] = useState<Battery | null>(null);
  const [hr, setHr] = useState<Hr | null>(null);
  const [spo2, setSpo2] = useState<Spo2 | null>(null);
  const [accel, setAccel] = useState<Accel | null>(null);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [hrHistory, setHrHistory] = useState<{ t: number; bpm: number }[]>([]);
  const [accelHistory, setAccelHistory] = useState<Accel[]>([]);
  const [ppgHistory, setPpgHistory] = useState<{ t: number; a: number | null; b: number | null }[]>(
    [],
  );
  const [cadence, setCadence] = useState(0);
  const [gestures, setGestures] = useState<GestureItem[]>([]);
  const [gestureState, setGestureState] = useState<{ capturing: boolean; arming: string | null }>({
    capturing: false,
    arming: null,
  });
  const [gestureSignal, setGestureSignal] = useState<GestureSignal | null>(null);
  const [lastHit, setLastHit] = useState<GestureHit | null>(null);
  const [lastSaved, setLastSaved] = useState<GestureSaved | null>(null);

  const socket = useRef<WebSocket | null>(null);
  const prevActivity = useRef<Activity | null>(null);
  const lastPpg = useRef<{ a: number | null; b: number | null }>({ a: null, b: null });

  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    const connect = () => {
      if (closed) return;
      const ws = new WebSocket(WS_URL);
      socket.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        // The bridge is a local process; assume it will come back.
        retry = setTimeout(connect, 1500);
      };
      ws.onerror = () => ws.close();

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data as string) as Message;
        switch (msg.type) {
          case "battery":
            setBattery(msg);
            break;
          case "hr":
            setHr(msg);
            setHrHistory((prev) => push(prev, { t: msg.t, bpm: msg.bpm }));
            break;
          case "spo2":
            setSpo2(msg);
            break;
          case "accel":
            setAccel(msg);
            setAccelHistory((prev) => push(prev, msg));
            break;
          case "ppg": {
            // The two channels arrive as separate frames. Carry the other
            // channel forward, or every point would have a null neighbour and
            // the line would never draw a segment.
            const value = msg.saturated ? null : msg.value;
            if (msg.channel === "a") lastPpg.current.a = value;
            else lastPpg.current.b = value;
            setPpgHistory((prev) => push(prev, { t: msg.t, ...lastPpg.current }));
            break;
          }
          case "activity": {
            const previous = prevActivity.current;
            if (previous && msg.t > previous.t) {
              const steps = msg.steps - previous.steps;
              const minutes = (msg.t - previous.t) / 60;
              // Ignore day rollovers and long idle gaps.
              if (steps > 0 && minutes > 0 && minutes < 1) {
                setCadence(Math.round(steps / minutes));
              } else if (steps <= 0) {
                setCadence(0);
              }
            }
            prevActivity.current = msg;
            setActivity(msg);
            break;
          }
          case "mode":
            setModeState(msg.mode);
            setPinned(msg.pinned);
            break;
          case "gestures":
            setGestures(msg.items);
            break;
          case "gesture_state":
            setGestureState({ capturing: msg.capturing, arming: msg.arming });
            break;
          case "gesture_signal":
            setGestureSignal(msg);
            break;
          case "gesture_saved":
            setLastSaved(msg);
            break;
          case "gesture":
            setLastHit(msg);
            break;
        }
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket.current?.close();
    };
  }, []);

  const send = (payload: object) => socket.current?.send(JSON.stringify(payload));

  const setMode = (wanted: Mode | "auto") => {
    send({ mode: wanted });
    setPinned(wanted !== "auto");
  };

  const recordGesture = (name: string) => {
    send({ record: name });
    setPinned(true);
    setModeState("gesture");
  };

  const cancelGesture = () => send({ cancel: true });
  const deleteGesture = (name: string) => send({ delete: name });

  return {
    gestures,
    gestureState,
    gestureSignal,
    lastHit,
    lastSaved,
    recordGesture,
    cancelGesture,
    deleteGesture,
    connected,
    mode,
    pinned,
    battery,
    hr,
    spo2,
    accel,
    activity,
    hrHistory,
    accelHistory,
    ppgHistory,
    cadence,
    setMode,
  };
}

/** Roll / pitch in degrees from a gravity vector, for the ring orientation view. */
export function orientation(a: Accel | null) {
  if (!a) return { roll: 0, pitch: 0 };
  const roll = (Math.atan2(a.y, a.z) * 180) / Math.PI;
  const pitch = (Math.atan2(-a.x, Math.hypot(a.y, a.z)) * 180) / Math.PI;
  return { roll, pitch };
}
