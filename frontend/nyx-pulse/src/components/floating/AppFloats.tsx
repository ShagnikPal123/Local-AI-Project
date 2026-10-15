/** The floating panels that look after their own data (connectors, remote access), on whichever tab they were sent to.
 * Mounted once by App; the chat's own bars float from the chat (ChatPanel). */

import { ConnectorsBody, RemoteBody, useConnectors, usePhone } from "../chat/compact/BarChips";
import { FloatingCard, listenForTabDrops, useFloats } from "./FloatingPanels";

listenForTabDrops();

function Connectors() { return <ConnectorsBody list={useConnectors()} />; }
function Remote() { return <RemoteBody phone={usePhone()} />; }

export function AppFloats({ active }: { active: string }) {
  const floats = useFloats();
  const c = floats.connectors, r = floats.remote;
  return (
    <>
      {c && c.tab === active && <FloatingCard id="connectors" label="Connectors" spot={c}><Connectors /></FloatingCard>}
      {r && r.tab === active && <FloatingCard id="remote" label="Remote access" spot={r}><Remote /></FloatingCard>}
    </>
  );
}
