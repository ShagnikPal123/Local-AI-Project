/** What things look like on the planet: buildings by kind, floors and era, the figures, graves, markers and the
 * things in orbit. Geometry and materials are shared through small caches — a world of 900 buildings and 400 AIs
 * must stay one smooth scene. */

import * as THREE from "three";
import { FLOOR_HEIGHT } from "./geo";

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

/** Rows of lit and unlit windows, repeated once per floor. */
function windowTexture(floors: number): THREE.Texture {
  const key = `windows:${Math.min(80, Math.max(1, floors))}`;
  const cached = textures.get(key);
  if (cached) return cached;
  let base = textures.get("windows:base");
  if (!base) {
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 16;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, 64, 16);
    for (let column = 0; column < 6; column += 1) {
      const lit = (column * 7 + 3) % 5 !== 0;
      ctx.fillStyle = lit ? "#ffe9a8" : "#1a1a22";
      ctx.fillRect(3 + column * 10, 4, 6, 8);
    }
    base = new THREE.CanvasTexture(canvas);
    base.colorSpace = THREE.SRGBColorSpace;
    base.wrapS = THREE.RepeatWrapping;
    base.wrapT = THREE.RepeatWrapping;
    textures.set("windows:base", base);
  }
  const texture = base.clone();
  texture.needsUpdate = true;
  texture.repeat.set(1, Math.max(1, floors));
  textures.set(key, texture);
  return texture;
}

function lightLevel(era: number): number {
  return 0.25 + era * 0.16;
}

