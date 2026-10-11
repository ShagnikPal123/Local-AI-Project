/** The planet (U34–U39): a world you can orbit, zoom from the whole planet down to one workplace, and click.
 *
 * Everything drawn is real state. Territories are the office's sections; buildings rise floor by floor with finished
 * tasks; every AI is a small human figure that walks to its workplace when it has work, wanders when it is awake and
 * idle, and lies down at home when it sleeps; common bots (no model) build and keep things; graves stand in the
 * capital's cemetery; a contest of ideas is a red arc with crossed swords; a start-up flies its flag; stations and
 * artificial planets orbit once the planet is full. Messages between agents fly as pulses along talk lines.
 *
 * Controls: drag to orbit, scroll to zoom, click anything for its details (it flies there), Escape or "Whole planet"
 * to come back out. Reduced motion stops the drifting and the walking animation (figures jump to where they are).
 */

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { KIND_LABELS } from "../format";
import type { Pick, WorldBot, WorldBuilding, WorldSector, WorldSnapshot } from "../types";
import {
  GOV_SPACING, R, arcPoints, hash, latLonToVec, offsetOnSurface, plotPosition, plotsFor, sectorReach,
  setPlanetRadius, slerpSurface, standUp, tangentFrame,
} from "./geo";
import {
  ATMOSPHERE_FRAGMENT, ATMOSPHERE_VERTEX, Terrain, WATER_DEPTH, cloudTexture, moonMeshes, paintPlanet,
  planetGeometry as makePlanetGeometry, ringMesh, seaMaterial, type Site,
} from "./surface";
import {
  artificialPlanet, botGeometry, buildingGroup, disposeMeshCaches, figureGeometries, graveGeometry, showPhase,
  startupFlag, stationMesh, warSprite, type Look,
} from "./meshes";
import { Transport, type TransportNode } from "./transport";

export interface PlanetHandle {
  focus: (pick: Pick | null) => void;
  zoom: (factor: number) => void;
  reset: () => void;
}

export interface AgentLook {
  status: string;
  role: string;
  employment?: string;
  step?: string;
}

interface Props {
  snapshot: WorldSnapshot;
  version: number;
  agents: Record<string, AgentLook>;
  roleColors: Record<string, string>;
  sectionColors: Record<string, string>;
  talks: { id: string; from: string; to: string[]; at: number }[];
  selected: Pick | null;
  onPick: (pick: Pick | null) => void;
  onLevel?: (level: "planet" | "sector" | "workplace") => void;
  /** Pixels on the right covered by the details card: the view shifts left so what was picked stays in sight. */
  inset?: number;
}

const WORKPLACES = new Set(["office", "lab", "data_center", "mine", "farm", "factory", "refinery", "archive", "studio",
  "bank", "tower"]);
/** The government's district is not a sector: its buildings carry this instead of a sector id (world/state.py). */
const GOV = "gov";
const PROXY_MATERIAL = new THREE.MeshBasicMaterial({ visible: false });

/** Bake finished buildings into a few meshes per material: one district is a handful of draw calls, however big.
 * Small parts (rooftop plant, columns, antennas) go into a second set that hides from far away. */
function bake(groups: THREE.Group[]): { main: THREE.Mesh[]; detail: THREE.Mesh[] } {
  const buckets = [new Map<THREE.Material, THREE.BufferGeometry[]>(), new Map<THREE.Material, THREE.BufferGeometry[]>()];
  for (const group of groups) {
    group.updateMatrixWorld(true);
    const body = group.getObjectByName("body");
    body?.traverse((object) => {
      const item = object as THREE.Mesh;
      if (!item.isMesh || Array.isArray(item.material)) return;
      const copy = item.geometry.clone().applyMatrix4(item.matrixWorld);
      const flat = copy.index ? copy.toNonIndexed() : copy;
      if (flat !== copy) copy.dispose();
      for (const name of Object.keys(flat.attributes)) {
        if (!["position", "normal", "uv"].includes(name)) flat.deleteAttribute(name);
      }
      if (!flat.getAttribute("uv")) {
        flat.setAttribute("uv", new THREE.Float32BufferAttribute(new Float32Array(flat.getAttribute("position").count * 2), 2));
      }
      const bucket = buckets[item.userData.detail ? 1 : 0];
      const list = bucket.get(item.material) ?? [];
      list.push(flat);
      bucket.set(item.material, list);
    });
  }
  const [main, detail] = buckets.map((bucket) => Array.from(bucket.entries()).flatMap(([material, list]) => {
    const merged = mergeGeometries(list, false);
    list.forEach((g) => g.dispose());
    if (!merged) return [];
    const made = new THREE.Mesh(merged, material);
    made.raycast = () => undefined;
    return [made];
  }));
  return { main, detail };
}

interface District {
  signature: string;
  centre: THREE.Vector3;
  main: THREE.Mesh[];
  detail: THREE.Mesh[];
  proxies: THREE.Mesh[];
}
const MAX_FIGURES = 512;
const MAX_COMMON = 640;
const MAX_GRAVES = 520;
const UP = new THREE.Vector3(0, 1, 0);
const LIE = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2);

/** Shift the picture left by half the covered width, so the middle of what is left is the middle of the view. */
function applyInset(camera: THREE.PerspectiveCamera, width: number, height: number, inset: number): void {
  if (inset > 0 && width > inset * 1.4) camera.setViewOffset(width, height, inset / 2, 0, width, height);
  else camera.clearViewOffset();
  camera.updateProjectionMatrix();
}

/** Remove a group's children and free what only they used (materials made per item, their geometry). */
function disposeChildren(group: THREE.Object3D): void {
  for (const child of [...group.children]) {
    group.remove(child);
    const item = child as THREE.Mesh;
    item.geometry?.dispose();
    const material = item.material as THREE.Material | THREE.Material[] | undefined;
    if (Array.isArray(material)) material.forEach((m) => m.dispose());
    else material?.dispose();
  }
}

interface Figure {
  aid: string;
  pos: THREE.Vector3;
  target: THREE.Vector3;
  home: THREE.Vector3;
  work: THREE.Vector3;
  wander: THREE.Vector3;
  nextWander: number;
  asleep: boolean;
  working: boolean;
  color: THREE.Color;
  phase: number;
  yaw: number;
}

interface Pulse {
  line: THREE.Line;
  dot: THREE.Mesh;
  points: THREE.Vector3[];
  born: number;
}

interface Fly {
  fromTarget: THREE.Vector3;
  toTarget: THREE.Vector3;
  fromCamera: THREE.Vector3;
  toCamera: THREE.Vector3;
  start: number;
  duration: number;
}

function sectorColor(sid: string, colors: Record<string, string>): string {
  return colors[sid] || `hsl(${Math.round(hash(sid) * 360)}, 70%, 65%)`;
}

