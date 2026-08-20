import type { ReactNode } from "react";

type Props = {
  title: string;
  hint?: string;
  /** Rendered at the top-right — usually a live/stale badge. */
  badge?: ReactNode;
  children: ReactNode;
  className?: string;
};

export default function Card({ title, hint, badge, children, className = "" }: Props) {
  return (
    <section
      className={`flex flex-col rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4 ${className}`}
    >
      <header className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium tracking-wide text-[var(--text-secondary)]">{title}</h2>
        {badge}
      </header>
      <div className="flex flex-1 flex-col">{children}</div>
      {hint && <p className="mt-3 text-xs text-[var(--text-muted)]">{hint}</p>}
    </section>
  );
}

export function Stat({
  value,
  unit,
  muted = false,
}: {
  value: string | number;
  unit?: string;
  muted?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span
        className={`text-4xl font-semibold tabular-nums ${
          muted ? "text-[var(--text-muted)]" : "text-[var(--text-primary)]"
        }`}
      >
        {value}
      </span>
      {unit && <span className="text-sm text-[var(--text-secondary)]">{unit}</span>}
    </div>
  );
}

export function Badge({ tone, children }: { tone: "live" | "idle"; children: ReactNode }) {
  const live = tone === "live";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs ${
        live
          ? "border-[var(--good-border)] text-[var(--good)]"
          : "border-[var(--border)] text-[var(--text-muted)]"
      }`}
    >
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${live ? "animate-pulse" : ""}`}
        style={{ background: live ? "var(--good)" : "var(--text-muted)" }}
      />
      {children}
    </span>
  );
}
