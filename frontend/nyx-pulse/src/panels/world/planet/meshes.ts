/** What things look like on the planet: buildings by kind, floors and era, the construction rigs, the figures, graves,
 * markers and the things in orbit.
 *
 * The upscale (owner, 2026-10-10: "make structures look better and more realistic"): facades are textured — stone
 * with small windows, then brick and steel, then glass curtain walls, then lit futuristic skins — with window lights
 * that only glow on the night side of the planet; towers get podiums, setbacks, crowns and rooftop plant; houses go
 * from huts to cottages to apartment blocks to green towers; the government's district has its own civic buildings.
 * Building is done in phases you can see: a pad, a crane, a steel frame, the facade closing in, scaffolding.
 *
 * Geometry and materials are shared through small caches, and the scene bakes every finished building of a district
 * into a few meshes (PlanetScene), so a world of 1,600 buildings stays one smooth scene. */

import * as THREE from "three";
import { FLOOR_HEIGHT, hash } from "./geo";

export interface Look {
  style: string;
  palette: string[];
}

const DEFAULT_LOOK: Look = { style: "block", palette: ["#9aa4b2", "#5ac8fa", "#4a5260"] };

const geometries = new Map<string, THREE.BufferGeometry>();
const materials = new Map<string, THREE.Material>();
const textures = new Map<string, THREE.Texture>();

function geo<T extends THREE.BufferGeometry>(key: string, make: () => T): T {
  let found = geometries.get(key);
  if (!found) {
    found = make();
    geometries.set(key, found);
  }
  return found as T;
}

function mat<T extends THREE.Material>(key: string, make: () => T): T {
  let found = materials.get(key);
  if (!found) {
    found = make();
    materials.set(key, found);
  }
  return found as T;
}

export function disposeMeshCaches(): void {
  geometries.forEach((g) => g.dispose());
  materials.forEach((m) => m.dispose());
  textures.forEach((t) => t.dispose());
  geometries.clear();
  materials.clear();
  textures.clear();
}

// --- night lights ----------------------------------------------------------------------------------------------

/** Where the sun is (the scene's key light points from here to the planet's centre). */
export const SUN_DIRECTION = new THREE.Vector3(-40, 26, 30).normalize();
const sunUniform = { value: SUN_DIRECTION };

/** Window lights glow on the night side only: the emissive term fades out where the sun is up. */
function nightGlow<T extends THREE.Material>(material: T): T {
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uSunDir = sunUniform;
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vNightPos;")
      .replace("#include <project_vertex>",
        "#include <project_vertex>\nvNightPos = (modelMatrix * vec4(transformed, 1.0)).xyz;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", "#include <common>\nuniform vec3 uSunDir;\nvarying vec3 vNightPos;")
      .replace("#include <emissivemap_fragment>",
        "#include <emissivemap_fragment>\nfloat nightK = smoothstep(0.12, -0.2, dot(normalize(vNightPos), uSunDir));\n" +
        "totalEmissiveRadiance *= mix(0.08, 1.0, nightK);");
  };
  material.customProgramCacheKey = () => "night-glow";
  return material;
}

// --- facades ---------------------------------------------------------------------------------------------------

/** 0 stone and timber · 1 brick and steel · 2 glass curtain walls · 3 lit, futuristic skins. */
export type Tier = 0 | 1 | 2 | 3;
export function tierOf(era: number): Tier {
  return era <= 1 ? 0 : era <= 3 ? 1 : era <= 5 ? 2 : 3;
}

/** One facade tile is 8 window bays wide and 8 floors tall. */
const BAY = 0.05;
const TILE_U = BAY * 8;
const TILE_V = FLOOR_HEIGHT * 8;

function facadeTextures(tier: Tier): { map: THREE.Texture; glow: THREE.Texture } {
  const key = `facade:${tier}`;
  const found = textures.get(`${key}:map`);
  if (found) return { map: found, glow: textures.get(`${key}:glow`)! };
  const size = 256;
  const cell = size / 8;
  const albedo = document.createElement("canvas");
  const lights = document.createElement("canvas");
  albedo.width = albedo.height = lights.width = lights.height = size;
  const a = albedo.getContext("2d")!;
  const l = lights.getContext("2d")!;
  l.fillStyle = "#000";
  l.fillRect(0, 0, size, size);
  const wall = ["#f2ede4", "#e6e1da", "#dfe6ee", "#cfd6e2"][tier];
  a.fillStyle = wall;
  a.fillRect(0, 0, size, size);
  for (let floor = 0; floor < 8; floor += 1) {
    for (let bay = 0; bay < 8; bay += 1) {
      const x = bay * cell;
      const y = floor * cell;
      const lit = hash(`w${tier}:${floor}:${bay}`) < [0.32, 0.45, 0.5, 0.6][tier];
      const warm = hash(`c${tier}:${floor}:${bay}`) < (tier >= 2 ? 0.45 : 0.85);
      const light = warm ? "#ffd59a" : "#cfe4ff";
      if (tier === 0) {
        a.fillStyle = "#3a3f47";
        a.fillRect(x + 11, y + 8, 10, 15);
        if (lit) { l.fillStyle = light; l.fillRect(x + 11, y + 8, 10, 15); }
      } else if (tier === 1) {
        a.fillStyle = "#c9c2b8";
        a.fillRect(x, y + cell - 4, cell, 4);
        a.fillStyle = "#39434f";
        a.fillRect(x + 5, y + 6, cell - 10, 18);
        if (lit) { l.fillStyle = light; l.fillRect(x + 5, y + 6, cell - 10, 18); }
      } else if (tier === 2) {
        a.fillStyle = "#4d6176";
        a.fillRect(x + 2, y + 2, cell - 4, cell - 6);
        a.fillStyle = "#6f879e";
        a.fillRect(x + 2, y + 2, cell - 4, 5);
        if (lit) { l.fillStyle = light; l.fillRect(x + 3, y + 3, cell - 6, cell - 8); }
      } else {
        a.fillStyle = "#2f3a4c";
        a.fillRect(x + 1, y + 1, cell - 2, cell - 5);
        l.fillStyle = "#7fe9ff";
        l.fillRect(x, y + cell - 3, cell, 2);
        if (lit) { l.fillStyle = warm ? "#ffe2b8" : "#e6f2ff"; l.fillRect(x + 3, y + 3, cell - 6, cell - 9); }
      }
    }
  }
  const make = (canvas: HTMLCanvasElement, srgb: boolean) => {
    const texture = new THREE.CanvasTexture(canvas);
    if (srgb) texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.anisotropy = 4;
    return texture;
  };
  const map = make(albedo, true);
  const glow = make(lights, true);
  textures.set(`${key}:map`, map);
  textures.set(`${key}:glow`, glow);
  return { map, glow };
}

