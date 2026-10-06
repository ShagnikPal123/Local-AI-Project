/** Feature tree → triangles, for the Build studio.
 *
 * Two paths, chosen per part:
 *
 * - **Exact** (almost everything): real three.js primitives, copies expanded
 *   from repeat / radial / mirror, and true mesh booleans (three-bvh-csg) for
 *   cuts and intersections. A 1.6 mm board with 2.8 mm holes comes out crisp,
 *   which a sampled field at any affordable resolution cannot do.
 * - **Smooth** (a part with a fillet blend or a shell): a signed distance field
 *   sampled on a grid sized to the part, polygonised with marching cubes. That
 *   is what makes a blend an actual fillet rather than a crease.
 *
 * Results are cached by the geometry fields of the part, so reopening the tab,
 * moving a piece or rewiring a net never re-meshes anything. Meshing is queued
 * and yields to the browser between parts, so the space paints immediately with
 * outline boxes that turn into real parts one by one - the studio never sits on
 * a blank "Loading" screen again.
 */

import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { edgeTable, triTable } from "three/examples/jsm/objects/MarchingCubes.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { ADDITION, Brush, Evaluator, INTERSECTION, SUBTRACTION } from "three-bvh-csg";
import type { Feature, Part, Placement, Vec3 } from "./types";

const DEG = Math.PI / 180;
const AXIS: Record<"x" | "y" | "z", number> = { x: 0, y: 1, z: 2 };

// --- where each copy of a feature sits ----------------------------------------------

function baseMatrix(feature: Feature): THREE.Matrix4 {
  const rotation = new THREE.Quaternion().setFromEuler(
    new THREE.Euler(feature.rot[0] * DEG, feature.rot[1] * DEG, feature.rot[2] * DEG, "XYZ"),
  );
  return new THREE.Matrix4().compose(new THREE.Vector3(...feature.at), rotation, new THREE.Vector3(1, 1, 1));
}

/** Every copy of a feature as a matrix. Shared with design_studio.part_bounds' rules:
 * repeat steps from `at`; a radial ring is centred on `at`; each mirror axis doubles the set. */
export function copyMatrices(feature: Feature): THREE.Matrix4[] {
  const base = baseMatrix(feature);
  let matrices: THREE.Matrix4[] = [base];

  if (feature.repeat && feature.repeat.count > 1) {
    const [sx, sy, sz] = feature.repeat.step;
    matrices = Array.from({ length: feature.repeat.count }, (_, n) =>
      new THREE.Matrix4().makeTranslation(sx * n, sy * n, sz * n).multiply(base));
  }

  if (feature.radial && feature.radial.count > 1) {
    const { count, axis, radius } = feature.radial;
    const centre = new THREE.Vector3(...feature.at);
    const out = new THREE.Vector3(axis === "x" ? 0 : radius, 0, axis === "x" ? radius : 0);
    const turnAxis = new THREE.Vector3(axis === "x" ? 1 : 0, axis === "y" ? 1 : 0, axis === "z" ? 1 : 0);
    const ring: THREE.Matrix4[] = [];
    for (const matrix of matrices) {
      const local = new THREE.Matrix4().makeTranslation(-centre.x, -centre.y, -centre.z).multiply(matrix);
      for (let k = 0; k < count; k++) {
        ring.push(
          new THREE.Matrix4().makeTranslation(centre.x, centre.y, centre.z)
            .multiply(new THREE.Matrix4().makeRotationAxis(turnAxis, (Math.PI * 2 * k) / count))
            .multiply(new THREE.Matrix4().makeTranslation(out.x, out.y, out.z))
            .multiply(local),
        );
      }
    }
    matrices = ring;
  }

  for (const axis of feature.mirror ?? []) {
    const scale = [1, 1, 1];
    scale[AXIS[axis]] = -1;
    const reflect = new THREE.Matrix4().makeScale(scale[0], scale[1], scale[2]);
    matrices = matrices.concat(matrices.map((m) => reflect.clone().multiply(m)));
  }
  return matrices;
}

// --- bounds (mirrors design_studio.part_bounds, used before any mesh exists) ---------

