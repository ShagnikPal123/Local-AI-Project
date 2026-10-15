/** One subagent this session started, as the Agents pane lists it. */
export type AgentRow = { id: string; description: string; type: string; status: string; startedAt: number }

/** One file Claude touched; `edits` counts Edit/Write calls, `reads` the rest. */
export type FileRow = { path: string; reads: number; edits: number; added: number; removed: number; at: number }

/** One tool call, drawn as a card in the Files pane. */
export type CallCard = { id: string; tool: string; label: string; added: number; removed: number; isDone: boolean; isError: boolean }

/** The turn that is running now, or null between turns. */
export type Turn = { startedAt: number; tools: number }

/** Session numbers the usage band reads (from session.measure). */
export type Usage = { contextPercent: number | null; contextTokens: number | null; usd: number | null; limit: string | null }

declare module 'claude-code' {
  interface PluginState {
    'combined-mod': {
      turn: Turn | null
      agents: AgentRow[]
      files: FileRow[]
      calls: CallCard[]
      usage: Usage
      lastAnswerAt: number
      skin: string
      held: string[]
    }
  }
}