/** A facade material: the era's skin tinted by the technology's colour, its windows lit at night. */
function facade(tier: Tier, body: string, glow: string): THREE.Material {
  return mat(`facade:${tier}:${body}:${glow}`, () => {
    const { map, glow: lights } = facadeTextures(tier);
    const tint = new THREE.Color(body).lerp(new THREE.Color("#ffffff"), tier === 0 ? 0.25 : 0.1);
    return nightGlow(new THREE.MeshStandardMaterial({
      color: tint, map, emissive: tier === 3 ? new THREE.Color(glow).lerp(new THREE.Color("#ffffff"), 0.5)
        : new THREE.Color("#ffffff"),
      emissiveMap: lights, emissiveIntensity: tier === 3 ? 1.3 : 1.05,
      roughness: [0.88, 0.7, 0.28, 0.22][tier], metalness: [0.02, 0.15, 0.45, 0.6][tier],
    }));
  });
}

function solid(color: string, opts: { emissive?: string; intensity?: number; rough?: number; metal?: number;
  transparent?: number } = {}): THREE.Material {
  const key = `solid:${color}:${opts.emissive ?? ""}:${opts.intensity ?? 0}:${opts.rough ?? 0.7}:${opts.metal ?? 0.1}:${opts.transparent ?? 1}`;
  return mat(key, () => new THREE.MeshStandardMaterial({
    color: new THREE.Color(color), roughness: opts.rough ?? 0.7, metalness: opts.metal ?? 0.1,
    emissive: new THREE.Color(opts.emissive ?? "#000000"), emissiveIntensity: opts.intensity ?? 0,
    transparent: (opts.transparent ?? 1) < 1, opacity: opts.transparent ?? 1,
  }));
}

/** Facade UVs: one tile per 8 bays and 8 floors, so every building shares one material whatever its size. Roofs and
 * floors sample the tile's corner (plain wall, unlit). */
function facadeBox(w: number, h: number, d: number): THREE.BufferGeometry {
  return geo(`fbox:${w.toFixed(3)}:${h.toFixed(3)}:${d.toFixed(3)}`, () => {
    const g = new THREE.BoxGeometry(w, h, d);
    const uv = g.getAttribute("uv") as THREE.BufferAttribute;
    for (let face = 0; face < 6; face += 1) {
      for (let k = 0; k < 4; k += 1) {
        const i = face * 4 + k;
        if (face === 2 || face === 3) {
          uv.setXY(i, 0.002, 0.998);
        } else {
          const width = face < 2 ? d : w;
          uv.setXY(i, uv.getX(i) * Math.max(0.25, width / TILE_U), uv.getY(i) * (h / TILE_V));
        }
      }
    }
    return g;
  });
}

function facadeCyl(top: number, bottom: number, h: number, sides = 16): THREE.BufferGeometry {
  return geo(`fcyl:${top}:${bottom}:${h.toFixed(3)}:${sides}`, () => {
    const g = new THREE.CylinderGeometry(top, bottom, h, sides);
    const uv = g.getAttribute("uv") as THREE.BufferAttribute;
    const normal = g.getAttribute("normal") as THREE.BufferAttribute;
    const around = Math.max(1, Math.round((2 * Math.PI * Math.max(top, bottom)) / TILE_U));
    for (let i = 0; i < uv.count; i += 1) {
      if (Math.abs(normal.getY(i)) > 0.9) uv.setXY(i, 0.002, 0.998);
      else uv.setXY(i, uv.getX(i) * around, uv.getY(i) * (h / TILE_V));
    }
    return g;
  });
}

function mesh(geometry: THREE.BufferGeometry, material: THREE.Material, y = 0, x = 0, z = 0, detail = false): THREE.Mesh {
  const m = new THREE.Mesh(geometry, material);
  m.position.set(x, y, z);
  if (detail) m.userData.detail = true;
  return m;
}

const box = (w: number, h: number, d: number) =>
  geo(`box:${w.toFixed(3)}:${h.toFixed(3)}:${d.toFixed(3)}`, () => new THREE.BoxGeometry(w, h, d));
const cyl = (top: number, bottom: number, h: number, sides = 14) =>
  geo(`cyl:${top}:${bottom}:${h.toFixed(3)}:${sides}`, () => new THREE.CylinderGeometry(top, bottom, h, sides));
const cone = (r: number, h: number, sides = 4) =>
  geo(`cone:${r}:${h.toFixed(3)}:${sides}`, () => new THREE.ConeGeometry(r, h, sides));
const dome = (r: number) =>
  geo(`dome:${r}`, () => new THREE.SphereGeometry(r, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2));
const torus = (r: number, tube: number) =>
  geo(`torus:${r}:${tube}`, () => new THREE.TorusGeometry(r, tube, 8, 40));

/** A pitched roof: ridge along x, ``w`` long, ``d`` deep, ``rise`` high, sitting on y = 0. */
function gable(w: number, d: number, rise: number): THREE.BufferGeometry {
  return geo(`gable:${w}:${d}:${rise}`, () => {
    const x = w / 2;
    const z = d / 2;
    const p = [
      -x, 0, z, x, 0, z, x, rise, 0, -x, 0, z, x, rise, 0, -x, rise, 0, // front slope
      x, 0, -z, -x, 0, -z, -x, rise, 0, x, 0, -z, -x, rise, 0, x, rise, 0, // back slope
      -x, 0, -z, -x, 0, z, -x, rise, 0, // left gable
      x, 0, z, x, 0, -z, x, rise, 0, // right gable
    ];
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(p, 3));
    g.setAttribute("uv", new THREE.Float32BufferAttribute(new Array((p.length / 3) * 2).fill(0), 2));
    g.computeVertexNormals();
    return g;
  });
}