function localExtent(feature: Feature): Vec3 {
  const s = feature.size;
  switch (feature.type) {
    case "box":
    case "wedge":
      return [s.w / 2, s.h / 2, s.d / 2];
    case "cylinder":
    case "pipe":
      return [s.r, s.h / 2, s.r];
    case "sphere":
      return [s.r, s.r, s.r];
    case "cone": {
      const widest = Math.max(s.r, s.r2 ?? 0);
      return [widest, s.h / 2, widest];
    }
    case "torus":
      return [s.r + s.t, s.t, s.r + s.t];
    case "extrude": {
      const p = feature.profile ?? [[10, 10]];
      return [Math.max(...p.map(([x]) => Math.abs(x))), s.h / 2, Math.max(...p.map(([, z]) => Math.abs(z)))];
    }
    case "revolve": {
      const p = feature.profile ?? [[10, 10]];
      const reach = Math.max(...p.map(([r]) => Math.abs(r)));
      return [reach, Math.max(...p.map(([, y]) => Math.abs(y))), reach];
    }
  }
}

export function featureBox(feature: Feature, matrix: THREE.Matrix4): THREE.Box3 {
  const [hx, hy, hz] = localExtent(feature);
  const grow = (feature.blend || 0) * 0.25; // same rule as design_studio.part_bounds
  return new THREE.Box3(new THREE.Vector3(-hx - grow, -hy - grow, -hz - grow), new THREE.Vector3(hx + grow, hy + grow, hz + grow))
    .applyMatrix4(matrix);
}

export function partBox(part: Part): THREE.Box3 {
  const box = new THREE.Box3();
  for (const feature of part.features) {
    if (feature.op !== "add") continue;
    for (const matrix of copyMatrices(feature)) box.union(featureBox(feature, matrix));
  }
  if (box.isEmpty()) box.set(new THREE.Vector3(-5, -5, -5), new THREE.Vector3(5, 5, 5));
  return box;
}

export function placementMatrix(placement: Placement): THREE.Matrix4 {
  const rotation = new THREE.Quaternion().setFromEuler(
    new THREE.Euler(placement.rot[0] * DEG, placement.rot[1] * DEG, placement.rot[2] * DEG, "XYZ"),
  );
  const s = placement.scale || 1;
  return new THREE.Matrix4().compose(new THREE.Vector3(...placement.at), rotation, new THREE.Vector3(s, s, s));
}

// --- primitives ---------------------------------------------------------------------

/** Keep only what the booleans and the material need, as plain triangles. */
function tidy(geometry: THREE.BufferGeometry): THREE.BufferGeometry {
  const flat = geometry.index ? geometry.toNonIndexed() : geometry;
  for (const name of Object.keys(flat.attributes)) {
    if (name !== "position" && name !== "normal") flat.deleteAttribute(name);
  }
  if (!flat.getAttribute("normal")) flat.computeVertexNormals();
  return flat;
}

function flipWinding(geometry: THREE.BufferGeometry): void {
  for (const name of Object.keys(geometry.attributes)) {
    const attribute = geometry.getAttribute(name) as THREE.BufferAttribute;
    const size = attribute.itemSize;
    const array = attribute.array as Float32Array;
    for (let tri = 0; tri < attribute.count; tri += 3) {
      for (let c = 0; c < size; c++) {
        const a = (tri + 1) * size + c;
        const b = (tri + 2) * size + c;
        const keep = array[a];
        array[a] = array[b];
        array[b] = keep;
      }
    }
    attribute.needsUpdate = true;
  }
}

function signedVolume(geometry: THREE.BufferGeometry): number {
  const p = geometry.getAttribute("position");
  let volume = 0;
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  for (let i = 0; i < p.count; i += 3) {
    a.fromBufferAttribute(p, i);
    b.fromBufferAttribute(p, i + 1);
    c.fromBufferAttribute(p, i + 2);
    volume += a.dot(b.cross(c)) / 6;
  }
  return volume;
}

/** Hand-built and lathed shapes: make the triangles face out, then light them flat. */
function outward(geometry: THREE.BufferGeometry): THREE.BufferGeometry {
  const flat = tidy(geometry);
  if (signedVolume(flat) < 0) flipWinding(flat);
  flat.deleteAttribute("normal");
  flat.computeVertexNormals();
  return flat;
}

function wedge(w: number, d: number, h: number): THREE.BufferGeometry {
  // Full height along z = +d/2, down to nothing at z = -d/2 (the SDF uses the same slope).
  const A = [-w / 2, -h / 2, -d / 2], B = [w / 2, -h / 2, -d / 2], C = [w / 2, -h / 2, d / 2];
  const D = [-w / 2, -h / 2, d / 2], E = [-w / 2, h / 2, d / 2], F = [w / 2, h / 2, d / 2];
  const triangles = [A, B, C, A, C, D, D, C, F, D, F, E, A, F, B, A, E, F, A, D, E, B, F, C];
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(triangles.flat(), 3));
  return outward(geometry);
}

