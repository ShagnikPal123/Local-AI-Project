/** Nyx avatar — the Ichnos character, animated to reflect what the agent is doing.
 *
 * The artwork is a raster asset (`/ichnos.png`); everything around it is CSS, so
 * the motion costs no repaint of the image itself and stays cheap in the header,
 * where this renders on every screen.
 *
 * State is carried by the halo and the orbiting spark rather than by tinting the
 * character: recolouring the art fought its own palette and made "thinking" look
 * like a rendering bug. A ring and a moving spark read instantly at 30px.
 */

// Imported rather than referenced as "/ichnos.png": Vite copies public/ to the
// dist root, but server.py only mounts /assets, so a public-root path 404s.
// Importing it makes Vite emit the file into /assets with a content hash, which
// the existing mount already serves.
import ichnosArt from "../assets/ichnos.png";

export type AvatarState = "idle" | "thinking" | "coding" | "listening" | "error";

const STATE_COLOR: Record<AvatarState, string> = {
  idle: "var(--color-accent)",
  thinking: "var(--color-accent-400)",
  coding: "var(--color-ok)",
  listening: "var(--color-accent-2)",
  error: "var(--color-danger)",
};

interface Props {
  state?: AvatarState;
  size?: number;
  title?: string;
  /** Larger presentations (hero, empty states) get the drifting sparks too. */
  showSparks?: boolean;
}

export function NyxAvatar({ state = "idle", size = 30, title, showSparks }: Props) {
  const color = STATE_COLOR[state];
  const busy = state === "thinking" || state === "listening" || state === "coding";
  const label = title ?? `Nyx is ${state}`;
  // Sparks are decorative and unreadable below ~48px, so they are opt-in and
  // suppressed at header scale.
  const sparks = (showSparks ?? size >= 64) && state !== "error";

  return (
    <span
      className="nyx-avatar"
      data-state={state}
      role="img"
      aria-label={label}
      title={label}
      style={{ ["--nyx-avatar-size" as string]: `${size}px`, ["--nyx-avatar-color" as string]: color }}
    >
      <span className="nyx-avatar__halo" aria-hidden="true" />
      <img className="nyx-avatar__art" src={ichnosArt} alt="" width={size} height={size} draggable={false} />
      {busy && <span className="nyx-avatar__orbit" aria-hidden="true" />}
      {sparks && (
        <span className="nyx-avatar__sparks" aria-hidden="true">
          <i style={{ left: "6%", top: "22%", animationDelay: "0s" }} />
          <i style={{ left: "88%", top: "36%", animationDelay: ".7s" }} />
          <i style={{ left: "18%", top: "78%", animationDelay: "1.4s" }} />
          <i style={{ left: "76%", top: "82%", animationDelay: "2.1s" }} />
        </span>
      )}
    </span>
  );
}
