/**
 * The persona badge (owner, 2026-10-14: "have specific chats only for a personality and add the badges feature so it
 * ids as that personality"). A chat that speaks as one of the avatars, or in a voice the owner approved for that one
 * chat, says so beside its name. No badge means Ichos itself.
 */

import type { ChatPersona } from "./types";

export function PersonaBadge({ persona, small = false }: { persona?: ChatPersona | null; small?: boolean }) {
  if (!persona) return null;
  const what = persona.kind === "avatar" ? "Avatar" : "Voice";
  return (
    <span className={`persona-badge persona-badge--${persona.kind}${small ? " persona-badge--small" : ""}`}
          title={persona.kind === "avatar"
            ? `${persona.name}'s own chat — only ${persona.name} speaks here`
            : `This chat only speaks as ${persona.name} (you approved it)`}>
      <span aria-hidden="true">{persona.kind === "avatar" ? "◉" : "♪"}</span>
      <span className="persona-badge__name">{persona.name}</span>
      <span className="sr-only"> ({what})</span>
    </span>
  );
}