function lathe(profile: [number, number][], segments = 48): THREE.BufferGeometry {
  const points = profile.map(([r, y]) => new THREE.Vector2(Math.max(0, r), y));
  const first = points[0];
  const last = points[points.length - 1];
  if (first.distanceTo(last) > 1e-6) points.push(first.clone());
  return outward(new THREE.LatheGeometry(points, segments));
}

function roundedCylinderProfile(r: number, h: number, round: number): [number, number][] {
  const k = Math.min(round, r - 0.01, h / 2 - 0.01);
  const out: [number, number][] = [[0, -h / 2], [r - k, -h / 2]];
  for (let i = 1; i <= 6; i++) {
    const a = -Math.PI / 2 + (i / 6) * (Math.PI / 2);
    out.push([r - k + Math.cos(a) * k, -h / 2 + k + Math.sin(a) * k]);
  }
  for (let i = 1; i <= 6; i++) {
    const a = (i / 6) * (Math.PI / 2);
    out.push([r - k + Math.cos(a) * k, h / 2 - k + Math.sin(a) * k]);
  }
  out.push([0, h / 2]);
  return out;
}

function primitive(feature: Feature): THREE.BufferGeometry {
  const s = feature.size;
  const round = feature.round || 0;
  switch (feature.type) {
    case "box": {
      const radius = Math.min(round, Math.min(s.w, s.d, s.h) / 2 - 0.01);
      return tidy(radius > 0.05 ? new RoundedBoxGeometry(s.w, s.h, s.d, 2, radius) : new THREE.BoxGeometry(s.w, s.h, s.d));
    }
    case "cylinder":
      if (feature.sides && feature.sides >= 3) return tidy(new THREE.CylinderGeometry(s.r, s.r, s.h, feature.sides));
      if (round > 0.05) return lathe(roundedCylinderProfile(s.r, s.h, round));
      return tidy(new THREE.CylinderGeometry(s.r, s.r, s.h, 40));
    case "pipe": {
      const inner = Math.max(0.01, s.r - s.t);
      return lathe([[inner, -s.h / 2], [s.r, -s.h / 2], [s.r, s.h / 2], [inner, s.h / 2]], feature.sides && feature.sides >= 3 ? feature.sides : 48);
    }
    case "sphere":
      return tidy(new THREE.SphereGeometry(s.r, 32, 18));
    case "cone":
      return tidy(new THREE.CylinderGeometry(Math.max(0.01, s.r2 ?? 0), s.r, s.h, feature.sides && feature.sides >= 3 ? feature.sides : 40));
    case "torus":
      return tidy(new THREE.TorusGeometry(s.r, s.t, 14, 48).rotateX(Math.PI / 2));
    case "wedge":
      return wedge(s.w, s.d, s.h);
    case "extrude": {
      const shape = new THREE.Shape((feature.profile ?? []).map(([x, z]) => new THREE.Vector2(x, z)));
      const geometry = new THREE.ExtrudeGeometry(shape, { depth: s.h, bevelEnabled: false, curveSegments: 1 });
      geometry.translate(0, 0, -s.h / 2).rotateX(Math.PI / 2);
      return outward(geometry);
    }
    case "revolve":
      return lathe(feature.profile ?? [[0, 0], [10, 0], [10, 10]]);
  }
}

// --- the exact path -----------------------------------------------------------------

function paint(geometry: THREE.BufferGeometry, hex: string): THREE.BufferGeometry {
  const colour = new THREE.Color(hex);
  const count = geometry.getAttribute("position").count;
  const array = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    array[i * 3] = colour.r;
    array[i * 3 + 1] = colour.g;
    array[i * 3 + 2] = colour.b;
  }
  geometry.setAttribute("color", new THREE.BufferAttribute(array, 3));
  return geometry;
}

/** All copies of one feature as one geometry, in part space. */
export function featureGeometry(feature: Feature, colour: string): THREE.BufferGeometry {
  const shape = primitive(feature);
  const copies = copyMatrices(feature).map((matrix) => {
    const copy = shape.clone().applyMatrix4(matrix);
    if (matrix.determinant() < 0) flipWinding(copy);
    return copy;
  });
  const merged = copies.length === 1 ? copies[0] : mergeGeometries(copies, false);
  return paint(merged, colour);
}

let evaluator: Evaluator | null = null;

