"use client";

import { useEffect, useRef, useState } from "react";

import type { RingState } from "@/lib/ring";

/** How long a detection stays on screen before fading back to "waiting". */
const HOLD_MS = 4000;

/** Examples below this and matching is unreliable, so recording chases it. */
const TARGET_EXAMPLES = 3;

export default function Gestures({ ring }: { ring: RingState }) {
  const [name, setName] = useState("");
  const [recent, setRecent] = useState<{ name: string; at: number } | null>(null);
  // While set, keep re-arming for this gesture until it has enough examples,
  // so getting to three is one click rather than three rounds of retyping.
  const [chasing, setChasing] = useState<string | null>(null);
  const handledSave = useRef<number>(0);

  const { lastHit, gestureState, gestureSignal, gestures, lastSaved } = ring;
  const inGestureMode = ring.mode === "gesture";

  const startRecording = (target: string) => {
    ring.recordGesture(target);
    setChasing(target);
  };

  const stopRecording = () => {
    setChasing(null);
    ring.cancelGesture();
  };

  // After each save, re-arm automatically until the target is reached.
  useEffect(() => {
    if (!lastSaved || lastSaved.t === handledSave.current) return;
    handledSave.current = lastSaved.t;
    if (chasing !== lastSaved.name) return;

    if (lastSaved.examples < TARGET_EXAMPLES) {
      ring.recordGesture(lastSaved.name);
    } else {
      setChasing(null);
    }
    // ring is recreated each render; depending on it would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastSaved, chasing]);

  // Keep a detection visible briefly rather than flashing it away.
  useEffect(() => {
    if (lastHit?.name) setRecent({ name: lastHit.name, at: lastHit.t });
  }, [lastHit]);

  useEffect(() => {
    if (!recent) return;
    const timer = setTimeout(() => setRecent(null), HOLD_MS);
    return () => clearTimeout(timer);
  }, [recent]);

  const arming = gestureState.arming;
  // Polling returns a sample ~10x/sec, but the ring may repeat a cached value.
  // If almost nothing is fresh while you are moving, gestures cannot work.
  const stale =
    inGestureMode &&
    gestureSignal !== null &&
    gestureSignal.sample_hz > 3 &&
    gestureSignal.fresh_hz < 1;

  const recorded = (target: string) =>
    gestures.find((gesture) => gesture.name === target)?.examples ?? 0;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed) {
      startRecording(trimmed);
      setName("");
    }
  };

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5">
      <header className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium tracking-wide text-[var(--text-secondary)]">Gestures</h2>
        {inGestureMode && gestureSignal && (
          <span className="text-xs tabular-nums text-[var(--text-muted)]">
            {gestureSignal.sample_hz} Hz polled · {gestureSignal.fresh_hz} Hz fresh
          </span>
        )}
      </header>

      {!inGestureMode && (
        <p className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-3 text-sm text-[var(--text-secondary)]">
          Gesture capture needs the sensor pinned to{" "}
          <button
            onClick={() => ring.setMode("gesture")}
            className="text-[var(--accent)] underline underline-offset-2"
          >
            gesture mode
          </button>
          . Recording switches to it automatically.
        </p>
      )}

      {stale && (
        <p className="mb-4 rounded-lg border border-[var(--warn-border)] bg-[var(--surface-1)] p-3 text-sm text-[var(--warn)]">
          The ring is returning the same reading over and over. If this persists while you move your
          hand, it is repeating a cached value and gestures will not work at this rate.
        </p>
      )}

      {/* The live detection readout — the whole point of the panel. */}
      <div className="mb-5 flex min-h-28 flex-col items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-5 text-center">
        {arming ? (
          <>
            <p className="text-sm text-[var(--text-secondary)]">
              {gestureState.capturing ? "Capturing…" : "Ready — perform the gesture now"}
            </p>
            <p className="mt-1 text-2xl font-semibold">{arming}</p>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              example {Math.min(recorded(arming) + 1, TARGET_EXAMPLES)} of {TARGET_EXAMPLES}
              {recorded(arming) >= TARGET_EXAMPLES && " — extra examples only help"}
            </p>
            <button
              onClick={stopRecording}
              className="mt-2 text-xs text-[var(--text-muted)] underline underline-offset-2"
            >
              stop recording
            </button>
          </>
        ) : recent ? (
          <>
            <p className="text-xs uppercase tracking-widest text-[var(--text-muted)]">detected</p>
            <p className="mt-1 text-5xl font-semibold text-[var(--good)]">{recent.name}</p>
          </>
        ) : gestureState.capturing ? (
          <p className="text-lg text-[var(--accent)]">capturing motion…</p>
        ) : (
          <>
            <p className="text-lg text-[var(--text-muted)]">
              {gestures.length === 0 ? "no gestures recorded yet" : "waiting for a gesture"}
            </p>
            {/* On a miss, show what it was actually close to. Without this
                there is no way to tell a bad recording from two gestures that
                are simply too alike. */}
            {lastHit && !lastHit.name && lastHit.reason && (
              <div className="mt-2">
                <p className="text-xs text-[var(--text-muted)]">
                  last attempt: {lastHit.reason} · {lastHit.samples} samples
                </p>
                {lastHit.ranking?.length > 0 && (
                  <ul className="mt-1 flex flex-wrap justify-center gap-x-3 text-xs text-[var(--text-muted)]">
                    {lastHit.ranking.map((entry) => (
                      <li key={entry.name} className="tabular-nums">
                        {entry.name}{" "}
                        <span
                          className={
                            entry.distance <= entry.threshold
                              ? "text-[var(--good)]"
                              : "text-[var(--text-muted)]"
                          }
                        >
                          {entry.distance}
                        </span>
                        <span className="opacity-60">/{entry.threshold}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <form onSubmit={submit} className="mb-4 flex flex-wrap gap-2">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Gesture name, e.g. O"
          className="min-w-40 flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-2 text-sm outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
        />
        <button
          type="submit"
          disabled={!name.trim()}
          className="rounded-lg border border-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
        >
          Record
        </button>
      </form>

      {ring.lastSaved && (
        <p
          className={`mb-4 text-xs ${
            ring.lastSaved.outlier ? "text-[var(--warn)]" : "text-[var(--text-muted)]"
          }`}
        >
          saved “{ring.lastSaved.name}” — {ring.lastSaved.examples} example
          {ring.lastSaved.examples === 1 ? "" : "s"}, {ring.lastSaved.samples} samples
          {ring.lastSaved.agreement !== null && `, agreement ${ring.lastSaved.agreement}`}.{" "}
          {ring.lastSaved.outlier
            ? "This one looks very different from your other takes — delete the gesture and re-record if matching gets worse."
            : "Record it 3 or more times for reliable matching."}
        </p>
      )}

      {gestures.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {gestures.map((gesture) => {
            const thin = gesture.examples < TARGET_EXAMPLES;
            return (
              <li
                key={gesture.name}
                className={`flex items-center gap-2 rounded-full border py-1 pl-3 pr-2 text-sm ${
                  thin ? "border-[var(--warn-border)]" : "border-[var(--border)]"
                }`}
              >
                <span>{gesture.name}</span>
                <span
                  className={`tabular-nums text-xs ${
                    thin ? "text-[var(--warn)]" : "text-[var(--text-muted)]"
                  }`}
                  title={
                    thin
                      ? `only ${gesture.examples} example(s) — matching will be weak`
                      : `${gesture.examples} examples`
                  }
                >
                  {gesture.examples}/{TARGET_EXAMPLES}
                </span>
                <button
                  onClick={() => startRecording(gesture.name)}
                  className="rounded-full border border-[var(--accent)] px-2 py-0.5 text-xs text-[var(--text-primary)]"
                  title={`Record another example of ${gesture.name}`}
                >
                  + example
                </button>
                <button
                  onClick={() => ring.deleteGesture(gesture.name)}
                  aria-label={`Delete ${gesture.name}`}
                  className="rounded-full px-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
