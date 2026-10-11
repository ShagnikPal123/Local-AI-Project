/** Ichos's voice face (owner, 2026-10-10): three faces, one for each thing a voice does.
 *
 *  • **Listening** — a swarm of particles held in a sphere. It stirs when you talk: the louder you are, the further
 *    the particles push out to the shell and the faster they shiver (the echo-cancelled microphone level, `micVad`).
 *  • **Thinking** — several Möbius strips turning inside each other, light running along each band, the half-twist
 *    itself rolling round.
 *  • **Speaking** — Equalize's sphere as it was, now an equalizer wrapped on a globe: each latitude is a frequency
 *    band of Ichos's own voice (`outputLevels`), so the sphere moves with what it says.
 *
 * The three live in one WebGL scene and cross-fade, because voice2 does them at once: while you talk it is already
 * drafting the answer (the strips show inside the swarm as `drafting` rises), and while it speaks it still listens
 * (the swarm blooms when you talk over it). Everything moves on the GPU; the CPU only sets a handful of uniforms.
 */

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { vadRunning, vadState } from "../../voice/micVad";
import { outputLevels } from "../../voice/voicePlayer";
import "./voiceface.css";

export type FaceState = "idle" | "listening" | "thinking" | "speaking";

export const FACE_WORDS: Record<FaceState, string> = { idle: "Ready", listening: "Listening", thinking: "Thinking", speaking: "Speaking" };

const BANDS = 16;
const COLOURS = { idle: 0xa594ff, listening: 0x60cdff, thinking: 0xfce100, speaking: 0x6ccb5f };
const STRIP_COLOURS = [0xfce100, 0xffb547, 0xff8a65, 0xa594ff];

// --- shaders --------------------------------------------------------------------------------------------------------

const POINT_FRAGMENT = /* glsl */ `
  uniform vec3 uColor; uniform float uOpacity;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    gl_FragColor = vec4(uColor, smoothstep(0.5, 0.05, d) * uOpacity * vAlpha);
  }`;

/** Particles anywhere inside the ball; they drift, shiver and push out to the shell with the owner's voice. */
const SWARM_VERTEX = /* glsl */ `
  uniform float uTime, uLevel, uSize, uPixel, uScale;
  attribute float aSeed;
  varying float vAlpha;
  void main() {
    float r = length(position);
    vec3 dir = r > 0.0 ? position / r : vec3(0.0, 1.0, 0.0);
    float rr = mix(r, 0.72 + 0.28 * r, uLevel);
    float t = uTime * (0.6 + 0.8 * fract(aSeed * 3.7));
    vec3 drift = vec3(sin(t * 1.3 + aSeed * 20.0), cos(t * 1.7 + aSeed * 13.0), sin(t * 1.1 + aSeed * 7.0));
    float shiver = 1.0 + uLevel * 0.22 * sin(uTime * 14.0 + aSeed * 40.0);
    vec3 p = (dir * rr * shiver + drift * (0.045 + 0.12 * uLevel)) * uScale;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = max(1.2, uSize * uPixel / -mv.z * (0.7 + 0.6 * fract(aSeed * 5.3)));
    vAlpha = 0.6 + 0.4 * fract(aSeed * 7.13) * (0.6 + 0.4 * r);
  }`;

/** A Fibonacci sphere; each latitude rides one band of the voice, equator low, poles high. */
const GLOBE_VERTEX = /* glsl */ `
  uniform float uTime, uLevel, uSize, uPixel, uScale, uBands[${BANDS}];
  attribute float aSeed;
  varying float vAlpha;
  void main() {
    float lat = abs(position.y);
    float f = lat * float(${BANDS - 1});
    int i = int(floor(f));
    float band = mix(uBands[i], uBands[min(i + 1, ${BANDS - 1})], fract(f));
    float theta = atan(position.z, position.x);
    float wave = sin(uTime * 1.6 + position.y * 6.0 + position.x * 3.0) * (0.025 + 0.06 * uLevel)
               + sin(theta * 6.0 - uTime * 4.0) * 0.05 * uLevel;
    vec3 p = position * (1.0 + band * 0.2 + wave) * uScale;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = max(1.2, uSize * uPixel / -mv.z * (1.0 + band * 0.8));
    vAlpha = 0.55 + 0.45 * band + 0.2 * fract(aSeed * 7.13);
  }`;

