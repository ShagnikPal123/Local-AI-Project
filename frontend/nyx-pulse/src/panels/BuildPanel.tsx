/** Build — 3D design for parts, machines and circuits (panels/build/, design_studio.py).
 *
 * This file stays tiny on purpose. It used to be a placeholder that said
 * "Loading the studio…" forever; the studio itself is a separate chunk now, so
 * opening any other tab never pays for three.js or the boolean engine, and the
 * Build tab shows its layout the moment it is clicked.
 */

import { lazy, Suspense } from "react";

const BuildStudio = lazy(() => import("./build/BuildStudio"));

function StudioSkeleton() {
  return (
    <div className="bs-shell-skeleton" aria-busy="true" aria-label="Opening the Build studio">
      <div className="bs-shell-skeleton__bar" />
      <div className="bs-shell-skeleton__body">
        <div className="bs-shell-skeleton__rail" />
        <div className="bs-shell-skeleton__stage"><span>Opening the Build studio…</span></div>
        <div className="bs-shell-skeleton__side" />
      </div>
    </div>
  );
}

export function BuildPanel() {
  return (
    <Suspense fallback={<StudioSkeleton />}>
      <BuildStudio />
    </Suspense>
  );
}