/** A natural-draught cooling tower (hyperboloid). */
function coolingTower(r: number, h: number): THREE.BufferGeometry {
  return geo(`cool:${r}:${h.toFixed(3)}`, () => {
    const points: THREE.Vector2[] = [];
    for (let i = 0; i <= 12; i += 1) {
      const t = i / 12;
      const waist = 0.62 + 0.38 * Math.pow((t - 0.72) / 0.72, 2);
      points.push(new THREE.Vector2(r * Math.min(1, waist), t * h));
    }
    return new THREE.LatheGeometry(points, 20);
  });
}

// --- the pieces buildings are made of -------------------------------------------------------------------------------

/** A parapet, rooftop plant, a water tank (older) or an antenna (taller, newer). All small: hidden from far away. */
function roof(g: THREE.Group, w: number, d: number, y: number, tier: Tier, seed: string, tall: boolean, look: Look): void {
  const [, glow, roofColor] = look.palette;
  if (tier >= 1) {
    const lip = solid(tier >= 2 ? "#9aa3ad" : "#8a8278", { metal: tier >= 2 ? 0.5 : 0.1 });
    g.add(mesh(box(w + 0.01, 0.012, d + 0.01), lip, y + 0.006));
  } else {
    return;
  }
  const units = 1 + Math.floor(hash(`${seed}u`) * 3);
  for (let i = 0; i < units; i += 1) {
    const ux = (hash(`${seed}x${i}`) - 0.5) * w * 0.6;
    const uz = (hash(`${seed}z${i}`) - 0.5) * d * 0.6;
    g.add(mesh(box(w * 0.22, 0.025, d * 0.18), solid("#7d8189", { metal: 0.4 }), y + 0.024, ux, uz, true));
  }
  if (tier === 1 && hash(`${seed}t`) < 0.6) {
    g.add(mesh(cyl(0.022, 0.022, 0.04, 10), solid("#6b5442", { rough: 0.9 }), y + 0.05, w * 0.25, -d * 0.2, true));
    g.add(mesh(cone(0.026, 0.025, 10), solid(roofColor || "#4a3a30"), y + 0.083, w * 0.25, -d * 0.2, true));
  }
  if (tier >= 2 && tall) {
    g.add(mesh(cyl(0.004, 0.006, 0.22, 6), solid("#d1d1d6", { metal: 0.7 }), y + 0.11, -w * 0.2, d * 0.15, true));
    g.add(mesh(geo("beacon", () => new THREE.SphereGeometry(0.008, 8, 6)),
      solid("#ff453a", { emissive: "#ff453a", intensity: 1.4 }), y + 0.225, -w * 0.2, d * 0.15, true));
  }
  if (tier === 3) {
    const ring = mesh(torus(Math.max(w, d) * 0.62, 0.006), solid(glow, { emissive: glow, intensity: 1.2 }), y - 0.04);
    ring.rotation.x = Math.PI / 2;
    g.add(ring);
  }
}

/** A tower that reads as real architecture: a podium, the shaft, setbacks as it climbs, a crown. */
function tower(g: THREE.Group, w: number, d: number, h: number, tier: Tier, look: Look, seed: string): number {
  const [body, glow] = look.palette;
  const skin = facade(tier, body, glow);
  if (tier <= 1 || h < 0.5) {
    g.add(mesh(facadeBox(w, h, d), skin, h / 2));
    if (tier === 0) {
      g.add(mesh(cone(Math.max(w, d) * 0.78, Math.min(0.12, w * 0.6), 4), solid(look.palette[2] || "#5a4a3a"),
        h + Math.min(0.12, w * 0.6) / 2).rotateY(Math.PI / 4));
    }
    roof(g, w, d, h, tier, seed, h > 0.4, look);
    return h;
  }
  const podium = Math.min(0.17, h * 0.12);
  g.add(mesh(facadeBox(w * 1.3, podium, d * 1.3), skin, podium / 2));
  const shaft = h * (tier === 3 ? 0.55 : 0.68);
  let y = podium;
  if (tier === 3) {
    // A twisting, tapering stack: each block turns a little and narrows.
    const blocks = Math.max(3, Math.min(9, Math.round((h - podium) / 0.35)));
    const step = (h - podium) / blocks;
    for (let i = 0; i < blocks; i += 1) {
      const k = 1 - (i / blocks) * 0.45;
      const block = mesh(facadeBox(w * k, step * 0.96, d * k), skin, y + step / 2);
      block.rotation.y = i * 0.11 + hash(seed) * 0.4;
      g.add(block);
      y += step;
    }
  } else {
    g.add(mesh(facadeBox(w, shaft - podium, d), skin, podium + (shaft - podium) / 2));
    const upper = h - shaft;
    g.add(mesh(facadeBox(w * 0.74, upper, d * 0.74), skin, shaft + upper / 2));
    y = h;
  }
  roof(g, w * (tier === 3 ? 0.55 : 0.74), d * (tier === 3 ? 0.55 : 0.74), y, tier, seed, true, look);
  if (look.style === "spire" || tier === 3) {
    g.add(mesh(cone(w * 0.16, Math.min(0.5, h * 0.18), 8), solid(glow, { emissive: glow, intensity: 0.8, metal: 0.5 }),
      y + Math.min(0.5, h * 0.18) / 2));
  } else if (look.style === "dome") {
    g.add(mesh(dome(w * 0.3), solid(glow, { emissive: glow, intensity: 0.35, metal: 0.4, rough: 0.3 }), y));
  } else if (look.style === "ring") {
    const ring = mesh(torus(w * 0.7, 0.01), solid(glow, { emissive: glow, intensity: 1 }), y - h * 0.15);
    ring.rotation.x = Math.PI / 2;
    g.add(ring);
  }
  return y;
}

function columns(g: THREE.Group, count: number, x0: number, x1: number, z: number, h: number, y = 0): void {
  for (let i = 0; i < count; i += 1) {
    const x = count === 1 ? (x0 + x1) / 2 : x0 + ((x1 - x0) * i) / (count - 1);
    g.add(mesh(cyl(0.012, 0.014, h, 10), solid("#ece6da", { rough: 0.6 }), y + h / 2, x, z, true));
  }
}

function colonnadeRing(g: THREE.Group, r: number, h: number, count: number, y = 0): void {
  for (let i = 0; i < count; i += 1) {
    const a = (i / count) * Math.PI * 2;
    g.add(mesh(cyl(0.014, 0.016, h, 10), solid("#ece6da", { rough: 0.6 }), y + h / 2, Math.cos(a) * r,
      Math.sin(a) * r, true));
  }
}

