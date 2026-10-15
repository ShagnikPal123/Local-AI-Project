# combined-mod

Five Claude Code mods as one plugin (Drive doc 2, item 2.3). Nothing in it calls a model or spends tokens.

| Idea | From | What you see |
|---|---|---|
| Progress | savvy-progress | Band above the prompt: `◐ Working 0:42 · 7 tools · 2 agents`. `/combo-agents` opens a pane with every subagent and its live status. |
| Skins | claude-skins | The band doubles as a usage band (context %, cost, plan limit). `/combo-files` shows tool calls as cards with `+added −removed` badges. `/combo-skin nyx\|ember\|ocean\|mono` recolours everything. |
| Blast radius | blast-radius | A risky shell command (`rm -rf`, `git reset --hard`, `git push --force`, `DROP TABLE`, `curl … \| sh`, …) is held for your yes, with what it would delete or lose. It only ever tightens: a deny stays a deny. `/combo-hold off` turns it off. |
| File tree | claude-code-filetree | `/combo-files` shows the files Claude read and changed as a tree under the working folder; the newest is marked `▶`. |
| Cache tax | cache-tax | The band counts down the prompt cache's 5 minutes (`cache warm 3:12`, then `cache cold`). The first send after it went cold is held once, saying how many tokens it will re-read; press Enter again within a minute to send. `/combo-cache off` turns it off. |

## Install (Claude Code, on the PC)

At the prompt of a Claude Code terminal session:

```
/plugin install combined-mod --marketplace "<project folder>\claude-mods\combined-mod"
```

Answer `y` to add the marketplace, then pick the user scope. Restart Claude Code if the band does not show.

To try it without installing: `claude --plugin-dir "<that folder>"`.

## Develop

```
claude plugin validate claude-mods/combined-mod
claude plugin test claude-mods/combined-mod
```

`hooks/risk.ts` holds the risky-command rules as plain functions; add a rule there and a line to `hooks/register.test.ts`.
