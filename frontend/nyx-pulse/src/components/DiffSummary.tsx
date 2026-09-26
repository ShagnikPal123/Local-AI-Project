/** Which file an edit touches and how many lines (Request R9).
 *
 * The owner: "when its working and editing … show how many lines are affected and in which file." The server
 * sends exact numbers (`diff_stats.py`) where it has both versions; anything else is read from the unified diff
 * here, so every Code-tab proposal and every Improve change carries the same summary. Counts are written out
 * ("+8 −4"), never shown by colour alone.
 */

import "./diffsummary.css";

export interface FileLines {
  path: string;
  added: number;
  removed: number;
  affected: number;
  ranges: [number, number][];
  created?: boolean;
  deleted?: boolean;
}

export interface LineStats {
  files: FileLines[];
  added: number;
  removed: number;
  affected: number;
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

function cleanPath(header: string): string {
  const path = header.split("\t")[0].trim();
  if (!path || path === "/dev/null") return "";
  return path.startsWith("a/") || path.startsWith("b/") ? path.slice(2) : path;
}

/** Mirrors `diff_stats.stats` in Python. */
export function parseDiff(diff: string): LineStats {
  const files: FileLines[] = [];
  let current: FileLines | null = null;
  let oldPath = "";
  let newLine = 0;
  let runAdd = 0;
  let runDel = 0;
  const closeRun = () => {
    if (current && (runAdd || runDel)) current.affected += Math.max(runAdd, runDel);
    runAdd = 0;
    runDel = 0;
  };
  const mark = (n: number) => {
    if (!current) return;
    const last = current.ranges[current.ranges.length - 1];
    if (last && n <= last[1] + 1) last[1] = Math.max(last[1], n);
    else current.ranges.push([n, n]);
  };
  for (const line of (diff || "").split("\n")) {
    if (line.startsWith("--- ")) { closeRun(); oldPath = cleanPath(line.slice(4)); continue; }
    if (line.startsWith("+++ ")) {
      const newPath = cleanPath(line.slice(4));
      current = { path: newPath || oldPath, added: 0, removed: 0, affected: 0, ranges: [], created: !oldPath, deleted: !newPath };
      files.push(current);
      continue;
    }
    const hunk = HUNK.exec(line);
    if (hunk) {
      closeRun();
      if (!current) { current = { path: "", added: 0, removed: 0, affected: 0, ranges: [] }; files.push(current); }
      newLine = Number(hunk[2]);
      continue;
    }
    if (!current || line.startsWith("\\")) continue;
    if (line.startsWith("+")) { current.added += 1; runAdd += 1; mark(newLine); newLine += 1; }
    else if (line.startsWith("-")) { current.removed += 1; runDel += 1; mark(Math.max(1, newLine)); }
    else { closeRun(); newLine += 1; }
  }
  closeRun();
  const kept = files.filter((f) => f.added || f.removed || f.created);
  return {
    files: kept,
    added: kept.reduce((n, f) => n + f.added, 0),
    removed: kept.reduce((n, f) => n + f.removed, 0),
    affected: kept.reduce((n, f) => n + f.affected, 0),
  };
}

function rangesText(ranges: [number, number][]): string {
  const shown = ranges.slice(0, 3).map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`));
  const more = ranges.length - shown.length;
  const single = ranges.length === 1 && ranges[0][0] === ranges[0][1];
  return `line${single ? "" : "s"} ${shown.join(", ")}${more > 0 ? ` and ${more} more` : ""}`;
}

/** "server.py: 12 lines (+8 −4) at lines 120–131" — for status lines and toasts. */
export function describeLines(stats: LineStats): string {
  if (!stats.files.length) return "no lines changed";
  const parts = stats.files.slice(0, 4).map((f) => (f.created
    ? `new file ${f.path}, ${f.added} lines`
    : `${f.path || "the file"}: ${f.affected} line${f.affected === 1 ? "" : "s"} (+${f.added} −${f.removed})${f.ranges.length ? ` at ${rangesText(f.ranges)}` : ""}`));
  const text = parts.join("; ") + (stats.files.length > 4 ? `; and ${stats.files.length - 4} more files` : "");
  return stats.files.length > 1 ? `${stats.files.length} files, ${stats.affected} lines — ${text}` : text;
}

function baseName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

/** The compact card line: file name, lines affected, +/−, and where. One row per file. */
export function DiffSummary({ lines, diff, verb = "Changes", compact = false }: {
  lines?: LineStats | null;
  diff?: string;
  verb?: string;
  compact?: boolean;
}) {
  const stats = lines && Array.isArray(lines.files) ? lines : parseDiff(diff ?? "");
  if (!stats.files.length) return null;
  const many = stats.files.length > 1;
  return (
    <div className={`diffsum${compact ? " is-compact" : ""}`} role="group" aria-label={describeLines(stats)}>
      {many && (
        <div className="diffsum__total">
          {verb} <b>{stats.files.length} files</b> · <b>{stats.affected} lines</b> <span className="diffsum__add">+{stats.added}</span> <span className="diffsum__del">−{stats.removed}</span>
        </div>
      )}
      <ul className="diffsum__files">
        {stats.files.slice(0, compact ? 3 : 12).map((file, i) => (
          <li key={`${file.path}-${i}`} className="diffsum__file">
            <code className="diffsum__path" title={file.path}>{baseName(file.path) || "file"}</code>
            <span className="diffsum__count">
              {file.created ? `new · ${file.added} lines` : `${file.affected} line${file.affected === 1 ? "" : "s"}`}
            </span>
            {!file.created && (
              <span className="diffsum__pm" aria-hidden="true"><span className="diffsum__add">+{file.added}</span> <span className="diffsum__del">−{file.removed}</span></span>
            )}
            {!file.created && file.ranges.length > 0 && <span className="diffsum__where">{rangesText(file.ranges)}</span>}
          </li>
        ))}
        {stats.files.length > (compact ? 3 : 12) && <li className="diffsum__more">and {stats.files.length - (compact ? 3 : 12)} more files</li>}
      </ul>
    </div>
  );
}
