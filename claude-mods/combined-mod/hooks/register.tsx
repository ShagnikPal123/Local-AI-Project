/**
 * combined-mod: five Claude Code mods as one plugin (Drive doc 2, item 2.3).
 *
 *   progress     the band above the prompt shows the running turn (time, tool calls, agents) and an
 *                Agents pane lists every subagent with its live status          (savvy-progress)
 *   skins        the band doubles as a usage band (context, cost, plan limit), tool calls become
 *                cards with diff badges, and /combo-skin recolours it all       (claude-skins)
 *   blast radius a risky shell command is held for your yes, with what it would delete or lose
 *                                                                                (blast-radius)
 *   file tree    a Files pane shows the files Claude read and changed, newest marked
 *                                                                                (claude-code-filetree)
 *   cache tax    the band counts down the prompt cache's 5 minutes; the first send after it went cold
 *                is held once with what it will re-read, so you can choose      (cache-tax)
 *
 * Nothing here runs a model or spends tokens. Settings live in $.store so they survive restarts.
 */

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { AgentRow, CallCard, FileRow, Turn, Usage } from '../types'
import { assess, diffCounts, summarizeDirty } from './risk'

const turnA = atom({ plugin: 'combined-mod', key: 'turn' } as const, null)
const agentsA = atom({ plugin: 'combined-mod', key: 'agents' } as const, [])
const filesA = atom({ plugin: 'combined-mod', key: 'files' } as const, [])
const callsA = atom({ plugin: 'combined-mod', key: 'calls' } as const, [])
const usageA = atom({ plugin: 'combined-mod', key: 'usage' } as const, { contextPercent: null, contextTokens: null, usd: null, limit: null })
const lastAnswerA = atom({ plugin: 'combined-mod', key: 'lastAnswerAt' } as const, 0)
const skinA = atom({ plugin: 'combined-mod', key: 'skin' } as const, 'nyx')
const heldA = atom({ plugin: 'combined-mod', key: 'held' } as const, [])

/** The prompt cache lives 5 minutes after its last use. */
const CACHE_TTL_MS = 5 * 60 * 1000
/** A held cold send goes through if it is sent again within this long. */
const CONFIRM_MS = 60 * 1000
const AGENTS_PANE = 'combo-agents'
const FILES_PANE = 'combo-files'
const SHELLS = new Set(['Bash', 'PowerShell'])
const FILE_TOOLS = new Set(['Read', 'Edit', 'Write', 'NotebookEdit', 'MultiEdit'])
const CHANGING = new Set(['Edit', 'Write', 'NotebookEdit', 'MultiEdit'])

export type Skin = { accent: string; good: string; warn: string; bad: string }
const NYX: Skin = { accent: '#a78bfa', good: '#34d399', warn: '#fbbf24', bad: '#f87171' }
export const SKINS: Record<string, Skin> = {
  nyx: NYX,
  ember: { accent: '#fb923c', good: '#facc15', warn: '#f97316', bad: '#ef4444' },
  ocean: { accent: '#38bdf8', good: '#2dd4bf', warn: '#fde047', bad: '#fb7185' },
  mono: { accent: '#d4d4d4', good: '#e5e5e5', warn: '#a3a3a3', bad: '#ffffff' },
}

/** A skin by name; an unknown name falls back to the default. */
export function skinOf(name: string): Skin {
  return SKINS[name] ?? NYX
}

export function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function shortTokens(n: number): string {
  return n >= 1000 ? `${Math.round(n / 1000)}k` : String(n)
}

