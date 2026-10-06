/** The memory field — Nyx's super brain drawn as a living 3D galaxy of what it knows.
 *
 * Every point is a real node from `/api/brain/points` (a memory Nyx read or said,
 * a concept, or a source hub), placed around its source cluster and coloured by
 * it. The strongest links draw as faint threads. New memories arrive over the
 * workspace bus (`brain.impulse`) and bloom in without a reload; clusters Nyx is
 * working in pulse. 100k+ points render as one GPU draw call (custom point shader,
 * additive blending), so it stays smooth as the brain grows.
 *
 * Controls: drag to rotate, Shift-drag or right-drag to pan, scroll to zoom,
 * arrow keys rotate, +/- zoom, 0 resets, F goes full screen. Clicking a point asks
 * the engine what it is. Reduced motion stops the idle drift, twinkle and blooms.
 */

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import * as THREE from "three";
import { authHeaders } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";

export interface BrainCluster {
  id: number;
  key: string;
  label: string;
  color: string;
  count: number;
  centre: [number, number, number];
  top: string[];
}

export interface BrainStats {
  fps: number;
  points: number;
  edges: number;
}

export interface BrainNodeInfo {
  id: number;
  label: string;
  kind: string;
  cluster: number;
  hits: number;
  memory?: { text: string; source: string; kind: string; ref: string } | null;
  neighbours: { id: number; label: string; kind: string; cluster: number; weight: number }[];
}

export interface BrainFieldHandle {
  reset: () => void;
  focusCluster: (id: number | null) => void;
  zoom: (factor: number) => void;
  fullscreen: () => void;
  reload: () => void;
}

interface Props {
  clusters: BrainCluster[];
  reduced: boolean;
  /** Clusters Nyx is working in right now (pulse). */
  active: number[];
  /** Point indices to light up (search results). */
  highlight: number[];
  onStats?: (stats: BrainStats) => void;
  onSelect?: (node: BrainNodeInfo | null) => void;
  /** Screen-space label anchors, recomputed each frame for the HUD tags. */
  onProject?: (anchors: { id: number; x: number; y: number; visible: boolean }[]) => void;
  /** Pixels to move the field's centre left (so a side sheet doesn't cover it). */
  shiftX?: number;
}

const MAX_EXTRA = 60000;
/** Cluster centres are drawn this much further apart than stored, so big clouds don't merge. */
const CENTRE_SCALE = 2.1;
const vertex = /* glsl */ `
  attribute float aSize;
  attribute float aSeed;
  attribute float aBorn;
  attribute float aCluster;
  attribute float aHighlight;
  uniform float uTime;
  uniform float uScale;
  uniform float uReduced;
  uniform float uFocus;
  uniform float uPulse[12];
  uniform float uDensity[12];
  uniform float uSizeK;
  uniform float uAlphaK;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float twinkle = uReduced > 0.5 ? 1.0 : 0.82 + 0.18 * sin(uTime * (0.6 + aSeed * 1.8) + aSeed * 40.0);
    float age = uTime - aBorn;
    float bloom = aBorn < 0.0 || uReduced > 0.5 ? 1.0 : smoothstep(0.0, 1.2, age) * (1.0 + 2.2 * exp(-age * 1.6));
    int ci = int(aCluster + 0.5);
    float pulse = ci >= 0 && ci < 12 ? uPulse[ci] : 0.0;
    float focus = uFocus < 0.0 ? 1.0 : (abs(aCluster - uFocus) < 0.5 ? 1.25 : 0.35);
    float size = aSize * (1.0 + pulse * 0.9 + aHighlight * 2.5) * bloom;
    gl_PointSize = clamp(size * uScale * (uSizeK / max(1.0, -mv.z)), 1.0, 48.0);
    gl_Position = projectionMatrix * mv;
    vColor = mix(color, vec3(1.0), clamp(aHighlight * 0.6 + pulse * 0.2, 0.0, 0.8));
    // Thousands of points overlap in a cluster and blending adds them up: keep each one faint so a dense
    // cloud glows in its own colour instead of saturating to white. Concepts and hubs read brighter.
    float density = ci >= 0 && ci < 12 ? uDensity[ci] : 1.0;
    float base = aSize < 2.0 ? 0.5 * density : (aSize < 10.0 ? 0.7 * sqrt(density) : 1.0);
    vAlpha = uAlphaK * twinkle * focus * base * (1.0 + pulse * 0.8 + aHighlight * 3.0);
  }
`;
const fragment = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec2 p = gl_PointCoord - 0.5;
    float d = length(p);
    if (d > 0.5) discard;
    float core = smoothstep(0.5, 0.0, d);
    float glow = pow(core, 3.0);
    vec3 rgb = vColor * (0.45 * core + 0.75 * glow) * vAlpha;
    // Alpha follows brightness, so faint edges don't paint dark discs over a custom background.
    gl_FragColor = vec4(rgb, clamp(max(rgb.r, max(rgb.g, rgb.b)), 0.0, 1.0));
  }
