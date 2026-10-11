/** How the world moves, drawn from its transport technology (world/tech.py TRANSPORT_LEVELS): footpaths, then
 * dirt roads with carts, steam railways, motorways full of cars, electric rail, maglev on raised guideways, drone
 * swarms, hover vehicles flying between the cities, glowing skyways, a space elevator from the government's
 * district, warp gates, and star lanes out to other worlds.
 *
 * The owner (2026-10-10): "Tech should be able to get super advanced, from trains to hover vehicles, it shows the
 * user their idea is growing." The network joins every sector and the government district (a spanning tree, plus
 * the next-nearest link once there are motorways); streets ring each sector between its rows of plots. Nothing
 * here is stored: it is all derived from the snapshot, and rebuilt only when the places or the level change. */

import * as THREE from "three";
import { PLOT_SPACING, R, arcPoints, hash, slerpSurface } from "./geo";
import { sharedSolid } from "./meshes";

export interface TransportNode {
  id: string;
  dir: THREE.Vector3;
  /** How far its built-up area reaches, in surface units. */
  reach: number;
  /** Rings of plots, for its streets. */
  rings: number;
}

type HeightFn = (dir: THREE.Vector3) => number;

interface Path {
  points: THREE.Vector3[];
  lengths: number[];
  total: number;
}

interface Mover {
  path: number;
  s: number;
  speed: number;
  slot: number;
}

interface Orbiter {
  centre: THREE.Vector3;
  radius: number;
  altitude: number;
  speed: number;
  phase: number;
  slot: number;
}

const MAX_CARS = 320;
const MAX_TRAIN_CARS = 160;
const MAX_HOVER = 260;
const MAX_DRONES = 200;
const TRAIN_LENGTH = 4;
const UP = new THREE.Vector3(0, 1, 0);

function measure(points: THREE.Vector3[]): Path {
  const lengths = [0];
  for (let i = 1; i < points.length; i += 1) lengths.push(lengths[i - 1] + points[i].distanceTo(points[i - 1]));
  return { points, lengths, total: lengths[lengths.length - 1] || 1 };
}

/** Where along a path, and which way it faces. ``s`` wraps, so movers loop (there and back on open paths). */
function along(path: Path, s: number, out: THREE.Vector3, dir: THREE.Vector3): void {
  const total = path.total;
  let d = ((s % (2 * total)) + 2 * total) % (2 * total);
  let backwards = false;
  if (d > total) {
    d = 2 * total - d;
    backwards = true;
  }
  let lo = 0;
  let hi = path.lengths.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (path.lengths[mid] <= d) lo = mid;
    else hi = mid;
  }
  const a = path.points[lo];
  const b = path.points[Math.min(hi, path.points.length - 1)];
  const span = path.lengths[hi] - path.lengths[lo] || 1;
  out.copy(a).lerp(b, (d - path.lengths[lo]) / span);
  dir.copy(b).sub(a);
  if (backwards) dir.negate();
  if (dir.lengthSq() < 1e-12) dir.set(1, 0, 0);
  dir.normalize();
}

