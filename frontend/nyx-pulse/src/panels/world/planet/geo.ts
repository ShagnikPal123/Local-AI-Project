/** Where things are on the planet: sectors by latitude/longitude, buildings on plots around each sector's centre,
 * figures walking along the surface, and arcs between places. Pure math, no scene. */

import * as THREE from "three";

/** The planet's radius in scene units. A floor is FLOOR_HEIGHT tall; a person is about one floor. */
export const R = 10;
export const FLOOR_HEIGHT = 0.085;
/** Distance between neighbouring plots, along the surface. */
export const PLOT_SPACING = 0.56;

const UP = new THREE.Vector3(0, 1, 0);

export function latLonToVec(lat: number, lon: number, radius = R): THREE.Vector3 {
  const phi = THREE.MathUtils.degToRad(90 - lat);
  const theta = THREE.MathUtils.degToRad(lon + 180);
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  );
}

/** East and north on the surface at ``normal`` (unit). Stable everywhere except exactly at the poles. */
export function tangentFrame(normal: THREE.Vector3): { east: THREE.Vector3; north: THREE.Vector3 } {
  const helper = Math.abs(normal.y) > 0.98 ? new THREE.Vector3(1, 0, 0) : UP;
  const east = new THREE.Vector3().crossVectors(helper, normal).normalize();
  const north = new THREE.Vector3().crossVectors(normal, east).normalize();
  return { east, north };
}

/** Plot 0 is the centre; then hexagonal rings of 6, 12, 18 … plots. Returns (x, y) in plot-spacing units. */
export function plotOffset(plot: number): [number, number] {
  if (plot <= 0) return [0, 0];
  let ring = 1;
  let first = 1;
  while (plot >= first + 6 * ring) {
    first += 6 * ring;
    ring += 1;
  }
  const index = plot - first;
  const angle = (index / (6 * ring)) * Math.PI * 2 + ring * 0.37;
  return [Math.cos(angle) * ring, Math.sin(angle) * ring];
}

/** A point on the surface, ``dx``/``dy`` surface units east/north of ``centre`` (a surface point). */
export function offsetOnSurface(centre: THREE.Vector3, dx: number, dy: number, radius = R): THREE.Vector3 {
  const normal = centre.clone().normalize();
  const { east, north } = tangentFrame(normal);
  return normal.multiplyScalar(radius).addScaledVector(east, dx).addScaledVector(north, dy).normalize().multiplyScalar(radius);
}

export function plotPosition(lat: number, lon: number, plot: number, radius = R): THREE.Vector3 {
  const [x, y] = plotOffset(plot);
  return offsetOnSurface(latLonToVec(lat, lon, radius), x * PLOT_SPACING, y * PLOT_SPACING, radius);
}

/** How far a sector's plots reach, for its territory disc. */
export function sectorReach(plots: number): number {
  let ring = 0;
  let count = 1;
  while (count < plots) {
    ring += 1;
    count += 6 * ring;
  }
  return (ring + 0.8) * PLOT_SPACING;
}

/** The rotation that stands something up on the surface at ``point``. */
export function standUp(point: THREE.Vector3): THREE.Quaternion {
  return new THREE.Quaternion().setFromUnitVectors(UP, point.clone().normalize());
}

/** Along the surface from a to b (both on the sphere), at t ∈ [0, 1]. */
export function slerpSurface(a: THREE.Vector3, b: THREE.Vector3, t: number, out = new THREE.Vector3()): THREE.Vector3 {
  const ua = a.clone().normalize();
  const ub = b.clone().normalize();
  const dot = THREE.MathUtils.clamp(ua.dot(ub), -1, 1);
  const omega = Math.acos(dot);
  if (omega < 1e-5) return out.copy(b);
  const sin = Math.sin(omega);
  const wa = Math.sin((1 - t) * omega) / sin;
  const wb = Math.sin(t * omega) / sin;
  const length = THREE.MathUtils.lerp(a.length(), b.length(), t);
  return out.copy(ua.multiplyScalar(wa).add(ub.multiplyScalar(wb))).normalize().multiplyScalar(length);
}

/** An arc above the surface between two places — talk lines, contests. ``rise`` is how much higher a longer arc
 * flies: a little, so even a line to the far side of the planet stays close to the ground. */
export function arcPoints(a: THREE.Vector3, b: THREE.Vector3, lift: number, segments = 48, rise = 0.06): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];
  const distance = a.distanceTo(b);
  for (let i = 0; i <= segments; i += 1) {
    const t = i / segments;
    const p = slerpSurface(a, b, t);
    const height = Math.sin(Math.PI * t) * (lift + distance * rise);
    points.push(p.normalize().multiplyScalar(R + 0.02 + height));
  }
  return points;
}

/** A stable small number from a string — colours and jitter that never change between reloads. */
export function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}
