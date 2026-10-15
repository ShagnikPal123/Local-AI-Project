/**
 * Blast radius: which shell commands are risky enough to hold, and what they would touch.
 *
 * Plain functions with no `$`, so the tests can run every rule without an engine. The hook in
 * register.tsx adds the live part (how many files a delete would remove, what a hard reset would lose).
 */

export type Risk = {
  /** What kind of damage, in a few words. */
  why: string
  /** Paths the command names that it would delete or overwrite ("." when it is the whole folder). */
  targets: string[]
  /** `git` when the live check should ask git what would be lost. */
  probe?: 'git-dirty' | 'paths'
}

type Rule = { test: RegExp; why: string; probe?: Risk['probe'] }

const RULES: Rule[] = [
  { test: /\brm\s+(-[a-z]*[rf][a-z]*\s+)+/i, why: 'deletes files', probe: 'paths' },
  { test: /\bremove-item\b.*-(recurse|force)\b/i, why: 'deletes files', probe: 'paths' },
  { test: /\b(rd|rmdir)\s+\/s\b|\bdel\s+\/[sq]\b/i, why: 'deletes files', probe: 'paths' },
  { test: /\bgit\s+reset\s+--hard\b/i, why: 'throws away uncommitted changes', probe: 'git-dirty' },
  { test: /\bgit\s+clean\s+-[a-z]*f/i, why: 'deletes untracked files', probe: 'git-dirty' },
  { test: /\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)/i, why: 'throws away uncommitted changes', probe: 'git-dirty' },
  { test: /\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f\b)/i, why: 'rewrites history on the remote' },
  { test: /\bgit\s+branch\s+-D\b/, why: 'deletes a branch that may not be merged' },
  { test: /\bgit\s+stash\s+(drop|clear)\b/i, why: 'deletes stashed work' },
  { test: /\b(drop\s+(table|database|schema)|truncate\s+table)\b/i, why: 'deletes database data' },
  { test: /\b(mkfs|format\s+[a-z]:|diskpart)\b|\bdd\s+if=/i, why: 'can wipe a disk' },
  { test: /\b(chmod|chown)\s+-R\b/i, why: 'changes permissions on a whole tree' },
  { test: /\b(curl|wget|iwr|invoke-webrequest)\b[^|]*\|\s*(sh|bash|iex|invoke-expression|python)\b/i, why: 'runs a script straight from the internet' },
  { test: /\b(npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b/i, why: 'publishes a package' },
  { test: /\bdocker\s+(system|volume|image)\s+prune\b|\bkubectl\s+delete\b/i, why: 'deletes containers or cluster objects' },
  { test: /\bshutdown\b|\bstop-computer\b|\brestart-computer\b/i, why: 'turns the computer off or restarts it' },
]

/** The first rule a command breaks, or null when it is safe to run without a hold. */
export function assess(command: string): Risk | null {
  const text = command.trim()
  for (const rule of RULES) {
    if (rule.test.test(text)) {
      return { why: rule.why, targets: rule.probe === 'paths' ? deleteTargets(text) : [], probe: rule.probe }
    }
  }
  return null
}

/** The path arguments of a delete: every word after the command that is not a flag. */
export function deleteTargets(command: string): string[] {
  const first = command.split(/&&|\|\||;|\|/)[0] ?? command
  const words = first.match(/"[^"]*"|'[^']*'|\S+/g) ?? []
  const start = words.findIndex(w => /^(rm|remove-item|rd|rmdir|del)$/i.test(w))
  return words
    .slice(start + 1)
    .filter(w => !/^-|^\/[a-z]$/i.test(w))
    .map(w => w.replace(/^["']|["']$/g, ''))
    .slice(0, 8)
}

/** `git status --porcelain` lines as "M src/a.ts, ?? notes.md and 3 more". */
export function summarizeDirty(porcelain: string, max = 6): string {
  const lines = porcelain.split('\n').map(l => l.trim()).filter(Boolean)
  if (lines.length === 0) return 'nothing uncommitted would be lost'
  const shown = lines.slice(0, max).join(', ')
  return lines.length > max ? `${shown} and ${lines.length - max} more` : shown
}

/** Lines added and removed by an Edit or Write, for the diff badge on a tool card. */
export function diffCounts(oldText: string, newText: string): { added: number; removed: number } {
  const count = (s: string) => (s === '' ? 0 : s.split('\n').length)
  return { added: count(newText), removed: count(oldText) }
}
