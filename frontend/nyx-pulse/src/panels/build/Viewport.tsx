/** The Build studio's 3D view.
 *
 * Loaded lazily (it carries three.js and the boolean engine), so the tab's
 * chrome, part lists and checks paint before any of this arrives.
 *
 * Highlighting is the point of this file. The owner asked for "each part
 * highlighted, similar to a tutorial": whatever a tutorial step, a check, a
 * wire or a click points at is outlined and lit, and when a tutorial is running
 * everything else fades back so there is exactly one thing to look at. The
 * camera glides to it. Hovering anything names it.
 */

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { cachedMesh, featurePreview, meshPart, partBox, placementMatrix } from "./geometry";
import { PIN_COLORS, type Focus, type NetPoint, type Part, type Selection, type Snapshot, type Vec3 } from "./types";

export type StudioMode = "space" | "part" | "circuit";
export type Tool = "select" | "move" | "rotate";

export interface ViewportProps {
  snapshot: Snapshot;
  mode: StudioMode;
  tool: Tool;
  selection: Selection;
  multi: string[];
  focus: Focus | null;
  editingPart: Part | null;
  activeFeatureId: string | null;
  pendingPin: NetPoint | null;
  frameRequest: number;
  onSelect: (selection: Selection, additive: boolean) => void;
  onPickPin: (point: NetPoint) => void;
  onMove: (placementId: string, at: Vec3, rot: Vec3) => void;
  onStatus: (text: string) => void;
}

const ACCENT = new THREE.Color("#a594ff");
const DEG = 180 / Math.PI;

interface PieceView {
  group: THREE.Group;
  mesh: THREE.Mesh;
  material: THREE.MeshStandardMaterial;
  outline: THREE.LineSegments | null;
  outlineKey: string;
  pins: THREE.Points | null;
  pinIds: string[];
  meshKey: string;
  placeholder: boolean;
}

function dot(): THREE.Texture {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const g = canvas.getContext("2d")!;
  g.beginPath();
  g.arc(32, 32, 26, 0, Math.PI * 2);
  g.fillStyle = "#fff";
  g.fill();
  g.lineWidth = 6;
  g.strokeStyle = "rgba(0,0,0,0.85)";
  g.stroke();
  return new THREE.CanvasTexture(canvas);
}

function label(className: string): HTMLDivElement {
  const el = document.createElement("div");
  el.className = className;
  el.style.display = "none";
  return el;
}

