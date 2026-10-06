/** A connector's tile mark: its short glyph in the brand's own colour on a dark rounded square.
 *
 * The owner's reference photo showed brand logos. Nyx ships no third-party artwork, so each app gets its colour and
 * a one- or two-letter mark from the catalogue instead — recognisable at a glance, and nothing to license.
 */

import type { CSSProperties } from "react";
import type { Connector } from "./types";

export function Mark({ connector, size = "md" }: { connector: Pick<Connector, "mark" | "color" | "name">; size?: "md" | "lg" }) {
  const mark = connector.mark || connector.name.slice(0, 1);
  const style = { "--brand": connector.color || "var(--color-accent)" } as CSSProperties;
  return (
    <span className={`cx-mark cx-mark--${size}${mark.length > 2 ? " is-wide" : ""}`} style={style} aria-hidden="true">
      {mark}
    </span>
  );
}