function boolean(a: THREE.BufferGeometry, b: THREE.BufferGeometry, op: typeof ADDITION): THREE.BufferGeometry {
  if (!evaluator) {
    evaluator = new Evaluator();
    evaluator.attributes = ["position", "normal", "color"];
    evaluator.useGroups = false;
  }
  const left = new Brush(a);
  const right = new Brush(b);
  left.updateMatrixWorld();
  right.updateMatrixWorld();
  return evaluator.evaluate(left, right, op).geometry;
}

function overlaps(a: THREE.BufferGeometry, b: THREE.BufferGeometry): boolean {
  if (!a.boundingBox) a.computeBoundingBox();
  if (!b.boundingBox) b.computeBoundingBox();
  return a.boundingBox!.intersectsBox(b.boundingBox!);
}

function darker(hex: string, amount = 0.72): string {
  return `#${new THREE.Color(hex).multiplyScalar(amount).getHexString()}`;
}

function exactMesh(part: Part): { geometry: THREE.BufferGeometry; approximate: boolean } {
  let result: THREE.BufferGeometry | null = null;
  let approximate = false;
  const cutColour = darker(part.color);

  part.features.forEach((feature, index) => {
    const geometry = featureGeometry(feature, feature.op === "add" ? feature.color || part.color : cutColour);
    if (!result) {
      result = geometry;
      return;
    }
    try {
      if (feature.op === "add") {
        // Union for real only when a later cut will need to know what is solid.
        // Overlapping triangle soup is invisible from outside, and far cheaper.
        const laterBoolean = part.features.slice(index + 1).some((f) => f.op !== "add");
        result = laterBoolean && overlaps(result, geometry)
          ? boolean(result, geometry, ADDITION)
          : mergeGeometries([result, geometry], false);
      } else if (feature.op === "cut") {
        if (overlaps(result, geometry)) result = boolean(result, geometry, SUBTRACTION);
      } else {
        result = overlaps(result, geometry) ? boolean(result, geometry, INTERSECTION) : new THREE.BufferGeometry();
      }
      result.boundingBox = null;
    } catch {
      // A degenerate shape can defeat the boolean. Keep drawing instead of
      // blanking the part, and say the view is approximate.
      approximate = true;
      if (feature.op === "add") result = mergeGeometries([result, geometry], false);
    }
  });
  const final = (result as THREE.BufferGeometry | null) ?? new THREE.BufferGeometry();
  return { geometry: final, approximate };
}

// --- the smooth path (signed distance field) ------------------------------------------

type Sdf = (x: number, y: number, z: number) => number;

function sdBox(x: number, y: number, z: number, hx: number, hy: number, hz: number): number {
  const qx = Math.abs(x) - hx, qy = Math.abs(y) - hy, qz = Math.abs(z) - hz;
  const ox = Math.max(qx, 0), oy = Math.max(qy, 0), oz = Math.max(qz, 0);
  return Math.sqrt(ox * ox + oy * oy + oz * oz) + Math.min(Math.max(qx, Math.max(qy, qz)), 0);
}

/** Signed distance to a closed 2D polygon (after Inigo Quilez). */
function sdPolygon(px: number, py: number, points: [number, number][]): number {
  let d = (px - points[0][0]) ** 2 + (py - points[0][1]) ** 2;
  let sign = 1;
  for (let i = 0, j = points.length - 1; i < points.length; j = i, i++) {
    const [ix, iy] = points[i];
    const [jx, jy] = points[j];
    const ex = jx - ix, ey = jy - iy;
    const wx = px - ix, wy = py - iy;
    const t = Math.max(0, Math.min(1, (wx * ex + wy * ey) / (ex * ex + ey * ey || 1)));
    const bx = wx - ex * t, by = wy - ey * t;
    d = Math.min(d, bx * bx + by * by);
    const c1 = py >= iy, c2 = py < jy, c3 = ex * wy > ey * wx;
    if ((c1 && c2 && c3) || (!c1 && !c2 && !c3)) sign = -sign;
  }
  return sign * Math.sqrt(d);
}

function extrudeDistance(d2: number, y: number, halfHeight: number): number {
  const wx = d2, wy = Math.abs(y) - halfHeight;
  return Math.min(Math.max(wx, wy), 0) + Math.hypot(Math.max(wx, 0), Math.max(wy, 0));
}

