/** The lobby: every office file and folder, the way the owner asked for it.
 *
 * *"the next time I open it after it's fully stopped, it has a new layout where I can see past projects and
 * click on the file, I can also click a button to open in file explorer. In this page I can also say create a
 * new project… In here I can also make empty folders which I can then drag and drop projects [into]… If in the
 * same folder I can click a button on the side that says link work flows so memory and work is linked."*
 *
 * An **office file** holds one office. A **folder** holds office files and other folders, nested like Windows.
 * Dragging a card onto a folder moves it on disk, so File Explorer and this page never disagree.
 */

import { useMemo, useState } from "react";
import { officeApi } from "./officeApi";
import type { LibraryItem, LibraryTree } from "./types";

interface LobbyProps {
  tree: LibraryTree;
  onOpen: (officeId: string) => void;
  onChanged: () => Promise<void> | void;
  onError: (message: string) => void;
  runningOffice: string;
}

function ago(seconds: number): string {
  if (!seconds) return "never opened";
  const minutes = Math.max(1, Math.round((Date.now() / 1000 - seconds) / 60));
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function Lobby({ tree, onOpen, onChanged, onError, runningOffice }: LobbyProps) {
  const [folderId, setFolderId] = useState("");
  const [picked, setPicked] = useState<LibraryItem | null>(null);
  const [renaming, setRenaming] = useState("");
  const [dropTarget, setDropTarget] = useState("");
  const [busy, setBusy] = useState(false);

  const folders = tree.folders;
  const offices = tree.offices;
  const here = useMemo(() => [
    ...folders.filter((f) => f.parent === folderId),
    ...offices.filter((o) => o.parent === folderId).sort((a, b) => b.updated_at - a.updated_at),
  ], [folders, offices, folderId]);

  const trail = useMemo(() => {
    const path: LibraryItem[] = [];
    let current = folders.find((f) => f.id === folderId);
    while (current) {
      path.unshift(current);
      current = folders.find((f) => f.id === current?.parent);
    }
    return path;
  }, [folders, folderId]);

  const currentFolder = folders.find((f) => f.id === folderId) ?? null;

  const act = async (work: Promise<{ ok: boolean; error?: string }>) => {
    setBusy(true);
    const result = await work;
    setBusy(false);
    if (!result.ok) onError(result.error ?? "That did not work.");
    await onChanged();
    return result.ok;
  };

  const newOffice = async () => {
    setBusy(true);
    const result = await officeApi.newOffice("", folderId);
    setBusy(false);
    if (!result.ok) {
      onError(result.error);
      return;
    }
    await onChanged();
    onOpen(result.data.office.id);
  };

  return (
    <div className="ofc-lobby">
      <header className="ofc-lobby__head">
        <div>
          <h1>Office Space</h1>
          <p className="ofc-muted">
            An office file holds one office — its team, its chat, its memory and everything it makes. Folders hold
            office files and other folders, like Windows.
          </p>
        </div>
        <div className="ofc-lobby__actions">
          <button className="ofc-btn" disabled={busy}
                  onClick={() => void act(officeApi.newFolder("New folder", folderId))}>New folder</button>
          <button className="ofc-btn ofc-btn--primary" disabled={busy} onClick={() => void newOffice()}>
            New office
          </button>
        </div>
      </header>

      <nav className="ofc-crumbs" aria-label="Where you are">
        <button className={`ofc-crumb${folderId === "" ? " is-here" : ""}`} onClick={() => setFolderId("")}
                onDragOver={(event) => { event.preventDefault(); setDropTarget("root"); }}
                onDragLeave={() => setDropTarget("")}
                onDrop={async (event) => {
                  event.preventDefault();
                  setDropTarget("");
                  const id = event.dataTransfer.getData("text/nyx-office-item");
                  if (id) await act(officeApi.move(id, ""));
                }}>
          All offices
        </button>
        {trail.map((folder) => (
          <button key={folder.id} className={`ofc-crumb${folder.id === folderId ? " is-here" : ""}`}
                  onClick={() => setFolderId(folder.id)}>› {folder.name}</button>
        ))}
        {currentFolder && (
          <span className="ofc-crumbs__right">
            <label className="ofc-check ofc-check--inline" title="Offices in this folder share memory and can read
each other's work">
              <input type="checkbox" checked={Boolean(currentFolder.linked)} disabled={busy}
                     onChange={(event) => void act(officeApi.setLinked(currentFolder.id, event.currentTarget.checked))} />
              Link work flows
            </label>
            <button className="ofc-link" onClick={() => void officeApi.reveal(currentFolder.id)}>
              Open in File Explorer
            </button>
          </span>
        )}
      </nav>

      <div className="ofc-lobby__body">
        <div className="ofc-grid">
          {here.map((item) => {
            const isFolder = item.kind === "folder";
            const inside = isFolder
              ? folders.filter((f) => f.parent === item.id).length + offices.filter((o) => o.parent === item.id).length
              : 0;
            return (
              <article key={item.id}
                       className={`ofc-cardlet${isFolder ? " is-folder" : ""}${picked?.id === item.id ? " is-picked" : ""}`
                         + (dropTarget === item.id ? " is-drop" : "")
                         + (item.id === runningOffice ? " is-running" : "")}
                       draggable
                       onDragStart={(event) => event.dataTransfer.setData("text/nyx-office-item", item.id)}
                       onDragOver={(event) => { if (isFolder) { event.preventDefault(); setDropTarget(item.id); } }}
                       onDragLeave={() => setDropTarget("")}
                       onDrop={async (event) => {
                         if (!isFolder) return;
                         event.preventDefault();
                         setDropTarget("");
                         const id = event.dataTransfer.getData("text/nyx-office-item");
                         if (id && id !== item.id) await act(officeApi.move(id, item.id));
                       }}
                       onClick={() => setPicked(item)}
                       onDoubleClick={() => (isFolder ? setFolderId(item.id) : onOpen(item.id))}>
                <span className="ofc-cardlet__icon" aria-hidden="true">
                  {isFolder ? (item.linked ? "🔗" : "📁") : "🏢"}
                </span>
                {renaming === item.id ? (
                  <input className="ofc-rename" autoFocus defaultValue={item.name}
                         onClick={(event) => event.stopPropagation()}
                         onBlur={(event) => { setRenaming(""); void act(officeApi.rename(item.id, event.currentTarget.value)); }}
                         onKeyDown={(event) => {
                           if (event.key === "Enter") event.currentTarget.blur();
                           if (event.key === "Escape") setRenaming("");
                         }} />
                ) : (
                  <b className="ofc-cardlet__name">{item.name}</b>
                )}
                <span className="ofc-muted ofc-cardlet__meta">
                  {isFolder
                    ? `${inside} item${inside === 1 ? "" : "s"}${item.linked ? " · linked" : ""}`
                    : `${item.agents ?? 0} agents · ${ago(item.updated_at)}`}
                </span>
                {!isFolder && item.summary && <span className="ofc-cardlet__summary">{item.summary}</span>}
                {item.id === runningOffice && <span className="ofc-cardlet__live">working now</span>}
              </article>
            );
          })}

          {here.length === 0 && (
            <div className="ofc-empty">
              <p>{folderId ? "This folder is empty." : "No offices yet."}</p>
              <button className="ofc-btn ofc-btn--primary" onClick={() => void newOffice()}>
                {folderId ? "New office here" : "Make your first office"}
              </button>
            </div>
          )}
        </div>

        {picked && (
          <aside className="ofc-details" aria-label={`${picked.name} details`}>
            <h3>{picked.name}</h3>
            <p className="ofc-muted">{picked.kind === "folder" ? "Folder" : "Office file"} · {picked.path}</p>
            {picked.kind === "office" && (
              <>
                <p className="ofc-muted">{picked.agents ?? 0} agents · {picked.sections ?? 0} sections ·
                  {" "}{picked.jobs ?? 0} job{picked.jobs === 1 ? "" : "s"} · {ago(picked.updated_at)}</p>
                {picked.last_request && <p className="ofc-details__quote">“{picked.last_request}”</p>}
                {picked.summary && <p>{picked.summary}</p>}
              </>
            )}
            {picked.kind === "folder" && (
              <label className="ofc-check">
                <input type="checkbox" checked={Boolean(picked.linked)} disabled={busy}
                       onChange={async (event) => {
                         await act(officeApi.setLinked(picked.id, event.currentTarget.checked));
                         setPicked({ ...picked, linked: event.currentTarget.checked });
                       }} />
                Link work flows — the offices in here share memory and can read each other's work
              </label>
            )}
            <div className="ofc-details__actions">
              {picked.kind === "office"
                ? <button className="ofc-btn ofc-btn--primary" onClick={() => onOpen(picked.id)}>Open</button>
                : <button className="ofc-btn ofc-btn--primary" onClick={() => setFolderId(picked.id)}>Open folder</button>}
              <button className="ofc-btn ofc-btn--small" onClick={() => void officeApi.reveal(picked.id)}>
                In File Explorer
              </button>
              <button className="ofc-btn ofc-btn--small" onClick={() => setRenaming(picked.id)}>Rename</button>
              <button className="ofc-btn ofc-btn--small ofc-btn--risk" disabled={busy || picked.id === runningOffice}
                      onClick={async () => {
                        if (await act(officeApi.remove(picked.id))) setPicked(null);
                      }}>Move to trash</button>
            </div>
            <p className="ofc-muted">Deleting moves it into <code>.trash</code> inside the offices folder — nothing
              is destroyed.</p>
          </aside>
        )}
      </div>
    </div>
  );
}
