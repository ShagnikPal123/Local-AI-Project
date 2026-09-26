/** Turn events → the AssistantTurn view model.
 *
 * Pure: the same (turn, event) always gives the same result, and nothing is
 * mutated. Timestamps come from the event (`ts`, seconds or ms); the stream
 * layer stamps receipt time on events the server sent without one.
 */

import type {
  AgentActivity,
  AssistantTurn,
  SkillRef,
  ToolStep,
  TurnEvent,
  TurnPhase,
} from "../components/chat";

const PHASES: ReadonlySet<string> = new Set(["route", "think", "agents", "skills", "tool", "answer"]);

const str = (value: unknown): string => (typeof value === "string" ? value : value == null ? "" : String(value));
const num = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

/** Seconds (Python time.time) or milliseconds → milliseconds. */
export function toMs(value: unknown): number | undefined {
  const n = num(value);
  if (n === undefined) return undefined;
  return n < 1e12 ? Math.round(n * 1000) : n;
}

export function newTurn(turnId: string, chatId: string, startedAt: number): AssistantTurn {
  return {
    turnId,
    chatId,
    state: "streaming",
    status: "Starting",
    thoughts: [],
    steps: [],
    agents: [],
    skillsUsed: [],
    skillsCreated: [],
    approvals: [],
    answer: "",
    startedAt,
  };
}

function skillOf(raw: unknown, temp?: boolean): SkillRef | null {
  if (!raw || typeof raw !== "object") return null;
  const s = raw as Record<string, unknown>;
  const id = str(s.id);
  if (!id) return null;
  return {
    id,
    name: str(s.name) || id,
    source: str(s.source) || undefined,
    temp: typeof s.temp === "boolean" ? s.temp : temp,
    description: str(s.description) || undefined,
    instructions: str(s.instructions) || undefined,
  };
}

function mergeSkills(list: SkillRef[], add: SkillRef[]): SkillRef[] {
  if (add.length === 0) return list;
  const next = [...list];
  for (const skill of add) {
    const at = next.findIndex((s) => s.id === skill.id);
    if (at === -1) next.push(skill);
    else next[at] = { ...next[at], ...skill };
  }
  return next;
}

/** The step an event without a call id belongs to: the newest running one, else the newest. */
function stepIndex(steps: ToolStep[], callId: string, name?: string): number {
  if (callId) {
    const at = steps.findIndex((s) => s.callId === callId);
    if (at !== -1) return at;
  }
  for (let i = steps.length - 1; i >= 0; i--) {
    if (steps[i].status === "running" && (!name || steps[i].name === name)) return i;
  }
  return callId ? -1 : steps.length - 1;
}

function patchStep(steps: ToolStep[], index: number, patch: (s: ToolStep) => ToolStep): ToolStep[] {
  const next = [...steps];
  next[index] = patch(steps[index]);
  return next;
}

/** Close anything still marked running once the turn has ended. */
function settle(turn: AssistantTurn, failed: boolean): Pick<AssistantTurn, "steps" | "agents"> {
  return {
    steps: turn.steps.some((s) => s.status === "running")
      ? turn.steps.map((s) => (s.status === "running" ? { ...s, status: failed ? "error" : "ok" } : s))
      : turn.steps,
    agents: turn.agents.some((a) => a.status === "working")
      ? turn.agents.map((a) => (a.status === "working" ? { ...a, status: failed ? "error" : "done" } : a))
      : turn.agents,
  };
}