export const PlanetScene = forwardRef<PlanetHandle, Props>(function PlanetScene(props, ref) {
  const { snapshot, version, agents, roleColors, sectionColors, talks, selected, onPick, onLevel, inset = 0 } = props;
  const host = useRef<HTMLDivElement | null>(null);
  const labelLayer = useRef<HTMLDivElement | null>(null);
  const tip = useRef<HTMLDivElement | null>(null);
  const latest = useRef({ snapshot, agents, roleColors, sectionColors, onPick, onLevel, selected, inset });
  latest.current = { snapshot, agents, roleColors, sectionColors, onPick, onLevel, selected, inset };

  // Everything three.js lives here, made once per mount.
  const three = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    controls: OrbitControls;
    planetGeometry: THREE.BufferGeometry;
    planet: THREE.Mesh;
    clouds: THREE.Mesh;
    territories: THREE.Group;
    buildings: THREE.Group;
    baked: THREE.Group;
    proxies: THREE.Group;
    districts: Map<string, District>;
    dirty: Set<string>;
    terrain: Terrain;
    siteKey: string;
    sea: THREE.Mesh;
    moons: THREE.Group;
    transport: Transport;
    look: Look | null;
    markers: THREE.Group;
    sky: THREE.Group;
    lines: THREE.Group;
    lights: THREE.Points;
    bodies: THREE.InstancedMesh;
    heads: THREE.InstancedMesh;
    commons: THREE.InstancedMesh;
    graves: THREE.InstancedMesh;
    ring: THREE.Mesh;
    /** Buildings under construction or coming down: drawn on their own, phase by phase. */
    built: Map<number, { group: THREE.Group; key: string; shown: number; district: string }>;
    wars: Map<string, { sprite: THREE.Sprite; line: THREE.Line }>;
    flags: Map<string, THREE.Group>;
    figures: Figure[];
    figureIndex: Map<string, number>;
    commonSites: { site: THREE.Vector3; phase: number; radius: number }[];
    graveIds: number[];
    pulses: Pulse[];
    seenTalks: Set<string>;
    fly: Fly | null;
    era: number;
    lookKey: string;
    reduced: boolean;
    lastInteract: number;
    level: "planet" | "sector" | "workplace";
  } | null>(null);

  // ------------------------------------------------------------------ set up once

  useEffect(() => {
    const element = host.current;
    if (!element) return undefined;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.setClearColor("#000000");
    element.appendChild(renderer.domElement);
    renderer.domElement.className = "wld-canvas";
    renderer.domElement.setAttribute("aria-hidden", "true");

    // The planet's own size and look come from the world's seed (world/planet.py).
    const planetLook = latest.current.snapshot.planet;
    setPlanetRadius(planetLook?.radius ?? 1);
    const terrain = new Terrain(planetLook);
    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    const environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = environment;
    scene.environmentIntensity = 0.45;
    const camera = new THREE.PerspectiveCamera(42, 1, 0.05, 6000);
    camera.position.set(0, R * 0.9, R * 3.2);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.enablePan = false;
    controls.minDistance = R * 1.25;
    controls.maxDistance = R * 14;
    controls.rotateSpeed = 0.6;
    controls.zoomSpeed = 0.9;

    scene.add(new THREE.AmbientLight("#8a90b8", 0.55));
    scene.add(new THREE.HemisphereLight("#cfd8ff", "#1a1420", 0.55));
    const sun = new THREE.DirectionalLight("#fff4e0", 2.3);
    sun.position.set(-40, 26, 30);
    scene.add(sun);
    const rim = new THREE.DirectionalLight("#7f74ff", 0.6);
    rim.position.set(40, -10, -30);
    scene.add(rim);

    // Stars.
    const starPositions = new Float32Array(2600 * 3);
    for (let i = 0; i < 2600; i += 1) {
      const v = new THREE.Vector3(hash(`s${i}x`) - 0.5, hash(`s${i}y`) - 0.5, hash(`s${i}z`) - 0.5).normalize()
        .multiplyScalar(R * 70 + hash(`s${i}d`) * R * 40);
      starPositions.set([v.x, v.y, v.z], i * 3);
    }
    const stars = new THREE.Points(new THREE.BufferGeometry().setAttribute("position",
      new THREE.BufferAttribute(starPositions, 3)), new THREE.PointsMaterial({ color: "#ffffff", size: 1.4,
      sizeAttenuation: false, transparent: true, opacity: 0.7 }));
    scene.add(stars);

    const planetGeometry = makePlanetGeometry();
    paintPlanet(planetGeometry, terrain, 0);
    const planet = new THREE.Mesh(planetGeometry, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9,
      metalness: 0.02, envMapIntensity: 0.25 }));
    planet.userData.pick = { kind: "world" } satisfies Pick;
    scene.add(planet);
    const sea = new THREE.Mesh(new THREE.SphereGeometry(R - WATER_DEPTH, 160, 110), seaMaterial(terrain.planet));
    sea.raycast = () => undefined;
    scene.add(sea);
    if (terrain.planet.rings) scene.add(ringMesh(terrain.planet));
    const moons = new THREE.Group();
    moonMeshes(terrain.planet).forEach((moon) => moons.add(moon));
    scene.add(moons);

    const atmosphereUniforms = { uColor: { value: new THREE.Color(terrain.planet.air) }, uStrength: { value: 0.6 } };
    const atmosphere = new THREE.Mesh(new THREE.SphereGeometry(R * 1.045, 64, 48), new THREE.ShaderMaterial({
      vertexShader: ATMOSPHERE_VERTEX, fragmentShader: ATMOSPHERE_FRAGMENT, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, uniforms: atmosphereUniforms,
    }));
    atmosphere.raycast = () => undefined;
    scene.add(atmosphere);

    const clouds = new THREE.Mesh(new THREE.SphereGeometry(R * 1.03, 96, 64), new THREE.MeshStandardMaterial({
      map: cloudTexture(terrain.planet), transparent: true, depthWrite: false, opacity: 0.0, roughness: 1 }));
    clouds.raycast = () => undefined;
    scene.add(clouds);

    const territories = new THREE.Group();
    const buildings = new THREE.Group();
    const baked = new THREE.Group();
    const proxies = new THREE.Group();
    const markers = new THREE.Group();
    const sky = new THREE.Group();
    const lines = new THREE.Group();
    const transport = new Transport();
    scene.add(territories, buildings, baked, proxies, markers, sky, lines, transport.group);

    const lights = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({ color: "#ffd78a", size: 0.07,
      transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false }));
    lights.raycast = () => undefined;
    scene.add(lights);

    const figureGeo = figureGeometries();
    const bodies = new THREE.InstancedMesh(figureGeo.body, new THREE.MeshStandardMaterial({ roughness: 0.55 }), MAX_FIGURES);
    const heads = new THREE.InstancedMesh(figureGeo.head, new THREE.MeshStandardMaterial({ color: "#f2dcc6", roughness: 0.6 }), MAX_FIGURES);
    bodies.count = 0;
    heads.count = 0;
    bodies.frustumCulled = false;
    heads.frustumCulled = false;
    // The figures move every frame: a fixed bound around the whole planet keeps clicks finding them.
    bodies.boundingSphere = new THREE.Sphere(new THREE.Vector3(), R * 1.2);
    heads.raycast = () => undefined;
    const commons = new THREE.InstancedMesh(botGeometry(), new THREE.MeshStandardMaterial({ color: "#ffcc4d",
      emissive: "#ff9f0a", emissiveIntensity: 0.35, metalness: 0.5, roughness: 0.4 }), MAX_COMMON);
    commons.count = 0;
    commons.frustumCulled = false;
    commons.raycast = () => undefined;
    const graves = new THREE.InstancedMesh(graveGeometry(), new THREE.MeshStandardMaterial({ color: "#8e8e96", roughness: 0.9 }), MAX_GRAVES);
    graves.count = 0;
    graves.frustumCulled = false;
    graves.boundingSphere = new THREE.Sphere(new THREE.Vector3(), R * 1.2);
    scene.add(bodies, heads, commons, graves);

    const ring = new THREE.Mesh(new THREE.RingGeometry(0.16, 0.2, 40), new THREE.MeshBasicMaterial({ color: "#a594ff",
      transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }));
    ring.visible = false;
    ring.raycast = () => undefined;
    scene.add(ring);

    three.current = {
      renderer, scene, camera, controls, planetGeometry, planet, clouds, territories, buildings, baked, proxies,
      districts: new Map(), dirty: new Set(), terrain, siteKey: "", sea, moons, transport, look: null,
      markers, sky, lines,
      lights, bodies, heads, commons, graves, ring, built: new Map(), wars: new Map(), flags: new Map(), figures: [],
      figureIndex: new Map(), commonSites: [], graveIds: [], pulses: [], seenTalks: new Set(), fly: null, era: -1,
      lookKey: "", reduced, lastInteract: performance.now(), level: "planet",
    };

    const resize = () => {
      const width = element.clientWidth || 1;
      const height = element.clientHeight || 1;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      applyInset(camera, width, height, latest.current.inset);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);

    controls.addEventListener("start", () => {
      if (three.current) {
        three.current.lastInteract = performance.now();
        three.current.fly = null;
      }
    });

    // --- picking and hovering
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let down: { x: number; y: number } | null = null;
    const pickAt = (clientX: number, clientY: number): { pick: Pick | null; point: THREE.Vector3 | null } => {
      const state = three.current;
      if (!state) return { pick: null, point: null };
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects([state.buildings, state.proxies, state.markers, state.sky, state.bodies,
        state.graves, state.territories, state.planet], true);
      for (const hit of hits) {
        if (hit.object === state.bodies && hit.instanceId !== undefined) {
          const figure = state.figures[hit.instanceId];
          if (figure) return { pick: { kind: "bot", id: figure.aid }, point: hit.point };
        }
        if (hit.object === state.graves && hit.instanceId !== undefined) {
          const gid = state.graveIds[hit.instanceId];
          if (gid !== undefined) return { pick: { kind: "grave", id: gid }, point: hit.point };
        }
        let object: THREE.Object3D | null = hit.object;
        while (object && !object.userData.pick) object = object.parent;
        if (object?.userData.pick) return { pick: object.userData.pick as Pick, point: hit.point };
      }
      return { pick: null, point: null };
    };
    const onDown = (event: PointerEvent) => {
      down = { x: event.clientX, y: event.clientY };
    };
    const onUp = (event: PointerEvent) => {
      if (!down) return;
      const moved = Math.hypot(event.clientX - down.x, event.clientY - down.y);
      down = null;
      if (moved > 6) return;
      const { pick } = pickAt(event.clientX, event.clientY);
      latest.current.onPick(pick && pick.kind === "world" ? null : pick);
    };
    let hoverAt = 0;
    const onMove = (event: PointerEvent) => {
      const now = performance.now();
      if (now - hoverAt < 70 || down) return;
      hoverAt = now;
      const { pick } = pickAt(event.clientX, event.clientY);
      const words = pick && pick.kind !== "world" ? describePick(pick) : "";
      renderer.domElement.style.cursor = words ? "pointer" : "grab";
      if (tip.current) {
        tip.current.textContent = words;
        tip.current.style.opacity = words ? "1" : "0";
        const rect = element.getBoundingClientRect();
        tip.current.style.transform = `translate(${event.clientX - rect.left + 14}px, ${event.clientY - rect.top + 12}px)`;
      }
    };
    const onLeave = () => {
      if (tip.current) tip.current.style.opacity = "0";
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);
    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("pointerleave", onLeave);

    // --- the loop
    let frame = 0;
    let frameCount = 0;
    let last = performance.now();
    const matrix = new THREE.Matrix4();
    const quaternion = new THREE.Quaternion();
    const yawQ = new THREE.Quaternion();
    const scale = new THREE.Vector3(1, 1, 1);
    const temp = new THREE.Vector3();
    const dim = new THREE.Color();
    const animate = () => {
      frame = requestAnimationFrame(animate);
      const state = three.current;
      if (!state || document.hidden) return;
      const now = performance.now();
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const t = now / 1000;
      const world = latest.current.snapshot.world;
      const running = world.status === "running";
      const walk = (running ? 0.32 : 0.14) * Math.max(0.4, world.walk || 1);

      // Flying to something the owner picked.
      if (state.fly) {
        const k = Math.min(1, (now - state.fly.start) / state.fly.duration);
        const e = 1 - Math.pow(1 - k, 3);
        controls.target.lerpVectors(state.fly.fromTarget, state.fly.toTarget, e);
        camera.position.lerpVectors(state.fly.fromCamera, state.fly.toCamera, e);
        if (k >= 1) state.fly = null;
      }
      // A slow drift when nobody has touched the planet for a while — never under reduced motion.
      controls.autoRotate = !state.reduced && state.level === "planet" && now - state.lastInteract > 9000 && !state.fly;
      controls.autoRotateSpeed = 0.25;
      controls.update();
      if (camera.position.length() < R + 0.35) camera.position.setLength(R + 0.35);
      if (!state.reduced) state.clouds.rotation.y += dt * 0.004;

      // Buildings go through their phases toward the progress the world reports; a finished one joins its
      // district's baked meshes.
      state.built.forEach((entry, bid) => {
        const building = entry.group.userData.building as WorldBuilding;
        const goal = building.state === "standing" ? 1 : Math.max(0.02, building.progress);
        entry.shown += (goal - entry.shown) * Math.min(1, dt * (state.reduced ? 30 : 1.6));
        showPhase(entry.group, entry.shown, building.state, t, state.reduced);
        if (building.state === "standing" && entry.shown > 0.995) {
          state.buildings.remove(entry.group);
          state.built.delete(bid);
          state.dirty.add(entry.district);
        }
      });
      if (state.dirty.size && frameCount % 20 === 0) {
        for (const district of Array.from(state.dirty)) rebake(district);
        state.dirty.clear();
      }
      frameCount += 1;
      // Rooftop plant, columns and antennas only when you are close enough to see them.
      state.districts.forEach((district) => {
        const near = camera.position.distanceTo(district.centre) < R * 0.75;
        district.detail.forEach((m) => { m.visible = near; });
      });
      state.transport.tick(dt, t, state.reduced, running);
      state.moons.children.forEach((moon) => {
        const orbit = moon.userData.orbit as { radius: number; speed: number; tilt: number; phase: number };
        const a = (state.reduced ? 0 : t * orbit.speed) + orbit.phase;
        moon.position.set(Math.cos(a) * orbit.radius, Math.sin(a) * orbit.radius * Math.sin(orbit.tilt),
          Math.sin(a) * orbit.radius * Math.cos(orbit.tilt));
      });

      // The AIs walk.
      const figures = state.figures;
      for (let i = 0; i < figures.length; i += 1) {
        const f = figures[i];
        if (!f.working && !f.asleep && now > f.nextWander) {
          f.wander = offsetOnSurface(f.home, (hash(`${f.aid}${Math.floor(now / 5000)}x`) - 0.5) * 0.9,
            (hash(`${f.aid}${Math.floor(now / 5000)}y`) - 0.5) * 0.9);
          f.nextWander = now + 4000 + hash(`${f.aid}${now}`) * 5000;
        }
        f.target = f.asleep ? f.home : f.working ? f.work : f.wander;
        const distance = f.pos.distanceTo(f.target);
        let moving = false;
        if (state.reduced) {
          f.pos.copy(f.target);
        } else if (distance > 0.005) {
          const step = Math.min(1, (walk * dt) / distance);
          temp.copy(f.pos);
          slerpSurface(f.pos, f.target, step, f.pos);
          moving = true;
          const { east, north } = tangentFrame(f.pos.clone().normalize());
          const dir = f.pos.clone().sub(temp);
          if (dir.lengthSq() > 1e-9) f.yaw = Math.atan2(dir.dot(east), dir.dot(north));
        }
        quaternion.setFromUnitVectors(UP, temp.copy(f.pos).normalize());
        yawQ.setFromAxisAngle(UP, f.yaw);
        quaternion.multiply(yawQ);
        if (f.asleep) quaternion.multiply(LIE);
        const bob = moving && !state.reduced ? Math.abs(Math.sin(t * 9 + f.phase)) * 0.012 : 0;
        temp.copy(f.pos).setLength(R + (f.asleep ? 0.03 : 0) + bob);
        matrix.compose(temp, quaternion, scale);
        state.bodies.setMatrixAt(i, matrix);
        state.heads.setMatrixAt(i, matrix);
        state.bodies.setColorAt(i, f.asleep ? dim.copy(f.color).multiplyScalar(0.35) : f.color);
      }
      state.bodies.count = figures.length;
      state.heads.count = figures.length;
      state.bodies.instanceMatrix.needsUpdate = true;
      state.heads.instanceMatrix.needsUpdate = true;
      if (state.bodies.instanceColor) state.bodies.instanceColor.needsUpdate = true;

      // Common bots hop around their sites.
      const sites = state.commonSites;
      for (let i = 0; i < sites.length; i += 1) {
        const site = sites[i];
        const angle = (state.reduced ? 0 : t * (running ? 1.2 : 0.4)) + site.phase;
        const p = offsetOnSurface(site.site, Math.cos(angle) * site.radius, Math.sin(angle) * site.radius);
        const hop = state.reduced ? 0 : Math.abs(Math.sin(t * 6 + site.phase * 3)) * 0.03;
        quaternion.setFromUnitVectors(UP, temp.copy(p).normalize());
        matrix.compose(p.setLength(R + hop), quaternion, scale);
        state.commons.setMatrixAt(i, matrix);
      }
      state.commons.count = sites.length;
      state.commons.instanceMatrix.needsUpdate = true;

      // Contests pulse; talk pulses travel; the sky turns.
      state.wars.forEach(({ sprite, line }) => {
        const pulse = state.reduced ? 1 : 1 + Math.sin(t * 3) * 0.12;
        sprite.scale.set(0.42 * pulse, 0.42 * pulse, 1);
        (line.material as THREE.LineBasicMaterial).opacity = state.reduced ? 0.8 : 0.5 + Math.sin(t * 3) * 0.3;
      });
      state.pulses = state.pulses.filter((pulse) => {
        const age = (now - pulse.born) / 1600;
        if (age >= 1) {
          state.lines.remove(pulse.line, pulse.dot);
          pulse.line.geometry.dispose();
          return false;
        }
        const index = Math.min(pulse.points.length - 1, Math.floor(age * pulse.points.length));
        pulse.dot.position.copy(pulse.points[index]);
        (pulse.line.material as THREE.LineBasicMaterial).opacity = 0.7 * (1 - age);
        return true;
      });
      state.sky.children.forEach((child, index) => {
        const orbit = child.userData.orbit as { radius: number; speed: number; tilt: number; phase: number } | undefined;
        if (!orbit) return;
        const a = (state.reduced ? 0 : t * orbit.speed) + orbit.phase;
        child.position.set(Math.cos(a) * orbit.radius, Math.sin(a) * orbit.radius * Math.sin(orbit.tilt),
          Math.sin(a) * orbit.radius * Math.cos(orbit.tilt));
        child.rotation.y += state.reduced ? 0 : dt * 0.3 * (index % 2 ? 1 : -1);
      });

      // The selection ring follows what is picked.
      const picked = latest.current.selected;
      // A picked sector lights its whole territory instead of wearing a ring.
      const at = picked && picked.kind !== "sector" ? pickPosition(picked) : null;
      if (at) {
        state.ring.visible = true;
        state.ring.position.copy(at).setLength(R + 0.015);
        state.ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), at.clone().normalize());
        const s = picked?.kind === "building" ? 1.6 : 0.8;
        const pulse = state.reduced ? 1 : 1 + Math.sin(t * 4) * 0.08;
        state.ring.scale.setScalar(s * pulse);
      } else {
        state.ring.visible = false;
      }
      for (const child of state.territories.children) {
        const pick = child.userData.pick as Pick | undefined;
        if (!pick || pick.kind !== "sector") continue;
        const material = (child as THREE.Mesh).material as THREE.MeshBasicMaterial;
        const on = picked?.kind === "sector" && picked.id === pick.id;
        material.opacity = on ? 0.26 + (state.reduced ? 0 : Math.sin(t * 3) * 0.04) : child.userData.baseOpacity ?? 0.1;
      }

      // The air thins out as you come down to the surface, so it never paints a band across the view.
      const height = camera.position.length() - R;
      atmosphereUniforms.uStrength.value = THREE.MathUtils.clamp((height - 1.5) / (R * 1.6), 0.08, 0.62);
      // Clouds thin out as you come down, so a city is never hidden under them.
      (state.clouds.material as THREE.MeshStandardMaterial).opacity = (state.clouds.userData.opacity ?? 0) *
        THREE.MathUtils.clamp((height - R * 0.25) / (R * 0.9), 0, 1);

      // Sector labels sit over their territories, and hide on the far side.
      const layer = labelLayer.current;
      if (layer) {
        const width = element.clientWidth;
        const height = element.clientHeight;
        const viewDir = camera.position.clone().normalize();
        for (const node of Array.from(layer.children) as HTMLElement[]) {
          const lat = Number(node.dataset.lat);
          const lon = Number(node.dataset.lon);
          const p = latLonToVec(lat, lon, R + 0.4);
          const facing = p.clone().normalize().dot(viewDir);
          const projected = p.project(camera);
          const visible = facing > 0.12 && projected.z < 1;
          node.style.opacity = visible ? String(Math.min(1, (facing - 0.12) * 4)) : "0";
          node.style.pointerEvents = visible ? "auto" : "none";
          node.style.transform = `translate(-50%, -100%) translate(${(projected.x * 0.5 + 0.5) * width}px, ${(-projected.y * 0.5 + 0.5) * height}px)`;
        }
      }
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("pointermove", onMove);
      renderer.domElement.removeEventListener("pointerleave", onLeave);
      controls.dispose();
      transport.dispose();
      environment.dispose();
      pmrem.dispose();
      scene.traverse((object) => {
        const meshLike = object as THREE.Mesh;
        meshLike.geometry?.dispose?.();
      });
      disposeMeshCaches();
      renderer.dispose();
      renderer.domElement.remove();
      three.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ------------------------------------------------------------------ positions, from the latest snapshot

  const sectorOf = (sid: string): WorldSector | undefined => latest.current.snapshot.sectors.find((s) => s.sid === sid);

  /** The government district's centre — its own place, apart from every sector. */
  const seat = (): { lat: number; lon: number } | null => {
    const gov = latest.current.snapshot.government;
    return gov && gov.lat !== null && gov.lat !== undefined ? { lat: gov.lat, lon: gov.lon } : null;
  };

  const buildingPosition = (building: WorldBuilding): THREE.Vector3 | null => {
    if (building.sector === GOV) {
      const at = seat();
      return at ? plotPosition(at.lat, at.lon, building.plot, R, GOV_SPACING) : null;
    }
    const sector = sectorOf(building.sector);
    if (!sector) return null;
    return plotPosition(sector.lat, sector.lon, building.plot);
  };

  const districtCentre = (sid: string): THREE.Vector3 | null => {
    if (sid === GOV) {
      const at = seat();
      return at ? latLonToVec(at.lat, at.lon) : null;
    }
    const sector = sectorOf(sid);
    return sector ? latLonToVec(sector.lat, sector.lon) : null;
  };

  /** The national cemetery, beside the government's district. */
  const graveyard = (): THREE.Vector3 | null => {
    const at = seat();
    if (at) return offsetOnSurface(latLonToVec(at.lat, at.lon), -(GOV_SPACING * 3.2 + 0.4), -0.6);
    const shot = latest.current.snapshot;
    const first = shot.sectors[0];
    if (!first) return null;
    return offsetOnSurface(latLonToVec(first.lat, first.lon), -(sectorReach(plotsFor(shot.world.era)) + 0.55), -0.5);
  };

  const placeBuilding = (building: WorldBuilding, look: Look | null): THREE.Group | null => {
    const position = buildingPosition(building);
    if (!position) return null;
    const group = buildingGroup(building.kind, building.floors, building.era, look, building.tag ?? "", `b${building.bid}`);
    group.position.copy(position);
    group.quaternion.copy(standUp(position));
    group.rotateY(building.sector === GOV ? 0 : hash(`b${building.bid}`) * Math.PI * 2);
    group.userData.pick = { kind: "building", id: building.bid } satisfies Pick;
    group.userData.building = building;
    return group;
  };

  /** Bake one district's finished buildings again (after one finished, came down or changed). */
  function rebake(sid: string): void {
    const state = three.current;
    if (!state) return;
    const shot = latest.current.snapshot;
    const old = state.districts.get(sid);
    const standing = shot.buildings.filter((b) => b.sector === sid && b.state === "standing" && !state.built.has(b.bid));
    const signature = standing.map((b) => `${b.bid}:${b.kind}:${b.floors}:${b.era}:${b.plot}:${b.tag ?? ""}`).join("|")
      + `@${state.lookKey}`;
    if (old && old.signature === signature) return;
    if (old) {
      [...old.main, ...old.detail].forEach((m) => { state.baked.remove(m); m.geometry.dispose(); });
      old.proxies.forEach((m) => state.proxies.remove(m));
      state.districts.delete(sid);
    }
    const centre = districtCentre(sid);
    if (!standing.length || !centre) return;
    const groups: THREE.Group[] = [];
    const proxies: THREE.Mesh[] = [];
    for (const building of standing) {
      const group = placeBuilding(building, state.look);
      if (!group) continue;
      showPhase(group, 1, "standing", 0, true);
      groups.push(group);
      const [w, d] = (group.userData.size as [number, number]) ?? [0.3, 0.3];
      const h = (group.userData.height as number) ?? 0.2;
      const proxy = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), PROXY_MATERIAL);
      proxy.geometry.translate(0, h / 2, 0);
      proxy.position.copy(group.position);
      proxy.quaternion.copy(group.quaternion);
      proxy.userData.pick = { kind: "building", id: building.bid } satisfies Pick;
      proxies.push(proxy);
      state.proxies.add(proxy);
    }
    const { main, detail } = bake(groups);
    main.forEach((m) => state.baked.add(m));
    detail.forEach((m) => state.baked.add(m));
    state.districts.set(sid, { signature, centre: centre.clone(), main, detail, proxies });
  }

  function pickPosition(pick: Pick): THREE.Vector3 | null {
    const shot = latest.current.snapshot;
    const state = three.current;
    switch (pick.kind) {
      case "government":
        return districtCentre(GOV);
      case "sector": {
        const sector = sectorOf(pick.id);
        return sector ? latLonToVec(sector.lat, sector.lon) : null;
      }
      case "building": {
        const building = shot.buildings.find((b) => b.bid === pick.id);
        return building ? buildingPosition(building) : null;
      }
      case "bot": {
        const index = state?.figureIndex.get(pick.id);
        return index !== undefined && state ? state.figures[index]?.pos.clone() ?? null : null;
      }
      case "grave": {
        const index = state?.graveIds.indexOf(pick.id) ?? -1;
        const yard = graveyard();
        if (!yard || index < 0) return yard;
        return offsetOnSurface(yard, (index % 10) * 0.13 - 0.58, 0.3 - Math.floor(index / 10) * 0.16);
      }
      case "war": {
        const war = shot.wars.find((w) => w.wid === pick.id);
        const a = war && sectorOf(war.a);
        const b = war && sectorOf(war.b);
        return a && b ? slerpSurface(latLonToVec(a.lat, a.lon), latLonToVec(b.lat, b.lon), 0.5) : null;
      }
      case "startup": {
        const startup = shot.startups.find((s) => s.suid === pick.id);
        const sector = startup ? sectorOf(startup.sector) : undefined;
        return sector ? latLonToVec(sector.lat, sector.lon) : districtCentre(GOV);
      }
      default:
        return null;
    }
  }

  function describePick(pick: Pick): string {
    const shot = latest.current.snapshot;
    switch (pick.kind) {
      case "sector": {
        const sector = sectorOf(pick.id);
        return sector ? `${sector.name} · ${sector.gov}` : "";
      }
      case "government":
        return shot.government?.name ?? "The government";
      case "building": {
        const building = shot.buildings.find((b) => b.bid === pick.id);
        if (!building) return "";
        const label = building.kind === "ministry" ? ministryName(shot, building.tag) : KIND_LABELS[building.kind] ?? building.kind;
        return `${label}${building.floors > 1 ? ` · ${building.floors} floors` : ""}${building.state === "constructing" ? " · being built" : building.state === "demolishing" ? " · coming down" : ""}`;
      }
      case "bot": {
        const bot = shot.bots.find((b) => b.aid === pick.id);
        const agent = latest.current.agents[pick.id];
        return bot ? `${bot.name} · ${bot.state === "asleep" ? "asleep" : agent?.status === "working" ? "working" : "awake"}` : "";
      }
      case "grave": {
        const grave = shot.graves.find((g) => g.gid === pick.id);
        return grave ? `Here lies ${grave.name}` : "";
      }
      case "war": {
        const war = shot.wars.find((w) => w.wid === pick.id);
        return war ? `Contest: ${war.reason}` : "";
      }
      case "startup": {
        const startup = shot.startups.find((s) => s.suid === pick.id);
        return startup ? `Start-up: ${startup.name}` : "";
      }
      case "station":
        return pick.id >= 100 ? "Artificial planet" : "Space station";
      default:
        return "";
    }
  }

  // ------------------------------------------------------------------ the camera

  const flyTo = useCallback((point: THREE.Vector3 | null, distance: number, level: "planet" | "sector" | "workplace") => {
    const state = three.current;
    if (!state) return;
    const { camera, controls } = state;
    const toTarget = point ? point.clone() : new THREE.Vector3();
    let toCamera: THREE.Vector3;
    if (point) {
      const normal = point.clone().normalize();
      const { north } = tangentFrame(normal);
      toCamera = point.clone().addScaledVector(normal, distance * 0.78).addScaledVector(north, -distance * 0.62);
      controls.minDistance = 0.6;
    } else {
      toCamera = camera.position.clone().normalize().multiplyScalar(distance);
      controls.minDistance = R * 1.25;
    }
    state.fly = { fromTarget: controls.target.clone(), toTarget, fromCamera: camera.position.clone(), toCamera,
      start: performance.now(), duration: state.reduced ? 1 : 950 };
    state.level = level;
    state.lastInteract = performance.now();
    latest.current.onLevel?.(level);
  }, []);

  const planetDistance = () => {
    const shot = latest.current.snapshot;
    return R * 2.7 + Math.min(R * 1.2, shot.sectors.length * 1.4) + (shot.world.stations ? R * 0.4 : 0) +
      (shot.world.planets ? R * 1.6 : 0);
  };

  useImperativeHandle(ref, () => ({
    focus: (pick) => {
      if (!pick || pick.kind === "world") {
        flyTo(null, planetDistance(), "planet");
        return;
      }
      const at = pickPosition(pick);
      if (!at) return;
      const close = pick.kind === "building" || pick.kind === "bot" || pick.kind === "grave";
      flyTo(at, close ? 2.4 : pick.kind === "sector" || pick.kind === "startup" || pick.kind === "government" ? 7 : 14,
        close ? "workplace" : "sector");
    },
    zoom: (factor) => {
      const state = three.current;
      if (!state) return;
      const offset = state.camera.position.clone().sub(state.controls.target);
      offset.multiplyScalar(factor);
      const length = THREE.MathUtils.clamp(offset.length(), state.controls.minDistance, state.controls.maxDistance);
      state.camera.position.copy(state.controls.target).add(offset.setLength(length));
      state.lastInteract = performance.now();
    },
    reset: () => flyTo(null, planetDistance(), "planet"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [flyTo]);

  // ------------------------------------------------------------------ the world changed: bring the scene up to date

  useEffect(() => {
    const state = three.current;
    if (!state) return;
    const shot = snapshot;
    const world = shot.world;

    // The land is flattened where the sectors and the government stand; repainted when they or the era change.
    const plots = plotsFor(world.era);
    const reach = sectorReach(plots);
    const govAt = seat();
    const flatSites: Site[] = shot.sectors.map((s) => ({ dir: latLonToVec(s.lat, s.lon, 1), reach }));
    if (govAt) flatSites.push({ dir: latLonToVec(govAt.lat, govAt.lon, 1), reach: GOV_SPACING * 3.6 });
    const yard = graveyard();
    if (yard) flatSites.push({ dir: yard.clone().normalize(), reach: 1.4 });
    const siteKey = `${world.era}|${flatSites.map((s) => `${s.dir.x.toFixed(4)}:${s.dir.y.toFixed(4)}:${s.reach.toFixed(2)}`).join("|")}`;
    if (siteKey !== state.siteKey) {
      state.siteKey = siteKey;
      state.terrain.setSites(flatSites);
      paintPlanet(state.planetGeometry, state.terrain, world.era);
    }
    if (state.era !== world.era) {
      state.clouds.userData.opacity = world.era >= 1
        ? Math.min(0.55, 0.2 + world.era * 0.04) * (0.5 + state.terrain.planet.clouds * 0.6) : 0;
      if (state.era === -1) {
        // Open facing the government's district, from a little to the south.
        const first = govAt ?? shot.sectors[0];
        const facing = first ? latLonToVec(first.lat - 14, first.lon + 10, 1) : new THREE.Vector3(0, 0.3, 1);
        state.camera.position.copy(facing.normalize().multiplyScalar(planetDistance()));
      }
      state.era = world.era;
    }
    const tech = [...world.techs].reverse().find((t) => t.era <= world.era) ?? world.techs[world.techs.length - 1];
    const look: Look | null = tech ? { style: tech.style, palette: tech.palette } : null;
    const lookKey = look ? `${look.style}:${look.palette.join(",")}` : "";
    state.look = look;
    if (lookKey !== state.lookKey) {
      state.built.forEach((entry) => state.buildings.remove(entry.group));
      state.built.clear();
      state.lookKey = lookKey;
    }

    // Territories: a cap that hugs the surface, and its border — rebuilt only when one of them changed.
    const territoryKey = shot.sectors.map((s) => `${s.sid}:${s.lat}:${s.lon}:${s.full}:${sectionColors[s.sid] ?? ""}`)
      .join("|") + `@${reach}@${govAt ? `${govAt.lat}:${govAt.lon}` : ""}`;
    if (territoryKey !== state.territories.userData.key) {
      state.territories.userData.key = territoryKey;
      disposeChildren(state.territories);
    }
    if (!state.territories.children.length && govAt) {
      // The government's plaza: pale stone under the civic buildings.
      const plaza = new THREE.Mesh(new THREE.SphereGeometry(R + 0.004, 48, 6, 0, Math.PI * 2, 0, (GOV_SPACING * 2.7) / R),
        new THREE.MeshStandardMaterial({ color: "#9c968a", roughness: 0.9 }));
      plaza.quaternion.copy(standUp(latLonToVec(govAt.lat, govAt.lon)));
      plaza.userData.pick = { kind: "government" } satisfies Pick;
      state.territories.add(plaza);
    }
    for (const sector of state.territories.children.length > (govAt ? 1 : 0) ? [] : shot.sectors) {
      const color = new THREE.Color(sectorColor(sector.sid, sectionColors));
      const cap = new THREE.Mesh(new THREE.SphereGeometry(R + 0.006, 48, 6, 0, Math.PI * 2, 0, reach / R),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.08, depthWrite: false }));
      cap.quaternion.copy(standUp(latLonToVec(sector.lat, sector.lon)));
      cap.userData.pick = { kind: "sector", id: sector.sid } satisfies Pick;
      cap.userData.baseOpacity = 0.08;
      state.territories.add(cap);
      const border: THREE.Vector3[] = [];
      const centre = latLonToVec(sector.lat, sector.lon);
      for (let i = 0; i <= 72; i += 1) {
        const a = (i / 72) * Math.PI * 2;
        border.push(offsetOnSurface(centre, Math.cos(a) * reach, Math.sin(a) * reach, R + 0.012));
      }
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(border),
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: sector.full ? 0.9 : 0.5 }));
      line.raycast = () => undefined;
      state.territories.add(line);
    }

    // Buildings: those being built or torn down are drawn on their own, phase by phase; every finished one is baked
    // into its district.
    const present = new Set<number>();
    const touched = new Set<string>();
    for (const building of shot.buildings) {
      present.add(building.bid);
      const key = `${building.kind}|${building.floors}|${building.era}|${building.sector}|${building.plot}|${building.tag ?? ""}`;
      const existing = state.built.get(building.bid);
      if (building.state === "standing" && !existing) continue;
      if (existing && existing.key === key) {
        existing.group.userData.building = building;
        continue;
      }
      if (existing) state.buildings.remove(existing.group);
      const group = placeBuilding(building, look);
      if (!group) continue;
      state.buildings.add(group);
      state.built.set(building.bid, { group, key, district: building.sector,
        shown: existing ? existing.shown : building.state === "demolishing" ? 1 : Math.max(0.02, building.progress) });
      touched.add(building.sector);
    }
    for (const [bid, entry] of Array.from(state.built.entries())) {
      if (!present.has(bid)) {
        state.buildings.remove(entry.group);
        state.built.delete(bid);
        touched.add(entry.district);
      }
    }
    const districtIds = new Set<string>([...shot.sectors.map((s) => s.sid), GOV, ...Array.from(state.districts.keys())]);
    districtIds.forEach((sid) => rebake(sid));

    // Roads, rails and whatever flies, from the transport technology.
    const nodes: TransportNode[] = [];
    if (govAt) nodes.push({ id: GOV, dir: latLonToVec(govAt.lat, govAt.lon, 1), reach: GOV_SPACING * 2.6, rings: 2 });
    const rings = Math.max(1, Math.round(reach / 0.56 - 0.8));
    for (const sector of shot.sectors) {
      nodes.push({ id: sector.sid, dir: latLonToVec(sector.lat, sector.lon, 1), reach, rings });
    }
    state.transport.update(nodes, shot.tech?.transport ?? 0, (dir) => state.terrain.height(dir), world.era, GOV);

    // City lights at night, from the era of steel frames on.
    const glow: number[] = [];
    if (world.era >= 2) {
      for (const building of shot.buildings) {
        if (!WORKPLACES.has(building.kind) || building.state !== "standing") continue;
        const p = buildingPosition(building);
        if (!p) continue;
        for (let i = 0; i < Math.min(6, 1 + Math.floor(building.floors / 3)); i += 1) {
          const q = offsetOnSurface(p, (hash(`l${building.bid}${i}`) - 0.5) * 0.5, (hash(`m${building.bid}${i}`) - 0.5) * 0.5,
            R + 0.03);
          glow.push(q.x, q.y, q.z);
        }
      }
    }
    state.lights.geometry.dispose();
    state.lights.geometry = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(glow, 3));

    // Contests: a red arc between the two sectors, crossed swords at its top.
    const liveWars = new Set<string>();
    for (const war of shot.wars) {
      if (war.status === "resolved") continue;
      const a = sectorOf(war.a);
      const b = sectorOf(war.b);
      if (!a || !b) continue;
      liveWars.add(war.wid);
      if (state.wars.has(war.wid)) continue;
      const points = arcPoints(latLonToVec(a.lat, a.lon), latLonToVec(b.lat, b.lon), 0.6, 64);
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({ color: "#ff453a", transparent: true, opacity: 0.7 }));
      line.raycast = () => undefined;
      const sprite = warSprite();
      sprite.position.copy(points[Math.floor(points.length / 2)]).multiplyScalar(1.01);
      sprite.userData.pick = { kind: "war", id: war.wid } satisfies Pick;
      state.markers.add(line, sprite);
      state.wars.set(war.wid, { sprite, line });
    }
    for (const [wid, entry] of Array.from(state.wars.entries())) {
      if (!liveWars.has(wid)) {
        state.markers.remove(entry.sprite, entry.line);
        entry.line.geometry.dispose();
        state.wars.delete(wid);
      }
    }

    // Start-ups fly a flag in their own sector (or at the government's district while they wait for approval).
    const liveFlags = new Set<string>();
    for (const startup of shot.startups) {
      if (startup.status === "declined") continue;
      const sector = sectorOf(startup.sector);
      const centre = sector ? latLonToVec(sector.lat, sector.lon) : districtCentre(GOV);
      if (!centre) continue;
      liveFlags.add(startup.suid);
      if (state.flags.has(startup.suid)) continue;
      const spot = startup.sector ? offsetOnSurface(centre, 0.32, 0.32) : offsetOnSurface(centre, -0.9, 0.9);
      const flag = startupFlag(startup.status === "founded" ? "#30d158" : "#ffd60a");
      flag.position.copy(spot);
      flag.quaternion.copy(standUp(spot));
      flag.userData.pick = { kind: "startup", id: startup.suid } satisfies Pick;
      state.markers.add(flag);
      state.flags.set(startup.suid, flag);
    }
    for (const [suid, flag] of Array.from(state.flags.entries())) {
      const startup = shot.startups.find((s) => s.suid === suid);
      if (!liveFlags.has(suid) || (startup && startup.status === "founded" && !startup.sector)) {
        state.markers.remove(flag);
        state.flags.delete(suid);
      }
    }

    // Space: stations, then artificial planets.
    const skyKey = `${world.stations}:${world.planets}`;
    if (skyKey !== state.sky.userData.key) {
      state.sky.userData.key = skyKey;
      state.sky.clear();
      for (let i = 0; i < world.stations; i += 1) {
        const station = stationMesh();
        station.userData.pick = { kind: "station", id: i } satisfies Pick;
        station.userData.orbit = { radius: R * 1.35 + i * 0.9, speed: 0.06 + i * 0.012, tilt: 0.35 + i * 0.4, phase: i * 1.9 };
        state.sky.add(station);
      }
      for (let i = 0; i < world.planets; i += 1) {
        const made = artificialPlanet(i);
        made.userData.pick = { kind: "station", id: 100 + i } satisfies Pick;
        made.userData.orbit = { radius: R * 3.4 + i * 5, speed: 0.015 + i * 0.005, tilt: 0.2 + i * 0.5, phase: i * 2.4 };
        state.sky.add(made);
      }
    }

    // Permanent talk lines between the government and every sector, once there are steel frames to hang them on.
    const capital = govAt ? { sid: GOV, lat: govAt.lat, lon: govAt.lon } : undefined;
    const linesKey = world.era >= 2 ? shot.sectors.map((s) => `${s.sid}:${s.lat}:${s.lon}`).join("|") : "";
    const rebuildLines = linesKey !== state.lines.userData.key;
    if (rebuildLines) {
      state.lines.userData.key = linesKey;
      state.lines.children.filter((c) => c.userData.permanent).forEach((c) => {
        state.lines.remove(c);
        (c as THREE.Line).geometry.dispose();
      });
    }
    if (capital && world.era >= 2 && rebuildLines) {
      for (const sector of shot.sectors) {
        if (sector.sid === capital.sid) continue;
        const points = arcPoints(latLonToVec(capital.lat, capital.lon), latLonToVec(sector.lat, sector.lon), 0.35, 48, 0.03);
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
          new THREE.LineBasicMaterial({ color: "#a594ff", transparent: true, opacity: 0.14 }));
        line.userData.permanent = true;
        line.raycast = () => undefined;
        state.lines.add(line);
      }
    }

    // The people: where each one lives and works.
    const bySector = new Map<string, WorldBot[]>();
    for (const bot of shot.bots) {
      const list = bySector.get(bot.sector) ?? [];
      list.push(bot);
      bySector.set(bot.sector, list);
    }
    const next: Figure[] = [];
    const index = new Map<string, number>();
    for (const [sid, bots] of Array.from(bySector.entries())) {
      const sector = sectorOf(sid);
      if (!sector) continue;
      const centre = latLonToVec(sector.lat, sector.lon);
      const standing = shot.buildings.filter((b) => b.sector === sid && b.state !== "demolishing");
      const homes = standing.filter((b) => b.kind === "house").sort((a, b) => a.plot - b.plot);
      const works = standing.filter((b) => WORKPLACES.has(b.kind) || b.kind === "capitol" || b.kind === "council")
        .sort((a, b) => a.plot - b.plot);
      bots.sort((a, b) => a.aid.localeCompare(b.aid)).forEach((bot, i) => {
        if (next.length >= MAX_FIGURES) return;
        const house = homes.length ? homes[Math.floor(i / 4) % homes.length] : null;
        const place = works.length ? works[i % works.length] : null;
        const jitter = (key: string, spread: number) => (hash(`${bot.aid}${key}`) - 0.5) * spread;
        const homeBase = house ? buildingPosition(house) ?? centre : centre;
        const workBase = place ? buildingPosition(place) ?? centre : centre;
        const home = offsetOnSurface(homeBase, jitter("hx", 0.24), jitter("hy", 0.24) - 0.14);
        const work = offsetOnSurface(workBase, 0.2 * Math.cos(hash(bot.aid) * 6.28), 0.2 * Math.sin(hash(bot.aid) * 6.28));
        const agent = agents[bot.aid];
        const previous = three.current?.figureIndex.get(bot.aid);
        const old = previous !== undefined ? state.figures[previous] : undefined;
        const roleColor = agent ? roleColors[agent.role] : "";
        const figure: Figure = {
          aid: bot.aid,
          pos: old ? old.pos : home.clone(),
          target: home.clone(),
          home,
          work,
          wander: old ? old.wander : home.clone(),
          nextWander: old ? old.nextWander : 0,
          asleep: bot.state === "asleep" && agent?.status !== "working",
          working: agent?.status === "working",
          color: new THREE.Color(roleColor || `hsl(${Math.round(hash(bot.role) * 360)}, 65%, 62%)`),
          phase: hash(bot.aid) * 10,
          yaw: old ? old.yaw : hash(bot.aid) * 6.28,
        };
        index.set(bot.aid, next.length);
        next.push(figure);
      });
    }
    state.figures = next;
    state.figureIndex = index;

    // Common bots: on every building site first, then keeping the tall workplaces.
    const sites: { site: THREE.Vector3; phase: number; radius: number }[] = [];
    for (const [sid, count] of Object.entries(shot.common)) {
      const busy = shot.buildings.filter((b) => b.sector === sid && b.state !== "standing");
      const kept = shot.buildings.filter((b) => b.sector === sid && b.state === "standing" && WORKPLACES.has(b.kind) && b.floors >= 4);
      const places = [...busy, ...kept];
      for (let i = 0; i < count && sites.length < MAX_COMMON; i += 1) {
        const place = places[i % Math.max(1, places.length)];
        const p = place ? buildingPosition(place) : null;
        if (!p) continue;
        sites.push({ site: p, phase: hash(`c${sid}${i}`) * Math.PI * 2, radius: 0.16 + hash(`r${sid}${i}`) * 0.08 });
      }
    }
    state.commonSites = sites;

    // Graves, in rows in the national cemetery beside the government's district.
    const shown = shot.graves.slice(-MAX_GRAVES);
    state.graveIds = shown.map((g) => g.gid);
    if (yard) {
      const matrix = new THREE.Matrix4();
      const unit = new THREE.Vector3(1, 1, 1);
      shown.forEach((grave, i) => {
        const p = offsetOnSurface(yard, (i % 10) * 0.13 - 0.58, 0.3 - Math.floor(i / 10) * 0.16);
        matrix.compose(p, standUp(p), unit);
        state.graves.setMatrixAt(i, matrix);
        state.graves.setColorAt(i, new THREE.Color(grave.rejoined ? "#5a5a63" : "#a1a1aa"));
      });
    }
    state.graves.count = yard ? shown.length : 0;
    // A lawn under the stones, so the cemetery is a place of its own wherever it falls (sea or land).
    const lawn = state.scene.getObjectByName("cemetery") as THREE.Mesh | undefined;
    const rows = Math.max(1, Math.ceil(shown.length / 10));
    const lawnSize = Math.min(1.6, 0.55 + rows * 0.09);
    if (yard && shown.length) {
      const key = `${yard.x.toFixed(3)}:${yard.y.toFixed(3)}:${lawnSize}`;
      if (!lawn || lawn.userData.key !== key) {
        if (lawn) {
          state.scene.remove(lawn);
          lawn.geometry.dispose();
          (lawn.material as THREE.Material).dispose();
        }
        const made = new THREE.Mesh(new THREE.SphereGeometry(R + 0.004, 40, 6, 0, Math.PI * 2, 0, lawnSize / R),
          new THREE.MeshStandardMaterial({ color: "#2f4a35", roughness: 1 }));
        made.name = "cemetery";
        made.userData.key = key;
        // Centred on the rows of stones, which run east and south from the yard's corner.
        made.quaternion.copy(standUp(offsetOnSurface(yard, 0, 0.3 - (rows - 1) * 0.08)));
        made.raycast = () => undefined;
        state.scene.add(made);
      }
    } else if (lawn) {
      state.scene.remove(lawn);
    }
    state.graves.instanceMatrix.needsUpdate = true;
    if (state.graves.instanceColor) state.graves.instanceColor.needsUpdate = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, sectionColors, roleColors]);

  // The details card opened or closed: keep what was picked in the visible part of the view.
  useEffect(() => {
    const state = three.current;
    const element = host.current;
    if (!state || !element) return;
    applyInset(state.camera, element.clientWidth || 1, element.clientHeight || 1, inset);
  }, [inset]);

  // Agents' statuses change far more often than the world: update only who is working and sleeping.
  useEffect(() => {
    const state = three.current;
    if (!state) return;
    const bots = new Map(snapshot.bots.map((b) => [b.aid, b]));
    for (const figure of state.figures) {
      const agent = agents[figure.aid];
      const bot = bots.get(figure.aid);
      figure.working = agent?.status === "working";
      figure.asleep = bot?.state === "asleep" && !figure.working;
    }
  }, [agents, snapshot.bots]);

  // Talk lines: a pulse from the sender's sector to each receiver's.
  useEffect(() => {
    const state = three.current;
    if (!state) return;
    const sectorOfAgent = new Map(snapshot.bots.map((b) => [b.aid, b.sector]));
    for (const talk of talks) {
      if (state.seenTalks.has(talk.id)) continue;
      state.seenTalks.add(talk.id);
      const from = sectorOf(sectorOfAgent.get(talk.from) ?? "");
      for (const receiver of talk.to.slice(0, 6)) {
        const to = sectorOf(sectorOfAgent.get(receiver) ?? "");
        if (!from || !to) continue;
        const a = latLonToVec(from.lat, from.lon);
        const b = from.sid === to.sid ? offsetOnSurface(a, 0.8, 0.5) : latLonToVec(to.lat, to.lon);
        const points = arcPoints(a, b, from.sid === to.sid ? 0.15 : 0.35, 48);
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
          new THREE.LineBasicMaterial({ color: "#64d2ff", transparent: true, opacity: 0.7 }));
        line.raycast = () => undefined;
        const dot = new THREE.Mesh(new THREE.SphereGeometry(0.05, 10, 8),
          new THREE.MeshBasicMaterial({ color: "#d6ceff" }));
        dot.raycast = () => undefined;
        state.lines.add(line, dot);
        state.pulses.push({ line, dot, points, born: performance.now() });
      }
    }
    if (state.seenTalks.size > 400) state.seenTalks = new Set(Array.from(state.seenTalks).slice(-200));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [talks]);

  return (
    <div className="wld-planet" ref={host}>
      <div className="wld-labels" ref={labelLayer}>
        {snapshot.government && snapshot.government.lat !== null && snapshot.government.lat !== undefined && (
          <button type="button" className="wld-label is-capital" data-lat={snapshot.government.lat}
                  data-lon={snapshot.government.lon} style={{ ["--sector" as string]: "var(--color-accent, #ff7a2e)" }}
                  onClick={() => onPick({ kind: "government" })}
                  aria-label={`${snapshot.government.name}. Open its branches and ministries.`}>
            <i aria-hidden="true" />Government
          </button>
        )}
        {snapshot.sectors.map((sector) => (
          <button key={sector.sid} type="button" className="wld-label"
                  data-lat={sector.lat} data-lon={sector.lon}
                  style={{ ["--sector" as string]: sectorColor(sector.sid, sectionColors) }}
                  onClick={() => onPick({ kind: "sector", id: sector.sid })}
                  aria-label={`${sector.name}, ${sector.gov}. Open its details.`}>
            <i aria-hidden="true" />{sector.name}
            {sector.startup && <span className="wld-label__tag">start-up</span>}
          </button>
        ))}
      </div>
      <div className="wld-tip" ref={tip} role="presentation" />
    </div>
  );
});

function ministryName(shot: WorldSnapshot, tag?: string): string {
  return shot.government?.ministries.find((m) => m.key === tag)?.name ?? "Ministry";
}
