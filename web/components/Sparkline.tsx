"use client";

import { useId, useMemo, useState } from "react";

export type Series = { label: string; color: string; points: (number | null)[] };

type Props = {
  series: Series[];
  height?: number;
  /** Fixed y-domain; omit to fit the data. */
  domain?: [number, number];
  unit?: string;
  /** Value to draw a recessive reference line at (e.g. 1g for the accel view). */
  reference?: number;
};

const PAD = { top: 8, right: 8, bottom: 8, left: 8 };

/**
 * Multi-series line chart with a crosshair + tooltip. Deliberately axis-light:
 * these are live rolling streams where the shape and the current value matter,
 * and the exact value lives in the tooltip and the stat tile above.
 */
export default function Sparkline({ series, height = 96, domain, unit = "", reference }: Props) {
  const clipId = useId();
  const [hover, setHover] = useState<number | null>(null);

  const length = Math.max(...series.map((s) => s.points.length), 1);

  const [min, max] = useMemo(() => {
    if (domain) return domain;
    const values = series.flatMap((s) => s.points.filter((p): p is number => p !== null));
    if (values.length === 0) return [0, 1];
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    if (lo === hi) return [lo - 1, hi + 1];
    const margin = (hi - lo) * 0.12;
    return [lo - margin, hi + margin];
  }, [series, domain]);

  const width = 320;
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;

  const xAt = (i: number) => PAD.left + (length <= 1 ? plotW : (i / (length - 1)) * plotW);
  const yAt = (v: number) => PAD.top + plotH - ((v - min) / (max - min)) * plotH;

  const path = (points: (number | null)[]) => {
    let d = "";
    let penDown = false;
    points.forEach((value, i) => {
      if (value === null) {
        penDown = false;
        return;
      }
      d += `${penDown ? "L" : "M"}${xAt(i).toFixed(1)} ${yAt(value).toFixed(1)} `;
      penDown = true;
    });
    return d.trim();
  };

  const hoverIndex = hover === null ? null : Math.round(((hover - PAD.left) / plotW) * (length - 1));

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        preserveAspectRatio="none"
        role="img"
        aria-label={series.map((s) => s.label).join(", ")}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setHover(((event.clientX - rect.left) / rect.width) * width);
        }}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x={PAD.left} y={0} width={plotW} height={height} />
          </clipPath>
        </defs>

        {reference !== undefined && reference >= min && reference <= max && (
          <line
            x1={PAD.left}
            x2={width - PAD.right}
            y1={yAt(reference)}
            y2={yAt(reference)}
            stroke="var(--grid)"
            strokeWidth={1}
            strokeDasharray="3 4"
          />
        )}

        <g clipPath={`url(#${clipId})`}>
          {series.map((s) => (
            <path
              key={s.label}
              d={path(s.points)}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </g>

        {hoverIndex !== null && hoverIndex >= 0 && hoverIndex < length && (
          <>
            <line
              x1={xAt(hoverIndex)}
              x2={xAt(hoverIndex)}
              y1={PAD.top}
              y2={height - PAD.bottom}
              stroke="var(--grid)"
              strokeWidth={1}
            />
            {series.map((s) => {
              const value = s.points[hoverIndex];
              if (value === null || value === undefined) return null;
              return (
                <circle
                  key={s.label}
                  cx={xAt(hoverIndex)}
                  cy={yAt(value)}
                  r={4}
                  fill={s.color}
                  stroke="var(--surface-2)"
                  strokeWidth={2}
                />
              );
            })}
          </>
        )}
      </svg>

      {hoverIndex !== null && hoverIndex >= 0 && hoverIndex < length && (
        <div
          className="pointer-events-none absolute top-0 rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-2 py-1 text-xs shadow-lg"
          style={{
            left: `${(xAt(hoverIndex) / width) * 100}%`,
            transform: "translateX(-50%)",
          }}
        >
          {series.map((s) => {
            const value = s.points[hoverIndex];
            return (
              <div key={s.label} className="flex items-center gap-1.5 whitespace-nowrap">
                <span
                  className="inline-block h-2 w-2 shrink-0 rounded-full"
                  style={{ background: s.color }}
                />
                <span className="text-[var(--text-secondary)]">{s.label}</span>
                <span className="tabular-nums text-[var(--text-primary)]">
                  {value === null || value === undefined ? "--" : Math.round(value)}
                  {unit}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