/** A flat strip along the surface: roads, rails, guideways. */
function ribbon(points: THREE.Vector3[], width: number, lateral = 0): THREE.BufferGeometry {
  const positions: number[] = [];
  const normals: number[] = [];
  const uvs: number[] = [];
  const index: number[] = [];
  const up = new THREE.Vector3();
  const fwd = new THREE.Vector3();
  const side = new THREE.Vector3();
  for (let i = 0; i < points.length; i += 1) {
    const p = points[i];
    up.copy(p).normalize();
    fwd.copy(points[Math.min(points.length - 1, i + 1)]).sub(points[Math.max(0, i - 1)]).normalize();
    side.crossVectors(fwd, up).normalize();
    const centre = p.clone().addScaledVector(side, lateral);
    const a = centre.clone().addScaledVector(side, width / 2);
    const b = centre.clone().addScaledVector(side, -width / 2);
    positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
    normals.push(up.x, up.y, up.z, up.x, up.y, up.z);
    uvs.push(0, i, 1, i);
    if (i > 0) {
      const k = i * 2;
      index.push(k - 2, k, k - 1, k - 1, k, k + 1);  // wound to face up
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(index);
  return geometry;
}

function offsetPath(points: THREE.Vector3[], lateral: number, lift: number): THREE.Vector3[] {
  const up = new THREE.Vector3();
  const fwd = new THREE.Vector3();
  const side = new THREE.Vector3();
  return points.map((p, i) => {
    up.copy(p).normalize();
    fwd.copy(points[Math.min(points.length - 1, i + 1)]).sub(points[Math.max(0, i - 1)]).normalize();
    side.crossVectors(fwd, up).normalize();
    return p.clone().addScaledVector(side, lateral).addScaledVector(up, lift);
  });
}

/** Minimum spanning tree over the places (by angle), plus each place's next-nearest link when ``extra``. */
function links(nodes: TransportNode[], extra: boolean): [number, number][] {
  const n = nodes.length;
  if (n < 2) return [];
  const angle = (i: number, j: number) => Math.acos(Math.min(1, Math.max(-1, nodes[i].dir.dot(nodes[j].dir))));
  const inTree = new Set([0]);
  const edges: [number, number][] = [];
  while (inTree.size < n) {
    let best: [number, number] | null = null;
    let bestAngle = Infinity;
    for (const i of inTree) {
      for (let j = 0; j < n; j += 1) {
        if (inTree.has(j)) continue;
        const a = angle(i, j);
        if (a < bestAngle) {
          bestAngle = a;
          best = [i, j];
        }
      }
    }
    if (!best) break;
    edges.push(best);
    inTree.add(best[1]);
  }
  if (extra && n > 2) {
    const has = new Set(edges.map(([a, b]) => `${Math.min(a, b)}:${Math.max(a, b)}`));
    for (let i = 0; i < n; i += 1) {
      const order = Array.from({ length: n }, (_, j) => j).filter((j) => j !== i).sort((a, b) => angle(i, a) - angle(i, b));
      for (const j of order.slice(0, 2)) {
        const key = `${Math.min(i, j)}:${Math.max(i, j)}`;
        if (!has.has(key)) {
          has.add(key);
          edges.push([i, j]);
          break;
        }
      }
    }
  }
  return edges;
}

export class Transport {
  readonly group = new THREE.Group();
  private statics = new THREE.Group();
  private key = "";
  private level = 0;
  private roads: Path[] = [];
  private rails: Path[] = [];
  private lanes: Path[] = [];
  private cars: Mover[] = [];
  private trains: Mover[] = [];
  private hovers: Mover[] = [];
  private drones: Orbiter[] = [];
  private gates: THREE.Mesh[] = [];
  private climber: THREE.Mesh | null = null;
  private elevator: { base: THREE.Vector3; top: THREE.Vector3 } | null = null;
  private carMesh: THREE.InstancedMesh;
  private trainMesh: THREE.InstancedMesh;
  private hoverMesh: THREE.InstancedMesh;
  private droneMesh: THREE.InstancedMesh;

  constructor() {
    const carGeometry = new THREE.BoxGeometry(0.022, 0.016, 0.04);
    carGeometry.translate(0, 0.008, 0);
    this.carMesh = new THREE.InstancedMesh(carGeometry, new THREE.MeshStandardMaterial({ roughness: 0.4, metalness: 0.5 }),
      MAX_CARS);
    const trainGeometry = new THREE.BoxGeometry(0.036, 0.034, 0.075);
    trainGeometry.translate(0, 0.017, 0);
    this.trainMesh = new THREE.InstancedMesh(trainGeometry, new THREE.MeshStandardMaterial({ roughness: 0.35,
      metalness: 0.5 }), MAX_TRAIN_CARS);
    const hoverGeometry = new THREE.CapsuleGeometry(0.018, 0.05, 4, 8);
    hoverGeometry.rotateX(Math.PI / 2);
    this.hoverMesh = new THREE.InstancedMesh(hoverGeometry, new THREE.MeshStandardMaterial({ color: "#e5e5ea",
      emissive: "#64d2ff", emissiveIntensity: 0.9, metalness: 0.7, roughness: 0.25 }), MAX_HOVER);
    this.droneMesh = new THREE.InstancedMesh(new THREE.SphereGeometry(0.012, 6, 4), new THREE.MeshBasicMaterial({
      color: "#ffd60a" }), MAX_DRONES);
    for (const m of [this.carMesh, this.trainMesh, this.hoverMesh, this.droneMesh]) {
      m.count = 0;
      m.frustumCulled = false;
      m.raycast = () => undefined;
      this.group.add(m);
    }
    this.statics.raycast = () => undefined;
    this.group.add(this.statics);
  }

  /** Rebuild when the places, the level or the era change. ``gov`` is the government district's node id. */
  update(nodes: TransportNode[], level: number, height: HeightFn, era: number, gov: string): void {
    const key = `${level}:${era}:${nodes.map((n) => `${n.id}:${n.dir.x.toFixed(3)}:${n.dir.y.toFixed(3)}:${n.rings}`).join("|")}`;
    if (key === this.key) return;
    this.key = key;
    this.level = level;
    this.clearStatics();
    this.roads = [];
    this.rails = [];
    this.lanes = [];
    if (level < 1 || !nodes.length) {
      this.cars = this.trains = this.hovers = [];
      this.drones = [];
      return;
    }

    const ground = (dir: THREE.Vector3, lift = 0.012) => {
      const h = height(dir);
      return dir.clone().multiplyScalar(R + (h < -0.01 ? 0.05 : Math.max(0, h)) + lift);
    };

    // Roads between the places.
    for (const [i, j] of links(nodes, level >= 3)) {
      const a = nodes[i];
      const b = nodes[j];
      const angle = Math.acos(Math.min(1, Math.max(-1, a.dir.dot(b.dir))));
      const from = slerpSurface(a.dir, b.dir, Math.min(0.45, (a.reach / R) / angle)).normalize();
      const to = slerpSurface(a.dir, b.dir, Math.max(0.55, 1 - (b.reach / R) / angle)).normalize();
      const length = from.angleTo(to) * R;
      const steps = Math.max(4, Math.ceil(length / 0.16));
      const points: THREE.Vector3[] = [];
      for (let k = 0; k <= steps; k += 1) points.push(ground(slerpSurface(from, to, k / steps).normalize()));
      this.roads.push(measure(points));
      if (level >= 2) this.rails.push(measure(offsetPath(points, 0.08, level >= 5 ? 0.16 : 0.004)));
      if (level >= 7) this.lanes.push(measure(arcPoints(a.dir.clone().multiplyScalar(R), b.dir.clone().multiplyScalar(R),
        0.9 + hash(`${a.id}${b.id}`) * 0.6, Math.max(24, steps), 0.02)));
    }
    // Streets: rings between each place's rows of plots.
    const streets: Path[] = [];
    for (const node of nodes) {
      const helper = Math.abs(node.dir.y) > 0.98 ? new THREE.Vector3(1, 0, 0) : UP;
      const east = new THREE.Vector3().crossVectors(helper, node.dir).normalize();
      const north = new THREE.Vector3().crossVectors(node.dir, east).normalize();
      for (let ring = 1; ring <= Math.max(1, node.rings); ring += 1) {
        const radius = (ring + 0.5) * PLOT_SPACING;
        const points: THREE.Vector3[] = [];
        const steps = Math.max(18, Math.round(radius * 30));
        for (let k = 0; k <= steps; k += 1) {
          const a = (k / steps) * Math.PI * 2;
          const p = node.dir.clone().multiplyScalar(R).addScaledVector(east, Math.cos(a) * radius)
            .addScaledVector(north, Math.sin(a) * radius).normalize();
          points.push(p.multiplyScalar(R + 0.008));
        }
        streets.push(measure(points));
      }
    }

    // Draw them.
    const roadColor = level >= 3 ? "#34373d" : level >= 2 ? "#6b5f50" : "#8a7355";
    const roadWidth = level >= 3 ? 0.085 : 0.05;
    for (const road of this.roads) this.addStatic(ribbon(road.points, roadWidth), sharedSolid(roadColor, { rough: 0.95 }));
    for (const street of streets) {
      this.addStatic(ribbon(street.points, level >= 3 ? 0.045 : 0.03), sharedSolid(roadColor, { rough: 0.95 }));
    }
    if (level >= 3) {
      // A dashed centre line on the motorways.
      for (const road of this.roads) {
        const dashes = road.points.filter((_, k) => k % 2 === 0).map((p) => p.clone().multiplyScalar(1 + 0.0004));
        this.addStatic(ribbon(dashes, 0.006), sharedSolid("#e8e2c8", { emissive: "#e8e2c8", intensity: 0.15 }));
      }
    }
    if (level >= 2) {
      const guideway = level >= 5;
      for (const rail of this.rails) {
        this.addStatic(ribbon(rail.points, guideway ? 0.045 : 0.032),
          guideway ? sharedSolid("#e5e5ea", { emissive: "#64d2ff", intensity: 0.25, metal: 0.4 })
            : sharedSolid(level >= 4 ? "#4a4d55" : "#3a302a", { rough: 0.9 }));
        if (guideway) {
          // Pylons from the ground up to the guideway.
          const pylon = new THREE.CylinderGeometry(0.008, 0.012, 0.16, 6);
          pylon.translate(0, -0.08, 0);
          const pylons = new THREE.InstancedMesh(pylon, sharedSolid("#c7c7cc", { metal: 0.4 }),
            Math.ceil(rail.points.length / 3));
          const m = new THREE.Matrix4();
          const q = new THREE.Quaternion();
          let count = 0;
          rail.points.forEach((p, k) => {
            if (k % 3) return;
            q.setFromUnitVectors(UP, p.clone().normalize());
            m.compose(p, q, new THREE.Vector3(1, 1, 1));
            pylons.setMatrixAt(count, m);
            count += 1;
          });
          pylons.count = count;
          pylons.raycast = () => undefined;
          this.statics.add(pylons);
        }
      }
    }
    if (level >= 8) {
      for (const lane of this.lanes) {
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(lane.points),
          new THREE.LineBasicMaterial({ color: "#64d2ff", transparent: true, opacity: 0.35,
            blending: THREE.AdditiveBlending, depthWrite: false }));
        line.raycast = () => undefined;
        this.statics.add(line);
      }
    }
    const govNode = nodes.find((n) => n.id === gov) ?? nodes[0];
    if (level >= 9 && govNode) {
      // The space elevator: a cable from the district to a counterweight station in orbit.
      const base = govNode.dir.clone().multiplyScalar(R);
      const top = govNode.dir.clone().multiplyScalar(R * 2.1);
      const cable = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.05, R * 1.1, 8),
        sharedSolid("#d1d1d6", { emissive: "#64d2ff", intensity: 0.35, metal: 0.6 }));
      cable.position.copy(base).lerp(top, 0.5);
      cable.quaternion.setFromUnitVectors(UP, govNode.dir);
      cable.raycast = () => undefined;
      const anchor = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.08, 10, 32),
        sharedSolid("#e5e5ea", { emissive: "#bf5af2", intensity: 0.4, metal: 0.6 }));
      anchor.position.copy(top);
      anchor.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), govNode.dir);
      anchor.raycast = () => undefined;
      this.climber = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.12, 0.12),
        sharedSolid("#ffd60a", { emissive: "#ffd60a", intensity: 0.8 }));
      this.climber.raycast = () => undefined;
      this.elevator = { base, top };
      this.statics.add(cable, anchor, this.climber);
    } else {
      this.climber = null;
      this.elevator = null;
    }
    this.gates = [];
    if (level >= 10) {
      for (const node of nodes) {
        const helper = Math.abs(node.dir.y) > 0.98 ? new THREE.Vector3(1, 0, 0) : UP;
        const east = new THREE.Vector3().crossVectors(helper, node.dir).normalize();
        const at = node.dir.clone().multiplyScalar(R).addScaledVector(east, node.reach + 0.35).normalize()
          .multiplyScalar(R + 0.32);
        const gate = new THREE.Mesh(new THREE.TorusGeometry(0.28, 0.035, 10, 36),
          new THREE.MeshStandardMaterial({ color: "#bf5af2", emissive: "#bf5af2", emissiveIntensity: 1.4 }));
        gate.position.copy(at);
        gate.lookAt(at.clone().add(east));
        gate.raycast = () => undefined;
        this.gates.push(gate);
        this.statics.add(gate);
      }
    }
    if (level >= 11 && govNode) {
      for (let k = 0; k < 5; k += 1) {
        const out = govNode.dir.clone().applyAxisAngle(UP, (k - 2) * 0.25).normalize();
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([
          govNode.dir.clone().multiplyScalar(R * 2.1), out.multiplyScalar(R * 6)]),
        new THREE.LineBasicMaterial({ color: "#ffd60a", transparent: true, opacity: 0.4,
          blending: THREE.AdditiveBlending, depthWrite: false }));
        line.raycast = () => undefined;
        this.statics.add(line);
      }
    }

    // Who travels on them.
    const groundPaths = [...this.roads, ...streets];
    this.roads = groundPaths;
    this.cars = [];
    const carCount = level >= 3 ? Math.min(MAX_CARS, this.roads.length * 5) : Math.min(80, this.roads.length * 2);
    for (let k = 0; k < carCount; k += 1) {
      const path = k % this.roads.length;
      this.cars.push({ path, s: hash(`car${k}`) * this.roads[path].total * 2,
        speed: (level >= 3 ? 0.22 : 0.07) * (0.7 + hash(`cs${k}`) * 0.6), slot: k });
    }
    const carMaterial = this.carMesh.material as THREE.MeshStandardMaterial;
    carMaterial.color.set("#ffffff");
    for (let k = 0; k < carCount; k += 1) {
      const palette = level >= 3 ? ["#ff453a", "#f2f2f7", "#0a84ff", "#ffd60a", "#3a3a3c", "#30d158"] : ["#7a5a3a"];
      this.carMesh.setColorAt(k, new THREE.Color(palette[Math.floor(hash(`cc${k}`) * palette.length)]));
    }
    if (this.carMesh.instanceColor) this.carMesh.instanceColor.needsUpdate = true;

    this.trains = [];
    if (level >= 2) {
      const perRail = level >= 4 ? 2 : 1;
      this.rails.forEach((rail, r) => {
        for (let k = 0; k < perRail && this.trains.length * TRAIN_LENGTH < MAX_TRAIN_CARS; k += 1) {
          this.trains.push({ path: r, s: hash(`tr${r}${k}`) * rail.total * 2,
            speed: level >= 5 ? 1.1 : level >= 4 ? 0.55 : 0.3, slot: this.trains.length });
        }
      });
      (this.trainMesh.material as THREE.MeshStandardMaterial).color.set(level >= 5 ? "#f2f2f7" : level >= 4 ? "#d8e4f0" : "#5a2a22");
      (this.trainMesh.material as THREE.MeshStandardMaterial).emissive.set(level >= 5 ? "#64d2ff" : "#000000");
      (this.trainMesh.material as THREE.MeshStandardMaterial).emissiveIntensity = level >= 5 ? 0.5 : 0;
    }

    this.hovers = [];
    if (level >= 7 && this.lanes.length) {
      const count = Math.min(MAX_HOVER, this.lanes.length * 10);
      for (let k = 0; k < count; k += 1) {
        const path = k % this.lanes.length;
        this.hovers.push({ path, s: hash(`hv${k}`) * this.lanes[path].total * 2,
          speed: 0.9 * (0.7 + hash(`hs${k}`) * 0.6), slot: k });
      }
    }
    this.drones = [];
    if (level >= 6) {
      const per = Math.max(4, Math.floor(MAX_DRONES / Math.max(1, nodes.length)));
      nodes.forEach((node, n) => {
        for (let k = 0; k < per && this.drones.length < MAX_DRONES; k += 1) {
          this.drones.push({ centre: node.dir.clone(), radius: 0.15 + hash(`dr${n}${k}`) * Math.max(0.3, node.reach),
            altitude: 0.3 + hash(`da${n}${k}`) * 0.5, speed: (0.4 + hash(`ds${n}${k}`)) * (k % 2 ? 1 : -1),
            phase: hash(`dp${n}${k}`) * Math.PI * 2, slot: this.drones.length });
        }
      });
    }
  }

  tick(dt: number, t: number, reduced: boolean, running: boolean): void {
    const pace = reduced ? 0 : running ? 1 : 0.4;
    const m = new THREE.Matrix4();
    const p = new THREE.Vector3();
    const dir = new THREE.Vector3();
    const up = new THREE.Vector3();
    const right = new THREE.Vector3();
    const place = (mesh: THREE.InstancedMesh, slot: number, at: THREE.Vector3, facing: THREE.Vector3, lift = 0) => {
      up.copy(at).normalize();
      right.crossVectors(up, facing).normalize();
      const fwd = facing.clone().crossVectors(right, up).normalize();
      m.makeBasis(right, up, fwd);
      m.setPosition(at.x + up.x * lift, at.y + up.y * lift, at.z + up.z * lift);
      mesh.setMatrixAt(slot, m);
    };

    for (const car of this.cars) {
      car.s += car.speed * dt * pace;
      const path = this.roads[car.path];
      if (!path) continue;
      along(path, car.s, p, dir);
      place(this.carMesh, car.slot, p, dir);
    }
    this.carMesh.count = this.cars.length;
    this.carMesh.instanceMatrix.needsUpdate = true;

    let slot = 0;
    for (const train of this.trains) {
      train.s += train.speed * dt * pace;
      const path = this.rails[train.path];
      if (!path) continue;
      for (let c = 0; c < TRAIN_LENGTH && slot < MAX_TRAIN_CARS; c += 1) {
        along(path, train.s - c * 0.085, p, dir);
        place(this.trainMesh, slot, p, dir);
        slot += 1;
      }
    }
    this.trainMesh.count = slot;
    this.trainMesh.instanceMatrix.needsUpdate = true;

    for (const hover of this.hovers) {
      hover.s += hover.speed * dt * pace;
      const path = this.lanes[hover.path];
      if (!path) continue;
      along(path, hover.s, p, dir);
      place(this.hoverMesh, hover.slot, p, dir, (hover.slot % 3) * 0.06);
    }
    this.hoverMesh.count = this.hovers.length;
    this.hoverMesh.instanceMatrix.needsUpdate = true;

    for (const drone of this.drones) {
      const helper = Math.abs(drone.centre.y) > 0.98 ? new THREE.Vector3(1, 0, 0) : UP;
      const east = new THREE.Vector3().crossVectors(helper, drone.centre).normalize();
      const north = new THREE.Vector3().crossVectors(drone.centre, east).normalize();
      const a = drone.phase + t * drone.speed * (reduced ? 0 : 1);
      p.copy(drone.centre).multiplyScalar(R).addScaledVector(east, Math.cos(a) * drone.radius)
        .addScaledVector(north, Math.sin(a) * drone.radius).normalize().multiplyScalar(R + drone.altitude);
      m.makeTranslation(p.x, p.y, p.z);
      this.droneMesh.setMatrixAt(drone.slot, m);
    }
    this.droneMesh.count = this.drones.length;
    this.droneMesh.instanceMatrix.needsUpdate = true;

    if (this.climber && this.elevator) {
      const k = reduced ? 0.4 : (Math.sin(t * 0.12) + 1) / 2;
      this.climber.position.copy(this.elevator.base).lerp(this.elevator.top, 0.05 + k * 0.9);
    }
    for (const gate of this.gates) {
      const pulse = reduced ? 1 : 1 + Math.sin(t * 2.4 + gate.id) * 0.08;
      gate.scale.setScalar(pulse);
    }
  }

  get transportLevel(): number {
    return this.level;
  }

  private addStatic(geometry: THREE.BufferGeometry, material: THREE.Material): void {
    const mesh = new THREE.Mesh(geometry, material);
    mesh.raycast = () => undefined;
    this.statics.add(mesh);
  }

  private clearStatics(): void {
    for (const child of [...this.statics.children]) {
      this.statics.remove(child);
      const item = child as THREE.Mesh;
      item.geometry?.dispose();
      // Shared solids live in the mesh cache; only materials made here are freed.
      const material = item.material as THREE.Material | undefined;
      if (material && !(material as THREE.Material).userData?.shared && (child instanceof THREE.Line ||
        this.gates.includes(child as THREE.Mesh))) material.dispose();
    }
  }

  dispose(): void {
    this.clearStatics();
    for (const m of [this.carMesh, this.trainMesh, this.hoverMesh, this.droneMesh]) {
      m.geometry.dispose();
      (m.material as THREE.Material).dispose();
    }
  }
}