/** A Möbius strip built from a flat grid: u runs round the loop, v across the band. The half-twist rolls with uPhase,
 * which stays seamless because turning u by 2π flips v. */
const STRIP_VERTEX = /* glsl */ `
  uniform float uRadius, uWidth, uPhase, uScale;
  varying vec2 vUv;
  void main() {
    float u = uv.x * 6.2831853;
    float v = (uv.y - 0.5) * 2.0 * uWidth;
    float half_ = u * 0.5 + uPhase;
    float ring = uRadius + v * cos(half_);
    vec3 p = vec3(ring * cos(u), ring * sin(u), v * sin(half_)) * uScale;
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }`;

const STRIP_FRAGMENT = /* glsl */ `
  uniform vec3 uColor; uniform float uOpacity, uTime, uSpeed;
  varying vec2 vUv;
  void main() {
    float flow = 0.5 + 0.5 * sin(vUv.x * 6.2831853 * 3.0 - uTime * uSpeed);
    float edge = smoothstep(0.0, 0.18, vUv.y) * smoothstep(1.0, 0.82, vUv.y);
    float rim = smoothstep(0.42, 0.5, abs(vUv.y - 0.5));
    float a = (0.12 + 0.88 * flow * flow) * edge + rim * 0.6;
    gl_FragColor = vec4(uColor * (0.75 + 0.5 * flow), a * uOpacity);
  }`;

// --- the scene ------------------------------------------------------------------------------------------------------