/** A classical front: steps, columns, a pediment. Banks, archives, courts, ministries. */
function temple(g: THREE.Group, w: number, d: number, h: number, look: Look, tier: Tier): void {
  const stone = solid(tier >= 2 ? "#dcd8d0" : "#e6dfd0", { rough: 0.65 });
  g.add(mesh(box(w * 1.12, 0.03, d * 1.15), stone, 0.015));
  g.add(mesh(facadeBox(w, h, d * 0.72), facade(Math.min(tier, 1) as Tier, "#efe9de", look.palette[1]), 0.03 + h / 2,
    0, -d * 0.12));
  columns(g, Math.max(4, Math.round(w / 0.06)), -w * 0.44, w * 0.44, d * 0.36, h, 0.03);
  g.add(mesh(box(w * 1.04, 0.025, d), stone, 0.03 + h + 0.012));
  g.add(mesh(gable(w * 1.04, d, Math.min(0.08, w * 0.22)), stone, 0.03 + h + 0.025));
}

// --- the bodies ----------------------------------------------------------------------------------------------------

/** The body of a building — everything that rises during construction. Origin at ground level. */
function body(kind: string, floors: number, era: number, look: Look, tag: string, seed: string): THREE.Group {
  const g = new THREE.Group();
  const [bodyColor, glow, roofColor] = look.palette;
  const tier = tierOf(era);
  const h = Math.max(0.05, floors * FLOOR_HEIGHT);
  switch (kind) {
    case "house": {
      if (tier === 0) {
        // Round huts of timber and thatch.
        g.add(mesh(cyl(0.07, 0.075, 0.07, 12), solid("#9a7b55", { rough: 0.95 }), 0.035, -0.05, 0));
        g.add(mesh(cone(0.095, 0.08, 12), solid("#b59a5c", { rough: 1 }), 0.11, -0.05, 0));
        g.add(mesh(cyl(0.05, 0.055, 0.055, 12), solid("#9a7b55", { rough: 0.95 }), 0.027, 0.08, 0.06));
        g.add(mesh(cone(0.07, 0.06, 12), solid("#b59a5c", { rough: 1 }), 0.085, 0.08, 0.06));
      } else if (tier === 1) {
        // A short row of cottages with pitched roofs and chimneys.
        for (let i = 0; i < 3; i += 1) {
          const x = -0.11 + i * 0.11;
          const hh = 0.07 + (floors > 1 ? 0.04 : 0);
          g.add(mesh(facadeBox(0.1, hh, 0.12), facade(0, ["#d9c7ad", "#c9b29a", "#e0d4c0"][i], glow), hh / 2, x));
          g.add(mesh(gable(0.1, 0.14, 0.05), solid(roofColor || "#7a3f2c", { rough: 0.85 }), hh, x));
          g.add(mesh(box(0.014, 0.04, 0.014), solid("#8a5a46"), hh + 0.04, x + 0.025, 0.02, true));
        }
      } else if (tier === 2) {
        const hh = Math.max(0.25, h * 1.4);
        g.add(mesh(facadeBox(0.3, hh, 0.16), facade(1, bodyColor, glow), hh / 2));
        for (let i = 0; i < Math.round(hh / FLOOR_HEIGHT); i += 1) {
          g.add(mesh(box(0.3, 0.006, 0.03), solid("#c7c7cc"), (i + 1) * FLOOR_HEIGHT - 0.01, 0, 0.09, true));
        }
        roof(g, 0.3, 0.16, hh, 1, seed, false, look);
      } else {
        // A green tower: glass with planted terraces.
        const hh = Math.max(0.4, h * 2);
        tower(g, 0.16, 0.16, hh, 2, look, seed);
        for (let i = 1; i < Math.round(hh / 0.12); i += 1) {
          g.add(mesh(box(0.2, 0.018, 0.2), solid("#3f8f4a", { rough: 1, emissive: "#30d158", intensity: 0.05 }),
            i * 0.12, 0, 0, true));
        }
      }
      break;
    }
    case "council": {
      const hh = Math.max(0.08, h);
      g.add(mesh(box(0.34, 0.025, 0.34), solid("#c9c2b4"), 0.0125));
      g.add(mesh(facadeCyl(0.12, 0.13, hh, 16), facade(Math.min(tier, 1) as Tier, "#efe9de", glow), 0.025 + hh / 2));
      colonnadeRing(g, 0.15, hh * 0.9, 10, 0.025);
      g.add(mesh(dome(0.12), solid(glow, { emissive: glow, intensity: 0.25, metal: 0.5, rough: 0.3 }), 0.025 + hh));
      break;
    }
    case "capitol": {
      // The Assembly: a round chamber on a wide stair, ringed by columns, under a great dome.
      const hh = Math.max(0.16, h * 1.2);
      g.add(mesh(cyl(0.48, 0.52, 0.04, 40), solid("#e2dccf", { rough: 0.7 }), 0.02));
      g.add(mesh(cyl(0.42, 0.44, 0.03, 40), solid("#ece6da", { rough: 0.7 }), 0.055));
      g.add(mesh(facadeCyl(0.3, 0.32, hh, 32), facade(Math.min(tier, 1) as Tier, "#f3eee4", glow), 0.07 + hh / 2));
      colonnadeRing(g, 0.36, hh * 0.92, 18, 0.07);
      g.add(mesh(cyl(0.38, 0.38, 0.03, 40), solid("#ece6da"), 0.07 + hh + 0.015));
      g.add(mesh(cyl(0.2, 0.22, 0.08, 32), solid("#ece6da"), 0.07 + hh + 0.07));
      g.add(mesh(dome(0.21), solid("#e9d9a6", { emissive: "#ffd60a", intensity: 0.18, metal: 0.65, rough: 0.28 }),
        0.07 + hh + 0.11));
      g.add(mesh(cyl(0.004, 0.004, 0.16, 6), solid("#d1d1d6"), 0.07 + hh + 0.32 + 0.08, 0, 0, true));
      break;
    }
    case "chancellery": {
      // The executive: a tall tower behind a forecourt, its flag on top.
      g.add(mesh(box(0.6, 0.02, 0.6), solid("#d8d2c6"), 0.01));
      const top = tower(g, 0.3, 0.26, Math.max(0.2, h), Math.max(1, tier) as Tier, look, seed);
      g.add(mesh(cyl(0.004, 0.004, 0.16, 6), solid("#e5e5ea"), top + 0.08, 0, 0, true));
      const flag = mesh(geo("flag:big", () => new THREE.PlaneGeometry(0.09, 0.055)),
        mat("flag:gov", () => new THREE.MeshStandardMaterial({ color: "#ff7a2e", emissive: "#ff7a2e",
          emissiveIntensity: 0.35, side: THREE.DoubleSide })), top + 0.13, 0.046, 0, true);
      g.add(flag);
      break;
    }
    case "court": {
      temple(g, 0.56, 0.4, Math.max(0.12, h), look, tier);
      g.add(mesh(dome(0.08), solid("#d8d2c6"), 0.03 + Math.max(0.12, h) + 0.08, 0, -0.08, true));
      break;
    }
    case "ministry": {
      const colors: Record<string, string> = { works: "#ff9f0a", science: "#64d2ff", treasury: "#ffd60a",
        transport: "#30d158", energy: "#ff453a", space: "#bf5af2", interstellar: "#5e5ce6" };
      const band = colors[tag] ?? glow;
      if (tier >= 2) {
        const top = tower(g, 0.34, 0.28, Math.max(0.25, h), tier, { ...look, style: "block" }, seed);
        g.add(mesh(box(0.36, 0.03, 0.3), solid(band, { emissive: band, intensity: 0.7 }), top * 0.3));
      } else {
        temple(g, 0.46, 0.36, Math.max(0.1, h), look, tier);
      }
      g.add(mesh(box(0.5, 0.012, 0.03), solid(band, { emissive: band, intensity: 0.6 }), 0.035, 0, 0.25));
      break;
    }
    case "tower": {
      tower(g, 0.2, 0.2, h, tier, look, seed);
      break;
    }
    case "office": {
      const w = 0.24 + hash(`${seed}w`) * 0.08;
      tower(g, w, 0.22 + hash(`${seed}d`) * 0.06, h, tier, look, seed);
      break;
    }
    case "bank": {
      if (tier >= 2 && h > 0.4) {
        const top = tower(g, 0.26, 0.26, h, tier, look, seed);
        g.add(mesh(box(0.27, 0.06, 0.27), solid("#e9d9a6", { emissive: "#ffd60a", intensity: 0.4, metal: 0.8, rough: 0.2 }),
          top - 0.03));
        temple(g, 0.42, 0.18, 0.12, look, 1);
      } else {
        temple(g, 0.36, 0.3, Math.max(0.1, h), look, tier);
        g.add(mesh(dome(0.1), solid("#e9d9a6", { emissive: "#ffd60a", intensity: 0.15, metal: 0.6, rough: 0.3 }),
          0.03 + Math.max(0.1, h) + 0.04));
      }
      break;
    }
    case "lab": {
      g.add(mesh(facadeBox(0.34, Math.max(0.06, h * 0.4), 0.18), facade(tier, bodyColor, glow), Math.max(0.06, h * 0.4) / 2,
        0, 0.08));
      g.add(mesh(facadeCyl(0.13, 0.14, h, 20), facade(tier, bodyColor, glow), h / 2, 0, -0.05));
      g.add(mesh(dome(0.135), solid("#9ad7ff", { emissive: "#64d2ff", intensity: 0.35, transparent: 0.82, rough: 0.08,
        metal: 0.3 }), h, 0, -0.05));
      if (tier >= 2) {
        const dish = mesh(geo("dish", () => new THREE.SphereGeometry(0.05, 14, 8, 0, Math.PI * 2, 0, Math.PI / 3)),
          solid("#e5e5ea", { metal: 0.6 }), Math.max(0.06, h * 0.4) + 0.05, 0.12, 0.1, true);
        dish.rotation.x = Math.PI;
        g.add(dish);
      }
      break;
    }
    case "data_center": {
      const hall = Math.max(0.05, h * 0.5);
      g.add(mesh(facadeBox(0.42, hall, 0.28), facade(tier >= 2 ? 3 : 1, "#3a3f4a", glow), hall / 2));
      for (let i = 0; i < 4; i += 1) {
        g.add(mesh(cyl(0.03, 0.03, 0.03, 12), solid("#8e8e96", { metal: 0.6 }), hall + 0.015, -0.15 + i * 0.1, 0.06, true));
        g.add(mesh(box(0.06, 0.012, 0.06), solid("#5a5f6b", { metal: 0.5 }), hall + 0.006, -0.15 + i * 0.1, -0.07, true));
      }
      if (tier >= 2) {
        for (let i = 0; i < 3; i += 1) {
          const panel = mesh(box(0.12, 0.004, 0.06), solid("#1d3b6b", { emissive: "#5ac8fa", intensity: 0.15, metal: 0.5,
            rough: 0.2 }), 0.03, -0.14 + i * 0.14, 0.2, true);
          panel.rotation.x = -0.4;
          g.add(panel);
        }
      }
      break;
    }
    case "mine": {
      g.add(mesh(cone(0.26, 0.12, 7), solid("#5a4c3e", { rough: 0.95 }), 0.06, -0.06, 0.04));
      g.add(mesh(cyl(0.12, 0.15, 0.015, 16), solid("#2a241f", { rough: 1 }), 0.006, 0.1, -0.08));
      const fh = Math.max(0.18, h * 0.9);
      const steel = solid(tier >= 2 ? "#a8adb5" : "#8a6d3b", { metal: 0.4 });
      g.add(mesh(box(0.016, fh, 0.016), steel, fh / 2, 0.05, -0.12));
      g.add(mesh(box(0.016, fh, 0.016), steel, fh / 2, 0.15, -0.12));
      g.add(mesh(box(0.016, fh * 0.9, 0.016), steel, fh * 0.45, 0.1, -0.03));
      g.add(mesh(box(0.13, 0.016, 0.016), steel, fh, 0.1, -0.12));
      const wheel = mesh(torus(0.035, 0.006), solid("#5a5a63", { metal: 0.6 }), fh + 0.03, 0.1, -0.12, true);
      g.add(wheel);
      if (tier >= 1) {
        const belt = mesh(box(0.3, 0.012, 0.03), solid("#3a3a40"), 0.09, -0.02, 0.1, true);
        belt.rotation.z = 0.35;
        g.add(belt);
        g.add(mesh(facadeBox(0.12, 0.08, 0.1), facade(1, "#8a8278", glow), 0.04, -0.15, 0.14));
      }
      break;
    }
    case "farm": {
      const crops = ["#6aa84f", "#c9b458", "#4c7a3a", "#8fbf5a"];
      for (let i = 0; i < 4; i += 1) {
        g.add(mesh(box(0.2, 0.01, 0.2), solid(crops[(i + Math.floor(hash(seed) * 4)) % 4], { rough: 1 }), 0.005,
          i % 2 ? 0.105 : -0.105, i < 2 ? 0.105 : -0.105));
      }
      if (tier >= 3) {
        tower(g, 0.14, 0.14, Math.max(0.4, h), 2, { ...look, palette: ["#bfe8c4", "#30d158", "#2a5a30"] }, seed);
      } else {
        g.add(mesh(box(0.1, 0.06, 0.08), solid("#9a3a2c", { rough: 0.85 }), 0.03, 0.12, 0.12));
        g.add(mesh(gable(0.1, 0.09, 0.04), solid("#5a4a40"), 0.06, 0.12, 0.12));
        const sh = Math.max(0.12, h);
        g.add(mesh(cyl(0.035, 0.035, sh, 12), solid("#c9c3b8", { metal: 0.3 }), sh / 2, 0.16, -0.12));
        g.add(mesh(dome(0.035), solid(roofColor || "#8e8e96", { metal: 0.4 }), sh, 0.16, -0.12));
      }
      break;
    }
    case "factory": {
      const fh = Math.max(0.07, h * 0.55);
      g.add(mesh(facadeBox(0.4, fh, 0.26), facade(Math.min(tier, 1) as Tier, bodyColor, glow), fh / 2));
      // A sawtooth roof.
      for (let i = 0; i < 4; i += 1) {
        const tooth = mesh(box(0.1, 0.004, 0.27), solid(tier >= 2 ? "#5ac8fa" : "#6b6b72", { metal: 0.4,
          emissive: tier >= 2 ? "#5ac8fa" : "#000000", intensity: tier >= 2 ? 0.2 : 0 }), fh + 0.025, -0.15 + i * 0.1);
        tooth.rotation.z = 0.5;
        g.add(tooth);
      }
      const stacks = tier >= 2 ? 1 : 2;
      for (let i = 0; i < stacks; i += 1) {
        g.add(mesh(cyl(0.022, 0.03, fh * 2.2, 12), solid("#7a6a62"), fh * 1.1, 0.14 - i * 0.07, -0.08));
        g.add(mesh(cyl(0.026, 0.026, 0.012, 12), solid("#ff453a", { emissive: "#ff453a", intensity: 0.5 }), fh * 2.2,
          0.14 - i * 0.07, -0.08, true));
      }
      break;
    }
    case "refinery": {
      const th = Math.max(0.08, h * 0.55);
      const steel = solid("#d1d1d6", { metal: 0.6, rough: 0.3 });
      g.add(mesh(cyl(0.07, 0.07, th, 18), steel, th / 2, -0.12, 0.08));
      g.add(mesh(cyl(0.06, 0.06, th * 0.8, 18), steel, th * 0.4, 0.02, 0.1));
      g.add(mesh(geo("sphtank", () => new THREE.SphereGeometry(0.06, 16, 12)), steel, 0.07, 0.14, 0.1));
      g.add(mesh(cyl(0.02, 0.025, th * 2, 10), solid("#8e8e96", { metal: 0.6 }), th, 0.1, -0.12));
      g.add(mesh(cyl(0.024, 0.024, 0.02, 10), solid(glow, { emissive: "#ff9f0a", intensity: 1.2 }), th * 2, 0.1, -0.12, true));
      const pipe = mesh(cyl(0.008, 0.008, 0.26, 8), solid("#a1a1aa", { metal: 0.6 }), 0.05, -0.02, -0.03, true);
      pipe.rotation.z = Math.PI / 2;
      g.add(pipe);
      break;
    }
    case "archive": {
      temple(g, 0.4, 0.3, Math.max(0.08, h * 0.7), look, tier);
      break;
    }
    case "studio": {
      g.add(mesh(facadeBox(0.3, h, 0.22), facade(tier, bodyColor, glow), h / 2));
      const glass = mesh(box(0.32, 0.012, 0.25), solid("#9ad7ff", { emissive: glow, intensity: 0.25, transparent: 0.8,
        rough: 0.1, metal: 0.3 }), h + 0.04);
      glass.rotation.z = 0.3;
      g.add(glass);
      break;
    }
    case "power": {
      if (era >= 7) {
        // Zero-point and fusion: a glowing tokamak ring in a dome.
        const core = mesh(torus(0.13, 0.035), solid(glow, { emissive: glow, intensity: 1.4 }), 0.06);
        core.rotation.x = Math.PI / 2;
        g.add(core);
        g.add(mesh(dome(0.2), solid("#c7e8ff", { transparent: 0.35, rough: 0.05, metal: 0.2 }), 0.0));
      } else if (era >= 5) {
        for (let i = 0; i < 6; i += 1) {
          const panel = mesh(box(0.16, 0.006, 0.07), solid("#1d3b6b", { emissive: "#5ac8fa", intensity: 0.12,
            metal: 0.6, rough: 0.15 }), 0.03, i % 2 ? 0.09 : -0.09, -0.15 + Math.floor(i / 2) * 0.12);
          panel.rotation.x = -0.45;
          g.add(panel);
        }
        g.add(mesh(cyl(0.012, 0.012, 0.3, 8), solid("#e5e5ea"), 0.15, 0.2, 0.15, true));
      } else {
        const ch = Math.max(0.2, h * 1.6);
        g.add(mesh(coolingTower(0.09, ch), solid("#cfcac2", { rough: 0.9 }), 0, -0.08, 0.05));
        g.add(mesh(coolingTower(0.08, ch * 0.9), solid("#cfcac2", { rough: 0.9 }), 0, 0.1, 0.07));
        g.add(mesh(facadeBox(0.2, 0.08, 0.1), facade(1, "#8a8278", glow), 0.04, 0, -0.14));
        g.add(mesh(cyl(0.015, 0.02, ch * 1.3, 10), solid("#7a6a62"), ch * 0.65, 0.12, -0.15));
      }
      break;
    }
    case "transit": {
      // A station hall with an arched roof over the platforms.
      const len = 0.42;
      g.add(mesh(box(len, 0.02, 0.2), solid("#a1a1aa"), 0.01));
      const arch = mesh(geo("arch", () => new THREE.CylinderGeometry(0.1, 0.1, len, 20, 1, true, 0, Math.PI)),
        solid(tier >= 2 ? "#bfe6ff" : "#7d8189", { transparent: tier >= 2 ? 0.7 : 1, metal: 0.5, rough: 0.3,
          emissive: tier >= 2 ? glow : "#000000", intensity: tier >= 2 ? 0.15 : 0 }), 0.02);
      arch.rotation.z = Math.PI / 2;
      arch.rotation.y = 0;
      g.add(arch);
      g.add(mesh(facadeBox(0.14, Math.max(0.1, h), 0.12), facade(tier, bodyColor, glow), Math.max(0.1, h) / 2, 0, 0.16));
      break;
    }
    case "spaceport": {
      g.add(mesh(cyl(0.3, 0.32, 0.03, 32), solid("#8e8e96", { rough: 0.8 }), 0.015));
      g.add(mesh(cyl(0.04, 0.045, 0.32, 16), solid("#f2f2f7", { metal: 0.3 }), 0.03 + 0.16));
      g.add(mesh(cone(0.04, 0.09, 16), solid("#ff7a2e", { emissive: "#ff7a2e", intensity: 0.2 }), 0.03 + 0.32 + 0.045));
      for (const a of [0, 2.1, 4.2]) {
        g.add(mesh(cone(0.02, 0.06, 4), solid("#d1d1d6"), 0.06, Math.cos(a) * 0.045, Math.sin(a) * 0.045, true));
      }
      g.add(mesh(box(0.025, 0.4, 0.025), solid("#ff9f0a", { metal: 0.4 }), 0.2, 0.12, 0));
      g.add(mesh(box(0.08, 0.012, 0.012), solid("#ff9f0a", { metal: 0.4 }), 0.3, 0.08, 0, true));
      break;
    }
    default: {
      tower(g, 0.26, 0.26, h, tier, look, seed);
      break;
    }
  }
  return g;
}

