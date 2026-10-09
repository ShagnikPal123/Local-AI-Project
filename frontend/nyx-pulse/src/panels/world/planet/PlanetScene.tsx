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
import type { Pick, WorldBot, WorldBuilding, WorldSector, WorldSnapshot } from "../types";
import {
  R, arcPoints, hash, latLonToVec, offsetOnSurface, plotPosition, sectorReach, slerpSurface, standUp, tangentFrame,
} from "./geo";
import { ATMOSPHERE_FRAGMENT, ATMOSPHERE_VERTEX, cloudTexture, paintPlanet } from "./surface";
import {
  artificialPlanet, botGeometry, buildingGroup, disposeMeshCaches, figureGeometries, graveGeometry, startupFlag,
  stationMesh, warSprite, type Look,
} from "./meshes";

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
    markers: THREE.Group;
    sky: THREE.Group;
    lines: THREE.Group;
    lights: THREE.Points;
    bodies: THREE.InstancedMesh;
    heads: THREE.InstancedMesh;
    commons: THREE.InstancedMesh;
    graves: THREE.InstancedMesh;
    ring: THREE.Mesh;
    built: Map<number, { group: THREE.Group; key: string; shown: number }>;
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

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.05, 3000);
    camera.position.set(0, 9, 32);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.enablePan = false;
    controls.minDistance = R + 2.5;
    controls.maxDistance = 140;
    controls.rotateSpeed = 0.6;
    controls.zoomSpeed = 0.9;

    scene.add(new THREE.AmbientLight("#8a90b8", 0.55));
    scene.add(new THREE.HemisphereLight("#cfd8ff", "#1a1420", 0.55));
    const sun = new THREE.DirectionalLight("#fff4e0", 2.1);
    sun.position.set(-40, 26, 30);
    scene.add(sun);
    const rim = new THREE.DirectionalLight("#7f74ff", 0.6);
    rim.position.set(40, -10, -30);
    scene.add(rim);

    // Stars.
    const starPositions = new Float32Array(2600 * 3);
    for (let i = 0; i < 2600; i += 1) {
      const v = new THREE.Vector3(hash(`s${i}x`) - 0.5, hash(`s${i}y`) - 0.5, hash(`s${i}z`) - 0.5).normalize()
        .multiplyScalar(700 + hash(`s${i}d`) * 400);
      starPositions.set([v.x, v.y, v.z], i * 3);
    }
    const stars = new THREE.Points(new THREE.BufferGeometry().setAttribute("position",
      new THREE.BufferAttribute(starPositions, 3)), new THREE.PointsMaterial({ color: "#ffffff", size: 1.4,
      sizeAttenuation: false, transparent: true, opacity: 0.7 }));
    scene.add(stars);

    const planetGeometry = new THREE.SphereGeometry(R, 160, 120);
    paintPlanet(planetGeometry, 0);
    const planet = new THREE.Mesh(planetGeometry, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.92,
      metalness: 0.02 }));
    planet.userData.pick = { kind: "world" } satisfies Pick;
    scene.add(planet);

    const atmosphereUniforms = { uColor: { value: new THREE.Color("#8fa8ff") }, uStrength: { value: 0.6 } };
    const atmosphere = new THREE.Mesh(new THREE.SphereGeometry(R * 1.045, 64, 48), new THREE.ShaderMaterial({
      vertexShader: ATMOSPHERE_VERTEX, fragmentShader: ATMOSPHERE_FRAGMENT, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, uniforms: atmosphereUniforms,
    }));
    atmosphere.raycast = () => undefined;
    scene.add(atmosphere);

    const clouds = new THREE.Mesh(new THREE.SphereGeometry(R * 1.018, 64, 48), new THREE.MeshStandardMaterial({
      map: cloudTexture(), transparent: true, depthWrite: false, opacity: 0.0, roughness: 1 }));
    clouds.raycast = () => undefined;
    scene.add(clouds);

    const territories = new THREE.Group();
    const buildings = new THREE.Group();
    const markers = new THREE.Group();
    const sky = new THREE.Group();
    const lines = new THREE.Group();
    scene.add(territories, buildings, markers, sky, lines);

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
      renderer, scene, camera, controls, planetGeometry, planet, clouds, territories, buildings, markers, sky, lines,
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
      const hits = raycaster.intersectObjects([state.buildings, state.markers, state.sky, state.bodies, state.graves,
        state.territories, state.planet], true);
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

      // Buildings rise (and come down) smoothly toward the progress the world reports.
      state.built.forEach((entry) => {
        const building = entry.group.userData.building as WorldBuilding;
        const goal = building.state === "standing" ? 1 : Math.max(0.06, building.progress);
        entry.shown += (goal - entry.shown) * Math.min(1, dt * (state.reduced ? 30 : 2.2));
        const rising = entry.group.getObjectByName("body");
        if (rising) rising.scale.y = Math.max(0.04, entry.shown);
        const scaffold = entry.group.getObjectByName("scaffold");
        if (scaffold) scaffold.visible = building.state !== "standing";
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
      atmosphereUniforms.uStrength.value = THREE.MathUtils.clamp((height - 1.5) / 18, 0.08, 0.62);

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

  const buildingPosition = (building: WorldBuilding): THREE.Vector3 | null => {
    const sector = sectorOf(building.sector);
    if (!sector) return null;
    return plotPosition(sector.lat, sector.lon, building.plot);
  };

  const graveyard = (): THREE.Vector3 | null => {
    const shot = latest.current.snapshot;
    const capital = shot.sectors.find((s) => s.important) ?? shot.sectors[0];
    if (!capital) return null;
    const plots = 8 + 4 * shot.world.era;
    return offsetOnSurface(latLonToVec(capital.lat, capital.lon), -(sectorReach(plots) + 0.55), -0.5);
  };

  function pickPosition(pick: Pick): THREE.Vector3 | null {
    const shot = latest.current.snapshot;
    const state = three.current;
    switch (pick.kind) {
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
        const sector = startup ? sectorOf(startup.sector) ?? shot.sectors.find((s) => s.important) : undefined;
        return sector ? latLonToVec(sector.lat, sector.lon) : null;
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
      case "building": {
        const building = shot.buildings.find((b) => b.bid === pick.id);
        if (!building) return "";
        const label = KIND_WORDS[building.kind] ?? building.kind;
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
      controls.minDistance = R + 2.5;
    }
    state.fly = { fromTarget: controls.target.clone(), toTarget, fromCamera: camera.position.clone(), toCamera,
      start: performance.now(), duration: state.reduced ? 1 : 950 };
    state.level = level;
    state.lastInteract = performance.now();
    latest.current.onLevel?.(level);
  }, []);

  const planetDistance = () => {
    const shot = latest.current.snapshot;
    return 26 + Math.min(18, shot.sectors.length * 1.4) + (shot.world.stations ? 6 : 0) + (shot.world.planets ? 16 : 0);
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
      flyTo(at, close ? 2.4 : pick.kind === "sector" || pick.kind === "startup" ? 6.5 : 12, close ? "workplace" : "sector");
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

    // The surface and the sky follow the era.
    if (state.era !== world.era) {
      paintPlanet(state.planetGeometry, world.era);
      (state.clouds.material as THREE.MeshStandardMaterial).opacity = world.era >= 1 ? Math.min(0.75, 0.3 + world.era * 0.08) : 0;
      if (state.era === -1) {
        // Open facing the capital, from a little to the south, so the world's centre is the first thing seen.
        const capital = shot.sectors.find((s) => s.important) ?? shot.sectors[0];
        const facing = capital ? latLonToVec(capital.lat - 14, capital.lon + 10, 1) : new THREE.Vector3(0, 0.3, 1);
        state.camera.position.copy(facing.normalize().multiplyScalar(planetDistance()));
      }
      state.era = world.era;
    }
    const tech = [...world.techs].reverse().find((t) => t.era <= world.era) ?? world.techs[world.techs.length - 1];
    const look: Look | null = tech ? { style: tech.style, palette: tech.palette } : null;
    const lookKey = look ? `${look.style}:${look.palette.join(",")}` : "";
    if (lookKey !== state.lookKey) {
      state.built.forEach((entry) => state.buildings.remove(entry.group));
      state.built.clear();
      state.lookKey = lookKey;
    }

    // Territories: a cap that hugs the surface, and its border — rebuilt only when one of them changed.
    const plots = 8 + 4 * world.era;
    const reach = sectorReach(plots);
    const territoryKey = shot.sectors.map((s) => `${s.sid}:${s.lat}:${s.lon}:${s.full}:${s.important}:${sectionColors[s.sid] ?? ""}`)
      .join("|") + `@${reach}`;
    if (territoryKey !== state.territories.userData.key) {
      state.territories.userData.key = territoryKey;
      disposeChildren(state.territories);
    }
    for (const sector of state.territories.children.length ? [] : shot.sectors) {
      const color = new THREE.Color(sectorColor(sector.sid, sectionColors));
      const cap = new THREE.Mesh(new THREE.SphereGeometry(R + 0.006, 48, 6, 0, Math.PI * 2, 0, reach / R),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: sector.important ? 0.14 : 0.1, depthWrite: false }));
      cap.quaternion.copy(standUp(latLonToVec(sector.lat, sector.lon)));
      cap.userData.pick = { kind: "sector", id: sector.sid } satisfies Pick;
      cap.userData.baseOpacity = sector.important ? 0.14 : 0.1;
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

    // Buildings: add, rebuild when their shape changed, remove the gone.
    const present = new Set<number>();
    for (const building of shot.buildings) {
      present.add(building.bid);
      const key = `${building.kind}|${building.floors}|${building.era}|${building.sector}|${building.plot}`;
      const existing = state.built.get(building.bid);
      if (existing && existing.key === key) {
        existing.group.userData.building = building;
        continue;
      }
      if (existing) state.buildings.remove(existing.group);
      const position = buildingPosition(building);
      if (!position) continue;
      const group = buildingGroup(building.kind, building.floors, building.era, look);
      group.position.copy(position);
      group.quaternion.copy(standUp(position));
      group.rotateY(hash(`b${building.bid}`) * Math.PI * 2);
      group.userData.pick = { kind: "building", id: building.bid } satisfies Pick;
      group.userData.building = building;
      state.buildings.add(group);
      state.built.set(building.bid, { group, key, shown: existing ? existing.shown : building.state === "standing" ? 1 : 0.06 });
    }
    for (const [bid, entry] of Array.from(state.built.entries())) {
      if (!present.has(bid)) {
        state.buildings.remove(entry.group);
        state.built.delete(bid);
      }
    }

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

    // Start-ups fly a flag in their own sector (or at the capital while they wait for approval).
    const liveFlags = new Set<string>();
    for (const startup of shot.startups) {
      if (startup.status === "declined") continue;
      const sector = sectorOf(startup.sector) ?? shot.sectors.find((s) => s.important);
      if (!sector) continue;
      liveFlags.add(startup.suid);
      if (state.flags.has(startup.suid)) continue;
      const centre = latLonToVec(sector.lat, sector.lon);
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
        station.userData.orbit = { radius: R * 1.55 + i * 0.8, speed: 0.08 + i * 0.015, tilt: 0.35 + i * 0.4, phase: i * 1.9 };
        state.sky.add(station);
      }
      for (let i = 0; i < world.planets; i += 1) {
        const made = artificialPlanet(i);
        made.userData.pick = { kind: "station", id: 100 + i } satisfies Pick;
        made.userData.orbit = { radius: R * 3.1 + i * 4, speed: 0.02 + i * 0.006, tilt: 0.2 + i * 0.5, phase: i * 2.4 };
        state.sky.add(made);
      }
    }

    // Permanent talk lines between the capital and every sector, once there are steel frames to hang them on.
    const capital = shot.sectors.find((s) => s.important);
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
        const points = arcPoints(latLonToVec(capital.lat, capital.lon), latLonToVec(sector.lat, sector.lon), 0.12, 40, 0.02);
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
          new THREE.LineBasicMaterial({ color: "#a594ff", transparent: true, opacity: 0.22 }));
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

    // Graves, in rows in the capital's cemetery.
    const yard = graveyard();
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
        {snapshot.sectors.map((sector) => (
          <button key={sector.sid} type="button" className={`wld-label${sector.important ? " is-capital" : ""}`}
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

const KIND_WORDS: Record<string, string> = {
  capitol: "Capitol", house: "Homes", office: "Office", lab: "Laboratory", data_center: "Data centre", mine: "Mine",
  farm: "Farm", factory: "Factory", refinery: "Refinery", archive: "Archive", studio: "Studio", bank: "Bank",
  tower: "Tower", council: "Council hall", station: "Space station", planet: "Artificial planet",
};