export function reduceTurn(turn: AssistantTurn | undefined, event: TurnEvent): AssistantTurn {
  const at = toMs(event.ts) ?? turn?.startedAt ?? 0;
  const base = turn ?? newTurn(str(event.turn_id), str(event.chat_id), at);
  const t = !base.turnId && event.turn_id ? { ...base, turnId: str(event.turn_id) } : base;

  switch (event.type) {
    case "turn.start":
      return {
        ...t,
        turnId: str(event.turn_id) || t.turnId,
        chatId: str(event.chat_id) || t.chatId,
        state: "streaming",
        status: t.status === "Starting" ? "Working out what you need" : t.status,
        phase: t.phase ?? "route",
      };

    case "status": {
      const phase = PHASES.has(str(event.phase)) ? (str(event.phase) as TurnPhase) : t.phase;
      return { ...t, status: str(event.text) || t.status, phase };
    }

    case "thought":
    case "thought.delta": {
      const text = str(event.text);
      if (!text) return t;
      const agent = str(event.agent) || undefined;
      const last = t.thoughts[t.thoughts.length - 1];
      if (event.type === "thought.delta" && last && (last.agent ?? "") === (agent ?? "")) {
        return { ...t, thoughts: [...t.thoughts.slice(0, -1), { ...last, text: last.text + text }], phase: t.phase ?? "think" };
      }
      return { ...t, thoughts: [...t.thoughts, { text, agent }], phase: t.phase ?? "think" };
    }

    case "agent.update": {
      const agentId = str(event.agent_id) || str(event.name);
      if (!agentId) return t;
      const index = t.agents.findIndex((a) => a.agentId === agentId || (!!event.name && a.name === event.name));
      const prev = index === -1 ? undefined : t.agents[index];
      const status = event.status === "done" || event.status === "error" ? event.status : "working";
      const next: AgentActivity = {
        ...prev,
        agentId,
        name: str(event.name) || prev?.name || agentId,
        emoji: str(event.emoji) || prev?.emoji,
        color: str(event.color) || prev?.color,
        status,
        step: str(event.step) || prev?.step,
        understanding: str(event.understanding) || prev?.understanding,
        task: str(event.task) || prev?.task,
        resultPreview: str(event.result_preview) || prev?.resultPreview,
        seconds: num(event.seconds) ?? prev?.seconds,
        updatedAt: at,
      };
      const agents = index === -1 ? [...t.agents, next] : t.agents.map((a, i) => (i === index ? next : a));
      return {
        ...t,
        agents,
        phase: "agents",
        status: status === "working" ? `${next.emoji ? `${next.emoji} ` : ""}${next.name}: ${next.step || "working"}` : t.status,
      };
    }

    case "agent.created": {
      const name = str(event.name);
      if (!name) return t;
      const agentId = str(event.agent_id) || name;
      const index = t.agents.findIndex((a) => a.agentId === agentId || a.name === name);
      const prev = index === -1 ? undefined : t.agents[index];
      const next: AgentActivity = {
        agentId: prev?.agentId ?? agentId,
        status: "done",
        step: "Joined the team",
        ...prev,
        name,
        emoji: str(event.emoji) || prev?.emoji,
        color: str(event.color) || prev?.color,
        goal: str(event.goal) || prev?.goal,
        created: true,
        updatedAt: at,
      };
      return { ...t, agents: index === -1 ? [...t.agents, next] : t.agents.map((a, i) => (i === index ? next : a)) };
    }

    case "skill.used": {
      const raw = Array.isArray(event.skills) ? event.skills : [];
      const skills = raw.map((s) => skillOf(s)).filter((s): s is SkillRef => s !== null);
      return skills.length ? { ...t, skillsUsed: mergeSkills(t.skillsUsed, skills), phase: t.phase ?? "skills" } : t;
    }

    case "skill.created": {
      const skill = skillOf(event.skill, true);
      return skill ? { ...t, skillsCreated: mergeSkills(t.skillsCreated, [skill]) } : t;
    }

    case "tool.start": {
      const callId = str(event.call_id) || `step-${t.steps.length + 1}`;
      if (t.steps.some((s) => s.callId === callId)) return t;
      const name = str(event.name) || "tool";
      const step: ToolStep = {
        callId,
        name,
        label: str(event.label) || name,
        category: str(event.category) || "general",
        args: event.args && typeof event.args === "object" ? (event.args as Record<string, unknown>) : undefined,
        status: "running",
        progress: [],
        images: [],
        agent: str(event.agent) || undefined,
        startedAt: at,
      };
      return { ...t, steps: [...t.steps, step], phase: "tool", status: step.label };
    }

    case "tool.progress": {
      const text = str(event.text);
      const index = stepIndex(t.steps, str(event.call_id));
      if (!text || index < 0) return t;
      return { ...t, steps: patchStep(t.steps, index, (s) => ({ ...s, progress: [...s.progress, text].slice(-50) })) };
    }

    case "tool.image": {
      const dataUrl = str(event.data_url) || str(event.url);
      if (!dataUrl) return t;
      const image = {
        dataUrl,
        width: num(event.width),
        height: num(event.height),
        name: str(event.name) || undefined,
        note: str(event.note) || undefined,
        uploadId: str(event.upload_id) || undefined,
        generated: event.generated === true,
      };
      const index = stepIndex(t.steps, str(event.call_id));
      if (index < 0) {
        const step: ToolStep = {
          callId: str(event.call_id) || `image-${t.steps.length + 1}`,
          name: str(event.name) || "image",
          label: str(event.label) || image.name || "Image",
          category: "general",
          status: "ok",
          progress: [],
          images: [image],
          startedAt: at,
        };
        return { ...t, steps: [...t.steps, step] };
      }
      return { ...t, steps: patchStep(t.steps, index, (s) => ({ ...s, images: [...s.images, image] })) };
    }

    case "tool.end": {
      const index = stepIndex(t.steps, str(event.call_id), str(event.name) || undefined);
      if (index < 0) return t;
      return {
        ...t,
        steps: patchStep(t.steps, index, (s) => ({
          ...s,
          status: event.ok === false ? "error" : "ok",
          preview: str(event.preview) || s.preview,
          ms: num(event.ms) ?? (at && s.startedAt ? at - s.startedAt : undefined),
        })),
      };
    }

    case "approval.request": {
      const id = str(event.id);
      if (!id) return t;
      const approval = {
        id,
        category: str(event.category),
        summary: str(event.summary) || "Nyx is asking for permission",
        detail: str(event.detail) || undefined,
      };
      const index = t.approvals.findIndex((a) => a.id === id);
      return {
        ...t,
        approvals: index === -1 ? [...t.approvals, approval] : t.approvals.map((a, i) => (i === index ? { ...a, ...approval } : a)),
        status: `Waiting for your OK: ${approval.summary}`,
      };
    }

    case "approval.resolved": {
      const id = str(event.id);
      if (!t.approvals.some((a) => a.id === id)) return t;
      return {
        ...t,
        approvals: t.approvals.map((a) => (a.id === id ? { ...a, resolved: true, approved: Boolean(event.approved) } : a)),
      };
    }

    case "answer.delta": {
      const text = str(event.text);
      return text ? { ...t, answer: t.answer + text, phase: "answer", status: "Writing the answer" } : t;
    }

    case "answer.reset":
      return t.answer ? { ...t, answer: "" } : t;

    case "cache.hit":
      return {
        ...t,
        cached: {
          cachedAt: toMs(event.cached_at) ?? toMs(event.created_at) ?? at,
          similarity: num(event.similarity) ?? num(event.score),
        },
      };

    case "model.role": {
      const label = str(event.label);
      if (!label) return t;
      const use = {
        role: str(event.role),
        title: str(event.title) || str(event.role),
        job: str(event.job),
        provider: str(event.provider),
        model: str(event.model),
        label,
        ms: num(event.ms),
        fellBack: event.fell_back === true,
        note: str(event.note) || undefined,
      };
      return { ...t, models: [...(t.models ?? []), use] };
    }

    case "prompt.optimized": {
      const optimized = str(event.optimized);
      if (!optimized) return t;
      const checks = (event.checks ?? {}) as Record<string, unknown>;
      return {
        ...t,
        optimized: {
          mode: str(event.mode),
          original: str(event.original),
          optimized,
          engine: str(event.engine),
          reason: str(event.reason),
          originalTokens: num(event.original_tokens) ?? 0,
          optimizedTokens: num(event.optimized_tokens) ?? 0,
          ms: num(event.ms) ?? 0,
          assumptions: Array.isArray(event.assumptions) ? event.assumptions.map(String) : [],
          notes: Array.isArray(checks.notes) ? checks.notes.map(String) : [],
        },
      };
    }

    case "provider.fallback": {
      const used = str(event.used);
      return used ? { ...t, fallback: { wanted: str(event.wanted), used, reason: str(event.reason) } } : t;
    }

    case "model.switched": {
      const provider = str(event.provider);
      return provider ? { ...t, switchedTo: provider } : t;
    }

    case "chat.created": {
      const chatId = str(event.chat_id);
      return chatId && event.open !== false
        ? { ...t, openChat: { chatId, title: str(event.title), kind: str(event.kind) || "new" } }
        : t;
    }

    case "learning.note": {
      const text = str(event.text) || str(event.note);
      return text ? { ...t, learningNotes: [...(t.learningNotes ?? []), text] } : t;
    }

    // The working checklist a Co-work turn keeps in front of you (chat_modes.update_checklist).
    case "checklist": {
      const items = Array.isArray(event.items)
        ? (event.items as { text?: unknown; status?: unknown }[])
            .map((item) => ({ text: str(item.text), status: (str(item.status) || "todo") as "todo" | "doing" | "done" | "blocked" | "skipped" }))
            .filter((item) => item.text)
        : [];
      return items.length ? { ...t, checklist: items } : t;
    }

    case "chat.mode": {
      const mode = str(event.mode);
      return mode ? { ...t, chatMode: mode } : t;
    }

    case "done": {
      const stopped = Boolean(event.stopped);
      return {
        ...t,
        ...settle(t, stopped),
        state: stopped ? "stopped" : "done",
        status: stopped ? "Stopped" : "Done",
        answer: t.answer || str(event.reply),
        sources: Array.isArray(event.sources) ? (event.sources as AssistantTurn["sources"]) : t.sources,
        provider: str(event.provider) || t.provider,
        model: str(event.model) || t.model,
        elapsedMs: num(event.elapsed_ms) ?? t.elapsedMs,
        chatId: t.chatId || str(event.chat_id),
      };
    }

    case "stopped":
      return { ...t, ...settle(t, true), state: "stopped", status: "Stopped" };

    case "error": {
      const message = str(event.message) || "Something went wrong";
      return { ...t, ...settle(t, true), state: "error", status: message, error: message };
    }

    default:
      return t;
  }
}

/** Event types after which a turn stream will send nothing more. */
export function isTerminal(type: string): boolean {
  return type === "done" || type === "error" || type === "stopped";
}