// --- construction ----------------------------------------------------------------------------------------------------

function steelFrame(w: number, h: number, d: number): THREE.BufferGeometry {
  return geo(`steel:${w.toFixed(2)}:${h.toFixed(2)}:${d.toFixed(2)}`, () => {
    const points: number[] = [];
    const x = w / 2;
    const z = d / 2;
    for (const [cx, cz] of [[-x, -z], [x, -z], [x, z], [-x, z]]) points.push(cx, 0, cz, cx, h, cz);
    const levels = Math.max(1, Math.min(24, Math.round(h / FLOOR_HEIGHT)));
    for (let i = 1; i <= levels; i += 1) {
      const y = (h * i) / levels;
      points.push(-x, y, -z, x, y, -z, x, y, -z, x, y, z, x, y, z, -x, y, z, -x, y, z, -x, y, -z);
    }
    return new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
  });
}

/** A tower crane: mast, jib and counterweight. The jib (named) turns while it works. */
function crane(height: number, reach: number): THREE.Group {
  const g = new THREE.Group();
  const yellow = solid("#ffcc00", { metal: 0.4, rough: 0.5 });
  g.add(mesh(box(0.02, height, 0.02), yellow, height / 2));
  const jib = new THREE.Group();
  jib.name = "jib";
  jib.position.y = height;
  jib.add(mesh(box(reach, 0.012, 0.014), yellow, 0, reach / 2 - 0.06));
  jib.add(mesh(box(0.05, 0.03, 0.03), solid("#5a5a63"), -0.01, -0.07));
  jib.add(mesh(cyl(0.002, 0.002, 0.12, 4), solid("#3a3a40"), -0.06, reach * 0.7));
  g.add(jib);
  return g;
}

