/** A page that is not finished yet says so up front (owner, 2026-10-10: "Give collab as work in progress since the
 * page is not up and running yet and also add admin access as a work in progress as we need this to ensure safety"). */

import type { ReactNode } from "react";

export function WorkInProgress({ title, why, children }: { title: string; why: string; children: ReactNode }) {
  return (
    <div className="wip">
      <div className="wip__banner" role="note">
        <span className="wip__badge">Work in progress</span>
        <div>
          <b>{title} is not finished yet.</b>
          <p>{why}</p>
        </div>
      </div>
      <div className="wip__body">{children}</div>
    </div>
  );
}
