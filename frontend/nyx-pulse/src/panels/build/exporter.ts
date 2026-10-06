/** STL files for 3D-print apps (Cura, PrusaSlicer, Bambu Studio, OrcaSlicer all open them).
 *
 * Loaded only when someone presses Download, so the exporter never weighs on
 * the tab's first paint. The file is made from the same mesh the viewport shows,
 * in millimetres, which is the unit every slicer assumes for STL.
 */

import * as THREE from "three";
import { STLExporter } from "three/examples/jsm/exporters/STLExporter.js";
import { meshPart, placementMatrix } from "./geometry";
import type { Part, Placement } from "./types";

function save(data: DataView | ArrayBuffer | string, name: string): void {
  const blob = new Blob([data as BlobPart], { type: "model/stl" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

const safe = (name: string) => name.replace(/[^\w.-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "part";

/** STL is Z-up by convention and three.js is Y-up: turn it so it lands flat on the slicer's bed. */
const Y_UP_TO_Z_UP = new THREE.Matrix4().makeRotationX(Math.PI / 2);

export async function downloadPartStl(part: Part): Promise<void> {
  const { geometry } = await meshPart(part);
  const mesh = new THREE.Mesh(geometry.clone().applyMatrix4(Y_UP_TO_Z_UP));
  const box = new THREE.Box3().setFromObject(mesh);
  mesh.geometry.translate(0, 0, -box.min.z); // sit on z = 0
  const data = new STLExporter().parse(mesh, { binary: true });
  save(data, `${safe(part.name)}.stl`);
}

export async function downloadAssemblyStl(name: string, parts: Part[], placements: Placement[]): Promise<void> {
  const byId = new Map(parts.map((p) => [p.id, p]));
  const scene = new THREE.Group();
  for (const placement of placements) {
    const part = byId.get(placement.part_id);
    if (!part) continue;
    const { geometry } = await meshPart(part);
    const copy = geometry.clone().applyMatrix4(placementMatrix(placement)).applyMatrix4(Y_UP_TO_Z_UP);
    scene.add(new THREE.Mesh(copy));
  }
  scene.updateMatrixWorld(true);
  const data = new STLExporter().parse(scene, { binary: true });
  save(data, `${safe(name)}-assembly.stl`);
}
