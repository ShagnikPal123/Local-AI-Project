/** The planet itself: seeded terrain — continents, seas, mountains, ice — coloured by its type (world/planet.py) and
 * by the era, with the land flattened where the sectors and the government's district stand, so a city never sits
 * on a cliff or under the sea. Also the clouds, the air, rings and moons. Made once per scene; the terrain is
 * repainted when a sector is founded or the era changes ("The world starts from nothing … the world itself grows").
 *
 * The owner (2026-10-10): "randomize how the planet actually looks and add a lot more size". */

import * as THREE from "three";
import type { WorldPlanet } from "../types";
import { R } from "./geo";

// --- seeded noise ------------------------------------------------------------------------------------------------

/** Improved Perlin noise in 3D with a seeded permutation, so the same world always has the same continents. */
class Perlin {
  private p = new Uint8Array(512);

  constructor(seed: number) {
    const perm = Array.from({ length: 256 }, (_, i) => i);
    let s = (seed >>> 0) || 1;
    const rand = () => {
      s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
      return s / 4294967296;
    };
    for (let i = 255; i > 0; i -= 1) {
      const j = Math.floor(rand() * (i + 1));
      [perm[i], perm[j]] = [perm[j], perm[i]];
    }
    for (let i = 0; i < 512; i += 1) this.p[i] = perm[i & 255];
  }

  noise(x: number, y: number, z: number): number {
    const p = this.p;
    const X = Math.floor(x) & 255;
    const Y = Math.floor(y) & 255;
    const Z = Math.floor(z) & 255;
    x -= Math.floor(x);
    y -= Math.floor(y);
    z -= Math.floor(z);
    const u = fade(x);
    const v = fade(y);
    const w = fade(z);
    const A = p[X] + Y;
    const AA = p[A] + Z;
    const AB = p[A + 1] + Z;
    const B = p[X + 1] + Y;
    const BA = p[B] + Z;
    const BB = p[B + 1] + Z;
    return lerp(w,
      lerp(v, lerp(u, grad(p[AA], x, y, z), grad(p[BA], x - 1, y, z)),
        lerp(u, grad(p[AB], x, y - 1, z), grad(p[BB], x - 1, y - 1, z))),
      lerp(v, lerp(u, grad(p[AA + 1], x, y, z - 1), grad(p[BA + 1], x - 1, y, z - 1)),
        lerp(u, grad(p[AB + 1], x, y - 1, z - 1), grad(p[BB + 1], x - 1, y - 1, z - 1))));
  }

  fbm(x: number, y: number, z: number, octaves: number): number {
    let total = 0;
    let amplitude = 1;
    let frequency = 1;
    let norm = 0;
    for (let i = 0; i < octaves; i += 1) {
      total += amplitude * this.noise(x * frequency, y * frequency, z * frequency);
      norm += amplitude;
      amplitude *= 0.5;
      frequency *= 2.03;
    }
    return total / norm;
  }
}

const fade = (t: number) => t * t * t * (t * (t * 6 - 15) + 10);
const lerp = (t: number, a: number, b: number) => a + t * (b - a);
function grad(hash: number, x: number, y: number, z: number): number {
  const h = hash & 15;
  const u = h < 8 ? x : y;
  const v = h < 4 ? y : h === 12 || h === 14 ? x : z;
  return ((h & 1) === 0 ? u : -u) + ((h & 2) === 0 ? v : -v);
}
const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

// --- the terrain ---------------------------------------------------------------------------------------------------

/** A place the land is flattened for: a sector or the government's district. ``reach`` is in surface units. */
export interface Site {
  dir: THREE.Vector3;
  reach: number;
}

export interface Sample {
  /** Elevation before the sea: about -1..1. */
  e: number;
  ridge: number;
  /** Height above the base radius, in scene units (negative under the sea). */
  h: number;
  /** How much a site flattened this point, 0..1. */
  w: number;
}

const DEFAULT_PLANET: WorldPlanet = {
  type: "terran", label: "Terran world", about: "", radius: 1, land: ["#4f7a43", "#7a6a4f", "#e8ecef"],
  sea: ["#0f2a4a", "#1f5f8f"], sea_level: 0.02, mountains: 0.8, ice: 0.86, air: "#8fb4ff", clouds: 0.55, greens: true,
  lava: false, rings: false, ring_color: "#d8c8a8", ring_tilt: 0.3, moons: [], noise: 7, day_hours: 24, tilt: 0,
};

/** Sea level sits this far under the base radius; flattened land is at the base radius. */
export const WATER_DEPTH = 0.03;
const LAND_RELIEF = 0.55;
const SEA_RELIEF = 0.4;

export class Terrain {
  readonly planet: WorldPlanet;
  private noise: Perlin;
  private sites: Site[] = [];

