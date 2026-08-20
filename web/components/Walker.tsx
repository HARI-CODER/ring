"use client";

/**
 * Walking figure whose stride rate tracks the measured cadence. Cadence is
 * derived from consecutive step totals, so it only moves once the ring has
 * reported at least two activity frames while you were walking.
 */
export default function Walker({ cadence }: { cadence: number }) {
  const walking = cadence > 0;
  // One full stride cycle = two steps.
  const period = walking ? Math.max(0.3, 120 / cadence) : 0;
  const style = walking
    ? { animation: `stride ${period}s linear infinite`, transformOrigin: "top center" }
    : undefined;

  return (
    <div className="flex flex-col items-center gap-2 py-2">
      <svg viewBox="0 0 60 90" className="h-24" aria-hidden="true">
        <g stroke="var(--accent)" strokeWidth="4" strokeLinecap="round" fill="none">
          <circle cx="30" cy="12" r="8" fill="var(--accent)" stroke="none" />
          <line x1="30" y1="21" x2="30" y2="52" />
          {/* Arms and legs counter-swing; the delay offsets make it read as a gait. */}
          <line x1="30" y1="30" x2="16" y2="44" style={style} />
          <line
            x1="30"
            y1="30"
            x2="44"
            y2="44"
            style={style ? { ...style, animationDelay: `-${period / 2}s` } : undefined}
          />
          <line x1="30" y1="52" x2="18" y2="80" style={style ? { ...style, animationDelay: `-${period / 2}s` } : undefined} />
          <line x1="30" y1="52" x2="42" y2="80" style={style} />
        </g>
      </svg>
      <p className="text-xs text-[var(--text-muted)]">
        {walking ? `${cadence} steps/min` : "not walking"}
      </p>
    </div>
  );
}
