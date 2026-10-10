/** An agent's identity mark: emoji in a colour disc, with a status ring and badge.
 *
 * Status is carried three ways so it never depends on colour alone:
 *  - ring style (`data-status`): animated arc while working, dashed when blocked,
 *    solid when done/error, none when idle;
 *  - a corner badge glyph: spinner dots / pause / check / exclamation;
 *  - the text label the parent renders next to it (or `label` for screen readers).
 */

import type { CSSProperties } from "react";
import { safeColor } from "./format";
import { Icon } from "./Icon";
import { IchosOrb } from "../orbs/IchosOrb";

export type AgentStatus = "idle" | "working" | "blocked" | "error" | "done";

export const STATUS_TEXT: Record<AgentStatus, string> = {
  idle: "Idle",
  working: "Working",
  blocked: "Waiting",
  error: "Needs attention",
  done: "Done",
};

interface AgentDiscProps {
  name: string;
  emoji?: string;
  color?: string;
  status?: AgentStatus;
  size?: "xs" | "sm" | "md" | "lg";
  /** When set, the disc is exposed as an image with this label; otherwise it is decorative. */
  label?: string;
  /** Hide the corner badge (used where the status text sits right beside the disc). */
  hideBadge?: boolean;
}

export function AgentDisc({ name, emoji, color, status = "idle", size = "md", label, hideBadge }: AgentDiscProps) {
  const c = safeColor(color);
  const style = c ? ({ ["--nyx-agent-color" as string]: c } as CSSProperties) : undefined;
  const glyph = emoji?.trim() || name.trim().charAt(0).toUpperCase() || "?";
  const a11y = label ? { role: "img" as const, "aria-label": label, title: label } : { "aria-hidden": true as const };
  return (
    <span className="nyx-disc" data-size={size} data-status={status} data-letter={emoji?.trim() ? undefined : "true"} style={style} {...a11y}>
      <span className="nyx-disc__glyph">{glyph}</span>
      <span className="nyx-disc__ring" />
      {!hideBadge && status !== "idle" && (
        <span className="nyx-disc__badge" data-status={status}>
          {status === "working" && <span className="nyx-disc__dots"><i /><i /><i /></span>}
          {status === "blocked" && <Icon name="pause" />}
          {status === "done" && <Icon name="check" />}
          {status === "error" && <span className="nyx-disc__bang">!</span>}
        </span>
      )}
    </span>
  );
}

/** Small inline busy mark — a "working" thought-orb; the accessible text lives next to it. */
export function Spinner({ className }: { className?: string }) {
  const xs = className?.includes("nyx-spinner--xs");
  return <IchosOrb state="working" size={xs ? 12 : 16} decorative className={className ? `nyx-spinner ${className}` : "nyx-spinner"} />;
}