function primitiveSdf(feature: Feature): Sdf {
  const s = feature.size;
  const round = feature.round || 0;
  switch (feature.type) {
    case "box": {
      const r = Math.min(round, Math.min(s.w, s.d, s.h) / 2 - 0.01);
      return (x, y, z) => sdBox(x, y, z, s.w / 2 - Math.max(r, 0), s.h / 2 - Math.max(r, 0), s.d / 2 - Math.max(r, 0)) - Math.max(r, 0);
    }
    case "cylinder": {
      if (feature.sides && feature.sides >= 3) {
        const polygon = Array.from({ length: feature.sides }, (_, i): [number, number] => {
          const a = (i / feature.sides!) * Math.PI * 2;
          return [Math.sin(a) * s.r, Math.cos(a) * s.r];
        });
        return (x, y, z) => extrudeDistance(sdPolygon(x, z, polygon), y, s.h / 2);
      }
      return (x, y, z) => extrudeDistance(Math.hypot(x, z) - s.r, y, s.h / 2);
    }
    case "pipe": {
      const mid = s.r - s.t / 2;
      return (x, y, z) => extrudeDistance(Math.abs(Math.hypot(x, z) - mid) - s.t / 2, y, s.h / 2);
    }
    case "sphere":
      return (x, y, z) => Math.hypot(x, y, z) - s.r;
    case "cone": {
      const r1 = s.r, r2 = s.r2 ?? 0, hh = s.h / 2;
      return (x, y, z) => {
        // Capped cone, bottom radius r1 at -h/2, top r2 at +h/2.
        const qx = Math.hypot(x, z), qy = y;
        const k1x = r2, k1y = hh;
        const k2x = r2 - r1, k2y = 2 * hh;
        const cax = qx - Math.min(qx, qy < 0 ? r1 : r2), cay = Math.abs(qy) - hh;
        const t = Math.max(0, Math.min(1, ((k1x - qx) * k2x + (k1y - qy) * k2y) / (k2x * k2x + k2y * k2y)));
        const cbx = qx - k1x + k2x * t, cby = qy - k1y + k2y * t;
        const sign = cbx < 0 && cay < 0 ? -1 : 1;
        return sign * Math.sqrt(Math.min(cax * cax + cay * cay, cbx * cbx + cby * cby));
      };
    }
    case "torus":
      return (x, y, z) => Math.hypot(Math.hypot(x, z) - s.r, y) - s.t;
    case "wedge": {
      const length = Math.hypot(s.d, s.h) || 1;
      return (x, y, z) => Math.max(sdBox(x, y, z, s.w / 2, s.h / 2, s.d / 2), (s.d * y - s.h * z) / length);
    }
    case "extrude": {
      const outline = feature.profile ?? [];
      return (x, y, z) => extrudeDistance(sdPolygon(x, z, outline), y, s.h / 2);
    }
    case "revolve": {
      const outline = feature.profile ?? [];
      return (x, y, z) => sdPolygon(Math.hypot(x, z), y, outline);
    }
  }
}

interface SdfTerm { op: Feature["op"]; blend: number; colour: THREE.Color; copies: { inverse: THREE.Matrix4; box: THREE.Box3 }[]; sdf: Sdf }

function smoothUnion(a: number, b: number, k: number): number {
  if (k <= 0) return Math.min(a, b);
  const h = Math.max(0, Math.min(1, 0.5 + (0.5 * (b - a)) / k));
  return b + (a - b) * h - k * h * (1 - h);
}
function smoothCut(a: number, b: number, k: number): number {
  if (k <= 0) return Math.max(a, -b);
  const h = Math.max(0, Math.min(1, 0.5 - (0.5 * (a + b)) / k));
  return a + (-b - a) * h + k * h * (1 - h);
}
function smoothIntersect(a: number, b: number, k: number): number {
  if (k <= 0) return Math.max(a, b);
  const h = Math.max(0, Math.min(1, 0.5 - (0.5 * (b - a)) / k));
  return b + (a - b) * h + k * h * (1 - h);
}

