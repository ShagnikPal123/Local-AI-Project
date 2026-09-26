/** The chat UI contract (Lead-owned — do not edit without the Lead).
 *
 * Two agents build against this file at the same time:
 *  - the Designer owns every presentational component in src/components/chat/
 *    (pure props in, callbacks out, no fetching);
 *  - the Integrator owns data: the SSE client, the event reducer that turns
 *    server events into these view models, ChatPanel, and persistence.
 *
 * Server event schema: OVERHAUL_CONTRACTS.md §3.1 and AI_HANDOFF/03_ARCHITECTURE.md.
 */

// ---------------------------------------------------------------------------
// Raw server events (what /api/chat/stream and /api/turns/{id}/stream send)
// ---------------------------------------------------------------------------

export type TurnEventType =
  | "turn.start" | "status" | "thought" | "thought.delta"
  | "agent.update" | "agent.created"
  | "skill.used" | "skill.created"
  | "tool.start" | "tool.progress" | "tool.image" | "tool.end"
  | "approval.request" | "approval.resolved"
  | "answer.delta" | "answer.reset"
  | "cache.hit" | "learning.note" | "model.role" | "prompt.optimized"
  | "done" | "error";

export interface TurnEvent {
  type: TurnEventType | string;
  turn_id?: string;
  ts?: number;
  [key: string]: unknown;
}