  constructor(planet: WorldPlanet | null | undefined) {
    this.planet = planet && planet.land?.length === 3 ? planet : DEFAULT_PLANET;
    this.noise = new Perlin(this.planet.noise || 7);
  }

  setSites(sites: Site[]): void {
    this.sites = sites;
  }

  sample(dir: THREE.Vector3): Sample {
    const n = this.noise;
    const x = dir.x;
    const y = dir.y;
    const z = dir.z;
    const continents = n.fbm(x * 0.9 + 11.3, y * 0.9 - 4.1, z * 0.9 + 2.7, 3);
    const detail = n.fbm(x * 2.4, y * 2.4, z * 2.4, 6);
    const e = continents * 1.25 + detail * 0.55;
    const ridgeRaw = 1 - Math.abs(n.noise(x * 4.1 + 3.3, y * 4.1, z * 4.1 - 7.7));
    const ridge = ridgeRaw * ridgeRaw * ridgeRaw;
    const s = this.planet.sea_level;
    let h: number;
    if (e > s) {
      const rise = e - s;
      h = rise * LAND_RELIEF * this.planet.mountains + ridge * 0.42 * this.planet.mountains * smooth(0.02, 0.3, rise);
    } else {
      h = Math.max(-0.4, (e - s) * SEA_RELIEF * 1.4) - WATER_DEPTH;
    }
    let w = 0;
    for (const site of this.sites) {
      const dot = site.dir.x * x + site.dir.y * y + site.dir.z * z;
      const distance = Math.acos(Math.min(1, Math.max(-1, dot))) * R;
      const margin = 0.9 + site.reach * 0.35;
      if (distance < site.reach + margin) w = Math.max(w, 1 - smooth(site.reach, site.reach + margin, distance));
    }
    if (w > 0) h = h * (1 - w);
    return { e, ridge, h, w };
  }

  height(dir: THREE.Vector3): number {
    return this.sample(dir).h;
  }

  /** The colour of the ground at ``dir``. ``era`` greens a living world and paves its cities. */
  color(dir: THREE.Vector3, sample: Sample, era: number, out: THREE.Color): THREE.Color {
    const planet = this.planet;
    const s = planet.sea_level;
    const rise = sample.e - s;
    const tmp = TMP_A;
    if (sample.h < -WATER_DEPTH * 0.5 && sample.w < 0.5) {
      // The sea floor, seen through the water: darker with depth.
      out.set(planet.sea[1]).lerp(tmp.set(planet.sea[0]), smooth(-0.02, -0.25, rise)).multiplyScalar(0.7);
      return out;
    }
    const moisture = this.noise.fbm(dir.x * 1.7 + 40, dir.y * 1.7, dir.z * 1.7, 3);
    out.set(planet.land[0]).lerp(tmp.set(planet.land[1]), Math.min(1, smooth(0.05, 0.45, rise) + moisture * 0.35));
    if (rise < 0.025 && !planet.lava) out.lerp(tmp.set("#cdbb8f"), 0.55);
    const peak = rise * planet.mountains + sample.ridge * 0.5 * planet.mountains;
    if (peak > 0.55) out.lerp(tmp.set(planet.land[2]), smooth(0.55, 0.85, peak));
    if (planet.greens) {
      // First Light is bare rock; life spreads with the eras.
      out.lerp(tmp.set("#7a6e60"), (1 - Math.min(1, era / 3)) * 0.65);
    }
    const iceLine = planet.ice + this.noise.noise(dir.x * 5, dir.y * 5, dir.z * 5) * 0.05;
    if (Math.abs(dir.y) > iceLine) out.lerp(tmp.set("#e8eef4"), smooth(iceLine, iceLine + 0.03, Math.abs(dir.y)));
    if (sample.w > 0) {
      const ground = era >= 4 ? "#4c5058" : era >= 2 ? "#6f6b63" : "#857559";
      out.lerp(tmp.set(ground), sample.w * 0.85);
    }
    out.offsetHSL(0, 0, this.noise.noise(dir.x * 9, dir.y * 9, dir.z * 9) * 0.035);
    return out;
  }
}

const TMP_A = new THREE.Color();

/** A unit sphere's vertex directions, kept so the terrain can be rebuilt without re-making the geometry. */
export function planetGeometry(): THREE.BufferGeometry {
  const geometry = new THREE.SphereGeometry(1, 300, 200);
  geometry.userData.dirs = Float32Array.from((geometry.getAttribute("position") as THREE.BufferAttribute).array);
  return geometry;
}

