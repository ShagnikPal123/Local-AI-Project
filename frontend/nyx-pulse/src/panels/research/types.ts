/** Shapes the Research routes return (`routes_research.py` → `research_engine.Job.view()`). */

export interface Source {
  n: number;
  kind: "web" | "paper" | string;
  title: string;
  url: string;
  authors: string[];
  year?: number | null;
  venue: string;
  doi: string;
  pdf_url: string;
  citations?: number | null;
  abstract: string;
  snippet: string;
  excerpt: string;
  read: boolean;
  error: string;
  found_by: string;
}

export interface Claim {
  claim: string;
  sources: number[];
  confidence: string;
}

export interface Paper {
  markdown?: string;
  style?: string;
  sections?: string[];
  title?: string;
  words?: number;
  references?: number[];
  created_at?: number;
  author?: string;
}

export interface Job {
  job_id: string;
  question: string;
  mode: "standard" | "deep";
  include_web: boolean;
  include_papers: boolean;
  max_sources: number;
  status: string;
  progress: number;
  step: string;
  log: { ts: number; text: string }[];
  plan: string[];
  sources: Source[];
  notes: Claim[];
  report: string;
  summary: string;
  removed_citations: string[];
  paper: Paper;
  taught: { facts?: number; examples?: number; at?: number };
  models: string[];
  created_at: number;
  ended_at?: number | null;
  error: string;
  elapsed_seconds: number;
  /** Only on the list view, which leaves the heavy fields out. */
  source_count?: number;
}

export interface Overview {
  jobs: Job[];
  settings: { auto_teach: boolean; style: string };
  styles: string[];
  sections: string[];
}

export interface FoundPaper {
  kind: string;
  title: string;
  authors: string[];
  year?: number | null;
  venue: string;
  doi: string;
  url: string;
  pdf_url: string;
  citations?: number | null;
  abstract: string;
  found_by: string;
  /** The paper's citation in every style (`GET /api/research/papers`), so switching style never searches again. */
  cite?: Record<string, string>;
}

/** `GET /api/research/{id}/citations?style=` — every source of a job in one style, by its number. */
export interface CitationList {
  style: string;
  citations: { n: number; text: string }[];
}

/** Statuses that mean the job is still working, so the page keeps asking for it. */
export const RUNNING = new Set(["queued", "planning", "searching", "reading", "analyzing", "writing"]);

export const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  planning: "Planning",
  searching: "Searching",
  reading: "Reading",
  analyzing: "Weighing evidence",
  writing: "Writing",
  done: "Done",
  stopped: "Stopped",
  error: "Failed",
};

export const STYLE_LABEL: Record<string, string> = {
  apa: "APA",
  mla: "MLA",
  chicago: "Chicago",
  ieee: "IEEE",
  harvard: "Harvard",
  bibtex: "BibTeX",
};

export function whenLabel(seconds: number): string {
  const delta = Date.now() / 1000 - seconds;
  if (delta < 90) return "just now";
  if (delta < 3600) return `${Math.round(delta / 60)} min ago`;
  if (delta < 86400) return `${Math.round(delta / 3600)} h ago`;
  return new Date(seconds * 1000).toLocaleDateString();
}

export function tookLabel(seconds: number): string {
  if (!seconds) return "";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds - minutes * 60)}s`;
}

/** Author line for a source or a found paper: "Dao, Fu and 3 others". */
export function authorLine(authors: string[] | undefined): string {
  const names = (authors ?? []).filter(Boolean);
  if (names.length === 0) return "";
  if (names.length <= 2) return names.join(" and ");
  return `${names[0]}, ${names[1]} and ${names.length - 2} other${names.length - 2 > 1 ? "s" : ""}`;
}

/** The report without the engine's reference list (always IEEE), so the tab can list references in the chosen style. */
export function reportBody(report: string): string {
  return report.replace(/\n+##\s*References\s*\n[\s\S]*$/, "").trimEnd();
}

/** The source numbers a piece of text cites, in order, once each. */
export function citedNumbers(text: string): number[] {
  return [...new Set([...text.matchAll(/\[(\d{1,3})\]/g)].map((m) => Number(m[1])))].sort((a, b) => a - b);
}

/** Make every `[n]` in a report a link to the source it points at (the owner asked for clickable citations). */
export function linkCitations(markdown: string, sources: Source[]): string {
  const urls = new Map(sources.filter((s) => s.url).map((s) => [s.n, s.url]));
  if (urls.size === 0) return markdown;
  return markdown.replace(/\[(\d{1,3})\]/g, (whole, digits: string) => {
    const url = urls.get(Number(digits));
    return url ? `[${whole}](${url})` : whole;
  });
}