/** Full building: the body, and the rigs that show each phase of building it (state.PHASES). */
export function buildingGroup(kind: string, floors: number, era: number, look: Look | null, tag = "",
  seed = ""): THREE.Group {
  const chosen = look && look.palette?.length === 3 ? look : DEFAULT_LOOK;
  const group = new THREE.Group();
  const rising = body(kind, floors, era, chosen, tag, seed || `${kind}${floors}${era}`);
  rising.name = "body";
  group.add(rising);
  const size = new THREE.Box3().setFromObject(rising).getSize(new THREE.Vector3());
  const w = Math.max(0.12, size.x);
  const d = Math.max(0.12, size.z);
  const h = Math.max(0.05, size.y);

  const pad = mesh(box(w + 0.06, 0.012, d + 0.06), solid("#9a948a", { rough: 1 }), 0.006);
  pad.name = "pad";
  pad.visible = false;
  group.add(pad);

  const frame = new THREE.LineSegments(steelFrame(w * 0.92, h, d * 0.92),
    mat("steel", () => new THREE.LineBasicMaterial({ color: "#ff9f0a", transparent: true, opacity: 0.9 })));
  frame.name = "frame";
  frame.visible = false;
  group.add(frame);

  const scaffold = new THREE.LineSegments(
    geo(`scaffold:${w.toFixed(2)}:${h.toFixed(2)}:${d.toFixed(2)}`, () => new THREE.WireframeGeometry(
      new THREE.BoxGeometry(w + 0.04, h + 0.02, d + 0.04, 2, Math.max(1, Math.min(16, Math.round(h / 0.1))), 2))),
    mat("scaffold", () => new THREE.LineBasicMaterial({ color: "#c7b98a", transparent: true, opacity: 0.55 })));
  scaffold.position.y = (h + 0.02) / 2;
  scaffold.name = "scaffold";
  scaffold.visible = false;
  group.add(scaffold);

  const rig = crane(h + 0.18, Math.max(0.3, w * 1.4));
  rig.position.set(w / 2 + 0.06, 0, -d / 2 - 0.04);
  rig.name = "crane";
  rig.visible = false;
  group.add(rig);

  group.userData.height = h;
  group.userData.size = [w, d];
  return group;
}