/** Displace and colour the planet for the current sites and era. */
export function paintPlanet(geometry: THREE.BufferGeometry, terrain: Terrain, era: number): void {
  const dirs = geometry.userData.dirs as Float32Array;
  const position = geometry.getAttribute("position") as THREE.BufferAttribute;
  const colors = new Float32Array(position.count * 3);
  const dir = new THREE.Vector3();
  const color = new THREE.Color();
  for (let i = 0; i < position.count; i += 1) {
    dir.set(dirs[i * 3], dirs[i * 3 + 1], dirs[i * 3 + 2]).normalize();
    const sample = terrain.sample(dir);
    position.setXYZ(i, dir.x * (R + sample.h), dir.y * (R + sample.h), dir.z * (R + sample.h));
    terrain.color(dir, sample, era, color);
    colors[i * 3] = color.r;
    colors[i * 3 + 1] = color.g;
    colors[i * 3 + 2] = color.b;
  }
  position.needsUpdate = true;
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
}

/** The sea: a shiny shell just under the base radius. On a volcanic world it is lava, and glows. */
export function seaMaterial(planet: WorldPlanet): THREE.Material {
  if (planet.lava) {
    return new THREE.MeshStandardMaterial({ color: planet.sea[1], emissive: planet.sea[1], emissiveIntensity: 0.9,
      roughness: 0.6 });
  }
  return new THREE.MeshStandardMaterial({ color: planet.sea[1], roughness: 0.16, metalness: 0.05, transparent: true,
    opacity: 0.86, envMapIntensity: 0.6 });
}

/** Clouds from the same seeded noise, wrapped on the sphere (equirectangular). */
export function cloudTexture(planet: WorldPlanet): THREE.Texture {
  const width = 512;
  const height = 256;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;
  const image = ctx.createImageData(width, height);
  const noise = new Perlin((planet.noise || 7) ^ 0x5bd1e995);
  const cover = (planet.clouds - 0.5) * 0.7;
  for (let y = 0; y < height; y += 1) {
    const lat = (0.5 - y / height) * Math.PI;
    for (let x = 0; x < width; x += 1) {
      const lon = (x / width) * Math.PI * 2;
      const dx = Math.cos(lat) * Math.cos(lon);
      const dy = Math.sin(lat);
      const dz = Math.cos(lat) * Math.sin(lon);
      const n = noise.fbm(dx * 2.6, dy * 5.2, dz * 2.6, 5) * 1.7 + cover;
      const alpha = smooth(0.02, 0.45, n);
      const index = (y * width + x) * 4;
      image.data[index] = 255;
      image.data[index + 1] = 255;
      image.data[index + 2] = 255;
      image.data[index + 3] = Math.round(alpha * 220);
    }
  }
  ctx.putImageData(image, 0, 0);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  return texture;
}

/** Rings, when the planet has them: bands of dust from a radial stripe texture. */
export function ringMesh(planet: WorldPlanet): THREE.Mesh {
  const inner = R * 1.45;
  const outer = R * 2.25;
  const geometry = new THREE.RingGeometry(inner, outer, 160, 1);
  const uv = geometry.getAttribute("uv") as THREE.BufferAttribute;
  const position = geometry.getAttribute("position") as THREE.BufferAttribute;
  for (let i = 0; i < uv.count; i += 1) {
    const r = Math.hypot(position.getX(i), position.getY(i));
    uv.setXY(i, (r - inner) / (outer - inner), 0.5);
  }
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 2;
  const ctx = canvas.getContext("2d")!;
  const noise = new Perlin((planet.noise || 7) + 99);
  const base = new THREE.Color(planet.ring_color);
  for (let x = 0; x < 512; x += 1) {
    const band = 0.5 + noise.fbm(x * 0.045, 0.5, 0.5, 4) * 1.4;
    const edge = smooth(0, 0.08, x / 512) * (1 - smooth(0.9, 1, x / 512));
    ctx.fillStyle = `rgba(${Math.round(base.r * 255)},${Math.round(base.g * 255)},${Math.round(base.b * 255)},${Math.max(0, Math.min(1, band)) * edge * 0.75})`;
    ctx.fillRect(x, 0, 1, 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ map: texture, transparent: true,
    side: THREE.DoubleSide, depthWrite: false }));
  mesh.rotation.x = Math.PI / 2 - planet.ring_tilt;
  mesh.raycast = () => undefined;
  return mesh;
}

export function moonMeshes(planet: WorldPlanet): THREE.Mesh[] {
  return planet.moons.map((moon, index) => {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(R * moon.size, 32, 24),
      new THREE.MeshStandardMaterial({ color: moon.color, roughness: 0.95 }));
    mesh.userData.orbit = { radius: R * moon.distance, speed: moon.speed, tilt: moon.tilt, phase: index * 2.1 + 0.6 };
    mesh.raycast = () => undefined;
    return mesh;
  });
}

export const ATMOSPHERE_VERTEX = /* glsl */ `
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    vNormal = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;
export const ATMOSPHERE_FRAGMENT = /* glsl */ `
  uniform vec3 uColor;
  uniform float uStrength;
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    float rim = pow(1.0 - max(dot(vNormal, vView), 0.0), 2.6);
    gl_FragColor = vec4(uColor, rim * uStrength);
  }
`;
