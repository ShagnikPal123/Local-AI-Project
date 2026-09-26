/** Research Tab — Deep research with real cited sources, paper search, and citation formatting (Request L). */

import { useState } from "react";
import { api } from "../api";

interface Paper {
  title: string;
  authors: string[];
  year?: number;
  venue?: string;
  citation_count?: number;
  abstract?: string;
  url?: string;
}

interface ResearchResult {
  job_id?: string;
  status?: string;
  report?: string;
  sources?: { title: string; url: string; snippet?: string }[];
}

export function ResearchPanel() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<"standard" | "deep">("deep");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [paperQuery, setPaperQuery] = useState("");
  const [papers, setPapers] = useState<Paper[]>([]);
  const [citationStyle, setCitationStyle] = useState("apa");
  const [formattedCitation, setFormattedCitation] = useState("");
  const [activeTab, setActiveTab] = useState<"research" | "papers">("research");

  async function startResearch() {
    if (!question.trim()) return;
    setLoading(true);
    setResult(null);
    const res = await api.post<{ job_id: string }>("/api/research", { question: question.trim(), mode });
    if (res.ok) {
      const jobId = res.data.job_id;
      // Poll for status
      const poll = async () => {
        const statRes = await api.get<ResearchResult>(`/api/research/${jobId}`);
        if (statRes.ok) {
          setResult(statRes.data);
          if (statRes.data.status === "done" || statRes.data.status === "error") {
            setLoading(false);
          } else {
            setTimeout(poll, 2000);
          }
        } else {
          setLoading(false);
        }
      };
      setTimeout(poll, 1500);
    } else {
      setLoading(false);
      setResult({ report: `Error starting research: ${res.error}` });
    }
  }

  async function searchPapers() {
    if (!paperQuery.trim()) return;
    const res = await api.post<{ papers: Paper[] }>("/api/research/papers", { query: paperQuery.trim() });
    if (res.ok) {
      setPapers(res.data.papers || []);
    }
  }

  async function citePaper(titleOrDoi: string) {
    const res = await api.post<{ citation: string }>("/api/research/cite", { doi_or_title: titleOrDoi, style: citationStyle });
    if (res.ok) {
      setFormattedCitation(res.data.citation);
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 960, margin: "0 auto", color: "var(--color-text)" }}>
      <div style={{ display: "flex", gap: 16, marginBottom: 20, borderBottom: "1px solid var(--color-border)", paddingBottom: 12 }}>
        <button
          className={`btn ${activeTab === "research" ? "btn-primary" : "btn-secondary"}`}
          onClick={() => setActiveTab("research")}>
          Deep Research
        </button>
        <button
          className={`btn ${activeTab === "papers" ? "btn-primary" : "btn-secondary"}`}
          onClick={() => setActiveTab("papers")}>
          Scholarly Papers
        </button>
      </div>

      {activeTab === "research" ? (
        <div>
          <h2>Deep Research &amp; Synthesis</h2>
          <p style={{ fontSize: 13, color: "var(--color-neutral-400)" }}>
            Ask a complex question. Nyx plans sub-questions, searches web &amp; scholarly papers, reads sources, and synthesizes a cited report.
          </p>
          <div style={{ display: "flex", gap: 10, marginBottom: 14, marginTop: 14 }}>
            <input
              style={{ flex: 1, padding: "10px 14px", borderRadius: 8, border: "1px solid var(--color-border)", background: "var(--color-nav)", color: "inherit" }}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. State-of-the-art transformer memory offloading techniques"
              onKeyDown={(e) => { if (e.key === "Enter") void startResearch(); }}
            />
            <select
              style={{ padding: "10px 12px", borderRadius: 8, border: "1px solid var(--color-border)", background: "var(--color-nav)", color: "inherit" }}
              value={mode}
              onChange={(e) => setMode(e.target.value as "standard" | "deep")}>
              <option value="deep">Deep (Multi-step)</option>
              <option value="standard">Standard (~1m)</option>
            </select>
            <button className="btn btn-primary" disabled={loading || !question.trim()} onClick={() => void startResearch()}>
              {loading ? "Researching…" : "Start Research"}
            </button>
          </div>

          {loading && (
            <div style={{ padding: 20, background: "var(--color-nav)", borderRadius: 8, marginBottom: 20 }}>
              <p>◌ Researching in background with real cited sources…</p>
            </div>
          )}

          {result && (
            <div style={{ background: "var(--color-nav)", padding: 20, borderRadius: 8, border: "1px solid var(--color-border)" }}>
              <h3>Research Report</h3>
              <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.6, fontSize: 14, marginTop: 10, marginBottom: 16 }}>
                {result.report}
              </div>
              {result.sources && result.sources.length > 0 && (
                <div>
                  <h4>Sources</h4>
                  <ul style={{ paddingLeft: 20, fontSize: 13, color: "var(--color-neutral-400)" }}>
                    {result.sources.map((s, idx) => (
                      <li key={idx}>
                        <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "var(--color-accent)" }}>{s.title}</a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div>
          <h2>Scholarly Paper Search &amp; Citing</h2>
          <div style={{ display: "flex", gap: 10, marginBottom: 14, marginTop: 14 }}>
            <input
              style={{ flex: 1, padding: "10px 14px", borderRadius: 8, border: "1px solid var(--color-border)", background: "var(--color-nav)", color: "inherit" }}
              value={paperQuery}
              onChange={(e) => setPaperQuery(e.target.value)}
              placeholder="Search arXiv / OpenAlex titles, authors, abstracts…"
              onKeyDown={(e) => { if (e.key === "Enter") void searchPapers(); }}
            />
            <select
              style={{ padding: "10px 12px", borderRadius: 8, border: "1px solid var(--color-border)", background: "var(--color-nav)", color: "inherit" }}
              value={citationStyle}
              onChange={(e) => setCitationStyle(e.target.value)}>
              <option value="apa">APA</option>
              <option value="mla">MLA</option>
              <option value="chicago">Chicago</option>
              <option value="ieee">IEEE</option>
              <option value="bibtex">BibTeX</option>
            </select>
            <button className="btn btn-primary" onClick={() => void searchPapers()}>Search Papers</button>
          </div>

          {formattedCitation && (
            <div style={{ padding: 12, background: "var(--color-accent-900)", borderRadius: 6, marginBottom: 16, fontSize: 13 }}>
              <b>Formatted Citation ({citationStyle.toUpperCase()}):</b>
              <div style={{ fontFamily: "monospace", marginTop: 4 }}>{formattedCitation}</div>
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {papers.map((p, i) => (
              <div key={i} style={{ padding: 14, background: "var(--color-nav)", borderRadius: 8, border: "1px solid var(--color-border)" }}>
                <h4 style={{ margin: "0 0 4px 0" }}>{p.title}</h4>
                <div style={{ fontSize: 12, color: "var(--color-neutral-400)", marginBottom: 6 }}>
                  {p.authors?.join(", ")} {p.year ? `(${p.year})` : ""} {p.venue ? `· ${p.venue}` : ""} {p.citation_count !== undefined ? `· ${p.citation_count} citations` : ""}
                </div>
                {p.abstract && <p style={{ fontSize: 13, marginBottom: 8 }}>{p.abstract}</p>}
                <div style={{ display: "flex", gap: 10 }}>
                  {p.url && <a href={p.url} target="_blank" rel="noreferrer" className="btn btn-secondary btn-sm">View Paper</a>}
                  <button className="btn btn-secondary btn-sm" onClick={() => void citePaper(p.title)}>Cite ({citationStyle.toUpperCase()})</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