function boxDistance(box: THREE.Box3, x: number, y: number, z: number): number {
  const dx = Math.max(box.min.x - x, 0, x - box.max.x);
  const dy = Math.max(box.min.y - y, 0, y - box.max.y);
  const dz = Math.max(box.min.z - z, 0, z - box.max.z);
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

const nextFrame = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

async function smoothMesh(part: Part, isCancelled: () => boolean): Promise<THREE.BufferGeometry> {
  const terms: SdfTerm[] = part.features.map((feature) => ({
    op: feature.op,
    blend: feature.blend || 0,
    colour: new THREE.Color(feature.color || part.color),
    sdf: primitiveSdf(feature),
    copies: copyMatrices(feature).map((matrix) => ({ inverse: matrix.clone().invert(), box: featureBox(feature, matrix) })),
  }));
  const shell = part.shell?.thickness ?? 0;

  const bounds = partBox(part);
  const size = bounds.getSize(new THREE.Vector3());
  const longest = Math.max(size.x, size.y, size.z, 1);
  let cell = Math.max(0.2, longest / 80);
  const budget = 420_000;
  while (((size.x / cell + 4) * (size.y / cell + 4) * (size.z / cell + 4)) > budget) cell *= 1.12;
  const nx = Math.ceil(size.x / cell) + 4, ny = Math.ceil(size.y / cell) + 4, nz = Math.ceil(size.z / cell) + 4;
  const ox = bounds.min.x - cell * 2, oy = bounds.min.y - cell * 2, oz = bounds.min.z - cell * 2;

  const field = new Float32Array(nx * ny * nz);
  const owner = new Uint8Array(nx * ny * nz);
  const local = new THREE.Vector3();

  for (let k = 0; k < nz; k++) {
    if (k % 6 === 0) {
      await nextFrame();
      if (isCancelled()) return new THREE.BufferGeometry();
    }
    const z = oz + k * cell;
    for (let j = 0; j < ny; j++) {
      const y = oy + j * cell;
      for (let i = 0; i < nx; i++) {
        const x = ox + i * cell;
        let d = Infinity;
        let who = 0;
        for (let t = 0; t < terms.length; t++) {
          const term = terms[t];
          let nearest = Infinity;
          for (const copy of term.copies) {
            const reach = boxDistance(copy.box, x, y, z);
            // A copy this far away cannot change the result; skip the exact call.
            if (term.op === "add" && reach > nearest) continue;
            if (term.op === "cut" && reach > term.blend + Math.max(0, -d) + cell) continue;
            local.set(x, y, z).applyMatrix4(copy.inverse);
            nearest = Math.min(nearest, term.sdf(local.x, local.y, local.z));
          }
          if (t === 0 || d === Infinity) {
            if (term.op === "add") { d = nearest; who = t; }
            continue;
          }
          if (nearest === Infinity) {
            if (term.op === "intersect") d = Math.max(d, cell * 4);
            continue;
          }
          if (term.op === "add") {
            if (nearest < d) who = t;
            d = smoothUnion(d, nearest, term.blend);
          } else if (term.op === "cut") {
            d = smoothCut(d, nearest, term.blend);
          } else {
            d = smoothIntersect(d, nearest, term.blend);
          }
        }
        if (shell > 0 && d !== Infinity) d = Math.max(d, -(d + shell));
        const index = i + nx * (j + ny * k);
        field[index] = d === Infinity ? cell * 4 : d;
        owner[index] = who;
      }
    }
  }
  return polygonise(field, owner, terms.map((t) => t.colour), nx, ny, nz, cell, ox, oy, oz);
}

/** Marching cubes on a box-shaped grid, using three's tables (Bourke corner order). */
function polygonise(field: Float32Array, owner: Uint8Array, colours: THREE.Color[], nx: number, ny: number, nz: number,
  cell: number, ox: number, oy: number, oz: number): THREE.BufferGeometry {
  const positions: number[] = [];
  const normals: number[] = [];
  const colourData: number[] = [];
  const at = (i: number, j: number, k: number) => field[i + nx * (j + ny * k)];
  const corners = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]];
  const edges = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
  const vertex = new Float32Array(12 * 3);
  const normal = new Float32Array(12 * 3);
  const colour = new Float32Array(12 * 3);
  const values = new Float32Array(8);

  const gradient = (i: number, j: number, k: number, out: number[]) => {
    const ci = Math.max(1, Math.min(nx - 2, i)), cj = Math.max(1, Math.min(ny - 2, j)), ck = Math.max(1, Math.min(nz - 2, k));
    out[0] = at(ci + 1, cj, ck) - at(ci - 1, cj, ck);
    out[1] = at(ci, cj + 1, ck) - at(ci, cj - 1, ck);
    out[2] = at(ci, cj, ck + 1) - at(ci, cj, ck - 1);
  };
  const ga = [0, 0, 0], gb = [0, 0, 0];

  for (let k = 0; k < nz - 1; k++) {
    for (let j = 0; j < ny - 1; j++) {
      for (let i = 0; i < nx - 1; i++) {
        let cube = 0;
        for (let c = 0; c < 8; c++) {
          values[c] = at(i + corners[c][0], j + corners[c][1], k + corners[c][2]);
          if (values[c] > 0) cube |= 1 << c; // bit set = outside, as three's metaballs do
        }
        const mask = edgeTable[cube];
        if (!mask) continue;
        for (let e = 0; e < 12; e++) {
          if (!(mask & (1 << e))) continue;
          const [a, b] = edges[e];
          const va = values[a], vb = values[b];
          const t = Math.abs(va - vb) < 1e-9 ? 0.5 : va / (va - vb);
          const [ax, ay, az] = corners[a];
          const [bx, by, bz] = corners[b];
          vertex[e * 3] = ox + (i + ax + (bx - ax) * t) * cell;
          vertex[e * 3 + 1] = oy + (j + ay + (by - ay) * t) * cell;
          vertex[e * 3 + 2] = oz + (k + az + (bz - az) * t) * cell;
          gradient(i + ax, j + ay, k + az, ga);
          gradient(i + bx, j + by, k + bz, gb);
          const nxv = ga[0] + (gb[0] - ga[0]) * t, nyv = ga[1] + (gb[1] - ga[1]) * t, nzv = ga[2] + (gb[2] - ga[2]) * t;
          const length = Math.hypot(nxv, nyv, nzv) || 1;
          normal[e * 3] = nxv / length;
          normal[e * 3 + 1] = nyv / length;
          normal[e * 3 + 2] = nzv / length;
          const pick = colours[owner[(i + (t < 0.5 ? ax : bx)) + nx * ((j + (t < 0.5 ? ay : by)) + ny * (k + (t < 0.5 ? az : bz)))]] ?? colours[0];
          colour[e * 3] = pick.r;
          colour[e * 3 + 1] = pick.g;
          colour[e * 3 + 2] = pick.b;
        }
        const row = cube << 4;
        for (let n = 0; triTable[row + n] !== -1; n += 3) {
          for (const e of [triTable[row + n], triTable[row + n + 1], triTable[row + n + 2]]) {
            positions.push(vertex[e * 3], vertex[e * 3 + 1], vertex[e * 3 + 2]);
            normals.push(normal[e * 3], normal[e * 3 + 1], normal[e * 3 + 2]);
            colourData.push(colour[e * 3], colour[e * 3 + 1], colour[e * 3 + 2]);
          }
        }
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colourData, 3));
  if (positions.length && signedVolume(geometry) < 0) flipWinding(geometry);
  return geometry;
}

