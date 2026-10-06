/** The Build tab: a 3D studio for parts, assemblies and circuits (Request H4 + 2026-09-15).
 *
 * Layout: parts on the left, the single shared space in the middle, details /
 * checks / Nyx on the right, and a walkthrough card over the space.
 *
 * Why it opens fast now: the chrome and data paint first; the 3D view is its own
 * chunk that starts downloading the moment this module loads (in parallel with
 * the project fetch), and parts appear as outline boxes that turn into real
 * shapes one at a time. Nothing waits on everything.
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { AskNyx } from "./AskNyx";
import { ChecksPanel } from "./ChecksPanel";
import { Inspector } from "./Inspector";
import { LeftRail } from "./LeftRail";
import { newPart, PartEditor } from "./PartEditor";
import { localTutorial, StudioTour, TutorialCard, useStudioTour } from "./Tutorial";
import { buildApi, type ApiResult, type FeatureType, type NetPoint, type Part, type Placement, type ProjectSummary, type Selection, type Snapshot, type Tutorial, type Vec3 } from "./types";
import type { StudioMode, Tool } from "./Viewport";
import "./build.css";

// Start fetching the 3D chunk now, not when the component first renders.
const viewportModule = import("./Viewport");
const Viewport = lazy(() => viewportModule);

type Panel = "inspect" | "checks" | "nyx";
const NONE: Selection = { kind: "none" };

export default function BuildStudio() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  const [mode, setMode] = useState<StudioMode>("space");
  const [tool, setTool] = useState<Tool>("select");
  const [panel, setPanel] = useState<Panel>("inspect");
  const [selection, setSelection] = useState<Selection>(NONE);
  const [multi, setMulti] = useState<string[]>([]);
  const [pendingPin, setPendingPin] = useState<NetPoint | null>(null);
  const [frameRequest, setFrameRequest] = useState(0);
  const [libraryVersion, setLibraryVersion] = useState(0);

  const [draft, setDraft] = useState<Part | null>(null);
  const [draftBefore, setDraftBefore] = useState<Part | null>(null);
  const [draftNote, setDraftNote] = useState("");
  const [activeFeature, setActiveFeature] = useState<string | null>(null);
  const [explain, setExplain] = useState<{ partId: string; text: string; model: string } | null>(null);
  const [queued, setQueued] = useState<{ action: "review"; words: string; nonce: number } | null>(null);

  const [tutorial, setTutorial] = useState<Tutorial | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const tour = useStudioTour();

  const project = snapshot?.project ?? null;

  // --- loading -------------------------------------------------------------------------

  const take = useCallback(<T extends Snapshot>(result: ApiResult<T>): T | null => {
    if (!result.ok) {
      setError(result.error);
      return null;
    }
    setError("");
    setSnapshot(result.data);
    return result.data;
  }, []);

  const refreshProjects = useCallback(async () => {
    const listed = await buildApi.projects();
    if (listed.ok) setProjects(listed.data.projects);
    return listed;
  }, []);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const listed = await refreshProjects();
      if (!alive) return;
      if (!listed.ok) {
        setLoadError(listed.error);
        return;
      }
      const wanted = listed.data.active || listed.data.projects[0]?.id;
      const opened = wanted ? await buildApi.open(wanted) : await buildApi.create("My first build");
      if (!alive) return;
      if (opened.ok) {
        setSnapshot(opened.data);
        if (!wanted) void refreshProjects();
      } else {
        setLoadError(opened.error);
      }
    })();
    return () => { alive = false; };
  }, [refreshProjects]);

  const act = useCallback(async <T extends Snapshot>(work: () => Promise<ApiResult<T>>): Promise<T | null> => {
    setBusy(true);
    try {
      return take(await work());
    } finally {
      setBusy(false);
    }
  }, [take]);

  const openProject = async (id: string) => {
    resetView();
    const opened = await act(() => buildApi.open(id));
    if (opened) setFrameRequest((n) => n + 1);
  };

  const resetView = () => {
    setSelection(NONE);
    setMulti([]);
    setPendingPin(null);
    setDraft(null);
    setStep(null);
    setTutorial(null);
    setMode("space");
  };

  // --- selection -----------------------------------------------------------------------

  const select = useCallback((next: Selection, additive = false) => {
    setStep(null);
    if (additive && next.kind === "placement") {
      setMulti((current) => {
        const base = current.length ? current : selection.kind === "placement" ? [selection.id] : [];
        return base.includes(next.id) ? base.filter((id) => id !== next.id) : [...base, next.id];
      });
      setSelection(next);
      setPanel("inspect");
      return;
    }
    setMulti([]);
    setSelection(next);
    if (next.kind !== "none") setPanel("inspect");
  }, [selection]);

  const pickPin = useCallback(async (point: NetPoint) => {
    if (!project) return;
    setMode("circuit");
    setPanel("inspect");
    if (!pendingPin) {
      setPendingPin(point);
      setSelection({ kind: "pin", placement: point.placement, pin: point.pin });
      return;
    }
    if (pendingPin.placement === point.placement && pendingPin.pin === point.pin) {
      setPendingPin(null);
      return;
    }
    const result = await act(() => buildApi.connect(project.id, pendingPin, point));
    setPendingPin(null);
    if (result) setSelection({ kind: "net", id: result.net.id });
  }, [project, pendingPin, act]);

  // --- parts ---------------------------------------------------------------------------

  const startEditing = (part: Part, note = "") => {
    setDraft(structuredClone(part));
    setDraftBefore(null);
    setDraftNote(note);
    setActiveFeature(part.features[0]?.id ?? null);
    setMode("part");
    setPanel("inspect");
    setStep(null);
    setFrameRequest((n) => n + 1);
  };

  const saveDraft = async (place: boolean) => {
    if (!project || !draft) return;
    const result = await act(() => buildApi.savePart(project.id, draft, draft.id, place));
    if (!result) return;
    setDraft(result.part);
    setDraftNote(place ? "Saved and placed in the space." : "Saved.");
    if (place) {
      closeEditor();
      const placed = result.project.placements.filter((p) => p.part_id === result.part.id).at(-1);
      if (placed) setSelection({ kind: "placement", id: placed.id });
    }
  };

  const closeEditor = () => {
    setDraft(null);
    setDraftBefore(null);
    setDraftNote("");
    setActiveFeature(null);
    setMode("space");
  };

  const askNyxToEdit = async (words: string) => {
    if (!project || !draft) return;
    if (!draft.id) {
      // A part nobody has saved yet cannot be edited on the server; draw it fresh with the change folded in.
      setBusy(true);
      const result = await buildApi.ask<{ part: Part; model: string }>(project.id, { action: "draw", words: `${draft.name}: ${words}. Start from: ${JSON.stringify(draft.features).slice(0, 3000)}` });
      setBusy(false);
      if (!result.ok) return setError(result.error);
      setDraftBefore(draft);
      setDraft(result.data.part);
      setDraftNote(`Changed by ${result.data.model}.`);
      setActiveFeature(null);
      return;
    }
    setBusy(true);
    // Save what is on screen first, so Nyx changes the part the owner is looking at.
    const saved = await buildApi.savePart(project.id, draft, draft.id);
    if (!saved.ok) {
      setBusy(false);
      return setError(saved.error);
    }
    const result = await buildApi.ask<{ part: Part; model: string }>(project.id, { action: "edit", part_id: draft.id, words });
    setBusy(false);
    if (!result.ok) return setError(result.error);
    setDraftBefore(draft);
    setDraft({ ...result.data.part, id: draft.id });
    setDraftNote(`Changed by ${result.data.model}. Save to keep it.`);
    setActiveFeature(null);
  };

  const placeCatalog = async (catalogId: string) => {
    if (!project) return;
    const result = await act(() => buildApi.place(project.id, { catalog_id: catalogId }));
    if (result) {
      setMode((m) => (m === "part" ? "space" : m));
      setSelection({ kind: "placement", id: result.placement.id });
      setMulti([]);
    }
  };

  const movePlacement = useCallback(async (id: string, fields: Partial<Placement>) => {
    if (!project) return;
    await act(() => buildApi.movePlacement(project.id, id, fields));
  }, [project, act]);

  const combine = async (name: string) => {
    if (!project || multi.length < 2) return;
    setBusy(true);
    try {
      const { combineParts } = await import("./geometry");
      const pieces = multi.map((id) => project.placements.find((p) => p.id === id)).filter((p): p is Placement => Boolean(p));
      const { spec, centre, featureCount } = combineParts(project.parts, pieces, name);
      if (featureCount > 200) {
        setError(`Those pieces add up to ${featureCount} shapes; a part can hold 200. Combine fewer at once.`);
        return;
      }
      const saved = await buildApi.savePart(project.id, spec);
      if (!saved.ok) return setError(saved.error);
      const placed = await buildApi.place(project.id, { part_id: saved.data.part.id, at: centre as Vec3 });
      if (!placed.ok) return setError(placed.error);
      let latest: Snapshot = placed.data;
      for (const piece of pieces) {
        const removed = await buildApi.deletePlacement(project.id, piece.id);
        if (removed.ok) latest = removed.data;
      }
      setSnapshot(latest);
      setMulti([]);
      setSelection({ kind: "placement", id: placed.data.placement.id });
      setStatus(`Combined ${pieces.length} pieces into ${saved.data.part.name}.`);
    } finally {
      setBusy(false);
    }
  };

  // --- the example -----------------------------------------------------------------------

  const makeExample = async () => {
    setBusy(true);
    resetView();
    try {
      const created = await buildApi.create("AI box (example)", "A ventilated box that runs a local AI model on a Raspberry Pi 5, with a fan over the heatsink and a 5 V 5 A supply.");
      if (!created.ok) return setError(created.error);
      const id = created.data.project.id;
      const place = async (catalog_id: string, at: Vec3) => {
        const result = await buildApi.place(id, { catalog_id, at });
        if (!result.ok) throw new Error(result.error);
        return result.data;
      };
      await place("base-plate", [0, 0, 0]);
      for (const [x, z] of [[-39, -24.5], [39, -24.5], [-39, 24.5], [39, 24.5]]) await place("standoff-m3-10", [x, 4, z]);
      const pi = await place("raspberry-pi-5", [0, 14.8, 0]);
      await place("heatsink-40mm", [0, 18.2, 0]);
      const fan = await place("fan-40mm", [0, 38.5, 0]);
      const psu = await place("psu-5v-5a", [0, 0, -105]);
      await place("vented-lid", [0, 4.5, 100]);
      const wire = async (a: NetPoint, b: NetPoint, name: string) => {
        const result = await buildApi.connect(id, a, b, name);
        if (!result.ok) throw new Error(result.error);
        return result.data;
      };
      await wire({ placement: psu.placement.id, pin: "out5" }, { placement: pi.placement.id, pin: "h2" }, "5 V rail");
      await wire({ placement: psu.placement.id, pin: "outg" }, { placement: pi.placement.id, pin: "h6" }, "Ground");
      await wire({ placement: fan.placement.id, pin: "p1" }, { placement: pi.placement.id, pin: "h4" }, "Fan 5 V");
      const last = await wire({ placement: fan.placement.id, pin: "p2" }, { placement: pi.placement.id, pin: "h14" }, "Fan ground");
      setSnapshot(last);
      setFrameRequest((n) => n + 1);
      await refreshProjects();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  };

  // --- tutorial ------------------------------------------------------------------------------

  const startTutorial = useCallback((source?: Snapshot) => {
    const current = source?.project ?? project;
    if (!current) return;
    const chosen = current.tutorial?.steps.length ? current.tutorial : localTutorial(current);
    if (!chosen.steps.length) {
      setError("There is nothing in this build to walk through yet.");
      return;
    }
    setMode("space");
    setTool("select");
    setSelection(NONE);
    setMulti([]);
    setTutorial(chosen);
    setStep(0);
  }, [project]);

  const focus = step !== null && tutorial ? tutorial.steps[step]?.focus ?? null : null;

  // --- keyboard ------------------------------------------------------------------------------

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.closest("input, textarea, select, [contenteditable]") || event.metaKey || event.ctrlKey || event.altKey) return;
      if (tour.step !== null || step !== null) return;
      const key = event.key.toLowerCase();
      if (key === "m" && mode === "space") setTool("move");
      else if (key === "r" && mode === "space") setTool("rotate");
      else if (key === "f") setFrameRequest((n) => n + 1);
      else if (key === "escape") {
        if (pendingPin) setPendingPin(null);
        else if (tool !== "select") setTool("select");
        else { setSelection(NONE); setMulti([]); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode, tool, pendingPin, step, tour.step]);

  const counts = useMemo(() => ({
    errors: snapshot?.checks.filter((c) => c.level === "error").length ?? 0,
    warnings: snapshot?.checks.filter((c) => c.level === "warn").length ?? 0,
  }), [snapshot]);

  const selectedPartId = selection.kind === "placement" ? project?.placements.find((p) => p.id === selection.id)?.part_id ?? "" : "";

  // --- render --------------------------------------------------------------------------------

  if (loadError) {
    return (
      <div className="bs bs--message">
        <div className="bs-message">
          <h2>The Build studio could not open</h2>
          <p>{loadError}</p>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>Try again</button>
        </div>
      </div>
    );
  }

  return (
    <div className="bs">
      <header className="bs-bar">
        <div className="bs-bar__group">
          <select className="bs-project" value={project?.id ?? ""} onChange={(e) => void openProject(e.target.value)} aria-label="Open a build" disabled={!project}>
            {!project && <option>Loading builds…</option>}
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            {project && !projects.some((p) => p.id === project.id) && <option value={project.id}>{project.name}</option>}
          </select>
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={async () => {
            resetView();
            const created = await act(() => buildApi.create("New build"));
            if (created) await refreshProjects();
          }}>New build</button>
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void makeExample()} title="A Raspberry Pi 5 AI box with a fan, supply and wiring">Example</button>
        </div>

        <div className="segmented" role="group" aria-label="Mode" data-tour="modes">
          {(["space", "part", "circuit"] as StudioMode[]).map((m) => (
            <button key={m} aria-pressed={mode === m} disabled={m === "part" && !draft} title={m === "part" && !draft ? "Edit or draw a part to open Part mode" : undefined}
              onClick={() => { setMode(m); setStep(null); if (m !== "circuit") setPendingPin(null); }}>
              {m === "space" ? "Space" : m === "part" ? "Part" : "Circuit"}
            </button>
          ))}
        </div>

        <div className="segmented" role="group" aria-label="Tool" data-tour="tools">
          {(["select", "move", "rotate"] as Tool[]).map((t) => (
            <button key={t} aria-pressed={tool === t} disabled={mode !== "space"} onClick={() => setTool(t)} title={`${t[0].toUpperCase()}${t.slice(1)} (${t === "select" ? "Esc" : t[0].toUpperCase()})`}>
              {t === "select" ? "Select" : t === "move" ? "Move" : "Rotate"}
            </button>
          ))}
        </div>
        <button className="btn btn-ghost btn-sm" onClick={() => setFrameRequest((n) => n + 1)} title="Frame (F)">Frame</button>

        <div className="bs-bar__status" aria-live="polite">{busy ? "Saving…" : status}</div>
        <button className="bs-icon bs-help" onClick={() => tour.setStep(0)} aria-label="Show the studio tour" title="Studio tour">?</button>
      </header>

      {error && (
        <div className="bs-alert" role="alert">
          <span>{error}</span>
          <button className="bs-icon" onClick={() => setError("")} aria-label="Dismiss">×</button>
        </div>
      )}

      <div className="bs-body">
        <LeftRail
          snapshot={snapshot}
          libraryVersion={libraryVersion}
          busy={busy}
          onPlaceCatalog={(id) => void placeCatalog(id)}
          onPlaceLibrary={async (id) => {
            if (!project) return;
            const result = await act(() => buildApi.place(project.id, { library_id: id }));
            if (result) setSelection({ kind: "placement", id: result.placement.id });
          }}
          onPlacePart={async (partId) => {
            if (!project) return;
            const result = await act(() => buildApi.place(project.id, { part_id: partId }));
            if (result) { setMode("space"); setSelection({ kind: "placement", id: result.placement.id }); }
          }}
          onEditPart={(partId) => { const part = project?.parts.find((p) => p.id === partId); if (part) startEditing(part); }}
          onNewPart={(type: FeatureType) => startEditing(newPart(type), "Shape it here, then Save and place.")}
          onDuplicatePart={async (partId) => { if (project) await act(() => buildApi.duplicatePart(project.id, partId)); }}
          onDeletePart={async (partId) => {
            if (!project) return;
            const part = project.parts.find((p) => p.id === partId);
            const placed = project.placements.filter((p) => p.part_id === partId).length;
            if (placed && !window.confirm(`Delete ${part?.name}? It is in the space ${placed} time${placed === 1 ? "" : "s"}; those pieces and their wires go too.`)) return;
            await act(() => buildApi.deletePart(project.id, partId));
            setSelection(NONE);
            if (draft?.id === partId) closeEditor();
          }}
          onSaveToLibrary={async (partId) => {
            if (!project) return;
            const result = await buildApi.saveToLibrary(project.id, partId);
            if (!result.ok) return setError(result.error);
            setLibraryVersion((v) => v + 1);
            setStatus(`Saved ${result.data.part.name} to your library.`);
          }}
          onLibraryChanged={() => setLibraryVersion((v) => v + 1)}
        />

        <main className="bs-stage" data-tour="viewport">
          {snapshot ? (
            <Suspense fallback={<div className="bs-stage__loading"><div className="bs-spinner" />Preparing the 3D view…</div>}>
              <Viewport
                snapshot={snapshot}
                mode={mode}
                tool={tool}
                selection={selection}
                multi={multi}
                focus={focus}
                editingPart={draft}
                activeFeatureId={activeFeature}
                pendingPin={pendingPin}
                frameRequest={frameRequest}
                onSelect={select}
                onPickPin={(point) => void pickPin(point)}
                onMove={(id, at, rot) => void movePlacement(id, { at, rot })}
                onStatus={setStatus}
              />
            </Suspense>
          ) : (
            <div className="bs-stage__loading"><div className="bs-spinner" />Opening your builds…</div>
          )}

          {project && mode === "space" && step === null && (
            <div className="bs-overlay bs-overlay--top" data-tour="walkthrough">
              <button className="btn btn-primary btn-sm" disabled={!project.placements.length} onClick={() => startTutorial()}>
                ▶ Walk through{project.tutorial?.steps.length ? ` (${project.tutorial.steps.length} steps)` : " this build"}
              </button>
              {project.placements.length > 0 && (
                <button className="btn btn-secondary btn-sm" disabled={busy} onClick={async () => {
                  setBusy(true);
                  setStatus("Nyx is writing the tutorial…");
                  const result = await buildApi.ask<Snapshot & { model: string }>(project.id, { action: "tutorial" });
                  setBusy(false);
                  setStatus("");
                  if (!result.ok) return setError(`${result.error} You can still use ▶ Walk through — it is built from the parts themselves.`);
                  setSnapshot(result.data);
                  startTutorial(result.data);
                }}>{project.tutorial ? "Rewrite with Nyx" : "Nyx: explain each part"}</button>
              )}
            </div>
          )}

          {mode === "part" && draft && (
            <div className="bs-overlay bs-overlay--top">
              <span className="chip">Editing {draft.name}{activeFeature ? ` · ${draft.features.find((f) => f.id === activeFeature)?.name ?? ""}` : ""}</span>
            </div>
          )}
          {mode === "circuit" && pendingPin && (
            <div className="bs-overlay bs-overlay--top"><span className="chip bs-chip--live">Now click the other pin · Esc cancels</span></div>
          )}

          {project && !project.placements.length && mode === "space" && (
            <div className="bs-empty">
              <h2>An empty space</h2>
              <p>Add a board from the catalog, draw a part, ask Nyx to design something, or open the example to see how a finished build looks.</p>
              <div className="bs-row">
                <button className="btn btn-primary" onClick={() => void makeExample()} disabled={busy}>Open the example</button>
                <button className="btn btn-secondary" onClick={() => setPanel("nyx")}>Ask Nyx to design it</button>
              </div>
            </div>
          )}

          {tutorial && step !== null && (
            <TutorialCard tutorial={tutorial} index={step} onIndex={setStep} onExit={() => setStep(null)} />
          )}
        </main>

        <aside className="bs-side" data-tour="panel" aria-label="Details">
          {mode !== "part" && (
            <div className="segmented bs-tabs" role="tablist">
              <button role="tab" aria-selected={panel === "inspect"} aria-pressed={panel === "inspect"} onClick={() => setPanel("inspect")}>{mode === "circuit" ? "Circuit" : "Inspect"}</button>
              <button role="tab" aria-selected={panel === "checks"} aria-pressed={panel === "checks"} onClick={() => setPanel("checks")}>
                Checks{counts.errors ? <span className="bs-badge is-error">{counts.errors}</span> : counts.warnings ? <span className="bs-badge">{counts.warnings}</span> : null}
              </button>
              <button role="tab" aria-selected={panel === "nyx"} aria-pressed={panel === "nyx"} onClick={() => setPanel("nyx")}>Nyx</button>
            </div>
          )}
          <div className="bs-side__body">
            {!snapshot && <div className="bs-skeleton-list">{Array.from({ length: 5 }, (_, i) => <div key={i} className="bs-skeleton" />)}</div>}

            {snapshot && mode === "part" && draft && (
              <PartEditor
                part={draft}
                activeFeatureId={activeFeature}
                busy={busy}
                isNew={!draft.id}
                aiNote={draftNote}
                onChange={(next) => { setDraft(next); setDraftNote((n) => (n.startsWith("Saved") ? "" : n)); }}
                onActivate={setActiveFeature}
                onSave={(place) => void saveDraft(place)}
                onCancel={closeEditor}
                onSaveToLibrary={async () => {
                  if (!project || !draft.id) return;
                  await buildApi.savePart(project.id, draft, draft.id);
                  const result = await buildApi.saveToLibrary(project.id, draft.id);
                  if (!result.ok) return setError(result.error);
                  setLibraryVersion((v) => v + 1);
                  setDraftNote(`Saved ${result.data.part.name} to your library.`);
                }}
                onAskNyx={(words) => void askNyxToEdit(words)}
                onUndoAi={draftBefore ? () => { setDraft(draftBefore); setDraftBefore(null); setDraftNote("Put back the version before Nyx changed it."); } : null}
              />
            )}

            {snapshot && mode !== "part" && panel === "inspect" && (
              <Inspector
                snapshot={snapshot}
                mode={mode === "circuit" ? "circuit" : "space"}
                selection={selection}
                multi={multi}
                pendingPin={pendingPin}
                busy={busy}
                explain={explain}
                onSelect={(s) => select(s)}
                onPickPin={(point) => void pickPin(point)}
                onCancelPin={() => setPendingPin(null)}
                onUpdatePlacement={(id, fields) => void movePlacement(id, fields)}
                onDeletePlacement={async (id) => { if (project) { await act(() => buildApi.deletePlacement(project.id, id)); setSelection(NONE); } }}
                onPlaceAnother={async (partId) => {
                  if (!project) return;
                  const result = await act(() => buildApi.place(project.id, { part_id: partId }));
                  if (result) setSelection({ kind: "placement", id: result.placement.id });
                }}
                onEditPart={(partId) => { const part = project?.parts.find((p) => p.id === partId); if (part) startEditing(part); }}
                onSaveToLibrary={async (partId) => {
                  if (!project) return;
                  const result = await buildApi.saveToLibrary(project.id, partId);
                  if (!result.ok) return setError(result.error);
                  setLibraryVersion((v) => v + 1);
                  setStatus(`Saved ${result.data.part.name} to your library.`);
                }}
                onExplainPart={async (partId) => {
                  if (!project) return;
                  setBusy(true);
                  const result = await buildApi.ask<{ text: string; model: string }>(project.id, { action: "explain_part", part_id: partId });
                  setBusy(false);
                  if (!result.ok) return setError(result.error);
                  setExplain({ partId, ...result.data });
                }}
                onCombine={(name) => void combine(name)}
                onJoin={async (kind) => {
                  if (!project || multi.length !== 2) return;
                  const result = await act(() => buildApi.addJoint(project.id, multi[0], multi[1], kind));
                  if (result) setStatus(`Joined with a ${kind} joint.`);
                }}
                onClearMulti={() => setMulti([])}
                onDisconnect={async (netId, point) => {
                  if (!project) return;
                  await act(() => buildApi.disconnect(project.id, netId, point));
                  if (!point) setSelection(NONE);
                }}
                onRenameNet={async (netId, name) => { if (project) await act(() => buildApi.renameNet(project.id, netId, { name })); }}
                onUpdateProject={async (fields) => {
                  if (!project) return;
                  const result = await act(() => buildApi.update(project.id, fields));
                  if (result && fields.name) await refreshProjects();
                }}
                onAskWiring={() => setPanel("nyx")}
                onSeatOnPlate={(id) => {
                  const box = snapshot.bounds[id];
                  const placement = project?.placements.find((p) => p.id === id);
                  if (box && placement) void movePlacement(id, { at: [placement.at[0], Math.round((placement.at[1] - box.min[1]) * 100) / 100, placement.at[2]] });
                }}
              />
            )}

            {snapshot && mode !== "part" && panel === "checks" && (
              <ChecksPanel
                snapshot={snapshot}
                busy={busy}
                onShow={(s) => { setMode("space"); select(s); setFrameRequest((n) => n + 1); }}
                onAskAbout={(question) => { setQueued({ action: "review", words: question, nonce: Date.now() }); setPanel("nyx"); }}
              />
            )}

            {snapshot && mode !== "part" && panel === "nyx" && (
              <AskNyx
                snapshot={snapshot}
                selectedPartId={selectedPartId}
                onSnapshot={setSnapshot}
                onPreviewPart={(part, model) => startEditing({ ...part, id: "" }, `Drawn by ${model}. Look it over, change anything, then Save and place.`)}
                onStartTutorial={(fresh) => startTutorial(fresh)}
                onPlaceCatalog={(id) => void placeCatalog(id)}
                onError={setError}
                queued={queued}
              />
            )}
          </div>
        </aside>
      </div>

      {tour.step !== null && <StudioTour step={tour.step} onStep={tour.setStep} onFinish={tour.finish} />}
    </div>
  );
}