/** Which parts show at construction ``progress`` (0..1) — the same phase edges as world/state.py PHASES. */
export function showPhase(group: THREE.Group, progress: number, state: string, t: number, reduced: boolean): void {
  const bodyPart = group.getObjectByName("body");
  const pad = group.getObjectByName("pad");
  const frame = group.getObjectByName("frame");
  const scaffold = group.getObjectByName("scaffold");
  const rig = group.getObjectByName("crane");
  if (!bodyPart || !pad || !frame || !scaffold || !rig) return;
  const standing = state === "standing" && progress >= 0.999;
  const p = Math.min(1, Math.max(0, progress));
  const clamp = (x: number) => Math.min(1, Math.max(0.02, x));
  if (standing) {
    bodyPart.visible = true;
    bodyPart.scale.y = 1;
    pad.visible = frame.visible = scaffold.visible = rig.visible = false;
    return;
  }
  if (state === "demolishing") {
    bodyPart.visible = true;
    bodyPart.scale.y = clamp(p);
    scaffold.visible = true;
    scaffold.scale.y = clamp(p);
    rig.visible = true;
    frame.visible = pad.visible = false;
  } else {
    pad.visible = true;
    rig.visible = p >= 0.06 && p < 0.9;
    frame.visible = p >= 0.2;
    frame.scale.y = clamp((p - 0.2) / 0.42);
    bodyPart.visible = p >= 0.62;
    bodyPart.scale.y = clamp((p - 0.62) / 0.28);
    scaffold.visible = p >= 0.62;
  }
  if (rig.visible && !reduced) {
    const jib = rig.getObjectByName("jib");
    if (jib) jib.rotation.y = Math.sin(t * 0.35 + group.id) * 1.4;
  }
}

