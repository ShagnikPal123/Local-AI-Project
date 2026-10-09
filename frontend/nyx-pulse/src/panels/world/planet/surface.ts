/** The planet itself: its surface coloured by era, its clouds and its air. Made once per scene; repainted
 * when the era changes ("The world starts from nothing … the world itself grows", U34). */

import * as THREE from "three";
import { R, hash } from "./geo";

const ERA_LAND = ["#6b5d4f", "#5d6b45", "#4f7a43", "#477a45", "#3f7448", "#3d6f52", "#3a6a5c"];
const ERA_SEA = ["#1a2433", "#1c3550", "#1d4466", "#1e4f7a", "#1f5687", "#215c90", "#235f96"];

/** The surface: continents from a cheap, stable noise, coloured by era — bare rock at First Light, green later. */
function surfaceNoise(x: number, y: number, z: number): number {
  let total = 0;
  let amplitude = 1;
  let frequency = 0.19;
  for (let octave = 0; octave < 4; octave += 1) {
    total += amplitude * Math.sin(x * frequency + Math.sin(y * frequency * 1.7)) *
      Math.cos(z * frequency * 1.3 + Math.sin(x * frequency * 0.7)) *
      Math.sin(y * frequency * 0.9 + z * frequency * 0.4 + octave);
    amplitude *= 0.5;
    frequency *= 2.1;
  }
  return total;
}

export function paintPlanet(geometry: THREE.BufferGeometry, era: number): void {
  const position = geometry.getAttribute("position") as THREE.BufferAttribute;
  const colors = new Float32Array(position.count * 3);
  const land = new THREE.Color(ERA_LAND[Math.min(era, ERA_LAND.length - 1)]);
  const sea = new THREE.Color(ERA_SEA[Math.min(era, ERA_SEA.length - 1)]);
  const rock = new THREE.Color("#4a443d");
  const ice = new THREE.Color("#dfe6ee");
  const color = new THREE.Color();
  for (let i = 0; i < position.count; i += 1) {
    const x = position.getX(i);
    const y = position.getY(i);
    const z = position.getZ(i);
    const n = surfaceNoise(x, y, z);
    if (Math.abs(y) > R * 0.9) {
      color.copy(ice);
    } else if (n > 0.02) {
      color.copy(land).lerp(rock, Math.min(1, Math.max(0, (n - 0.25) * 1.6)));
      color.offsetHSL(0, 0, (hash(`${i}`) - 0.5) * 0.03);
    } else {
      color.copy(sea).offsetHSL(0, 0, Math.max(-0.06, n * 0.08));
    }
    colors[i * 3] = color.r;
    colors[i * 3 + 1] = color.g;
    colors[i * 3 + 2] = color.b;
  }
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
}

export function cloudTexture(): THREE.Texture {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 256;
  const ctx = canvas.getContext("2d")!;
  ctx.clearRect(0, 0, 512, 256);
  for (let i = 0; i < 160; i += 1) {
    const x = hash(`cx${i}`) * 512;
    const y = 30 + hash(`cy${i}`) * 196;
    const r = 8 + hash(`cr${i}`) * 34;
    const gradient = ctx.createRadialGradient(x, y, 0, x, y, r);
    gradient.addColorStop(0, "rgba(255,255,255,0.38)");
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.ellipse(x, y, r * 1.8, r, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  return texture;
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
