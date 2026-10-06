/** What is wrong, what it costs, and what to print. All computed by the engine on every change. */

import { useState } from "react";
import type { Finding, Selection, Snapshot } from "./types";

export interface ChecksPanelProps {
  snapshot: Snapshot;
  busy: boolean;
  onShow: (selection: Selection) => void;
  onAskAbout: (question: string) => void;
}

const LEVEL_LABEL: Record<Finding["level"], string> = { error: "Error", warn: "Warning", info: "Note" };

export function ChecksPanel({ snapshot, busy, onShow, onAskAbout }: ChecksPanelProps) {
  const [exporting, setExporting] = useState("");
  const [exportError, setExportError] = useState("");
  const { checks, bom, printing, project } = snapshot;
  const buy = bom.lines.filter((line) => line.buy_or_print === "buy" && line.quantity > 0);
  const print = bom.lines.filter((line) => line.buy_or_print === "print" && line.quantity > 0);

  const show = (finding: Finding) => {
    const { kind, id } = finding.where;
    if (!id) return;
    if (kind === "placement") onShow({ kind: "placement", id });
    else if (kind === "net") onShow({ kind: "net", id });
    else if (kind === "part") {
      const first = project.placements.find((p) => p.part_id === id);
      if (first) onShow({ kind: "placement", id: first.id });
    }
  };

  const exportPart = async (partId: string) => {
    const part = project.parts.find((p) => p.id === partId);
    if (!part) return;
    setExporting(partId);
    setExportError("");
    try {
      const { downloadPartStl } = await import("./exporter");
      await downloadPartStl(part);
    } catch (error) {
      setExportError(`Could not make the STL: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setExporting("");
    }
  };

  const exportAll = async () => {
    setExporting("all");
    setExportError("");
    try {
      const { downloadAssemblyStl } = await import("./exporter");
      await downloadAssemblyStl(project.name, project.parts, project.placements);
    } catch (error) {
      setExportError(`Could not make the STL: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setExporting("");
    }
  };

  return (
    <div className="bs-inspector">
      <section className="bs-section" data-tour="checks">
        <div className="bs-section__head">
          <h3>Checks</h3>
          <span className="bs-muted">run on every change</span>
        </div>
        {!checks.length && <p className="bs-ok">No problems found. {project.placements.length ? "Nothing overlaps, everything fits, and the wiring rules pass." : "Add some parts to check."}</p>}
        <ul className="bs-findings">
          {checks.map((finding, index) => (
            <li key={index} className={`bs-finding is-${finding.level}`}>
              <div className="bs-finding__level">{LEVEL_LABEL[finding.level]}</div>
              <div className="bs-finding__text">{finding.message}</div>
              {finding.fix && <div className="bs-finding__fix">{finding.fix}</div>}
              <div className="bs-finding__actions">
                {finding.where.id && <button className="bs-link" onClick={() => show(finding)}>Show me</button>}
                <button className="bs-link" disabled={busy} onClick={() => onAskAbout(`About this problem: "${finding.message}". Why does it matter here, and what exactly should I change?`)}>Ask Nyx</button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="bs-section">
        <div className="bs-section__head"><h3>To buy</h3><span className="bs-muted">{bom.total_usd ? `$${bom.total_usd.toFixed(2)}` : ""}</span></div>
        {!buy.length && <p className="bs-muted">Nothing to buy yet.</p>}
        {buy.length > 0 && (
          <table className="bs-table">
            <thead><tr><th>Part</th><th>Qty</th><th>Each</th><th>Total</th></tr></thead>
            <tbody>
              {buy.map((line) => (
                <tr key={line.part_id}>
                  <td>{line.name}</td>
                  <td>{line.quantity}</td>
                  <td>{line.unit_price ? `$${line.unit_price.toFixed(2)}` : "—"}</td>
                  <td>{line.line_price ? `$${line.line_price.toFixed(2)}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="bs-muted bs-hint">{bom.note}{bom.unpriced ? ` ${bom.unpriced} part${bom.unpriced === 1 ? " has" : "s have"} no price yet.` : ""}</p>
      </section>

      <section className="bs-section">
        <div className="bs-section__head">
          <h3>To print</h3>
          <span className="bs-muted">{bom.print_grams ? `≈ ${Math.round(bom.print_grams)} g` : ""}</span>
        </div>
        {!print.length && !printing.length && <p className="bs-muted">No printable parts yet. Draw one in the “This build” tab.</p>}
        {printing.map((row) => (
          <div key={row.part_id} className="bs-print">
            <div className="bs-print__head">
              <b>{row.name}</b>
              <span className={row.fits ? "bs-ok" : "bs-error"}>{row.fits ? "fits" : "too big"}</span>
            </div>
            <div className="bs-muted">{row.size_mm.map((v) => v.toFixed(0)).join(" × ")} mm · {row.material} · ≈ {row.grams} g</div>
            {row.notes.map((note) => <div key={note} className="bs-finding__fix">{note}</div>)}
            <button className="btn btn-secondary btn-sm" disabled={Boolean(exporting)} onClick={() => void exportPart(row.part_id)}>
              {exporting === row.part_id ? "Making STL…" : "Download STL"}
            </button>
          </div>
        ))}
        {project.placements.length > 0 && (
          <button className="btn btn-secondary btn-sm" disabled={Boolean(exporting)} onClick={() => void exportAll()}>
            {exporting === "all" ? "Making STL…" : "Download whole assembly as STL"}
          </button>
        )}
        {exportError && <p className="bs-error">{exportError}</p>}
        <p className="bs-muted bs-hint">STL opens in Cura, PrusaSlicer, Bambu Studio and OrcaSlicer. Weights are rough estimates from the shapes.</p>
      </section>
    </div>
  );
}