export default function Viewport(props: ViewportProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const propsRef = useRef(props);
  propsRef.current = props;
  const apiRef = useRef<{ sync: () => void; frame: (box: THREE.Box3 | null) => void } | null>(null);

  useEffect(() => {
    const host = hostRef.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x050507, 1);
    renderer.domElement.className = "bs-canvas";
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.5, 30000);
    camera.position.set(260, 230, 320);
    const orbit = new OrbitControls(camera, renderer.domElement);
    orbit.enableDamping = true;
    orbit.dampingFactor = 0.12;
    orbit.screenSpacePanning = true;
    orbit.target.set(0, 20, 0);

    scene.add(new THREE.HemisphereLight(0xdfe6ff, 0x121216, 1.4));
    const sun = new THREE.DirectionalLight(0xffffff, 2.2);
    sun.position.set(180, 360, 220);
    scene.add(sun);
    const rim = new THREE.DirectionalLight(0x8f84ff, 0.7);
    rim.position.set(-260, 120, -200);
    scene.add(rim);

    // The bed: a grid, the plate, and the outline of the build volume.
    const bed = new THREE.Group();
    scene.add(bed);
    const world = new THREE.Group();
    scene.add(world);
    const wires = new THREE.Group();
    scene.add(wires);
    const editor = new THREE.Group();
    scene.add(editor);

    const transform = new TransformControls(camera, renderer.domElement);
    transform.setTranslationSnap(1);
    transform.setRotationSnap(THREE.MathUtils.degToRad(15));
    transform.setSize(0.8);
    scene.add(transform.getHelper());

    const hoverLabel = label("bs-label");
    const focusLabel = label("bs-label bs-label--focus");
    host.appendChild(hoverLabel);
    host.appendChild(focusLabel);

    const pinSprite = dot();
    const pieces = new Map<string, PieceView>();
    const waiting = new Set<string>();
    const raycaster = new THREE.Raycaster();
    raycaster.params.Points = { threshold: 2.2 };
    (raycaster.params as { Line2?: { threshold: number } }).Line2 = { threshold: 6 };
    const pointer = new THREE.Vector2();
    let hovered: { kind: "placement" | "pin" | "net"; id: string; pin?: string; name: string } | null = null;
    let dirty = true;
    let bedKey = "";
    let wiresKey = "";
    let editorKey = "";
    let lastFocusKey = "";
    let focusTarget: THREE.Vector3 | null = null;
    let glide: { from: THREE.Vector3; to: THREE.Vector3; fromTarget: THREE.Vector3; toTarget: THREE.Vector3; t: number } | null = null;
    let disposed = false;

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = host;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      wires.children.forEach((child) => {
        const material = (child as Line2).material as LineMaterial | undefined;
        material?.resolution?.set(w, h);
      });
      dirty = true;
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);

    // --- camera glide ----------------------------------------------------------------

    const frame = (box: THREE.Box3 | null) => {
      const { snapshot } = propsRef.current;
      const target = box && !box.isEmpty()
        ? box
        : new THREE.Box3(
          new THREE.Vector3(-snapshot.project.space.width / 2, 0, -snapshot.project.space.depth / 2),
          new THREE.Vector3(snapshot.project.space.width / 2, Math.min(snapshot.project.space.height, 120), snapshot.project.space.depth / 2),
        );
      const centre = target.getCenter(new THREE.Vector3());
      const radius = Math.max(target.getSize(new THREE.Vector3()).length() / 2, 12);
      const distance = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.15;
      const direction = camera.position.clone().sub(orbit.target).normalize();
      if (direction.lengthSq() < 0.5) direction.set(0.6, 0.55, 0.75).normalize();
      glide = { from: camera.position.clone(), to: centre.clone().add(direction.multiplyScalar(distance)), fromTarget: orbit.target.clone(), toTarget: centre, t: 0 };
      dirty = true;
    };

    // --- scene sync ------------------------------------------------------------------

    const syncBed = () => {
      const { width, depth, height } = propsRef.current.snapshot.project.space;
      const key = `${width}x${depth}x${height}`;
      if (key === bedKey) return;
      bedKey = key;
      bed.clear();
      const step = width > 600 ? 50 : 10;
      const grid = new THREE.GridHelper(Math.max(width, depth), Math.round(Math.max(width, depth) / step), 0x3a3a48, 0x1d1d26);
      bed.add(grid);
      const plate = new THREE.Mesh(
        new THREE.PlaneGeometry(width, depth).rotateX(-Math.PI / 2),
        new THREE.MeshBasicMaterial({ color: 0x0b0b10, transparent: true, opacity: 0.85, depthWrite: false }),
      );
      plate.position.y = -0.05;
      bed.add(plate);
      const volume = new THREE.Box3Helper(new THREE.Box3(new THREE.Vector3(-width / 2, 0, -depth / 2), new THREE.Vector3(width / 2, height, depth / 2)), 0x2c2c3a);
      bed.add(volume);
    };

    const setOutline = (piece: PieceView, show: boolean, colour: THREE.Color) => {
      if (!show) {
        if (piece.outline) piece.outline.visible = false;
        return;
      }
      if (!piece.outline || piece.outlineKey !== piece.meshKey) {
        if (piece.outline) {
          piece.group.remove(piece.outline);
          piece.outline.geometry.dispose();
        }
        const edges = new THREE.EdgesGeometry(piece.mesh.geometry, 28);
        piece.outline = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: colour, transparent: true, depthTest: false, opacity: 0.95 }));
        piece.outline.renderOrder = 10;
        piece.outlineKey = piece.meshKey;
        piece.group.add(piece.outline);
      }
      (piece.outline.material as THREE.LineBasicMaterial).color.copy(colour);
      piece.outline.visible = true;
    };

    const syncPieces = () => {
      const { snapshot, mode } = propsRef.current;
      const parts = new Map(snapshot.project.parts.map((p) => [p.id, p]));
      const live = new Set<string>();
      let shaping = 0;

      world.visible = mode !== "part";
      for (const placement of snapshot.project.placements) {
        const part = parts.get(placement.part_id);
        if (!part) continue;
        live.add(placement.id);
        let piece = pieces.get(placement.id);
        if (!piece) {
          const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, metalness: 0.12, transparent: true });
          const mesh = new THREE.Mesh(new THREE.BufferGeometry(), material);
          const group = new THREE.Group();
          group.add(mesh);
          world.add(group);
          piece = { group, mesh, material, outline: null, outlineKey: "", pins: null, pinIds: [], meshKey: "", placeholder: true };
          pieces.set(placement.id, piece);
        }
        const matrix = placementMatrix(placement);
        if (transform.object === piece.group) {
          // The gizmo drives position/quaternion, so the group must rebuild its own matrix.
          piece.group.matrixAutoUpdate = true;
          if (!transform.dragging) matrix.decompose(piece.group.position, piece.group.quaternion, piece.group.scale);
        } else {
          piece.group.matrixAutoUpdate = false;
          piece.group.matrix.copy(matrix);
          piece.group.matrixWorldNeedsUpdate = true;
        }
        piece.mesh.userData = { kind: "placement", id: placement.id, name: placement.name || part.name };

        const ready = cachedMesh(part);
        const wantKey = JSON.stringify([part.features, part.shell ?? null, part.color]);
        if (ready && piece.meshKey !== wantKey) {
          piece.mesh.geometry = ready.geometry;
          piece.meshKey = wantKey;
          piece.placeholder = false;
        } else if (!ready) {
          shaping++;
          if (piece.placeholder || piece.meshKey !== wantKey) {
            const box = partBox(part);
            const size = box.getSize(new THREE.Vector3());
            const centre = box.getCenter(new THREE.Vector3());
            const geometry = new THREE.BoxGeometry(size.x, size.y, size.z).translate(centre.x, centre.y, centre.z);
            const colour = new THREE.Color(part.color);
            const colours = new Float32Array(geometry.getAttribute("position").count * 3).map((_, i) => [colour.r, colour.g, colour.b][i % 3]);
            geometry.setAttribute("color", new THREE.BufferAttribute(colours, 3));
            if (piece.placeholder) piece.mesh.geometry = geometry;
            piece.placeholder = true;
          }
          if (!waiting.has(wantKey)) {
            waiting.add(wantKey);
            void meshPart(part).then(() => {
              waiting.delete(wantKey);
              if (!disposed) sync();
            });
          }
        }

        // Pins: screen-sized dots, so a 2.54 mm header is visible from across the bed.
        const pinKey = part.pins.map((p) => p.id + p.at.join(",")).join("|");
        if (!piece.pins || piece.pins.userData.key !== pinKey) {
          if (piece.pins) {
            piece.group.remove(piece.pins);
            piece.pins.geometry.dispose();
          }
          const positions = new Float32Array(part.pins.flatMap((p) => p.at));
          const colours = new Float32Array(part.pins.flatMap((p) => new THREE.Color(PIN_COLORS[p.kind] ?? "#64d2ff").toArray()));
          const geometry = new THREE.BufferGeometry();
          geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
          geometry.setAttribute("color", new THREE.BufferAttribute(colours, 3));
          piece.pins = new THREE.Points(geometry, new THREE.PointsMaterial({
            size: 9, sizeAttenuation: false, vertexColors: true, map: pinSprite, alphaTest: 0.4, transparent: true, depthTest: false,
          }));
          piece.pins.renderOrder = 20;
          piece.pins.userData = { key: pinKey, kind: "pins", id: placement.id };
          piece.pinIds = part.pins.map((p) => p.id);
          piece.group.add(piece.pins);
        }
      }
      for (const [id, piece] of pieces) {
        if (live.has(id)) continue;
        if (transform.object === piece.group) transform.detach();
        world.remove(piece.group);
        piece.material.dispose();
        piece.pins?.geometry.dispose();
        piece.outline?.geometry.dispose();
        pieces.delete(id);
      }
      propsRef.current.onStatus(shaping ? `Shaping ${shaping} part${shaping === 1 ? "" : "s"}…` : "");
    };

    const worldPin = (point: NetPoint): THREE.Vector3 | null => {
      const { snapshot } = propsRef.current;
      const placement = snapshot.project.placements.find((p) => p.id === point.placement);
      const part = placement && snapshot.project.parts.find((p) => p.id === placement.part_id);
      const pin = part?.pins.find((p) => p.id === point.pin);
      return placement && pin ? new THREE.Vector3(...pin.at).applyMatrix4(placementMatrix(placement)) : null;
    };

    const syncWires = () => {
      const { snapshot } = propsRef.current;
      const key = JSON.stringify([snapshot.project.nets, snapshot.project.placements.map((p) => [p.id, p.at, p.rot, p.scale])]);
      if (key === wiresKey) return;
      wiresKey = key;
      wires.children.forEach((child) => {
        (child as Line2).geometry.dispose();
        ((child as Line2).material as LineMaterial).dispose();
      });
      wires.clear();
      for (const net of snapshot.project.nets) {
        const ends = net.points.map(worldPin).filter((v): v is THREE.Vector3 => Boolean(v)).sort((a, b) => a.x - b.x);
        for (let i = 0; i < ends.length - 1; i++) {
          const a = ends[i], b = ends[i + 1];
          const lift = Math.max(8, a.distanceTo(b) * 0.25);
          const curve = new THREE.CatmullRomCurve3([a, a.clone().setY(Math.max(a.y, b.y) + lift), b.clone().setY(Math.max(a.y, b.y) + lift), b], false, "centripetal");
          const points = curve.getPoints(28).flatMap((p) => [p.x, p.y, p.z]);
          const geometry = new LineGeometry();
          geometry.setPositions(points);
          const material = new LineMaterial({ color: new THREE.Color(net.color).getHex(), linewidth: 3, transparent: true, opacity: 0.95, depthTest: false });
          material.resolution.set(host.clientWidth || 1, host.clientHeight || 1);
          const line = new Line2(geometry, material);
          line.computeLineDistances();
          line.renderOrder = 15;
          line.userData = { kind: "net", id: net.id, name: net.name };
          wires.add(line);
        }
      }
    };

    const syncEditor = () => {
      const { editingPart, activeFeatureId, mode } = propsRef.current;
      editor.visible = mode === "part" && Boolean(editingPart);
      if (!editingPart || mode !== "part") return;
      const key = JSON.stringify([editingPart.features, editingPart.shell ?? null, editingPart.color, activeFeatureId, editingPart.pins]);
      if (key === editorKey) return;
      editorKey = key;

      const draw = (geometry: THREE.BufferGeometry) => {
        editor.children.forEach((child) => {
          const node = child as THREE.Mesh;
          if (node.userData.transient) node.geometry?.dispose();
        });
        editor.clear();
        const body = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
          vertexColors: true, roughness: 0.5, metalness: 0.12, transparent: true, opacity: activeFeatureId ? 0.55 : 1,
        }));
        editor.add(body);

        const active = editingPart.features.find((f) => f.id === activeFeatureId);
        if (active) {
          // The feature being edited is the tutorial of this mode: a cut shows as the red
          // volume it removes, a solid shows lit with its edges traced.
          const ghost = featurePreview(active, active.op === "add" ? "#a594ff" : "#ff453a");
          const ghostMesh = new THREE.Mesh(ghost, new THREE.MeshStandardMaterial({
            vertexColors: true, transparent: true, opacity: active.op === "add" ? 0.5 : 0.38, depthWrite: false, emissive: new THREE.Color(active.op === "add" ? "#2a2260" : "#3a0d0a"),
          }));
          ghostMesh.renderOrder = 5;
          ghostMesh.userData.transient = true;
          editor.add(ghostMesh);
          const edges = new THREE.LineSegments(new THREE.EdgesGeometry(ghost, 28), new THREE.LineBasicMaterial({ color: active.op === "add" ? ACCENT : new THREE.Color("#ff6961"), depthTest: false }));
          edges.renderOrder = 11;
          edges.userData.transient = true;
          editor.add(edges);
        }
        if (editingPart.pins.length) {
          const geometry2 = new THREE.BufferGeometry();
          geometry2.setAttribute("position", new THREE.BufferAttribute(new Float32Array(editingPart.pins.flatMap((p) => p.at)), 3));
          geometry2.setAttribute("color", new THREE.BufferAttribute(new Float32Array(editingPart.pins.flatMap((p) => new THREE.Color(PIN_COLORS[p.kind] ?? "#64d2ff").toArray())), 3));
          const points = new THREE.Points(geometry2, new THREE.PointsMaterial({ size: 9, sizeAttenuation: false, vertexColors: true, map: pinSprite, alphaTest: 0.4, transparent: true, depthTest: false }));
          points.userData.transient = true;
          editor.add(points);
        }
        dirty = true;
      };

      const cached = cachedMesh(editingPart);
      if (cached) {
        draw(cached.geometry);
      } else {
        propsRef.current.onStatus("Shaping the part…");
        const wanted = editorKey;
        void meshPart(editingPart).then((result) => {
          if (disposed || wanted !== editorKey) return;
          propsRef.current.onStatus(result.approximate ? "Shown approximately — one shape could not be cut cleanly." : "");
          draw(result.geometry);
        });
      }
    };

    /** Who is lit, who is dimmed, and where the camera should look. */
    const syncHighlight = () => {
      const { snapshot, selection, multi, focus, mode, pendingPin } = propsRef.current;
      const lit = new Set<string>();
      let litNet = "";
      if (focus && focus.kind !== "none") {
        if (focus.kind === "placement") lit.add(focus.id);
        if (focus.kind === "part") snapshot.project.placements.filter((p) => p.part_id === focus.id).forEach((p) => lit.add(p.id));
        if (focus.kind === "net") {
          litNet = focus.id;
          snapshot.project.nets.find((n) => n.id === focus.id)?.points.forEach((pt) => lit.add(pt.placement));
        }
      }
      const touring = Boolean(focus && focus.kind !== "none");
      const selectedId = selection.kind === "placement" ? selection.id : selection.kind === "pin" ? selection.placement : "";
      const selectedNet = selection.kind === "net" ? selection.id : "";
      const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 260);

      for (const [id, piece] of pieces) {
        const isLit = lit.has(id);
        const isSelected = id === selectedId;
        const isMulti = multi.includes(id);
        const isHover = hovered?.kind === "placement" && hovered.id === id;
        const onNet = selectedNet && snapshot.project.nets.find((n) => n.id === selectedNet)?.points.some((pt) => pt.placement === id);

        let opacity = piece.placeholder ? 0.28 : 1;
        if (touring && !isLit) opacity = 0.12;
        else if (mode === "circuit" && !isSelected && !onNet) opacity = Math.min(opacity, 0.6);
        piece.material.opacity = opacity;
        piece.material.depthWrite = opacity > 0.9;
        piece.material.emissive.set(0x000000);
        if (isLit) piece.material.emissive.copy(ACCENT).multiplyScalar(0.18 + 0.2 * pulse);
        else if (isSelected || onNet) piece.material.emissive.copy(ACCENT).multiplyScalar(0.12);
        else if (isHover) piece.material.emissive.setScalar(0.08);

        setOutline(piece, isLit || isSelected || isMulti || Boolean(onNet), isMulti && !isSelected ? new THREE.Color("#f5f5f7") : ACCENT);
        if (piece.pins) {
          piece.pins.visible = mode === "circuit" || isSelected || isLit || selection.kind === "pin" && selection.placement === id;
          (piece.pins.material as THREE.PointsMaterial).size = pendingPin?.placement === id ? 11 : 9;
        }
      }

      for (const child of wires.children) {
        const line = child as Line2;
        const material = line.material as LineMaterial;
        const on = line.userData.id === litNet || line.userData.id === selectedNet || (hovered?.kind === "net" && hovered.id === line.userData.id);
        material.linewidth = on ? 6 : 3;
        material.opacity = touring && !on ? 0.15 : 0.95;
      }

      // Glide to what the tutorial points at, once per step.
      const focusKey = touring ? `${focus!.kind}:${focus!.id}` : "";
      if (focusKey && focusKey !== lastFocusKey) {
        const box = new THREE.Box3();
        for (const id of lit) {
          const piece = pieces.get(id);
          if (piece) box.union(new THREE.Box3().setFromObject(piece.mesh));
        }
        if (!box.isEmpty()) {
          frame(box);
          focusTarget = box.getCenter(new THREE.Vector3()).setY(box.max.y);
        }
      }
      if (!touring) focusTarget = null;
      lastFocusKey = focusKey;
    };

    const syncTransform = () => {
      const { selection, tool, mode, focus } = propsRef.current;
      const piece = selection.kind === "placement" ? pieces.get(selection.id) : undefined;
      const placement = selection.kind === "placement" ? propsRef.current.snapshot.project.placements.find((p) => p.id === selection.id) : undefined;
      const allowed = mode === "space" && tool !== "select" && piece && placement && !placement.locked && !(focus && focus.kind !== "none");
      if (!allowed) {
        if (transform.object) transform.detach();
        return;
      }
      if (transform.object !== piece!.group) {
        piece!.group.matrixAutoUpdate = true;
        piece!.group.matrix.decompose(piece!.group.position, piece!.group.quaternion, piece!.group.scale);
        transform.attach(piece!.group);
      }
      transform.setMode(tool === "rotate" ? "rotate" : "translate");
    };

    const sync = () => {
      if (disposed) return;
      syncBed();
      syncPieces();
      syncWires();
      syncEditor();
      syncTransform();
      syncHighlight();
      dirty = true;
    };

    apiRef.current = { sync, frame };

    // --- input ---------------------------------------------------------------------

    const pick = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      const { mode } = propsRef.current;
      if (mode === "part") return null;

      const pinTargets = [...pieces.values()].map((p) => p.pins).filter((p): p is THREE.Points => Boolean(p?.visible));
      const pinHit = raycaster.intersectObjects(pinTargets, false)[0];
      if (pinHit && pinHit.index !== undefined) {
        const placementId = pinHit.object.userData.id as string;
        const piece = pieces.get(placementId)!;
        const pinId = piece.pinIds[pinHit.index];
        const part = propsRef.current.snapshot.project.parts.find((p) => p.id === propsRef.current.snapshot.project.placements.find((pl) => pl.id === placementId)?.part_id);
        const pin = part?.pins.find((p) => p.id === pinId);
        return { kind: "pin" as const, id: placementId, pin: pinId, name: `${pin?.name ?? "pin"} · ${pin?.kind ?? ""}${pin?.voltage ? ` ${pin.voltage} V` : ""}` };
      }
      const wireHit = raycaster.intersectObjects(wires.children, false)[0];
      if (wireHit) return { kind: "net" as const, id: wireHit.object.userData.id as string, name: `Wire: ${wireHit.object.userData.name}` };
      const hit = raycaster.intersectObjects([...pieces.values()].map((p) => p.mesh), false)
        .find((h) => ((h.object as THREE.Mesh).material as THREE.MeshStandardMaterial).opacity > 0.2);
      if (hit) return { kind: "placement" as const, id: hit.object.userData.id as string, name: hit.object.userData.name as string };
      return null;
    };

    let down: { x: number; y: number } | null = null;
    const onDown = (event: PointerEvent) => { down = { x: event.clientX, y: event.clientY }; };
    const onUp = (event: PointerEvent) => {
      if (!down || transform.dragging) { down = null; return; }
      const moved = Math.hypot(event.clientX - down.x, event.clientY - down.y);
      down = null;
      if (moved > 5) return;
      const target = pick(event);
      const { onSelect, onPickPin, mode } = propsRef.current;
      if (target?.kind === "pin") {
        if (mode === "circuit") onPickPin({ placement: target.id, pin: target.pin! });
        else onSelect({ kind: "pin", placement: target.id, pin: target.pin! }, false);
      } else if (target?.kind === "net") {
        onSelect({ kind: "net", id: target.id }, false);
      } else if (target?.kind === "placement") {
        onSelect({ kind: "placement", id: target.id }, event.shiftKey || event.ctrlKey || event.metaKey);
      } else if (!event.shiftKey) {
        onSelect({ kind: "none" }, false);
      }
    };
    const onMoveHover = (event: PointerEvent) => {
      if (event.buttons) return;
      const target = pick(event);
      const changed = (target?.id ?? "") + (target?.pin ?? "") !== (hovered?.id ?? "") + (hovered?.pin ?? "");
      hovered = target;
      renderer.domElement.style.cursor = target ? "pointer" : "grab";
      if (target) {
        const rect = host.getBoundingClientRect();
        hoverLabel.textContent = target.name;
        hoverLabel.style.display = "block";
        hoverLabel.style.transform = `translate(${event.clientX - rect.left + 14}px, ${event.clientY - rect.top + 12}px)`;
      } else {
        hoverLabel.style.display = "none";
      }
      if (changed) {
        syncHighlight();
        dirty = true;
      }
    };
    const onLeave = () => {
      hovered = null;
      hoverLabel.style.display = "none";
      syncHighlight();
      dirty = true;
    };

    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);
    renderer.domElement.addEventListener("pointermove", onMoveHover);
    renderer.domElement.addEventListener("pointerleave", onLeave);
    orbit.addEventListener("change", () => { dirty = true; });
    transform.addEventListener("change", () => { dirty = true; });
    transform.addEventListener("dragging-changed", (event) => {
      orbit.enabled = !event.value;
      const object = transform.object;
      if (event.value || !object) return;
      const id = [...pieces.entries()].find(([, piece]) => piece.group === object)?.[0];
      if (!id) return;
      const euler = new THREE.Euler().setFromQuaternion(object.quaternion, "XYZ");
      const round = (v: number) => Math.round(v * 100) / 100;
      propsRef.current.onMove(id,
        [round(object.position.x), round(object.position.y), round(object.position.z)],
        [round(euler.x * DEG), round(euler.y * DEG), round(euler.z * DEG)]);
    });

    // --- loop ----------------------------------------------------------------------

    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (document.hidden) return;
      const delta = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (glide) {
        glide.t = Math.min(1, glide.t + delta / 0.55);
        const e = 1 - Math.pow(1 - glide.t, 3);
        camera.position.lerpVectors(glide.from, glide.to, e);
        orbit.target.lerpVectors(glide.fromTarget, glide.toTarget, e);
        if (glide.t >= 1) glide = null;
        dirty = true;
      }
      orbit.update();
      const { focus, snapshot } = propsRef.current;
      const touring = Boolean(focus && focus.kind !== "none");
      if (touring) {
        syncHighlight(); // the pulse
        dirty = true;
      }
      if (focusTarget && touring) {
        const screen = focusTarget.clone().project(camera);
        const title = focus!.kind === "net"
          ? snapshot.project.nets.find((n) => n.id === focus!.id)?.name
          : snapshot.project.placements.find((p) => p.id === focus!.id)?.name;
        if (screen.z < 1 && title) {
          focusLabel.textContent = title;
          focusLabel.style.display = "block";
          focusLabel.style.transform = `translate(-50%, -140%) translate(${((screen.x + 1) / 2) * host.clientWidth}px, ${((1 - screen.y) / 2) * host.clientHeight}px)`;
        }
      } else {
        focusLabel.style.display = "none";
      }
      if (dirty) {
        renderer.render(scene, camera);
        dirty = false;
      }
    };
    raf = requestAnimationFrame(tick);
    resize();
    sync();
    frame(null);

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      observer.disconnect();
      transform.detach();
      transform.dispose();
      orbit.dispose();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("pointermove", onMoveHover);
      renderer.domElement.removeEventListener("pointerleave", onLeave);
      scene.traverse((node) => {
        const mesh = node as THREE.Mesh;
        if (mesh.material) (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach((m) => m.dispose());
      });
      pinSprite.dispose();
      renderer.dispose();
      host.innerHTML = "";
    };
  }, []);

  // Everything the parent changes flows through one sync; the scene diffs itself.
  useEffect(() => {
    apiRef.current?.sync();
  }, [props.snapshot, props.mode, props.tool, props.selection, props.multi, props.focus, props.editingPart, props.activeFeatureId, props.pendingPin]);

  useEffect(() => {
    if (!props.frameRequest || !apiRef.current) return;
    const { snapshot, selection, mode, editingPart } = propsRef.current;
    if (mode === "part" && editingPart) {
      apiRef.current.frame(partBox(editingPart));
      return;
    }
    if (selection.kind === "placement") {
      const placement = snapshot.project.placements.find((p) => p.id === selection.id);
      const part = placement && snapshot.project.parts.find((p) => p.id === placement.part_id);
      if (placement && part) {
        apiRef.current.frame(partBox(part).applyMatrix4(placementMatrix(placement)));
        return;
      }
    }
    const everything = new THREE.Box3();
    for (const placement of snapshot.project.placements) {
      const part = snapshot.project.parts.find((p) => p.id === placement.part_id);
      if (part) everything.union(partBox(part).applyMatrix4(placementMatrix(placement)));
    }
    apiRef.current.frame(everything.isEmpty() ? null : everything);
  }, [props.frameRequest]);

  return <div ref={hostRef} className="bs-viewport" aria-label="3D view of the build. Drag to orbit, scroll to zoom, click a part to select it." />;
}