function pointsMaterial(vertex: string, colour: number, size: number, extra: Record<string, THREE.IUniform> = {}) {
  return new THREE.ShaderMaterial({
    vertexShader: vertex,
    fragmentShader: POINT_FRAGMENT,
    uniforms: {
      uTime: { value: 0 }, uLevel: { value: 0 }, uSize: { value: size }, uPixel: { value: 300 }, uScale: { value: 1 },
      uColor: { value: new THREE.Color(colour) }, uOpacity: { value: 0 }, ...extra,
    },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
}

function seeds(count: number): THREE.BufferAttribute {
  const s = new Float32Array(count);
  for (let i = 0; i < count; i += 1) s[i] = Math.random();
  return new THREE.BufferAttribute(s, 1);
}

function swarm(count: number): THREE.BufferGeometry {
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {
    const u = Math.random() * 2 - 1;
    const a = Math.random() * Math.PI * 2;
    const r = Math.cbrt(Math.random());                // even through the volume, not bunched at the centre
    const s = Math.sqrt(1 - u * u);
    positions.set([Math.cos(a) * s * r, u * r, Math.sin(a) * s * r], i * 3);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("aSeed", seeds(count));
  return geometry;
}

function globe(count: number): THREE.BufferGeometry {
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {               // Fibonacci sphere: even spacing, no seams
    const y = 1 - (i / (count - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const t = i * Math.PI * (3 - Math.sqrt(5));
    positions.set([Math.cos(t) * r, y, Math.sin(t) * r], i * 3);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("aSeed", seeds(count));
  return geometry;
}

type Strip = { mesh: THREE.Mesh; material: THREE.ShaderMaterial; spin: THREE.Vector3; phaseSpeed: number };

function strips(scene: THREE.Scene): Strip[] {
  const grid = new THREE.PlaneGeometry(1, 1, 220, 6);  // only its uvs are used; the shader bends it
  const specs = [
    { radius: 0.62, width: 0.2, tilt: [0.3, 0, 0.2], spin: [0.5, 0.9, 0.1], phase: 0.6, speed: 3.2 },
    { radius: 0.8, width: 0.16, tilt: [1.2, 0.4, 0], spin: [-0.4, 0.3, 0.7], phase: -0.45, speed: 2.6 },
    { radius: 0.48, width: 0.14, tilt: [-0.7, 1.1, 0.5], spin: [0.8, -0.5, 0.3], phase: 0.9, speed: 4.1 },
    { radius: 0.95, width: 0.1, tilt: [0.2, -0.9, 1.3], spin: [0.2, 0.6, -0.5], phase: -0.3, speed: 2.1 },
  ];
  return specs.map((spec, i) => {
    const material = new THREE.ShaderMaterial({
      vertexShader: STRIP_VERTEX,
      fragmentShader: STRIP_FRAGMENT,
      uniforms: {
        uRadius: { value: spec.radius }, uWidth: { value: spec.width }, uPhase: { value: 0 }, uScale: { value: 1 },
        uColor: { value: new THREE.Color(STRIP_COLOURS[i]) }, uOpacity: { value: 0 }, uTime: { value: 0 },
        uSpeed: { value: spec.speed },
      },
      transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
    });
    const mesh = new THREE.Mesh(grid, material);
    mesh.rotation.set(spec.tilt[0], spec.tilt[1], spec.tilt[2]);
    scene.add(mesh);
    return { mesh, material, spin: new THREE.Vector3(...spec.spin), phaseSpeed: spec.phase };
  });
}

/** How much of each face to show for a state. `drafting` (0–1) is voice2 thinking while you are still talking. */
function targets(state: FaceState, drafting: number, micLevel: number) {
  switch (state) {
    case "listening": return { swarm: 1, think: 0.45 * drafting, globe: 0 };
    case "thinking": return { swarm: 0.12 + 0.7 * micLevel, think: 1, globe: 0 };
    case "speaking": return { swarm: Math.min(0.6, micLevel * 1.5), think: 0, globe: 1 };
    default: return { swarm: 0, think: 0, globe: 0.8 };
  }
}

export function VoiceFace({ state, drafting = 0, label }: { state: FaceState; drafting?: number; label?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef({ state, drafting });
  live.current = { state, drafting };

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      el.dataset.fallback = "1";                       // no WebGL: the CSS glow alone stands in
      return;
    }
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.z = 3.2;

    const swarmMat = pointsMaterial(SWARM_VERTEX, COLOURS.listening, 0.042);
    const swarmPts = new THREE.Points(swarm(1600), swarmMat);
    const globeBands = new Array<number>(BANDS).fill(0);
    const globeMat = pointsMaterial(GLOBE_VERTEX, COLOURS.idle, 0.034, { uBands: { value: globeBands } });
    const globePts = new THREE.Points(globe(2400), globeMat);
    scene.add(swarmPts, globePts);
    const loops = strips(scene);

    const resize = () => {
      const size = Math.max(48, Math.min(el.clientWidth || 96, el.clientHeight || el.clientWidth || 96, 520));
      renderer.setSize(size, size, false);
      renderer.domElement.style.width = `${size}px`;
      renderer.domElement.style.height = `${size}px`;
      const pixel = (size * renderer.getPixelRatio()) / (2 * Math.tan((camera.fov * Math.PI) / 360));
      swarmMat.uniforms.uPixel.value = pixel;
      globeMat.uniforms.uPixel.value = pixel;
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(el);

    const weights = { swarm: 0, think: 0, globe: 0 };
    const bands = new Float32Array(BANDS);
    const smoothBands = new Float32Array(BANDS);
    // Resting, the globe wears the app's accent (Studio Glass: orange), so the face matches whatever style is on.
    const idleColour = new THREE.Color(COLOURS.idle);
    try {
      const accent = getComputedStyle(el).getPropertyValue("--color-accent").trim();
      if (/^(#|rgb|hsl)/.test(accent)) idleColour.setStyle(accent);
    } catch { /* keep the default */ }
    const globeColour = new THREE.Color(COLOURS.idle);
    let mic = 0, voice = 0, frame = 0, last = performance.now(), clock = 0;

    const draw = () => {
      const now = performance.now();
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      clock += reduced ? dt * 0.15 : dt;
      const { state: face, drafting } = live.current;

      // Levels: the owner's voice on the echo-cancelled mic, and Ichos's own voice off its audio element.
      const micNow = vadRunning() ? vadState().level : 0;
      mic += (Math.min(1, micNow * 1.6) - mic) * (micNow > mic ? 0.45 : 0.12);
      const voiceNow = outputLevels(bands);
      voice += (voiceNow - voice) * (voiceNow > voice ? 0.5 : 0.15);
      for (let b = 0; b < BANDS; b += 1) {
        smoothBands[b] += (bands[b] - smoothBands[b]) * (bands[b] > smoothBands[b] ? 0.55 : 0.18);
        globeBands[b] = face === "speaking" ? smoothBands[b] : smoothBands[b] * 0.3;
      }

      const goal = targets(face, Math.max(0, Math.min(1, drafting)), mic);
      const ease = 1 - Math.exp(-dt * 5);
      weights.swarm += (goal.swarm - weights.swarm) * ease;
      weights.think += (goal.think - weights.think) * ease;
      weights.globe += (goal.globe - weights.globe) * ease;

      swarmMat.uniforms.uTime.value = clock;
      swarmMat.uniforms.uLevel.value = reduced ? 0 : mic;
      swarmMat.uniforms.uOpacity.value = weights.swarm;
      swarmMat.uniforms.uScale.value = 0.82 + 0.18 * weights.swarm;
      swarmPts.visible = weights.swarm > 0.01;
      swarmPts.rotation.y += dt * (0.12 + mic * 0.9) * (reduced ? 0.15 : 1);

      if (face === "idle") globeColour.copy(idleColour); else globeColour.setHex(COLOURS.speaking);
      (globeMat.uniforms.uColor.value as THREE.Color).lerp(globeColour, ease);
      globeMat.uniforms.uTime.value = clock;
      globeMat.uniforms.uLevel.value = reduced ? 0 : voice;
      globeMat.uniforms.uOpacity.value = weights.globe;
      globeMat.uniforms.uScale.value = 0.85 + 0.15 * weights.globe;
      globePts.visible = weights.globe > 0.01;
      globePts.rotation.y += dt * (0.25 + voice * 0.6) * (reduced ? 0.15 : 1);
      globePts.rotation.x = Math.sin(clock * 0.3) * 0.15;

      const thinkHard = face === "thinking" ? 1 : 0.6;
      for (const loop of loops) {
        loop.material.uniforms.uTime.value = clock;
        loop.material.uniforms.uOpacity.value = weights.think * 0.85;
        loop.material.uniforms.uScale.value = 0.7 + 0.3 * weights.think;
        loop.material.uniforms.uPhase.value = clock * loop.phaseSpeed * thinkHard;
        loop.mesh.visible = weights.think > 0.01;
        const turn = dt * thinkHard * (reduced ? 0.15 : 1);
        loop.mesh.rotation.x += loop.spin.x * turn;
        loop.mesh.rotation.y += loop.spin.y * turn;
        loop.mesh.rotation.z += loop.spin.z * turn;
      }

      renderer.render(scene, camera);
      frame = requestAnimationFrame(draw);
    };
    draw();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      swarmPts.geometry.dispose(); swarmMat.dispose();
      globePts.geometry.dispose(); globeMat.dispose();
      loops.forEach((loop) => loop.material.dispose());
      loops[0]?.mesh.geometry.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return (
    <div ref={host} className={`voice-face is-${state}`} role="img"
      aria-label={label ?? `Ichos is ${FACE_WORDS[state].toLowerCase()}`} />
  );
}
