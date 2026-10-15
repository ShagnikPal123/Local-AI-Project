/** The files this chat's work touched, as a small tree under the work queue (doc 2 item 2.3, from the combined
 *  Claude Code mod's file tree). Folders group the files; a dot says written (accent), deleted (red) or only read.
 *  Collapsed to one line until clicked, so it never crowds the composer. */

import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";

interface TouchedFile { path: string; kind: "read" | "written" | "deleted"; reads: number; writes: number; tool?: string }

function split(path: string): [string, string] {
  const clean = path.replace(/\\/g, "/");
  const cut = clean.lastIndexOf("/");
  return cut < 0 ? ["", clean] : [clean.slice(0, cut), clean.slice(cut + 1)];
}

export function WorkFiles({ chatId, busy }: { chatId: string; busy: boolean }) {
  const [files, setFiles] = useState<TouchedFile[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => void api.get<{ files: TouchedFile[] }>(`/api/work-files?chat_id=${encodeURIComponent(chatId)}`)
      .then((r) => { if (alive && r.ok) setFiles(r.data.files); });
    load();
    // While a turn runs, follow it; once it ends the list stays as it was left.
    const timer = busy ? window.setInterval(load, 3000) : undefined;
    return () => { alive = false; if (timer) window.clearInterval(timer); };
  }, [chatId, busy]);

  const folders = useMemo(() => {
    const groups = new Map<string, { name: string; file: TouchedFile }[]>();
    for (const file of files) {
      const [folder, name] = split(file.path);
      groups.set(folder, [...(groups.get(folder) ?? []), { name, file }]);
    }
    return [...groups.entries()];
  }, [files]);

  if (files.length === 0) return null;
  const changed = files.filter((f) => f.kind !== "read").length;
  return (
    <div className="work-files">
      <button type="button" className="work-files__head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        Files touched: {files.length}{changed ? ` · ${changed} changed` : ""}
      </button>
      {open && (
        <ul className="work-files__tree">
          {folders.map(([folder, items]) => (
            <li key={folder}>
              {folder && <div className="work-files__folder" title={folder}>{folder}</div>}
              <ul>
                {items.map(({ name, file }) => (
                  <li key={file.path} className="work-files__file" title={`${file.path} · read ${file.reads}× · changed ${file.writes}×`}>
                    <span className={`work-files__dot work-files__dot--${file.kind}`} aria-label={file.kind} />
                    {name}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