/** Workspace events from /api/events/stream (channel "ui"). */
export interface WorkspaceEvent {
  type: string;          // "turn.state" | "agent.update" | "agent.created" | "agents.changed" | "skills.changed" | "ui.theme" | "ui.open_tab" | "tabs.changed" | "notify" | "permissions.changed" | …
  channel?: string;
  ts?: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// View models the components render
// ---------------------------------------------------------------------------

export type TurnState = "streaming" | "done" | "stopped" | "error";
export type TurnPhase = "route" | "think" | "agents" | "skills" | "tool" | "answer";

/** What the prompt optimizer did to a request (prompt_optimizer.py). */
export interface OptimizedRequest {
  mode: string;
  original: string;
  optimized: string;
  engine: string;
  reason: string;
  originalTokens: number;
  optimizedTokens: number;
  ms: number;
  assumptions: string[];
  notes: string[];
}

/** A job done by a model the owner assigned (model_roles): "NVIDIA Llama 3.2 Vision · image check". */
export interface ModelUse {
  role: string;
  title: string;
  job: string;
  provider: string;
  model: string;
  label: string;
  ms?: number;
  fellBack?: boolean;
  note?: string;
}

export interface StepImage {
  /** Set for pictures Nyx generated; the full image is /api/uploads/{uploadId}. */
  uploadId?: string;
  generated?: boolean;
  dataUrl: string;
  width?: number;
  height?: number;
  name?: string;
  note?: string;
}

/** One tool call, as a row in the step timeline. */
export interface ToolStep {
  callId: string;
  name: string;
  /** Human label from the server, e.g. "Running: Get-Process". */
  label: string;
  category: string;
  args?: Record<string, unknown>;
  status: "running" | "ok" | "error";
  /** Progress lines while it runs, oldest first. */
  progress: string[];
  /** First ~400 chars of the result. */
  preview?: string;
  ms?: number;
  images: StepImage[];
  /** Set when a delegated agent ran this step. */
  agent?: string;
  startedAt: number;
}

/** A specialist agent's work inside one turn. */
export interface AgentActivity {
  agentId: string;
  name: string;
  emoji?: string;
  color?: string;
  status: "working" | "done" | "error";
  step?: string;
  /** The agent's one-line restatement of its task ("Understood: …"). */
  understanding?: string;
  task?: string;
  resultPreview?: string;
  seconds?: number;
  /** True when this turn created the agent (it did not exist before). */
  created?: boolean;
  goal?: string;
  updatedAt: number;
}

export interface SkillRef {
  id: string;
  name: string;
  source?: string;
  /** A temporary skill made for this task; can be kept or exported. */
  temp?: boolean;
  description?: string;
  instructions?: string;
}

export interface ApprovalView {
  id: string;
  category: string;
  summary: string;
  detail?: string;
  resolved?: boolean;
  approved?: boolean;
}

export interface AttachmentRef {
  id: string;
  name: string;
  mime: string;
  kind: string;          // "image" | "pdf" | "document" | "text" | "other"
  size?: number;
  width?: number;
  height?: number;
  /** Authenticated URL: /api/uploads/{id}. */
  url?: string;
}

export interface ThoughtChunk {
  text: string;
  /** Empty for Nyx itself; an agent name when a specialist was thinking. */
  agent?: string;
}

/** Everything that happened in one assistant turn. */
/** A link the answer drew on (Request H15). */
export interface SourceLink {
  url: string;
  title: string;
  domain: string;
}

export interface AssistantTurn {
  turnId: string;
  chatId: string;
  state: TurnState;
  /** What is happening right now, in words. */
  status: string;
  phase?: TurnPhase;
  thoughts: ThoughtChunk[];
  steps: ToolStep[];
  agents: AgentActivity[];
  skillsUsed: SkillRef[];
  skillsCreated: SkillRef[];
  approvals: ApprovalView[];
  answer: string;
  provider?: string;
  model?: string;
  elapsedMs?: number;
  startedAt: number;
  error?: string;
  /** Set when the answer came from the response cache. */
  cached?: { cachedAt: number; similarity?: number };
  /** Short "Nyx learned…" notes from the learning system. */
  learningNotes?: string[];
  /** Models that did jobs in this turn, in order (image check, reading, image generation…). */
  models?: ModelUse[];
  feedback?: 1 | -1 | 0;
  /** Set when the prompt optimizer refined the owner's request before the model saw it. */
  optimized?: OptimizedRequest;
  /** True when this view was rebuilt by reattaching after a reload or tab switch. */
  resumed?: boolean;
  /** The provider picked in the dropdown could not answer, so another one did. */
  fallback?: { wanted: string; used: string; reason: string };
  /** Nyx switched the default provider during this turn (switch_model). */
  switchedTo?: string;
  /** Chats this turn created (new / duplicate / branch / fork) that the panel should open. */
  openChat?: { chatId: string; title: string; kind: string };
  /** Links the answer drew on, for the Sources drop-down. */
  sources?: SourceLink[];
  /** The working checklist a Co-work turn keeps current (chat_modes.update_checklist). */
  checklist?: { text: string; status: "todo" | "doing" | "done" | "blocked" | "skipped" }[];
  /** Which mode the slider under the composer was on for this turn. */
  chatMode?: string;
}

export interface ChatMessageView {
  id: string;
  role: "user" | "assistant" | "error" | "system";
  content: string;
  attachments?: AttachmentRef[];
  /** Present on assistant messages that came from a streamed turn. */
  turn?: AssistantTurn;
  provider?: string;
  createdAt?: number;
  /** Saved with the message, so the drop-down survives a reload. */
  sources?: SourceLink[];
}

/** A file picked in the composer before it is sent. */
export interface PendingAttachment {
  localId: string;
  name: string;
  size: number;
  mime: string;
  status: "uploading" | "ready" | "error";
  /** Object URL for image previews. */
  previewUrl?: string;
  uploadId?: string;
  error?: string;
}

/** A team member as the agent dock shows it. */
export interface TeamAgentView {
  agentId: string;
  name: string;
  emoji?: string;
  color?: string;
  status: "idle" | "working" | "blocked" | "error" | "done";
  step?: string;
  goal?: string;
  role?: "master" | "worker";
  lastActiveAt?: number | null;
  createdInChat?: string;
  tasksCompleted?: number;
}

export interface ChatSummaryView {
  id: string;
  title: string;
  updatedAt?: number;
  messageCount?: number;
  /** A turn is running in this chat right now (possibly started in another window). */
  running?: boolean;
  status?: string;
}

// ---------------------------------------------------------------------------
// Callbacks
// ---------------------------------------------------------------------------

export type MessageAction =
  | { type: "copy"; messageId: string }
  | { type: "retry"; messageId: string }
  | { type: "speak"; messageId: string }
  | { type: "branch"; messageId: string }
  | { type: "feedback"; messageId: string; turnId?: string; value: 1 | -1; comment?: string }
  | { type: "stop"; turnId: string }
  | { type: "approve"; approvalId: string; approve: boolean }
  | { type: "keepSkill"; skillId: string }
  | { type: "exportSkill"; skillId: string }
  | { type: "openAgent"; name: string }
  | { type: "askAgent"; name: string }
  | { type: "refreshCached"; messageId: string }
  | { type: "openImage"; src: string };

// ---------------------------------------------------------------------------
// Component props (the Designer implements these; the Integrator renders them)
// ---------------------------------------------------------------------------

export interface MessageListProps {
  messages: ChatMessageView[];
  onAction: (action: MessageAction) => void;
  /** Shown when the list is empty: suggestions, and the "agents are created in chat" hint. */
  emptyState?: { suggestions: string[]; onSuggestion: (text: string) => void };
}

export interface MessageBubbleProps {
  message: ChatMessageView;
  onAction: (action: MessageAction) => void;
  /** The newest assistant message expands its thinking/steps by default while streaming. */
  isLatest?: boolean;
}

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  attachments: PendingAttachment[];
  onAttachFiles: (files: File[]) => void;
  onRemoveAttachment: (localId: string) => void;
  /** For @mention autocomplete: typing "@" lists these. */
  agents: TeamAgentView[];
  placeholder?: string;
  disabled?: boolean;
  /** The "/" command menu (Request G5). */
  slash?: import("./SlashMenu").SlashHandlers;
  /** A message typed while a turn runs (Request G12): send it with the chosen mode. */
  onBusySend?: (mode: BusyMode) => void;
  /** Nyx's pick for that message, with a reason; null while deciding. */
  busyAdvice?: { mode: BusyMode; reason: string; source?: string } | null;
}

export type BusyMode = "queue" | "interrupt" | "parallel" | "branch";

export interface AgentDockProps {
  agents: TeamAgentView[];
  onOpenAgent: (name: string) => void;
  /** Inserts "@Name " into the composer. */
  onAskAgent: (name: string) => void;
  /** Collapsed state is remembered by the caller. */
  collapsed?: boolean;
  onToggle?: () => void;
  /** Opens every agent's details (Request H2). */
  onOpenDetails?: () => void;
}

export interface ChatSidebarProps {
  chats: ChatSummaryView[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}

export interface MarkdownProps {
  text: string;
  /** While streaming, an unclosed code fence renders as an open block instead of raw backticks. */
  streaming?: boolean;
}

export interface ToastItem {
  id: string;
  text: string;
  level: "info" | "ok" | "warn" | "error";
  action?: { label: string; onClick: () => void };
}

export interface ToastsProps {
  items: ToastItem[];
  onDismiss: (id: string) => void;
}
