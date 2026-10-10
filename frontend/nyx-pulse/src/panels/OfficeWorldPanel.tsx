/** Office & World, one tab (owner, 2026-10-10: "Merge Office Space and world"). A world is an office grown into a
 * planet, so they were always one place; the court sits beside them because offices and worlds can call it. */

import { lazy } from "react";
import { HubPanel } from "../components/HubPanel";

const OfficePanel = lazy(() => import("./office/OfficePanel").then((m) => ({ default: m.OfficePanel })));
const WorldPanel = lazy(() => import("./world/WorldPanel").then((m) => ({ default: m.WorldPanel })));
const CourtWindow = lazy(() => import("../components/court/CourtWindow").then((m) => ({ default: m.CourtWindow })));

export function OfficeWorldPanel() {
  return (
    <HubPanel id="office" title="Office & World" sections={[
      { id: "office", label: "Offices", purpose: "Teams of agents that take a job and deliver it — you watch them work.", render: () => <OfficePanel /> },
      { id: "world", label: "Worlds", purpose: "An office grown into a planet that develops as its agents deliver.", render: () => <WorldPanel /> },
      { id: "court", label: "Court", purpose: "Disagreements argued before three judges — from you, an office or a world.", render: () => <CourtWindow /> },
    ]} />
  );
}