function wall(look: Look, era: number, floors: number, windows = true): THREE.Material {
  const [body, glow] = look.palette;
  const key = `wall:${body}:${glow}:${era}:${windows ? floors : 0}`;
  return mat(key, () => new THREE.MeshStandardMaterial({
    color: new THREE.Color(body), roughness: 0.62, metalness: 0.12 + era * 0.05,
    emissive: windows ? new THREE.Color(glow) : new THREE.Color("#000000"),
    emissiveMap: windows ? windowTexture(floors) : null,
    emissiveIntensity: windows ? lightLevel(era) : 0,
  }));
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

function mesh(geometry: THREE.BufferGeometry, material: THREE.Material, y = 0, x = 0, z = 0): THREE.Mesh {
  const m = new THREE.Mesh(geometry, material);
  m.position.set(x, y, z);
  m.castShadow = false;
  m.receiveShadow = false;
  return m;
}

const box = (w: number, h: number, d: number) => geo(`box:${w}:${h.toFixed(3)}:${d}`, () => new THREE.BoxGeometry(w, h, d));
const cyl = (top: number, bottom: number, h: number, sides = 14) =>
  geo(`cyl:${top}:${bottom}:${h.toFixed(3)}:${sides}`, () => new THREE.CylinderGeometry(top, bottom, h, sides));
const cone = (r: number, h: number, sides = 4) => geo(`cone:${r}:${h.toFixed(3)}:${sides}`, () => new THREE.ConeGeometry(r, h, sides));
const dome = (r: number) => geo(`dome:${r}`, () => new THREE.SphereGeometry(r, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2));

/** The body of a building — everything that rises during construction. Origin at ground level. */
function body(kind: string, floors: number, era: number, look: Look): THREE.Group {
  const g = new THREE.Group();
  const [, glow, roof] = look.palette;
  const h = Math.max(0.05, floors * FLOOR_HEIGHT);
  switch (kind) {
    case "house": {
      const hh = Math.max(0.05, floors * 0.06);
      g.add(mesh(box(0.17, hh, 0.17), wall(look, era, floors, era >= 2), hh / 2));
      const r = mesh(cone(0.15, 0.09, 4), solid(roof), hh + 0.045);
      r.rotation.y = Math.PI / 4;
      g.add(r);
      break;
    }
    case "council": {
      g.add(mesh(cyl(0.13, 0.15, h), wall(look, era, floors), h / 2));
      g.add(mesh(dome(0.13), solid(glow, { emissive: glow, intensity: 0.35, metal: 0.4, rough: 0.35 }), h));
      break;
    }
    case "capitol": {
      g.add(mesh(box(0.56, 0.06, 0.56), solid(roof), 0.03));
      g.add(mesh(cyl(0.19, 0.21, h), wall(look, era, floors), 0.06 + h / 2));
      g.add(mesh(dome(0.2), solid("#e9d9a6", { emissive: "#ffd60a", intensity: 0.25, metal: 0.6, rough: 0.3 }), 0.06 + h));
      for (let i = 0; i < 10; i += 1) {
        const a = (i / 10) * Math.PI * 2;
        g.add(mesh(cyl(0.018, 0.018, h * 0.85, 8), solid("#e5e5ea"), 0.06 + h * 0.425, Math.cos(a) * 0.25, Math.sin(a) * 0.25));
      }
      g.add(mesh(cyl(0.006, 0.006, 0.22, 6), solid("#d1d1d6"), 0.06 + h + 0.2 + 0.11));
      break;
    }
    case "tower": {
      g.add(mesh(cyl(0.1, 0.15, h, 6), wall(look, era, floors), h / 2));
      g.add(mesh(cone(0.05, Math.max(0.12, h * 0.22), 6), solid(glow, { emissive: glow, intensity: 0.6 }), h + Math.max(0.12, h * 0.22) / 2));
      break;
    }
    case "lab": {
      g.add(mesh(cyl(0.16, 0.16, h, 16), wall(look, era, floors), h / 2));
      g.add(mesh(dome(0.16), solid("#9ad7ff", { emissive: "#64d2ff", intensity: 0.45, transparent: 0.85, rough: 0.1, metal: 0.3 }), h));
      break;
    }
    case "data_center": {
      const lh = Math.max(0.05, h * 0.55);
      // Dark halls with rows of status lights — the lights come from the window texture, not the whole box.
      const rows = Math.max(1, Math.round(floors * 0.55));
      const hall = mat(`dc:${glow}:${era}:${rows}`, () => new THREE.MeshStandardMaterial({
        color: new THREE.Color("#30343f"), roughness: 0.45, metalness: 0.55, emissive: new THREE.Color(glow),
        emissiveMap: windowTexture(rows), emissiveIntensity: lightLevel(era) * 1.4 }));
      g.add(mesh(box(0.42, lh, 0.28), hall, lh / 2));
      for (let i = 0; i < 3; i += 1) {
        g.add(mesh(cyl(0.035, 0.035, 0.05, 10), solid("#8e8e96", { metal: 0.6 }), lh + 0.025, -0.12 + i * 0.12, 0));
      }
      break;
    }
    case "mine": {
      g.add(mesh(cone(0.24, 0.16, 5), solid("#4a3f35", { rough: 0.95 }), 0.08));
      const fh = Math.max(0.16, h * 0.9);
      g.add(mesh(box(0.02, fh, 0.02), solid("#8a6d3b", { metal: 0.3 }), fh / 2, -0.07, 0));
      g.add(mesh(box(0.02, fh, 0.02), solid("#8a6d3b", { metal: 0.3 }), fh / 2, 0.07, 0));
      g.add(mesh(box(0.18, 0.02, 0.03), solid("#8a6d3b", { metal: 0.3 }), fh));
      g.add(mesh(cyl(0.03, 0.03, 0.02, 12), solid(glow, { emissive: glow, intensity: 0.8 }), fh + 0.02));
      break;
    }
    case "farm": {
      g.add(mesh(box(0.46, 0.012, 0.46), solid("#4c7a3a", { rough: 1 }), 0.006));
      for (let i = 0; i < 4; i += 1) g.add(mesh(box(0.42, 0.014, 0.03), solid("#6aa84f", { rough: 1 }), 0.014, 0, -0.15 + i * 0.1));
      const sh = Math.max(0.12, h);
      g.add(mesh(cyl(0.05, 0.05, sh, 12), solid("#c9c3b8"), sh / 2, 0.17, 0.17));
      g.add(mesh(dome(0.05), solid(roof), sh, 0.17, 0.17));
      break;
    }
    case "factory": {
      const fh = Math.max(0.06, h * 0.7);
      g.add(mesh(box(0.36, fh, 0.24), wall(look, era, Math.max(1, Math.round(floors * 0.7))), fh / 2));
      g.add(mesh(cyl(0.03, 0.035, fh * 1.6, 10), solid("#5a5a63"), fh * 0.8, 0.1, -0.06));
      g.add(mesh(cyl(0.03, 0.035, fh * 1.35, 10), solid("#5a5a63"), fh * 0.675, 0.02, -0.06));
      break;
    }
    case "refinery": {
      const th = Math.max(0.08, h * 0.6);
      g.add(mesh(cyl(0.085, 0.085, th, 16), solid("#c7c7cc", { metal: 0.5, rough: 0.35 }), th / 2, -0.1, 0));
      g.add(mesh(cyl(0.07, 0.07, th * 0.8, 16), solid("#c7c7cc", { metal: 0.5, rough: 0.35 }), th * 0.4, 0.08, 0.05));
      g.add(mesh(cyl(0.025, 0.025, th * 1.8, 8), solid("#8e8e96", { metal: 0.6 }), th * 0.9, 0.08, -0.1));
      g.add(mesh(cyl(0.03, 0.03, 0.02, 10), solid(glow, { emissive: glow, intensity: 0.9 }), th * 1.8, 0.08, -0.1));
      break;
    }
    case "archive": {
      const ah = Math.max(0.06, h * 0.7);
      g.add(mesh(box(0.38, ah, 0.24), wall(look, era, Math.max(1, Math.round(floors * 0.7)), false), ah / 2, 0, -0.02));
      for (let i = 0; i < 5; i += 1) g.add(mesh(cyl(0.012, 0.012, ah, 8), solid("#e5e5ea"), ah / 2, -0.16 + i * 0.08, 0.12));
      g.add(mesh(box(0.42, 0.025, 0.3), solid(roof), ah + 0.012));
      break;
    }
    case "studio": {
      g.add(mesh(box(0.28, h, 0.22), wall(look, era, floors), h / 2));
      const r = mesh(box(0.3, 0.02, 0.26), solid(glow, { emissive: glow, intensity: 0.3 }), h + 0.04);
      r.rotation.z = 0.32;
      g.add(r);
      break;
    }
    case "bank": {
      g.add(mesh(box(0.3, h, 0.3), wall(look, era, floors), h / 2));
      g.add(mesh(dome(0.12), solid("#e9d9a6", { emissive: "#ffd60a", intensity: 0.2, metal: 0.6, rough: 0.3 }), h));
      break;
    }
    default: {  // office
      g.add(mesh(box(0.26, h, 0.26), wall(look, era, floors), h / 2));
      break;
    }
  }
  // The era's own look, chosen by the managing AI (U37): spires, domes or rings on the taller workplaces.
  if (floors >= 4 && ["office", "tower", "bank", "studio", "lab"].includes(kind)) {
    if (look.style === "spire") g.add(mesh(cone(0.05, 0.18, 8), solid(glow, { emissive: glow, intensity: 0.7 }), h + 0.09));
    else if (look.style === "dome" && kind === "office") g.add(mesh(dome(0.11), solid(glow, { emissive: glow, intensity: 0.4 }), h));
    else if (look.style === "ring") {
      const ring = mesh(geo("ring:0.22", () => new THREE.TorusGeometry(0.22, 0.012, 8, 32)),
        solid(glow, { emissive: glow, intensity: 0.9 }), h * 0.6);
      ring.rotation.x = Math.PI / 2;
      g.add(ring);
    }
  }
  return g;
}

/** Full building: the body that rises, and a scaffold while it is being built. */
export function buildingGroup(kind: string, floors: number, era: number, look: Look | null): THREE.Group {
  const chosen = look && look.palette?.length === 3 ? look : DEFAULT_LOOK;
  const group = new THREE.Group();
  const rising = body(kind, floors, era, chosen);
  rising.name = "body";
  group.add(rising);
  const size = new THREE.Box3().setFromObject(rising).getSize(new THREE.Vector3());
  const frame = new THREE.LineSegments(
    geo(`frame:${size.x.toFixed(2)}:${size.y.toFixed(2)}:${size.z.toFixed(2)}`,
      () => new THREE.EdgesGeometry(new THREE.BoxGeometry(size.x + 0.04, size.y + 0.02, size.z + 0.04))),
    mat("frame", () => new THREE.LineBasicMaterial({ color: "#ffd60a", transparent: true, opacity: 0.75 })));
  frame.position.y = size.y / 2;
  frame.name = "scaffold";
  frame.visible = false;
  group.add(frame);
  group.userData.height = size.y;
  return group;
}

// --- figures ---------------------------------------------------------------------

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

// --- markers -------------------------------------------------------------------------

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