// --- cache and queue ------------------------------------------------------------------

export interface MeshResult { geometry: THREE.BufferGeometry; approximate: boolean; smooth: boolean; ms: number }

/** Only the fields that change the shape. Renaming a part never re-meshes it. */
export function geometryKey(part: Part): string {
  return JSON.stringify([part.color, part.shell ?? null, part.features.map((f) => [
    f.type, f.op, f.at, f.rot, f.size, f.round, f.blend, f.sides ?? 0, f.profile ?? 0, f.repeat ?? 0, f.radial ?? 0, f.mirror ?? 0, f.color ?? "",
  ])]);
}

export function needsSmoothPath(part: Part): boolean {
  return Boolean(part.shell?.thickness) || part.features.some((f, i) => i > 0 && (f.blend || 0) > 0);
}

const cache = new Map<string, MeshResult>();
const pending = new Map<string, Promise<MeshResult>>();

export function cachedMesh(part: Part): MeshResult | null {
  return cache.get(geometryKey(part)) ?? null;
}

let chain: Promise<unknown> = Promise.resolve();

/** Mesh a part, one at a time, yielding between parts so the page stays responsive. */
export function meshPart(part: Part): Promise<MeshResult> {
  const key = geometryKey(part);
  const hit = cache.get(key);
  if (hit) return Promise.resolve(hit);
  const running = pending.get(key);
  if (running) return running;

  const job = chain.then(async () => {
    await nextFrame();
    const started = performance.now();
    let result: MeshResult;
    try {
      if (needsSmoothPath(part)) {
        const geometry = await smoothMesh(part, () => false);
        result = { geometry, approximate: false, smooth: true, ms: performance.now() - started };
      } else {
        const { geometry, approximate } = exactMesh(part);
        result = { geometry, approximate, smooth: false, ms: performance.now() - started };
      }
    } catch {
      const box = partBox(part);
      const size = box.getSize(new THREE.Vector3());
      const centre = box.getCenter(new THREE.Vector3());
      const geometry = paint(tidy(new THREE.BoxGeometry(size.x, size.y, size.z).translate(centre.x, centre.y, centre.z)), part.color);
      result = { geometry, approximate: true, smooth: false, ms: performance.now() - started };
    }
    result.geometry.computeBoundingBox();
    result.geometry.computeBoundingSphere();
    cache.set(key, result);
    pending.delete(key);
    // A long session edits many versions of a part; keep the cache bounded.
    if (cache.size > 160) cache.delete(cache.keys().next().value as string);
    return result;
  });
  chain = job.catch(() => undefined);
  pending.set(key, job);
  return job;
}

