/** One office, live.
 *
 * The snapshot is fetched once and then kept up to date by ``office.event`` messages on the workspace stream —
 * a desk appearing, an agent's step changing, a task finishing, a message arriving. Each event carries the whole
 * record that changed, so applying one is an upsert and a dropped event heals on the next one (plus a quiet
 * re-fetch every 20 seconds, and whenever the window is focused again).
 *
 * The office keeps working whether or not this tab is open; this hook only watches.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { officeApi } from "./officeApi";
import type {
  FocusState, OfficeAgent, OfficeHire, OfficeJob, OfficeMessage, OfficeOutput, OfficeRole, OfficeSection, OfficeSnapshot,
  OfficeStaffChange, OfficeTask, Talk,
} from "./types";

const HEAL_MS = 20_000;
const TALK_TTL_MS = 4000;

export interface OfficeLive {
  snapshot: OfficeSnapshot | null;
  error: string;
  loading: boolean;
  talks: Talk[];
  reload: () => Promise<void>;
  apply: (snapshot: OfficeSnapshot) => void;
  agentsById: Record<string, OfficeAgent>;
  sectionsById: Record<string, OfficeSection>;
  rolesById: Record<string, OfficeRole>;
}

function upsert<T extends { id: string }>(rows: T[], row: T): T[] {
  const index = rows.findIndex((r) => r.id === row.id);
  if (index === -1) return [...rows, row];
  const copy = rows.slice();
  copy[index] = { ...copy[index], ...row };
  return copy;
}

export function useOffice(officeId: string): OfficeLive {
  const [snapshot, setSnapshot] = useState<OfficeSnapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [talks, setTalks] = useState<Talk[]>([]);
  const talkSeq = useRef(0);

  const reload = useCallback(async () => {
    if (!officeId) return;
    const result = await officeApi.snapshot(officeId);
    if (result.ok) {
      setSnapshot(result.data);
      setError("");
    } else {
      setError(result.error);
    }
    setLoading(false);
  }, [officeId]);

  useEffect(() => {
    setLoading(true);
    void reload();
  }, [reload]);

  // Heal quietly: a missed event or a change made from another window.
  useEffect(() => {
    if (!officeId) return;
    const timer = window.setInterval(() => void reload(), HEAL_MS);
    const onFocus = () => void reload();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [officeId, reload]);

  useEffect(() => {
    if (!officeId) return undefined;
    return onWorkspaceEvent((event) => {
      if (event.type === "office.focus") {
        setSnapshot((current) => (current ? { ...current, focus: event as unknown as FocusState } : current));
        return;
      }
      if (event.type !== "office.event" || event.office_id !== officeId) return;
      const kind = String(event.kind ?? "");
      if (kind === "talk") {
        const talk: Talk = {
          id: `talk-${talkSeq.current++}`,
          from: String(event.from ?? ""),
          to: (event.to as string[]) ?? [],
          at: Date.now(),
        };
        setTalks((rows) => [...rows.filter((t) => Date.now() - t.at < TALK_TTL_MS), talk].slice(-24));
        return;
      }
      setSnapshot((current) => {
        if (!current) return current;
        switch (kind) {
          case "agent":
          case "agent.created":
          case "gatekeeper":
            return { ...current, agents: upsert(current.agents, event.agent as OfficeAgent) };
          case "section":
          case "section.created":
            return { ...current, sections: upsert(current.sections, event.section as OfficeSection) };
          case "task":
            return { ...current, tasks: upsert(current.tasks, event.task as OfficeTask) };
          case "hire":
            return { ...current, hires: upsert(current.hires, event.hire as OfficeHire) };
          case "output":
            return { ...current, outputs: upsert(current.outputs ?? [], event.output as OfficeOutput) };
          case "staffing": {
            const change = event.change as OfficeStaffChange;
            const staffing = upsert(current.staffing ?? [], change);
            // Someone let go leaves the floor at once; the record stays in the staffing list.
            const agents = change.change === "let_go" ? current.agents.filter((a) => a.id !== change.agent_id) : current.agents;
            return { ...current, staffing, agents };
          }
          case "role.created":
            return { ...current, roles: upsert(current.roles, event.role as OfficeRole) };
          case "job":
          case "phase": {
            const job = event.job as OfficeJob;
            return { ...current, job, office: { ...current.office, phase: job.phase } };
          }
          case "office":
            return { ...current, office: { ...current.office, ...(event.office as object) } };
          case "message": {
            const message = event.message as OfficeMessage;
            const list = message.kind === "chat" ? "chat" : message.kind === "thread" ? "thread" : "feed";
            const rows = (current[list] as OfficeMessage[]).filter((m) => m.id !== message.id);
            return { ...current, [list]: [...rows, message].slice(-300) } as OfficeSnapshot;
          }
          default:
            return current;
        }
      });
      if (kind === "gatekeeper") {
        setSnapshot((current) => (current
          ? { ...current, office: { ...current.office, gatekeeper_id: String((event.agent as OfficeAgent)?.id ?? "") } }
          : current));
      }
    });
  }, [officeId]);

  // Drop finished lines so the floor does not accumulate them.
  useEffect(() => {
    if (!talks.length) return undefined;
    const timer = window.setTimeout(
      () => setTalks((rows) => rows.filter((t) => Date.now() - t.at < TALK_TTL_MS)), TALK_TTL_MS);
    return () => window.clearTimeout(timer);
  }, [talks]);

  const agentsById = useMemo(
    () => Object.fromEntries((snapshot?.agents ?? []).map((a) => [a.id, a])), [snapshot?.agents]);
  const sectionsById = useMemo(
    () => Object.fromEntries((snapshot?.sections ?? []).map((s) => [s.id, s])), [snapshot?.sections]);
  const rolesById = useMemo(
    () => Object.fromEntries((snapshot?.roles ?? []).map((r) => [r.id, r])), [snapshot?.roles]);

  return { snapshot, error, loading, talks, reload, apply: setSnapshot, agentsById, sectionsById, rolesById };
}