// --- figures ---------------------------------------------------------------------------------------------------

export function figureGeometries(): { body: THREE.BufferGeometry; head: THREE.BufferGeometry } {
  return {
    body: geo("figure:body", () => {
      const g = new THREE.CapsuleGeometry(0.026, 0.06, 4, 8);
      g.translate(0, 0.056, 0);
      return g;
    }),
    head: geo("figure:head", () => {
      const g = new THREE.SphereGeometry(0.024, 12, 8);
      g.translate(0, 0.135, 0);
      return g;
    }),
  };
}

export function botGeometry(): THREE.BufferGeometry {
  return geo("common:bot", () => {
    const g = new THREE.BoxGeometry(0.045, 0.045, 0.045);
    g.translate(0, 0.03, 0);
    return g;
  });
}

export function graveGeometry(): THREE.BufferGeometry {
  return geo("grave", () => {
    const g = new THREE.BoxGeometry(0.075, 0.11, 0.024);
    g.translate(0, 0.055, 0);
    return g;
  });
}

// --- markers -------------------------------------------------------------------------------------------------------

function glyphTexture(key: string, glyph: string, fill: string): THREE.Texture {
  const cached = textures.get(key);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext("2d")!;
  ctx.beginPath();
  ctx.arc(64, 64, 56, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.lineWidth = 6;
  ctx.strokeStyle = "rgba(255,255,255,0.85)";
  ctx.stroke();
  ctx.font = "64px system-ui, 'Segoe UI Emoji', sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#ffffff";
  ctx.fillText(glyph, 64, 70);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  textures.set(key, texture);
  return texture;
}

export function warSprite(): THREE.Sprite {
  const sprite = new THREE.Sprite(mat("sprite:war", () => new THREE.SpriteMaterial({
    map: glyphTexture("glyph:war", "⚔", "rgba(255,69,58,0.92)"), depthWrite: false, transparent: true })));
  sprite.scale.set(0.42, 0.42, 1);
  return sprite;
}

export function startupFlag(color: string): THREE.Group {
  const g = new THREE.Group();
  g.add(mesh(cyl(0.008, 0.008, 0.42, 6), solid("#d1d1d6"), 0.21));
  const flag = mesh(geo("flag", () => new THREE.PlaneGeometry(0.18, 0.11)),
    mat(`flag:${color}`, () => new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.5,
      side: THREE.DoubleSide })), 0.36, 0.09);
  g.add(flag);
  return g;
}

export function stationMesh(): THREE.Group {
  const g = new THREE.Group();
  const ring = mesh(geo("station:ring", () => new THREE.TorusGeometry(0.62, 0.07, 12, 48)),
    solid("#d1d1d6", { metal: 0.7, rough: 0.3, emissive: "#64d2ff", intensity: 0.25 }));
  g.add(ring);
  g.add(mesh(geo("station:hub", () => new THREE.SphereGeometry(0.16, 16, 12)), solid("#e5e5ea", { metal: 0.6 })));
  for (const angle of [0, Math.PI / 2, Math.PI, Math.PI * 1.5]) {
    const spoke = mesh(cyl(0.015, 0.015, 0.62, 6), solid("#8e8e96", { metal: 0.6 }));
    spoke.rotation.z = Math.PI / 2;
    spoke.rotation.y = angle;
    spoke.position.set(Math.cos(angle) * 0.31, 0, -Math.sin(angle) * 0.31);
    g.add(spoke);
  }
  const panel = mesh(box(0.9, 0.01, 0.22), solid("#1d3b6b", { emissive: "#5ac8fa", intensity: 0.3, metal: 0.4 }));
  panel.position.y = 0.32;
  g.add(panel);
  return g;
}

export function artificialPlanet(index: number): THREE.Group {
  const g = new THREE.Group();
  const colors = ["#a594ff", "#30d158", "#ff9f0a"];
  const color = colors[index % colors.length];
  g.add(mesh(geo("aplanet", () => new THREE.SphereGeometry(1.1, 32, 24)),
    solid(color, { emissive: color, intensity: 0.25, metal: 0.5, rough: 0.4 })));
  const band = mesh(geo("aplanet:band", () => new THREE.TorusGeometry(1.6, 0.04, 8, 64)),
    solid("#ffffff", { emissive: color, intensity: 0.8 }));
  band.rotation.x = Math.PI / 2.4;
  g.add(band);
  return g;
}

/** Shared solids for other modules (transport), from the same cache. */
export function sharedSolid(color: string, opts: { emissive?: string; intensity?: number; rough?: number;
  metal?: number; transparent?: number } = {}): THREE.Material {
  return solid(color, opts);
}