export const register: Register = on => {
  // Module-local: a reload starts these over, which is fine (they only steer one prompt or one tick).
  let coldHeldAt = 0
  let tick = 0
  let holdOn = true
  let cacheOn = true

  on('session.start', async ($, e, next) => {
    holdOn = (await $.store.get('holdRisky')) !== false
    cacheOn = (await $.store.get('cacheGuard')) !== false
    const saved = await $.store.get('skin')
    if (typeof saved === 'string' && saved in SKINS) await update($, skinA, () => saved)

    await $.command.register({ name: 'combo-agents', description: 'Show every subagent and what it is doing' })
    await $.command.register({ name: 'combo-files', description: 'Show the files Claude is working in, as a tree' })
    await $.command.register({ name: 'combo-skin', description: `Recolour the combined mod: ${Object.keys(SKINS).join(', ')}` })
    await $.command.register({ name: 'combo-hold', description: 'Turn the risky-command hold on or off' })
    await $.command.register({ name: 'combo-cache', description: 'Turn the cold-cache warning on or off' })

    // One slow heartbeat redraws the running clock and the cache countdown; it does nothing else.
    $.clock.every(1000, () => {
      tick += 1
      void (async () => {
        const turn = await read($, turnA)
        if (turn) {
          await update($, turnA, t => (t ? { ...t } : t))
          if (tick % 3 === 0) await refreshAgents($)
        } else if (tick % 15 === 0) {
          await update($, lastAnswerA, at => at + 0)
          await update($, usageA, u => ({ ...u }))
        }
      })().catch(() => undefined)
    })

    return next(e)
  })

  on('command.run', { command: 'combo-agents' }, async $ => {
    await $.ui.open({ id: AGENTS_PANE, title: 'Agents' })
    return { text: 'Agents pane opened.' }
  })

  on('command.run', { command: 'combo-files' }, async $ => {
    await $.ui.open({ id: FILES_PANE, title: 'Files' })
    return { text: 'Files pane opened.' }
  })

  on('command.run', { command: 'combo-skin' }, async ($, e) => {
    const name = e.args.trim().toLowerCase()
    if (!(name in SKINS)) return { text: `Skins: ${Object.keys(SKINS).join(', ')}. Try /combo-skin ocean.` }
    await update($, skinA, () => name)
    await $.store.set('skin', name)
    return { text: `Skin set to ${name}.` }
  })

  on('command.run', { command: 'combo-hold' }, async ($, e) => {
    holdOn = !/^(off|no|false)$/i.test(e.args.trim())
    await $.store.set('holdRisky', holdOn)
    return { text: `Risky-command hold is ${holdOn ? 'on' : 'off'}.` }
  })

  on('command.run', { command: 'combo-cache' }, async ($, e) => {
    cacheOn = !/^(off|no|false)$/i.test(e.args.trim())
    await $.store.set('cacheGuard', cacheOn)
    return { text: `Cold-cache warning is ${cacheOn ? 'on' : 'off'}.` }
  })

  // ── cache tax + progress: a prompt starts a turn ──────────────────────────
  on('prompt.submit', async ($, e, next) => {
    const typed = !e.isMeta && (e.origin.kind === 'composer' || e.origin.kind === 'bridge')
    if (typed && cacheOn) {
      const now = await $.clock.now()
      const last = await read($, lastAnswerA)
      const isCold = last > 0 && now - last > CACHE_TTL_MS
      if (isCold && now - coldHeldAt > CONFIRM_MS) {
        coldHeldAt = now
        const usage = await read($, usageA)
        const size = usage.contextTokens ? `about ${shortTokens(usage.contextTokens)} tokens` : 'the whole conversation'
        return {
          drop: `The prompt cache went cold ${clock(now - last - CACHE_TTL_MS)} ago, so this send re-reads ${size} at full price. ` +
            'Press Enter again within a minute to send anyway, or /compact or /clear first to make it cheaper.',
        }
      }
    }
    if (typed) await update($, turnA, () => ({ startedAt: Date.now(), tools: 0 }) as Turn)
    return next(e)
  }).catch(($, e, next) => next(e)) // a fault in this mod never blocks Claude

  // ── blast radius: hold a risky shell command with what it would change ───
  on('tool.check', async ($, e, next) => {
    const below = await next(e)
    if (!holdOn || !SHELLS.has(e.tool) || below.decision === 'deny') return below
    const command = String((e.input as { command?: unknown })?.command ?? '')
    const risk = assess(command)
    if (!risk) return below

    let radius = ''
    try {
      if (risk.probe === 'git-dirty') {
        const ran = await $.process.run(['git', 'status', '--porcelain'], { cwd: await $.session.cwd() })
        radius = ran.exitCode === 0 ? `Would lose: ${summarizeDirty(ran.stdout)}.` : ''
      } else if (risk.probe === 'paths') {
        radius = `Would delete: ${(await describeTargets($, risk.targets)).join(', ') || 'the paths named'}.`
      }
    } catch {
      radius = ''
    }
    const reason = `Blast radius: this command ${risk.why}. ${radius}`.trim()
    await update($, heldA, list => [...list, `${command.slice(0, 80)}  (${risk.why})`].slice(-20))
    $.ui.toast(`Held: ${risk.why}`)
    return { ...below, decision: 'ask', reason }
  }).catch(($, e, next) => next(e)) // a fault in this mod never blocks Claude

  // ── progress, skins and file tree: every tool call ────────────────────────
  on('tool.call', async ($, e, next) => {
    await update($, turnA, t => (t ? { ...t, tools: t.tools + 1 } : t))
    const input = e as unknown as Record<string, unknown>
    const path = typeof input.file_path === 'string' ? input.file_path : typeof input.notebook_path === 'string' ? input.notebook_path : ''
    let added = 0
    let removed = 0
    if (e.tool === 'Edit') ({ added, removed } = diffCounts(String(input.old_string ?? ''), String(input.new_string ?? '')))
    if (e.tool === 'Write') added = diffCounts('', String(input.content ?? '')).added

    const card: CallCard = {
      id: e.tool_use_id,
      tool: e.tool,
      label: path ? path.split(/[\\/]/).pop() ?? path : String(input.command ?? input.pattern ?? input.description ?? '').slice(0, 60),
      added,
      removed,
      isDone: false,
      isError: false,
    }
    await update($, callsA, list => [...list, card].slice(-60))

    const ran = await next(e)
    const failed = ran.deny !== undefined || ran.isError === true
    await update($, callsA, list => list.map(c => (c.id === card.id ? { ...c, isDone: true, isError: failed } : c)))

    if (path && FILE_TOOLS.has(e.tool) && !failed) {
      const at = Date.now()
      const changes = CHANGING.has(e.tool)
      await update($, filesA, list => {
        const found = list.find(f => f.path === path)
        const row: FileRow = found
          ? { ...found, at, reads: found.reads + (changes ? 0 : 1), edits: found.edits + (changes ? 1 : 0), added: found.added + added, removed: found.removed + removed }
          : { path, at, reads: changes ? 0 : 1, edits: changes ? 1 : 0, added, removed }
        return [...list.filter(f => f.path !== path), row].slice(-300)
      })
    }
    return ran
  }).catch(($, e, next) => next(e)) // a fault in this mod never blocks Claude

  on('agent.spawn', async ($, e, next) => {
    const spawned = await next(e)
    if (spawned.agentId) {
      const row: AgentRow = { id: spawned.agentId, description: e.description, type: e.subagentType, status: 'running', startedAt: Date.now() }
      await update($, agentsA, list => [...list.filter(a => a.id !== row.id), row].slice(-40))
    }
    return spawned
  }).catch(($, e, next) => next(e)) // a fault in this mod never blocks Claude

  on('session.measure', async ($, e, next) => {
    const limit = [...e.rateLimits].sort((a, b) => b.percentUsed - a.percentUsed)[0]
    const usage: Usage = {
      contextPercent: e.context.percent ?? null,
      contextTokens: e.context.tokens ?? null,
      usd: e.cost?.usd ?? null,
      limit: limit ? `${limit.kind} ${Math.round(limit.percentUsed)}%` : null,
    }
    await update($, usageA, () => usage)
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (!e.agentId) {
      await update($, lastAnswerA, () => Date.now())
      await update($, turnA, () => null)
    }
    await refreshAgents($)
    return next(e)
  })

  // ── drawing ───────────────────────────────────────────────────────────────
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const skin = skinOf(await read($, skinA))
    const turn = await read($, turnA)
    const agents = (await read($, agentsA)).filter(a => a.status === 'running' || a.status === 'pending')
    const usage = await read($, usageA)
    const last = await read($, lastAnswerA)
    const now = Date.now()

    const parts: string[] = []
    if (usage.contextPercent !== null) parts.push(`context ${Math.round(usage.contextPercent)}%`)
    if (usage.usd !== null) parts.push(`$${usage.usd.toFixed(2)}`)
    if (usage.limit) parts.push(usage.limit)

    let cacheText = ''
    let cacheColor = skin.good
    if (last > 0 && !turn) {
      const left = CACHE_TTL_MS - (now - last)
      cacheText = left > 0 ? `cache warm ${clock(left)}` : 'cache cold'
      cacheColor = left > 60_000 ? skin.good : left > 0 ? skin.warn : skin.bad
    }

    return (
      <Box>
        {turn ? (
          <Text color={skin.accent} bold>
            ◐ Working {clock(now - turn.startedAt)} · {turn.tools} tools{agents.length ? ` · ${agents.length} agents` : ''}{'  '}
          </Text>
        ) : null}
        <Text dimColor>{parts.join(' · ')}{parts.length && cacheText ? ' · ' : ''}</Text>
        {cacheText ? <Text color={cacheColor}>{cacheText}</Text> : null}
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: AGENTS_PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const skin = skinOf(await read($, skinA))
    const agents = await read($, agentsA)
    const held = await read($, heldA)
    const colorOf = (s: string) => (s === 'running' || s === 'pending' ? skin.accent : s === 'completed' ? skin.good : s === 'failed' || s === 'killed' ? skin.bad : skin.warn)
    return (
      <Box flexDirection="column">
        {agents.length === 0 && <Text dimColor>No subagents yet.</Text>}
        {agents.map(a => (
          <Text>
            <Text color={colorOf(a.status)}>{a.status.padEnd(9)}</Text> {a.type}: {a.description}
          </Text>
        ))}
        {held.length > 0 && <Text bold>Held for your yes</Text>}
        {held.slice(-5).map(h => (
          <Text color={skin.warn}>⚠ {h}</Text>
        ))}
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: FILES_PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const skin = skinOf(await read($, skinA))
    const files = await read($, filesA)
    const calls = await read($, callsA)
    const cwd = await $.session.cwd()
    const rows = treeRows(files, cwd)
    const room = Math.max(4, (e.viewport?.rows ?? 30) - 12)
    return (
      <Box flexDirection="column">
        {rows.length === 0 && <Text dimColor>No files touched yet.</Text>}
        {rows.slice(0, room).map(r =>
          r.isDir ? (
            <Text dimColor>{'  '.repeat(r.depth)}{r.name}/</Text>
          ) : (
            <Text color={r.isNewest ? skin.accent : undefined} bold={r.isNewest}>
              {'  '.repeat(r.depth)}{r.isNewest ? '▶ ' : ''}{r.name} <Text dimColor>{r.note}</Text>
            </Text>
          ),
        )}
        <Text bold>Recent tool calls</Text>
        {calls.slice(-8).map(c => (
          <Text>
            <Text color={c.isError ? skin.bad : c.isDone ? skin.good : skin.accent}>{c.isError ? '✗' : c.isDone ? '✓' : '…'}</Text> {c.tool} {c.label}
            {c.added || c.removed ? <Text color={skin.good}> +{c.added}</Text> : null}
            {c.added || c.removed ? <Text color={skin.bad}> −{c.removed}</Text> : null}
          </Text>
        ))}
      </Box>
    )
  })
}

