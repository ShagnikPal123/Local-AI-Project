/** Small, pure formatting helpers shared by the chat components.
 *
 * Timestamps arrive from two worlds: the Python engine (seconds since the
 * epoch, `time.time()`) and the browser (`Date.now()`, milliseconds). Every
 * helper here accepts either and normalises with `toMs`, so a component never
 * shows "55 years ago" because a seconds value slipped through.
 */

/** Seconds-or-milliseconds epoch → milliseconds. */
export function toMs(ts: number | null | undefined): number | undefined {
  if (ts == null || !Number.isFinite(ts) || ts <= 0) return undefined;
  return ts < 1e12 ? ts * 1000 : ts;
}

/** 420 → "420ms", 3240 → "3.2s", 65000 → "1m 05s". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 10) return `${s.toFixed(1)}s`;
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  const rest = Math.floor(s % 60);
  if (m < 60) return `${m}m ${String(rest).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

/** Whole seconds, for "Thought for 6s" / "Done in 12s". */
export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "";
  return formatDuration(seconds * 1000);
}

/** Relative time: "just now", "4m ago", "2h ago", "3d ago", then a date. */
export function formatAgo(ts: number | null | undefined, now: number = Date.now()): string {
  const ms = toMs(ts);
  if (ms === undefined) return "";
  const diff = Math.max(0, now - ms);
  const s = Math.floor(diff / 1000);
  if (s < 45) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${Math.max(1, m)}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Clock time for a message header ("14:32"). */
export function formatClock(ts: number | null | undefined): string {
  const ms = toMs(ts);
  if (ms === undefined) return "";
  return new Date(ms).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/** Full date-time for `title` / `dateTime` attributes. */
export function formatFull(ts: number | null | undefined): string {
  const ms = toMs(ts);
  if (ms === undefined) return "";
  return new Date(ms).toLocaleString();
}

export function isoTime(ts: number | null | undefined): string | undefined {
  const ms = toMs(ts);
  return ms === undefined ? undefined : new Date(ms).toISOString();
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`;
  const mb = kb / 1024;
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
}

/** Only pass colours we can trust into a CSS custom property. */
export function safeColor(color: string | null | undefined): string | undefined {
  if (!color) return undefined;
  const c = color.trim();
  if (/^#[0-9a-f]{3,8}$/i.test(c)) return c;
  if (/^(rgb|rgba|hsl|hsla|oklch|oklab)\([\d\s.,%/+\-a-z]*\)$/i.test(c)) return c;
  if (/^[a-z]{3,20}$/i.test(c)) return c;
  return undefined;
}

/** Links and media sources: nothing that can execute. */
export function safeHref(url: string | null | undefined, opts: { allowRelative?: boolean; allowBlob?: boolean } = {}): string | undefined {
  if (!url) return undefined;
  const u = url.trim();
  if (/^(https?:|mailto:)/i.test(u)) return u;
  if (opts.allowBlob && /^blob:/i.test(u)) return u;
  if (opts.allowRelative && /^\/(?!\/)/.test(u)) return u;
  return undefined;
}

/** Image sources for thumbnails: http(s), same-origin paths, blob: and raster data: URLs. */
export function safeImageSrc(src: string | null | undefined): string | undefined {
  if (!src) return undefined;
  const s = src.trim();
  if (/^data:image\/(png|jpe?g|gif|webp|avif|bmp);base64,/i.test(s)) return s;
  return safeHref(s, { allowRelative: true, allowBlob: true });
}

/** "Understood: compare two funds" → "compare two funds". */
export function stripUnderstood(text: string): string {
  return text.replace(/^\s*understood\s*[:\-–—]\s*/i, "").trim();
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
