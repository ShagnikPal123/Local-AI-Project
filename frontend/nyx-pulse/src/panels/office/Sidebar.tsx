/** The sidebar inside an open office: the other office files and folders, and this office's own work files.
 *
 * Project Null N50 — *"In addition in the office layout add a way to open a side bar which shows the other files
 * and folders."* Switching office from here is one click; the lobby is still there for moving things around.
 */

import { useEffect, useState } from "react";
import type { ReactElement } from "react";
import { officeApi } from "./officeApi";
import type { LibraryItem, LibraryTree } from "./types";

interface SidebarProps {
  tree: LibraryTree | null;
  officeId: string;
  onOpenOffice: (id: string) => void;
  onLobby: () => void;
  onNewOffice: (parent: string) => void;
  onReveal: (id: string) => void;
  onClose: () => void;
}

export function Sidebar({ tree, officeId, onOpenOffice, onLobby, onNewOffice, onReveal, onClose }: SidebarProps) {
  const [files, setFiles] = useState<{ path: string; size: number }[]>([]);
  const [openFile, setOpenFile] = useState<{ path: string; text: string } | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let alive = true;
    void officeApi.files(officeId).then((result) => {
      if (alive && result.ok) setFiles(result.data.files);
    });
    return () => { alive = false; };
  }, [officeId]);

  const children = (parent: string): LibraryItem[] => [
    ...(tree?.folders ?? []).filter((f) => f.parent === parent),
    ...(tree?.offices ?? []).filter((o) => o.parent === parent),
  ];

  const branch = (parent: string, depth: number): ReactElement[] =>
    children(parent).flatMap((item) => {
      const isFolder = item.kind === "folder";
      const shut = collapsed[item.id];
      const row = (
        <div key={item.id} className={`ofc-tree__row${item.id === officeId ? " is-current" : ""}`}
             style={{ paddingLeft: 8 + depth * 14 }}>
          {isFolder && (
            <button className="ofc-tree__twist" aria-label={shut ? "Open folder" : "Close folder"}
                    onClick={() => setCollapsed((c) => ({ ...c, [item.id]: !c[item.id] }))}>
              {shut ? "▸" : "▾"}
            </button>
          )}
          <button className="ofc-tree__name" onClick={() => (isFolder
            ? setCollapsed((c) => ({ ...c, [item.id]: !c[item.id] }))
            : onOpenOffice(item.id))}>
            <span className="ofc-tree__icon" aria-hidden="true">{isFolder ? (item.linked ? "🔗" : "📁") : "🏢"}</span>
            {item.name}
            {isFolder && item.linked && <em className="ofc-tree__tag">linked</em>}
          </button>
        </div>
      );
      return isFolder && !shut ? [row, ...branch(item.id, depth + 1)] : [row];
    });

  return (
    <aside className="ofc-side" aria-label="Offices, folders and files">
      <header className="ofc-side__head">
        <h3>Offices &amp; folders</h3>
        <button className="ofc-x" onClick={onClose} aria-label="Close the sidebar">✕</button>
      </header>
      <div className="ofc-side__actions">
        <button className="ofc-btn ofc-btn--small" onClick={onLobby}>All offices</button>
        <button className="ofc-btn ofc-btn--small" onClick={() => onNewOffice("")}>New office</button>
        <button className="ofc-btn ofc-btn--small" onClick={() => onReveal(officeId)}>In File Explorer</button>
      </div>
      <div className="ofc-tree">{branch("", 0)}</div>

      <header className="ofc-side__head ofc-side__head--second">
        <h3>What this office has made</h3>
      </header>
      <ul className="ofc-files">
        {files.length === 0 && <li className="ofc-muted">Nothing yet.</li>}
        {files.map((file) => (
          <li key={file.path}>
            <button className="ofc-link" onClick={async () => {
              const result = await officeApi.file(officeId, file.path);
              if (result.ok) setOpenFile({ path: file.path, text: result.data.text });
            }}>{file.path}</button>
            <span className="ofc-muted">{Math.max(1, Math.round(file.size / 1024))} KB</span>
          </li>
        ))}
      </ul>

      {openFile && (
        <div className="ofc-filepeek" role="dialog" aria-label={openFile.path}>
          <header>
            <b>{openFile.path}</b>
            <button className="ofc-x" onClick={() => setOpenFile(null)} aria-label="Close the file">✕</button>
          </header>
          <pre>{openFile.text.slice(0, 20000)}</pre>
        </div>
      )}
    </aside>
  );
}
