// Small shared pieces: the glass card, pills and the line icons on the left rail.
import type { ReactNode } from "react";

const PATHS: Record<string, string> = {
  home: "M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z",
  markets: "M4 19V9m5 10V5m5 14v-7m5 7V8",
  team: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7 1a2.5 2.5 0 1 0 0-5M3 20c0-3 3-5 6-5s6 2 6 5m2-5c2 0 4 1.5 4 4",
  tune: "M5 4v7m0 4v5m7-16v3m0 4v9m7-16v11m0 4v1M3 13h4m3-6h4m3 10h4",
  plug: "M9 3v5m6-5v5M7 8h10v3a5 5 0 0 1-10 0zm5 8v5",
  play: "M8 5v14l11-7z",
  stop: "M7 7h10v10H7z",
  bolt: "M13 3 5 14h6l-1 7 8-11h-6z",
  arrow: "M8 16 16 8m-7 0h7v7",
  out: "M15 4h4v16h-4M10 8l-4 4 4 4m-4-4h11",
  sun: "M12 4V2m0 20v-2m8-8h2M2 12h2m13.7-5.7 1.4-1.4M4.9 19.1l1.4-1.4m0-11.4L4.9 4.9m14.2 14.2-1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
};

export function Icon({ name, size = 18 }: { name: keyof typeof PATHS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={PATHS[name] ?? PATHS.arrow} />
    </svg>
  );
}

export function Card({ title, sub, children, className = "", action, accent }: { title?: string; sub?: string; children: ReactNode; className?: string; action?: ReactNode; accent?: boolean }) {
  return (
    <section className={`glass card ${accent ? "accent-card" : ""} ${className}`}>
      {(title || action) && (
        <header>
          <h3>{title}{sub && <small>{sub}</small>}</h3>
          {action ?? <span className="corner"><Icon name="arrow" size={14} /></span>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Pill({ value, digits = 1, suffix = "%" }: { value: number | null | undefined; digits?: number; suffix?: string }) {
  if (value === null || value === undefined) return <span className="pill">–</span>;
  return <span className={`pill ${value > 0 ? "up" : value < 0 ? "down" : ""}`}>{value > 0 ? "▲" : value < 0 ? "▼" : "•"} {Math.abs(value).toFixed(digits)}{suffix}</span>;
}

export function Tag({ children, tone = "" }: { children: ReactNode; tone?: string }) {
  return <span className={`tag-pill ${tone}`}>{children}</span>;
}
