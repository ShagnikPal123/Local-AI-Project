/** The small drawn icon each tab carries, in the rail and in the strip, so the two read as one family. */

// Lucide-style strokes (24 grid). Tabs without their own glyph get the first letter of their name.
export const GLYPHS: Record<string, string> = {
  nyx: "M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.8-.9L3 21l1.9-5.2A8.4 8.4 0 1 1 21 11.5z",
  build: "M21 16V8l-9-5-9 5v8l9 5 9-5zM3.3 7.6 12 12.6l8.7-5M12 22V12.6",
  research: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5",
  learn: "M22 10 12 5 2 10l10 5 10-5zM6 12v5c3 2 9 2 12 0v-5",
  notes: "M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4",
  code: "M16 18l6-6-6-6M8 6l-6 6 6 6",
  agents: "M9 7a3 3 0 1 0 0-.01M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M17 11a3 3 0 1 0 0-6M21 20c0-2.6-1.6-4.8-4-5.6",
  collab: "M6 3v12M18 9a3 3 0 1 0 0-.01M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 12a9 9 0 0 1-9 9",
  trading: "M3 3v18h18M7 15l4-4 3 3 6-7",
  improve: "M21 12a9 9 0 0 1-15.5 6.3L3 16M3 12a9 9 0 0 1 15.5-6.3L21 8M21 3v5h-5M3 21v-5h5",
  freewill: "M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z",
  kahuna: "M3 8l4.5 4L12 5l4.5 7L21 8l-2 11H5L3 8z",
  computer: "M3 4h18v12H3zM8 20h8M12 16v4",
  connectors: "M9 15l6-6M10 6l1-1a4.2 4.2 0 0 1 6 6l-1 1M14 18l-1 1a4.2 4.2 0 0 1-6-6l1-1",
  office: "M3 21h18M5 21V5l7-2v18M19 21V9l-7-2M9 9h.01M9 13h.01M9 17h.01",
  equalize: "M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4",
  predict: "M12 3a7 7 0 0 1 7 7c0 2.6-1.4 4.8-3.5 6H8.5A7 7 0 0 1 12 3zM8 19h8M9.5 21h5M10 9a2 2 0 0 1 2-2",
  projects: "M12 3l2.2 4.6 5 .7-3.6 3.5.9 5-4.5-2.4-4.5 2.4.9-5L4.8 8.3l5-.7L12 3z",
  artifacts: "M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4L12 2z",
  scheduled: "M12 7v5l3 2M21 12a9 9 0 1 1-3-6.7M21 4v5h-5",
  design: "M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.9 1.5-1.9-.3-1 .4-2.1 1.5-2.1H17a4 4 0 0 0 4-4c0-5-4-10-9-10zM7.5 12h.01M10 8h.01M15 8h.01",
  avatars: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4.4 3.6-8 8-8s8 3.6 8 8",
  admin: "M12 3l8 3v6c0 4.6-3.4 8.5-8 9-4.6-.5-8-4.4-8-9V6l8-3z",
};

export function TabGlyph({ id, label, size = 20 }: { id: string; label: string; size?: number }) {
  const d = GLYPHS[id];
  if (!d) return <span className="studio-rail__letter" aria-hidden="true">{label.slice(0, 1).toUpperCase()}</span>;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

