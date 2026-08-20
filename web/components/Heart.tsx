"use client";

/**
 * Heart that beats at the measured rate. The animation period is driven by the
 * BPM, so the visual is the data rather than decoration. With no reading it
 * holds still and greys out rather than faking a pulse.
 */
export default function Heart({ bpm }: { bpm: number | null }) {
  const beating = bpm !== null && bpm > 0;
  const period = beating ? 60 / bpm : 0;

  return (
    <div className="flex items-center justify-center py-2">
      <svg viewBox="0 0 32 30" className="h-24 w-24" aria-hidden="true">
        <path
          d="M16 28C16 28 2 19.5 2 10.5A7.5 7.5 0 0 1 16 6.8 7.5 7.5 0 0 1 30 10.5C30 19.5 16 28 16 28Z"
          fill={beating ? "var(--hr)" : "var(--surface-3)"}
          stroke={beating ? "var(--hr)" : "var(--border)"}
          strokeWidth={1.5}
          strokeLinejoin="round"
          style={{
            transformOrigin: "center",
            transformBox: "fill-box",
            animation: beating ? `heartbeat ${period}s ease-in-out infinite` : undefined,
          }}
        />
      </svg>
    </div>
  );
}