/** Refresh each subagent row's status from the engine's own list. */
async function refreshAgents($: EngineInterface): Promise<void> {
  const live = await $.agent.list()
  const byId = new Map(live.map(a => [a.id, a.status]))
  await update($, agentsA, list => list.map(a => (byId.has(a.id) ? { ...a, status: byId.get(a.id) as string } : a)))
}

async function describeTargets($: EngineInterface, targets: string[]): Promise<string[]> {
  const out: string[] = []
  for (const target of targets) {
    try {
      const stat = await $.fs.stat(target)
      if (stat.kind === 'dir') {
        const entries = await $.fs.list(target)
        out.push(`${target}/ (${entries.length} entries at the top level)`)
      } else {
        out.push(`${target} (${stat.size} bytes)`)
      }
    } catch {
      out.push(`${target} (not found)`)
    }
  }
  return out
}

export type TreeRow = { depth: number; name: string; isDir: boolean; isNewest: boolean; note: string }

/** Files as an indented tree under the working folder; directories first appear where a file needs them. */
export function treeRows(files: FileRow[], cwd: string): TreeRow[] {
  const norm = (p: string) => p.replace(/\\/g, '/')
  const root = norm(cwd).replace(/\/$/, '')
  const newest = files.reduce<FileRow | null>((best, f) => (!best || f.at > best.at ? f : best), null)
  const sorted = [...files].sort((a, b) => norm(a.path).localeCompare(norm(b.path)))
  const rows: TreeRow[] = []
  const opened = new Set<string>()
  for (const f of sorted) {
    const full = norm(f.path)
    const rel = full.startsWith(root + '/') ? full.slice(root.length + 1) : full
    const parts = rel.split('/').filter(Boolean)
    for (let i = 0; i < parts.length - 1; i++) {
      const key = parts.slice(0, i + 1).join('/')
      if (!opened.has(key)) {
        opened.add(key)
        rows.push({ depth: i, name: parts[i] ?? '', isDir: true, isNewest: false, note: '' })
      }
    }
    const bits = []
    if (f.edits) bits.push(`edited ${f.edits}× +${f.added} −${f.removed}`)
    if (f.reads) bits.push(`read ${f.reads}×`)
    rows.push({ depth: parts.length - 1, name: parts[parts.length - 1] ?? rel, isDir: false, isNewest: f === newest, note: bits.join(', ') })
  }
  return rows
}
