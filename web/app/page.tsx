"use client";

import Card, { Badge, Stat } from "@/components/Card";
import Gestures from "@/components/Gestures";
import Heart from "@/components/Heart";
import RingOrientation from "@/components/RingOrientation";
import Sparkline from "@/components/Sparkline";
import Walker from "@/components/Walker";
import { useRing, WS_URL } from "@/lib/ring";

/** A stream counts as live if it produced a sample recently. */
function fresh(t: number | undefined, seconds: number) {
  return t !== undefined && Date.now() / 1000 - t < seconds;
}

export default function Page() {
  const ring = useRing();
  const { accelHistory, ppgHistory, hrHistory } = ring;

  const hrLive = fresh(ring.hr?.t, 8);
  const motionLive = fresh(ring.accel?.t, 8);

  // Off the finger the optical channels emit a constant, not a waveform.
  const ppgVaries = (() => {
    const values = ppgHistory.map((p) => p.a).filter((v): v is number => v !== null);
    return values.length > 1 && new Set(values).size > 1;
  })();

  return (
    <main className="mx-auto max-w-6xl px-5 py-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">PBL Halo 2</h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Live sensor data over the local BLE bridge
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Badge tone={ring.connected ? "live" : "idle"}>
            {ring.connected ? "bridge connected" : "bridge offline"}
          </Badge>
          {ring.battery && (
            <span className="text-sm tabular-nums text-[var(--text-secondary)]">
              {ring.battery.percent}%{ring.battery.charging ? " charging" : ""}
            </span>
          )}
        </div>
      </header>

      {!ring.connected && (
        <p className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-4 text-sm text-[var(--text-secondary)]">
          No bridge at <code className="text-[var(--text-primary)]">{WS_URL}</code>. Start it with{" "}
          <code className="text-[var(--text-primary)]">.venv/bin/python bridge.py</code> — this page
          reconnects on its own.
        </p>
      )}

      {/* The ring runs one sensor at a time, so the mode is a first-class control. */}
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <span className="mr-1 text-sm text-[var(--text-secondary)]">Sensor</span>
        {(["auto", "hr", "motion", "gesture"] as const).map((option) => {
          const active =
            option === "auto" ? !ring.pinned : ring.pinned && ring.mode === option;
          return (
            <button
              key={option}
              onClick={() => ring.setMode(option)}
              className={`rounded-full border px-3 py-1 text-sm transition-colors ${
                active
                  ? "border-[var(--accent)] text-[var(--text-primary)]"
                  : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--grid)]"
              }`}
            >
              {option === "hr" ? "heart rate" : option}
            </button>
          );
        })}
        <span className="text-xs text-[var(--text-muted)]">
          currently reading {ring.mode ?? "--"}
          {!ring.pinned && " (alternating)"}
        </span>
      </div>

      <div className="mb-4">
        <Gestures ring={ring} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Card
          title="Heart rate"
          badge={<Badge tone={hrLive ? "live" : "idle"}>{hrLive ? "live" : "idle"}</Badge>}
          hint="Takes roughly 25s of uninterrupted measurement to lock on."
        >
          <Heart bpm={hrLive ? (ring.hr?.bpm ?? null) : null} />
          <Stat value={ring.hr?.bpm ?? "--"} unit="bpm" muted={!hrLive} />
          {hrHistory.length > 1 && (
            <div className="mt-3">
              <Sparkline
                series={[
                  { label: "heart rate", color: "var(--hr)", points: hrHistory.map((h) => h.bpm) },
                ]}
                unit=" bpm"
                height={72}
              />
            </div>
          )}
        </Card>

        <Card
          title="Orientation"
          badge={<Badge tone={motionLive ? "live" : "idle"}>{motionLive ? "live" : "idle"}</Badge>}
          hint="Tilt from gravity. Yaw is not shown — the ring has no gyro or magnetometer. Which sensor axis runs through the band is uncalibrated, so the tilt direction may not match the real ring."
        >
          <RingOrientation accel={motionLive ? ring.accel : null} />
        </Card>

        <Card
          title="Walking"
          badge={<Badge tone={ring.cadence > 0 ? "live" : "idle"}>
            {ring.cadence > 0 ? "moving" : "still"}
          </Badge>}
          hint="Totals come from the ring's own step counter and reset daily."
        >
          <Walker cadence={ring.cadence} />
          <div className="mt-2 grid grid-cols-3 gap-2">
            {[
              ["steps", ring.activity?.steps ?? "--"],
              [
                "km",
                ring.activity ? (ring.activity.distance_cm / 100000).toFixed(2) : "--",
              ],
              ["kcal", ring.activity?.calories ?? "--"],
            ].map(([label, value]) => (
              <div key={label as string}>
                <div className="text-xl font-semibold tabular-nums">{value}</div>
                <div className="text-xs text-[var(--text-muted)]">{label}</div>
              </div>
            ))}
          </div>
        </Card>

        <Card
          title="Accelerometer"
          className="lg:col-span-2"
          badge={<Badge tone={motionLive ? "live" : "idle"}>{motionLive ? "live" : "idle"}</Badge>}
          hint={`Raw counts at 8192 per g. Dashed line marks 0 — ${
            ring.mode === "gesture" ? "polled at about 10 Hz." : "pushed at about 1 Hz."
          }`}
        >
          <div className="mb-2 flex flex-wrap gap-4 text-xs">
            {[
              ["X", "var(--axis-x)", ring.accel?.x],
              ["Y", "var(--axis-y)", ring.accel?.y],
              ["Z", "var(--axis-z)", ring.accel?.z],
            ].map(([label, color, value]) => (
              <span key={label as string} className="flex items-center gap-1.5">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: color as string }}
                />
                <span className="text-[var(--text-secondary)]">{label}</span>
                <span className="tabular-nums text-[var(--text-primary)]">{value ?? "--"}</span>
              </span>
            ))}
          </div>
          <Sparkline
            height={140}
            reference={0}
            series={[
              { label: "X", color: "var(--axis-x)", points: accelHistory.map((a) => a.x) },
              { label: "Y", color: "var(--axis-y)", points: accelHistory.map((a) => a.y) },
              { label: "Z", color: "var(--axis-z)", points: accelHistory.map((a) => a.z) },
            ]}
          />
        </Card>

        <Card
          title="PPG (optical)"
          badge={
            ppgHistory.length > 1 && !ppgVaries ? <Badge tone="idle">flat</Badge> : undefined
          }
          hint={
            ppgVaries
              ? "The raw optical signal the heart-rate estimate is derived from."
              : "These only vary while the ring is worn; off the finger they sit at a fixed value."
          }
        >
          {ppgHistory.length > 1 ? (
            <Sparkline
              height={140}
              series={[
                {
                  label: "channel A",
                  color: "var(--axis-x)",
                  points: ppgHistory.map((p) => p.a),
                },
                {
                  label: "channel B",
                  color: "var(--axis-y)",
                  points: ppgHistory.map((p) => p.b),
                },
              ]}
            />
          ) : (
            <p className="py-8 text-center text-sm text-[var(--text-muted)]">
              waiting for motion mode
            </p>
          )}
        </Card>
      </div>
    </main>
  );
}
