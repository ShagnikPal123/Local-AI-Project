/** Plays a game spec in 3D (Request H5: "make games in 3d and 2d").
 *
 * The same engine and the same rooms as the 2D view, built out of lit, shadowed
 * blocks with depth and a camera that follows from an angle — a side-on 3D game
 * in the style of Ori or Trine. Drag to swing the camera round; it eases back.
 */

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { createState, inputFrom, roomOf, step, type State } from "./engine";
import type { GameSpec, Room } from "./types";

interface Props { game: GameSpec; onExit?: () => void }

const DEPTH = 3;

function buildRoom(game: GameSpec, room: Room): THREE.Group {
  const group = new THREE.Group();
  const solids: [number, number][] = [];
  const platforms: [number, number][] = [];
  const hazards: [number, number][] = [];
  const doors: [number, number][] = [];
  room.tiles.forEach((row, y) => {
    for (let x = 0; x < row.length; x += 1) {
      const tile = row[x];
      if (tile === "#") solids.push([x, y]);
      else if (tile === "=") platforms.push([x, y]);
      else if (tile === "^") hazards.push([x, y]);
      else if (tile === "D") doors.push([x, y]);
    }
  });

  const place = (mesh: THREE.InstancedMesh, cells: [number, number][], yOffset = 0) => {
    const matrix = new THREE.Matrix4();
    cells.forEach(([x, y], index) => {
      matrix.makeTranslation(x + 0.5, -(y + 0.5) + yOffset, 0);
      mesh.setMatrixAt(index, matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
  };

  if (solids.length) {
    place(new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, DEPTH),
      new THREE.MeshStandardMaterial({ color: game.palette.ground, roughness: 0.9 }), solids.length), solids);
  }
  if (platforms.length) {
    place(new THREE.InstancedMesh(new THREE.BoxGeometry(1, 0.25, DEPTH * 0.8),
      new THREE.MeshStandardMaterial({ color: game.palette.platform, roughness: 0.7 }), platforms.length), platforms, 0.37);
  }
  if (hazards.length) {
    place(new THREE.InstancedMesh(new THREE.ConeGeometry(0.4, 0.8, 4),
      new THREE.MeshStandardMaterial({ color: game.palette.hazard, emissive: game.palette.hazard, emissiveIntensity: 0.35 }),
      hazards.length), hazards, -0.1);
  }
  if (doors.length) {
    place(new THREE.InstancedMesh(new THREE.BoxGeometry(0.9, 1.6, 0.2),
      new THREE.MeshStandardMaterial({ color: game.palette.accent, emissive: game.palette.accent, emissiveIntensity: 0.8,
        transparent: true, opacity: 0.7 }), doors.length), doors, 0.3);
  }

  // A back wall so the room reads as a place, not blocks floating in space.
  const back = new THREE.Mesh(new THREE.PlaneGeometry(room.width + 20, room.height + 20),
    new THREE.MeshStandardMaterial({ color: game.palette.bg, roughness: 1 }));
  back.position.set(room.width / 2, -room.height / 2, -DEPTH / 2 - 0.01);
  back.receiveShadow = true;
  group.add(back);
  return group;
}

export function Play3D({ game, onExit }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const stateRef = useRef<State | null>(null);
  const keysRef = useRef<Set<string>>(new Set());
  const [hud, setHud] = useState({ health: 0, max: 0, room: "", message: "" });
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  pausedRef.current = paused;

  useEffect(() => {
    stateRef.current = createState(game);
  }, [game]);

  useEffect(() => {
    function down(event: KeyboardEvent) {
      if (event.key === "Escape") { setPaused((was) => !was); return; }
      if ([" ", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) event.preventDefault();
      keysRef.current.add(event.key.length === 1 ? event.key.toLowerCase() : event.key);
    }
    function up(event: KeyboardEvent) {
      keysRef.current.delete(event.key.length === 1 ? event.key.toLowerCase() : event.key);
    }
    function blur() { keysRef.current.clear(); }
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(game.palette.bg);
    scene.fog = new THREE.Fog(game.palette.bg, 18, 48);
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 200);
    scene.add(new THREE.HemisphereLight(0xbfc8ff, 0x101018, 0.7));
    const sun = new THREE.DirectionalLight(0xffffff, 1.3);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    sun.shadow.camera.left = -30; sun.shadow.camera.right = 30;
    sun.shadow.camera.top = 30; sun.shadow.camera.bottom = -30;
    scene.add(sun);
    scene.add(sun.target);

    const player = new THREE.Mesh(new THREE.CapsuleGeometry(0.32, 0.36, 4, 12),
      new THREE.MeshStandardMaterial({ color: game.player.colour, emissive: game.player.colour, emissiveIntensity: 0.15 }));
    player.castShadow = true;
    scene.add(player);
    const blade = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.12, 0.12),
      new THREE.MeshStandardMaterial({ color: game.palette.accent, emissive: game.palette.accent, emissiveIntensity: 1 }));
    scene.add(blade);

    let roomGroup: THREE.Group | null = null;
    let builtFor = "";
    const enemyMeshes = new Map<string, THREE.Mesh>();
    const itemMeshes = new Map<string, THREE.Mesh>();
    let swing = 0;
    let dragging = false;
    let lastX = 0;

    function onDown(event: PointerEvent) { dragging = true; lastX = event.clientX; renderer.domElement.setPointerCapture(event.pointerId); }
    function onMove(event: PointerEvent) {
      if (!dragging) return;
      swing = Math.max(-1.1, Math.min(1.1, swing + (event.clientX - lastX) * 0.006));
      lastX = event.clientX;
    }
    function onUp() { dragging = false; }
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("pointerup", onUp);

    function resize() {
      const width = host!.clientWidth || 640;
      const height = host!.clientHeight || 400;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(host);

    let frame = 0;
    let last = performance.now();
    let hudAt = 0;
    const camTarget = new THREE.Vector3();

    function loop(now: number) {
      frame = requestAnimationFrame(loop);
      const state = stateRef.current;
      if (!state) return;
      const dt = (now - last) / 1000;
      last = now;
      if (!pausedRef.current) step(game, state, inputFrom(keysRef.current), dt);
      const room = roomOf(game, state.roomId);
      if (!room) return;

      if (builtFor !== room.id) {
        if (roomGroup) {
          scene.remove(roomGroup);
          roomGroup.traverse((object) => {
            const mesh = object as THREE.Mesh;
            mesh.geometry?.dispose();
            const material = mesh.material as THREE.Material | undefined;
            material?.dispose?.();
          });
        }
        roomGroup = buildRoom(game, room);
        scene.add(roomGroup);
        builtFor = room.id;
        enemyMeshes.forEach((mesh) => scene.remove(mesh));
        enemyMeshes.clear();
        itemMeshes.forEach((mesh) => scene.remove(mesh));
        itemMeshes.clear();
      }

      player.position.set(state.x, -state.y, 0);
      player.visible = !(state.invuln > 0 && Math.floor(state.invuln * 12) % 2 === 0);
      player.rotation.z = state.dashTime > 0 ? -state.facing * 0.5 : 0;
      blade.visible = state.attackTime > 0;
      blade.position.set(state.x + state.facing * 0.85, -state.y, 0.3);

      const alive = new Set<string>();
      for (const enemy of state.enemies) {
        alive.add(enemy.key);
        let mesh = enemyMeshes.get(enemy.key);
        if (!mesh) {
          mesh = new THREE.Mesh(
            enemy.behaviour === "flyer" ? new THREE.OctahedronGeometry(0.4 * enemy.size) : new THREE.BoxGeometry(0.7 * enemy.size, 0.6 * enemy.size, 0.7 * enemy.size),
            new THREE.MeshStandardMaterial({ color: enemy.colour, emissive: enemy.colour, emissiveIntensity: 0.25 }));
          mesh.castShadow = true;
          scene.add(mesh);
          enemyMeshes.set(enemy.key, mesh);
        }
        mesh.position.set(enemy.x, -enemy.y, 0);
        if (enemy.behaviour === "flyer") mesh.rotation.y += dt * 2;
      }
      enemyMeshes.forEach((mesh, key) => { if (!alive.has(key)) { scene.remove(mesh); enemyMeshes.delete(key); } });

      for (const item of state.items) {
        let mesh = itemMeshes.get(item.key);
        if (!mesh) {
          mesh = new THREE.Mesh(new THREE.OctahedronGeometry(item.kind === "ability" ? 0.32 : 0.16),
            new THREE.MeshStandardMaterial({ color: item.kind === "ability" ? game.palette.accent : "#ffd60a",
              emissive: item.kind === "ability" ? game.palette.accent : "#ffd60a", emissiveIntensity: 0.9 }));
          scene.add(mesh);
          itemMeshes.set(item.key, mesh);
        }
        mesh.visible = !item.taken;
        mesh.position.set(item.x, -item.y + Math.sin(now / 400) * 0.08, 0);
        mesh.rotation.y += dt * 1.6;
      }

      if (!dragging) swing *= 0.94;
      camTarget.set(state.x, -state.y + 1.2, 0);
      const distance = 13;
      camera.position.lerp(new THREE.Vector3(
        camTarget.x + Math.sin(swing) * distance, camTarget.y + 2.4, Math.cos(swing) * distance), 0.12);
      camera.lookAt(camTarget);
      sun.position.set(state.x + 8, -state.y + 16, 12);
      sun.target.position.set(state.x, -state.y, 0);
      renderer.render(scene, camera);

      if (now - hudAt > 150) {
        hudAt = now;
        setHud({ health: state.health, max: state.maxHealth, room: room.name,
          message: state.messageFor > 0 ? state.message : "" });
      }
    }
    frame = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointermove", onMove);
      renderer.domElement.removeEventListener("pointerup", onUp);
      scene.traverse((object) => {
        const mesh = object as THREE.Mesh;
        mesh.geometry?.dispose?.();
        const material = mesh.material as THREE.Material | undefined;
        material?.dispose?.();
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [game]);

  return (
    <div className="game-play">
      <div className="game-play__hud">
        <span aria-label={`${hud.health} of ${hud.max} hearts left`}>
          {"♥".repeat(Math.max(0, hud.health))}<span className="muted">{"♡".repeat(Math.max(0, hud.max - hud.health))}</span>
          <span className="muted"> {hud.health}/{hud.max}</span>
        </span>
        <span className="muted">{hud.room}</span>
        <button className="btn btn-secondary btn-sm" onClick={() => setPaused((was) => !was)}>{paused ? "Carry on" : "Pause"}</button>
        <button className="btn btn-secondary btn-sm" onClick={() => { stateRef.current = createState(game); }}>Restart</button>
        {onExit && <button className="btn btn-secondary btn-sm" onClick={onExit}>Back to the editor</button>}
      </div>
      <div ref={hostRef} className="game-play__canvas game-play__three" tabIndex={0}
        aria-label={`${game.title} in 3D, playing. Arrow keys or A and D to move, Space to jump. Drag to swing the camera. Escape pauses.`} />
      {hud.message && <p className="game-play__message" role="status">{hud.message}</p>}
      {paused && <p className="game-play__message" role="status">Paused — press Esc to carry on</p>}
      <p className="muted game-play__keys">
        ← → or A D move · Space jumps{game.player.dash && " · Shift dashes"}{game.player.attack && " · J hits"} · drag to look round · Esc pauses
      </p>
    </div>
  );
}
