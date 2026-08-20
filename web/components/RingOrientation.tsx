"use client";

import type { Accel } from "@/lib/ring";
import { orientation } from "@/lib/ring";

/**
 * The ring, tilted by the gravity vector the accelerometer reports.
 *
 * Roll and pitch come from gravity, so this is absolute orientation and is
 * trustworthy while the hand is still. It cannot show yaw (rotation about the
 * vertical axis) -- that needs a gyro or magnetometer, and the ring exposes
 * neither. During fast motion the vector includes acceleration as well as
 * gravity, so the tilt overshoots; that is inherent, not a bug.
 */
export default function RingOrientation({ accel }: { accel: Accel | null }) {
  const { roll, pitch } = orientation(accel);
  const moving = accel !== null && Math.abs(accel.g - 1) > 0.15;

  return (
    <div className="flex flex-col items-center gap-3 py-2">
      <div
        className="flex h-28 w-28 items-center justify-center"
        style={{ perspective: "420px" }}
        aria-label={`Ring tilted ${Math.round(roll)} degrees roll, ${Math.round(pitch)} degrees pitch`}
      >
        <div
          className="transition-transform duration-500 ease-out"
          style={{
            transformStyle: "preserve-3d",
            // roll is rotation about X, pitch about Y -- feed each to its own
            // axis. (These were previously swapped, which pinned the ring
            // edge-on.) Pitch is applied first, matching the usual
            // pitch-then-roll reconstruction of attitude from gravity.
            transform: `rotateY(${pitch}deg) rotateX(${roll}deg)`,
          }}
        >
          <svg viewBox="0 0 100 100" className="h-24 w-24" aria-hidden="true">
            {/* Ring band, drawn as a torus-ish pair of ellipses. */}
            <ellipse
              cx="50"
              cy="50"
              rx="34"
              ry="34"
              fill="none"
              stroke={accel ? "var(--accent)" : "var(--surface-3)"}
              strokeWidth="11"
            />
            <ellipse
              cx="50"
              cy="50"
              rx="34"
              ry="34"
              fill="none"
              stroke="var(--surface-2)"
              strokeWidth="1.5"
              opacity="0.7"
            />
            {/* Sensor puck, so the rotation is readable. */}
            <circle
              cx="50"
              cy="16"
              r="5.5"
              fill="var(--surface-1)"
              stroke={accel ? "var(--accent)" : "var(--border)"}
              strokeWidth="2"
            />
          </svg>
        </div>
      </div>

      <dl className="grid grid-cols-3 gap-x-5 gap-y-0.5 text-center">
        {[
          ["roll", `${Math.round(roll)}°`],
          ["pitch", `${Math.round(pitch)}°`],
          ["force", accel ? `${accel.g.toFixed(2)} g` : "--"],
        ].map(([label, value]) => (
          <div key={label}>
            <dd className="tabular-nums text-sm text-[var(--text-primary)]">{value}</dd>
            <dt className="text-xs text-[var(--text-muted)]">{label}</dt>
          </div>
        ))}
      </dl>

      <p className="text-xs text-[var(--text-muted)]">
        {accel === null ? "waiting for motion data" : moving ? "in motion" : "at rest"}
      </p>

      {/* The numbers the angles are derived from, so the mapping is checkable. */}
      {accel && (
        <p className="font-mono text-[11px] tabular-nums text-[var(--text-muted)]">
          x {accel.x} · y {accel.y} · z {accel.z}
        </p>
      )}
    </div>
  );
}