`;

function hexToRgb(hex: string): [number, number, number] {
  const value = parseInt(hex.replace("#", ""), 16);
  return [((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255];
}

async function fetchBuffer(path: string): Promise<{ count: number; data: ArrayBuffer } | null> {
  try {
    const response = await fetch(path, { headers: authHeaders() });
    if (!response.ok) return null;
    return { count: Number(response.headers.get("X-Count") || 0), data: await response.arrayBuffer() };
  } catch {
    return null;
  }
}

export const BrainField = forwardRef<BrainFieldHandle, Props>(function BrainField(
  { clusters, reduced, active, highlight, onStats, onSelect, onProject, shiftX = 0 },
  ref,
) {
  const shiftRef = useRef(shiftX);
  shiftRef.current = shiftX;
  const host = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "empty" | "nogl">("loading");
  const api = useRef<{
    reset: () => void; focusCluster: (id: number | null) => void; zoom: (f: number) => void; reload: () => void;
    setActive: (ids: number[]) => void; setHighlight: (indices: number[]) => void; setReduced: (r: boolean) => void;
    setClusters: (c: BrainCluster[]) => void;
  } | null>(null);
  const callbacks = useRef({ onStats, onSelect, onProject });
  callbacks.current = { onStats, onSelect, onProject };

  useImperativeHandle(ref, () => ({
    reset: () => api.current?.reset(),
    focusCluster: (id) => api.current?.focusCluster(id),
    zoom: (f) => api.current?.zoom(f),
    reload: () => api.current?.reload(),
    fullscreen: () => {
      const el = host.current?.parentElement ?? host.current;
      if (!el) return;
      if (document.fullscreenElement) void document.exitFullscreen();
      else void el.requestFullscreen?.();
    },
  }), []);

  useEffect(() => {
    const container = host.current;
    if (!container) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      setStatus("nogl");
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    // Opaque black, unless the owner put a custom background behind Nyx (Request G8).
    const syncClear = () => renderer.setClearColor(0x000000, document.documentElement.classList.contains("has-custom-bg") ? 0 : 1);
    syncClear();
    const bgWatch = new MutationObserver(syncClear);
    bgWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    container.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.touchAction = "none";

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(55, 1, 0.5, 4000);
    const target = new THREE.Vector3();
    const goalTarget = new THREE.Vector3();
    let radius = 1500, goalRadius = 1080, theta = 0.6, phi = 1.2;
    let reducedMotion = reduced;
    let focus = -1;
    let clusterList: BrainCluster[] = clusters;

    const pulses = new Float32Array(12);
    const pulseGoal = new Float32Array(12);
    const densities = new Float32Array(12).fill(1);
    const uniforms = {
      uTime: { value: 0 }, uScale: { value: 1 }, uReduced: { value: reducedMotion ? 1 : 0 },
      uFocus: { value: -1 }, uPulse: { value: Array.from(pulses) }, uDensity: { value: Array.from(densities) },
      uSizeK: { value: 2000 }, uAlphaK: { value: 1.3 },
    };
    const material = new THREE.ShaderMaterial({
      vertexShader: vertex, fragmentShader: fragment, uniforms, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, vertexColors: true,
    });

    let points: THREE.Points | null = null;
    let geometry: THREE.BufferGeometry | null = null;
    let lines: THREE.LineSegments | null = null;
    let used = 0;
    let capacity = 0;
    /** Positions as the engine stored them; the drawn layout spreads big clusters around these. */
    let base = new Float32Array(0);
    const spreads = new Float32Array(12).fill(1);
    const clusterRgb = () => clusterList.map((c) => hexToRgb(c.color));
    const worldCentre = (c: BrainCluster): [number, number, number] => [c.centre[0] * CENTRE_SCALE, c.centre[1] * CENTRE_SCALE, c.centre[2] * CENTRE_SCALE];
    const computeLayout = () => {
      for (const c of clusterList) {
        if (c.id < 0 || c.id >= 12) continue;
        spreads[c.id] = Math.min(3.6, Math.max(1, Math.sqrt(c.count / 600)));
        densities[c.id] = Math.min(1, Math.max(0.1, Math.sqrt(900 / Math.max(1, c.count))));
      }
      uniforms.uDensity.value = Array.from(densities);
    };
    const place = (positions: Float32Array, i: number, cluster: number) => {
      const c = clusterList.find((item) => item.id === cluster);
      const bx = base[i * 3], by = base[i * 3 + 1], bz = base[i * 3 + 2];
      if (!c) { positions[i * 3] = bx; positions[i * 3 + 1] = by; positions[i * 3 + 2] = bz; return; }
      const s = spreads[cluster] ?? 1;
      const [cx, cy, cz] = c.centre;
      positions[i * 3] = cx * CENTRE_SCALE + (bx - cx) * s;
      positions[i * 3 + 1] = cy * CENTRE_SCALE + (by - cy) * s;
      positions[i * 3 + 2] = cz * CENTRE_SCALE + (bz - cz) * s;
    };

    const build = (count: number, data: ArrayBuffer) => {
      if (points) { scene.remove(points); geometry?.dispose(); }
      const view = new Float32Array(data);
      capacity = count + MAX_EXTRA;
      used = count;
      const positions = new Float32Array(capacity * 3);
      base = new Float32Array(capacity * 3);
      const colors = new Float32Array(capacity * 3);
      const sizes = new Float32Array(capacity);
      const seeds = new Float32Array(capacity);
      const born = new Float32Array(capacity).fill(-1);
      const clusterAttr = new Float32Array(capacity);
      const hl = new Float32Array(capacity);
      const rgb = clusterRgb();
      for (let i = 0; i < count; i += 1) {
        const o = i * 6;
        base[i * 3] = view[o]; base[i * 3 + 1] = view[o + 1]; base[i * 3 + 2] = view[o + 2];
        const cluster = view[o + 3], kind = view[o + 4], weight = view[o + 5];
        place(positions, i, cluster | 0);
        const c = rgb[cluster | 0] ?? [0.7, 0.7, 0.8];
        const shade = kind === 2 ? 1.25 : kind === 1 ? 1.0 : 0.75;
        colors[i * 3] = c[0] * shade; colors[i * 3 + 1] = c[1] * shade; colors[i * 3 + 2] = c[2] * shade;
        sizes[i] = kind === 2 ? 14 : kind === 1 ? 2.2 + Math.min(4, Math.log1p(weight) * 1.2) : 1.5;
        seeds[i] = (Math.sin(i * 12.9898) * 43758.5453) % 1;
        clusterAttr[i] = cluster;
      }
      geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      geometry.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
      geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
      geometry.setAttribute("aBorn", new THREE.BufferAttribute(born, 1));
      geometry.setAttribute("aCluster", new THREE.BufferAttribute(clusterAttr, 1));
      geometry.setAttribute("aHighlight", new THREE.BufferAttribute(hl, 1));
      geometry.setDrawRange(0, used);
      geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1600);
      points = new THREE.Points(geometry, material);
      points.frustumCulled = false;
      scene.add(points);
    };

    const buildEdges = (count: number, data: ArrayBuffer) => {
      if (lines) { scene.remove(lines); lines.geometry.dispose(); }
      if (!geometry || !count) return;
      // Only concept↔concept threads: a popular concept links to thousands of memories, and drawing
      // those turned every busy concept into a white starburst. The idea web is the part worth seeing.
      const raw = new Uint32Array(data);
      const sizeAttr = geometry.getAttribute("aSize").array as Float32Array;
      const kept: number[] = [];
      for (let i = 0; i < count && kept.length < 24000; i += 1) {
        const a = raw[i * 2], b = raw[i * 2 + 1];
        if (sizeAttr[a] >= 2 && sizeAttr[b] >= 2) kept.push(a, b);
      }
      const pairs = Uint32Array.from(kept);
      const pos = geometry.getAttribute("position") as THREE.BufferAttribute;
      const col = geometry.getAttribute("color") as THREE.BufferAttribute;
      const shown = pairs.length / 2;
      const linePositions = new Float32Array(shown * 6);
      const lineColors = new Float32Array(shown * 6);
      for (let i = 0; i < shown; i += 1) {
        const a = pairs[i * 2], b = pairs[i * 2 + 1];
        for (let k = 0; k < 3; k += 1) {
          linePositions[i * 6 + k] = pos.array[a * 3 + k] as number;
          linePositions[i * 6 + 3 + k] = pos.array[b * 3 + k] as number;
          lineColors[i * 6 + k] = (col.array[a * 3 + k] as number) * 0.6;
          lineColors[i * 6 + 3 + k] = (col.array[b * 3 + k] as number) * 0.6;
        }
      }
      const lineGeometry = new THREE.BufferGeometry();
      lineGeometry.setAttribute("position", new THREE.BufferAttribute(linePositions, 3));
      lineGeometry.setAttribute("color", new THREE.BufferAttribute(lineColors, 3));
      lines = new THREE.LineSegments(lineGeometry, new THREE.LineBasicMaterial({
        vertexColors: true, transparent: true, opacity: 0.026, blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      lines.frustumCulled = false;
      lines.userData.pairs = pairs;
      scene.add(lines);
    };

    /** Colours and cluster sizes come from the cluster list, which can arrive after the points:
     *  re-lay-out and repaint when it does (and when the counts change). */
    const recolor = () => {
      if (!geometry || !clusterList.length) return;
      computeLayout();
      const rgb = clusterRgb();
      const pos = geometry.getAttribute("position") as THREE.BufferAttribute;
      const col = geometry.getAttribute("color") as THREE.BufferAttribute;
      const size = geometry.getAttribute("aSize") as THREE.BufferAttribute;
      const clusterAttr = geometry.getAttribute("aCluster") as THREE.BufferAttribute;
      const colors = col.array as Float32Array;
      const positions = pos.array as Float32Array;
      for (let i = 0; i < used; i += 1) {
        const cluster = (clusterAttr.array as Float32Array)[i] | 0;
        place(positions, i, cluster);
        const c = rgb[cluster] ?? [0.7, 0.7, 0.8];
        const s = (size.array as Float32Array)[i];
        const shade = s >= 10 ? 1.25 : s >= 2 ? 1.0 : 0.75;
        colors[i * 3] = c[0] * shade; colors[i * 3 + 1] = c[1] * shade; colors[i * 3 + 2] = c[2] * shade;
      }
      col.needsUpdate = true;
      pos.needsUpdate = true;
      if (lines) {
        const lineColors = lines.geometry.getAttribute("color") as THREE.BufferAttribute;
        const linePositions = lines.geometry.getAttribute("position") as THREE.BufferAttribute;
        const pairsCount = lineColors.count / 2;
        const edgePairs = (lines.userData.pairs ?? null) as Uint32Array | null;
        if (edgePairs) {
          for (let i = 0; i < pairsCount; i += 1) {
            const a = edgePairs[i * 2], b = edgePairs[i * 2 + 1];
            for (let k = 0; k < 3; k += 1) {
              (lineColors.array as Float32Array)[i * 6 + k] = colors[a * 3 + k] * 0.6;
              (lineColors.array as Float32Array)[i * 6 + 3 + k] = colors[b * 3 + k] * 0.6;
              (linePositions.array as Float32Array)[i * 6 + k] = positions[a * 3 + k];
              (linePositions.array as Float32Array)[i * 6 + 3 + k] = positions[b * 3 + k];
            }
          }
          lineColors.needsUpdate = true;
          linePositions.needsUpdate = true;
        }
      }
    };

    let loadToken = 0;
    const load = async () => {
      const token = ++loadToken;
      setStatus("loading");
      const pointsData = await fetchBuffer("/api/brain/points");
      if (token !== loadToken) return;
      if (!pointsData || !pointsData.count) { setStatus("empty"); return; }
      build(pointsData.count, pointsData.data);
      recolor();
      setStatus("ready");
      const edgeData = await fetchBuffer("/api/brain/edges?limit=40000");
      if (token === loadToken && edgeData) buildEdges(edgeData.count, edgeData.data);
    };
    void load();

    const appendNodes = (nodes: { cluster: number; kind: number; x: number; y: number; z: number }[]) => {
      if (!geometry) return;
      const rgb = clusterRgb();
      const pos = geometry.getAttribute("position") as THREE.BufferAttribute;
      const col = geometry.getAttribute("color") as THREE.BufferAttribute;
      const size = geometry.getAttribute("aSize") as THREE.BufferAttribute;
      const bornAttr = geometry.getAttribute("aBorn") as THREE.BufferAttribute;
      const clusterAttr = geometry.getAttribute("aCluster") as THREE.BufferAttribute;
      const start = used;
      for (const node of nodes) {
        if (used >= capacity) break;
        const i = used;
        base.set([node.x, node.y, node.z], i * 3);
        place(pos.array as Float32Array, i, node.cluster);
        const c = rgb[node.cluster] ?? [0.8, 0.8, 0.9];
        const shade = node.kind === 2 ? 1.25 : node.kind === 1 ? 1.0 : 0.8;
        (col.array as Float32Array).set([c[0] * shade, c[1] * shade, c[2] * shade], i * 3);
        (size.array as Float32Array)[i] = node.kind === 2 ? 14 : node.kind === 1 ? 2.6 : 1.8;
        (bornAttr.array as Float32Array)[i] = uniforms.uTime.value;
        (clusterAttr.array as Float32Array)[i] = node.cluster;
        pulseGoal[node.cluster] = Math.max(pulseGoal[node.cluster], 0.8);
        used += 1;
      }
      if (used === start) return;
      for (const attr of [pos, col, size, bornAttr, clusterAttr]) {
        attr.addUpdateRange(start * attr.itemSize, (used - start) * attr.itemSize);
        attr.needsUpdate = true;
      }
      geometry.setDrawRange(0, used);
    };
    const offImpulse = onWorkspaceEvent((event) => {
      const e = event as { type: string; nodes?: { cluster: number; kind: number; x: number; y: number; z: number }[] };
      if (e.type === "brain.impulse" && e.nodes?.length) appendNodes(e.nodes);
      if (e.type === "brain.seeded") void load();
    });

    // --- controls ------------------------------------------------------------------
    let dragging: null | { x: number; y: number; pan: boolean; moved: number } = null;
    let lastInteraction = 0;
    const onPointerDown = (e: PointerEvent) => {
      renderer.domElement.setPointerCapture(e.pointerId);
      dragging = { x: e.clientX, y: e.clientY, pan: e.shiftKey || e.button === 2, moved: 0 };
      lastInteraction = performance.now();
    };
    const onPointerMove = (e: PointerEvent) => {
      if (!dragging) return;
      const dx = e.clientX - dragging.x, dy = e.clientY - dragging.y;
      dragging.x = e.clientX; dragging.y = e.clientY;
      dragging.moved += Math.abs(dx) + Math.abs(dy);
      lastInteraction = performance.now();
      if (dragging.pan) {
        const scale = radius / 700;
        const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
        const up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
        goalTarget.addScaledVector(right, -dx * scale).addScaledVector(up, dy * scale);
      } else {
        // + so the field follows the hand: raising theta moves the camera to screen-left.
        theta += dx * 0.005;
        phi = Math.min(Math.PI - 0.15, Math.max(0.15, phi - dy * 0.005));
      }
    };
    const raycaster = new THREE.Raycaster();
    raycaster.params.Points = { threshold: 3 };
    const onPointerUp = async (e: PointerEvent) => {
      const wasClick = dragging && dragging.moved < 4;
      dragging = null;
      if (!wasClick || !points) return;
      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.params.Points = { threshold: Math.max(1.5, radius / 180) };
      raycaster.setFromCamera(mouse, camera);
      const hit = raycaster.intersectObject(points, false).filter((h) => (h.index ?? 0) < used).sort((a, b) => a.distanceToRay! - b.distanceToRay!)[0];
      if (!hit || hit.index === undefined) { callbacks.current.onSelect?.(null); return; }
      try {
        const response = await fetch(`/api/brain/at/${hit.index}`, { headers: authHeaders() });
        if (response.ok) callbacks.current.onSelect?.(await response.json());
      } catch { /* engine restarting */ }
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      goalRadius = Math.min(2600, Math.max(40, goalRadius * Math.exp(e.deltaY * 0.0012)));
      lastInteraction = performance.now();
    };
    const onKey = (e: KeyboardEvent) => {
      const k = e.key;
      if (k === "ArrowLeft") theta += 0.08;
      else if (k === "ArrowRight") theta -= 0.08;
      else if (k === "ArrowUp") phi = Math.max(0.15, phi - 0.08);
      else if (k === "ArrowDown") phi = Math.min(Math.PI - 0.15, phi + 0.08);
      else if (k === "+" || k === "=") goalRadius = Math.max(40, goalRadius * 0.85);
      else if (k === "-") goalRadius = Math.min(2600, goalRadius * 1.18);
      else if (k === "0") api.current?.reset();
      else if (k.toLowerCase() === "f") { const el = container.parentElement ?? container; if (document.fullscreenElement) void document.exitFullscreen(); else void el.requestFullscreen?.(); }
      else return;
      e.preventDefault();
      lastInteraction = performance.now();
    };
    const el = renderer.domElement;
    el.tabIndex = 0;
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", "Nyx's memory field: every point is something Nyx has read or learned, grouped by source. Use arrow keys to rotate and plus or minus to zoom.");
    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointermove", onPointerMove);
    el.addEventListener("pointerup", onPointerUp);
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("keydown", onKey);
    el.addEventListener("contextmenu", (e) => e.preventDefault());

    api.current = {
      reset: () => { goalTarget.set(0, 0, 0); goalRadius = 1080; theta = 0.6; phi = 1.2; focus = -1; uniforms.uFocus.value = -1; },
      focusCluster: (id) => {
        focus = id ?? -1;
        uniforms.uFocus.value = focus;
        const cluster = clusterList.find((c) => c.id === id);
        if (cluster) { goalTarget.set(...worldCentre(cluster)); goalRadius = 260 + 110 * (spreads[cluster.id] ?? 1); } else { goalTarget.set(0, 0, 0); goalRadius = 1080; }
      },
      zoom: (f) => { goalRadius = Math.min(2600, Math.max(40, goalRadius * f)); },
      reload: () => void load(),
      setActive: (ids) => { pulseGoal.fill(0); ids.forEach((id) => { if (id >= 0 && id < 12) pulseGoal[id] = 1; }); },
      setHighlight: (indices) => {
        if (!geometry) return;
        const attr = geometry.getAttribute("aHighlight") as THREE.BufferAttribute;
        (attr.array as Float32Array).fill(0);
        indices.forEach((i) => { if (i >= 0 && i < capacity) (attr.array as Float32Array)[i] = 1; });
        attr.needsUpdate = true;
      },
      setReduced: (r) => { reducedMotion = r; uniforms.uReduced.value = r ? 1 : 0; },
      setClusters: (c) => {
        clusterList = c;
        recolor();
      },
    };

    // Tuning hook for the render (dev tools): window.__nyxBrain.lines(false), .alpha(0.5)
    (window as unknown as Record<string, unknown>).__nyxBrain = {
      lines: (on: boolean) => { if (lines) lines.visible = on; },
      points: (on: boolean) => { if (points) points.visible = on; },
      lineOpacity: (v: number) => { if (lines) (lines.material as THREE.LineBasicMaterial).opacity = v; },
      size: (v: number) => { uniforms.uSizeK.value = v; },
      alpha: (v: number) => { uniforms.uAlphaK.value = v; },
      stats: () => ({ used, lines: lines ? lines.geometry.getAttribute("position").count / 2 : 0, radius, spreads: Array.from(spreads), densities: Array.from(densities) }),
    };

    // --- loop -------------------------------------------------------------------------
    const resize = () => {
      const w = container.clientWidth || 1, h = container.clientHeight || 1;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = `${w}px`;
      renderer.domElement.style.height = `${h}px`;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      uniforms.uScale.value = Math.min(w, h) / 800 * (window.devicePixelRatio > 1 ? 1.25 : 1);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();

    let frame = 0;
    let viewShift = 0;
    let last = performance.now();
    let fpsFrames = 0, fpsTime = 0;
    const projected = new THREE.Vector3();
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      if (document.hidden) return;
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      uniforms.uTime.value += dt;
      if (!reducedMotion && !dragging && now - lastInteraction > 2500) theta += dt * 0.035;
      radius += (goalRadius - radius) * (reducedMotion ? 1 : Math.min(1, dt * 4));
      target.lerp(goalTarget, reducedMotion ? 1 : Math.min(1, dt * 4));
      for (let i = 0; i < 12; i += 1) {
        const goal = pulseGoal[i];
        pulses[i] += (goal - pulses[i]) * Math.min(1, dt * 3);
        if (goal > 0 && goal < 1) pulseGoal[i] = Math.max(0, goal - dt * 0.6);
      }
      uniforms.uPulse.value = Array.from(pulses);
      camera.position.set(
        target.x + radius * Math.sin(phi) * Math.cos(theta),
        target.y + radius * Math.cos(phi),
        target.z + radius * Math.sin(phi) * Math.sin(theta),
      );
      camera.lookAt(target);
      const cw = container.clientWidth || 1, ch = container.clientHeight || 1;
      const shift = cw > 900 ? shiftRef.current : 0;
      viewShift += (shift - viewShift) * (reducedMotion ? 1 : Math.min(1, dt * 5));
      if (Math.abs(viewShift) > 0.5) camera.setViewOffset(cw, ch, viewShift, 0, cw, ch);
      else camera.clearViewOffset();
      renderer.render(scene, camera);

      fpsFrames += 1;
      fpsTime += dt;
      if (fpsTime >= 0.5) {
        callbacks.current.onStats?.({ fps: Math.round(fpsFrames / fpsTime), points: used, edges: lines ? (lines.geometry.getAttribute("position").count / 2) : 0 });
        fpsFrames = 0; fpsTime = 0;
      }
      if (callbacks.current.onProject) {
        const w = container.clientWidth, h = container.clientHeight;
        callbacks.current.onProject(clusterList.filter((c) => c.count > 0).map((c) => {
          projected.set(...worldCentre(c)).project(camera);
          return { id: c.id, x: (projected.x * 0.5 + 0.5) * w, y: (-projected.y * 0.5 + 0.5) * h, visible: projected.z < 1 };
        }));
      }
    };
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      loadToken += 1;
      offImpulse();
      observer.disconnect();
      bgWatch.disconnect();
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("pointermove", onPointerMove);
      el.removeEventListener("pointerup", onPointerUp);
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("keydown", onKey);
      geometry?.dispose();
      lines?.geometry.dispose();
      material.dispose();
      renderer.dispose();
      container.removeChild(renderer.domElement);
      api.current = null;
    };
    // The scene is built once; props flow in through the api effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { api.current?.setActive(active); }, [active]);
  useEffect(() => { api.current?.setHighlight(highlight); }, [highlight]);
  useEffect(() => { api.current?.setReduced(reduced); }, [reduced]);
  useEffect(() => { api.current?.setClusters(clusters); }, [clusters]);

  const retry = useCallback(() => api.current?.reload(), []);

  return (
    <div ref={host} className="brain-host" style={{ position: "absolute", inset: 0, overflow: "hidden", background: "#000" }}>
      {status === "loading" && (
        <div className="brain-status" aria-live="polite">Loading the memory field…</div>
      )}
      {status === "empty" && (
        <div className="brain-status">
          The brain is empty — it fills as Nyx reads and talks.{" "}
          <button className="btn btn-secondary" onClick={retry}>Check again</button>
        </div>
      )}
      {status === "nogl" && (
        <div className="brain-status">This browser can't draw 3D (WebGL is off). Everything else still works.</div>
      )}
    </div>
  );
});
