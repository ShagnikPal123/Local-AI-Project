/** The row above the composer that enabled mods draw: their banners and status chips (mods.py). */

import { useMods } from "../../state/modsStore";
import "../mods.css";

export function ModBand() {
  const { view } = useMods();
  if (!view.banners.length && !view.statuses.length) return null;
  return (
    <div className="mod-band" aria-label="From your mods">
      {view.banners.map((banner, index) => (
        <div key={`${banner.mod}-${index}`} className={`mod-band__banner mod-band__banner--${banner.tone}`} title={`From the mod “${banner.name}”`}>
          {banner.text}
        </div>
      ))}
      {view.statuses.length > 0 && (
        <div className="mod-band__chips">
          {view.statuses.map((status, index) => (
            <span key={`${status.mod}-${index}`} className="chip mod-band__chip" title={`From the mod “${status.name}”`}>
              {status.text}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