/** One feature by itself, for highlighting it inside the part editor. */
export function featurePreview(feature: Feature, colour: string): THREE.BufferGeometry {
  try {
    return featureGeometry(feature, colour);
  } catch {
    const box = featureBox(feature, baseMatrix(feature));
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    return paint(tidy(new THREE.BoxGeometry(size.x, size.y, size.z).translate(centre.x, centre.y, centre.z)), colour);
  }
}

// --- combining several placed parts into one part --------------------------------------

/** Bake several placed parts into one new part spec.
 *
 * Modifiers are expanded into plain copies first: a mirror is defined across
 * its own part's origin, and that plane means nothing once the part has been
 * moved and turned. Mirrored copies get their reflection folded into a local X
 * flip, which every primitive here is symmetric under (an extruded outline has
 * its points flipped to match), so the result is exact.
 */
export function combineParts(parts: Part[], placements: Placement[], name: string): { spec: Partial<Part>; centre: Vec3; featureCount: number } {
  const byId = new Map(parts.map((p) => [p.id, p]));
  const centre = new THREE.Vector3();
  placements.forEach((pl) => centre.add(new THREE.Vector3(...pl.at)));
  centre.divideScalar(Math.max(1, placements.length));

  const features: Partial<Feature>[] = [];
  const pins: Part["pins"] = [];
  const specs: Record<string, number | string | boolean> = {};
  let electronic = false;

  for (const placement of placements) {
    const part = byId.get(placement.part_id);
    if (!part) continue;
    electronic ||= part.kind === "electronic";
    const world = new THREE.Matrix4().makeTranslation(-centre.x, -centre.y, -centre.z).multiply(placementMatrix(placement));
    const label = placement.name || part.name;

    for (const feature of part.features) {
      copyMatrices(feature).forEach((copy, index) => {
        let matrix = world.clone().multiply(copy);
        let profile = feature.profile;
        if (matrix.determinant() < 0) {
          matrix = matrix.multiply(new THREE.Matrix4().makeScale(-1, 1, 1));
          if (profile) profile = profile.map(([x, z]) => [-x, z] as [number, number]).reverse();
        }
        const position = new THREE.Vector3();
        const rotation = new THREE.Quaternion();
        const scale = new THREE.Vector3();
        matrix.decompose(position, rotation, scale);
        const s = Math.abs(scale.x) || 1;
        const euler = new THREE.Euler().setFromQuaternion(rotation, "XYZ");
        const size = Object.fromEntries(Object.entries(feature.size).map(([key, value]) => [key, key === "angle" ? value : value * s]));
        features.push({
          type: feature.type,
          name: `${label} · ${feature.name}${index ? ` ${index + 1}` : ""}`,
          op: feature.op,
          at: [position.x, position.y, position.z],
          rot: [euler.x / DEG, euler.y / DEG, euler.z / DEG],
          size,
          round: (feature.round || 0) * s,
          blend: (feature.blend || 0) * s,
          note: feature.note,
          color: feature.color || part.color,
          ...(feature.sides ? { sides: feature.sides } : {}),
          ...(profile ? { profile: profile.map(([a, b]) => [a * s, b * s] as [number, number]) } : {}),
        });
      });
    }

    for (const pin of part.pins) {
      const at = new THREE.Vector3(...pin.at).applyMatrix4(world);
      pins.push({ ...pin, id: `${placement.id.slice(-4)}${pin.id}`.slice(0, 32), name: `${label.slice(0, 16)} ${pin.name}`.slice(0, 40), at: [at.x, at.y, at.z] });
    }
    for (const key of ["price_usd", "draw_ma", "supply_ma"]) {
      const value = Number(part.specs?.[key] ?? 0);
      if (value) specs[key] = Number(specs[key] ?? 0) + value;
    }
  }

  // Part by part, in placement order: a later part's solid is never erased by an
  // earlier part's holes. (An earlier part can still be cut where a later part's
  // hole passes through it - which is usually the point of combining them.)

  return {
    spec: {
      name: name || "Combined part",
      kind: electronic ? "electronic" : "mechanical",
      color: byId.get(placements[0]?.part_id ?? "")?.color ?? "#9aa4b2",
      summary: `Made by combining ${placements.map((p) => p.name || byId.get(p.part_id)?.name).filter(Boolean).join(", ")}.`,
      features: features as Feature[],
      pins,
      specs,
      source: "owner",
    },
    centre: [centre.x, centre.y, centre.z],
    featureCount: features.length,
  };
}
