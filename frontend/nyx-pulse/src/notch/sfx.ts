/** The notch's little sounds, made on the fly with Web Audio — our own, no audio files.
 *
 * Coucou plays a sound on peek, open, close, hover, send, swallow, tick, approve, finish, error; Io does the same
 * moments with soft sine/triangle blips in the key of the voice globe. Volume and mute come from the notch header
 * (click the speaker to mute, hover it for the slider).
 */

export type Sfx =
  | "peek" | "open" | "close" | "hover" | "blip" | "send" | "gulp" | "tick" | "approve" | "finish" | "error"
  | "love" | "pop" | "annoyed" | "dizzy" | "timer";

let ctx: AudioContext | null = null;
let volume = 0.6;
let muted = false;

export function setSfxVolume(next: number, isMuted: boolean): void {
  volume = Math.max(0, Math.min(1, next));
  muted = isMuted;
}

function audio(): AudioContext | null {
  if (typeof window === "undefined" || !("AudioContext" in window)) return null;
  ctx ??= new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

/** [frequency Hz, start s, length s, wave] notes for each sound. */
const SOUNDS: Record<Sfx, [number, number, number, OscillatorType][]> = {
  peek: [[660, 0, 0.07, "sine"], [990, 0.06, 0.1, "sine"]],
  open: [[523, 0, 0.08, "sine"], [784, 0.05, 0.12, "sine"]],
  close: [[784, 0, 0.07, "sine"], [523, 0.05, 0.1, "sine"]],
  hover: [[1320, 0, 0.03, "sine"]],
  blip: [[880, 0, 0.04, "triangle"]],
  send: [[587, 0, 0.06, "sine"], [880, 0.04, 0.06, "sine"], [1175, 0.08, 0.1, "sine"]],
  gulp: [[220, 0, 0.09, "sine"], [160, 0.06, 0.12, "sine"]],
  tick: [[1760, 0, 0.018, "triangle"]],
  approve: [[659, 0, 0.09, "sine"], [831, 0.07, 0.09, "sine"], [988, 0.14, 0.16, "sine"]],
  finish: [[523, 0, 0.08, "sine"], [659, 0.08, 0.08, "sine"], [784, 0.16, 0.08, "sine"], [1047, 0.24, 0.22, "sine"]],
  error: [[196, 0, 0.14, "triangle"], [165, 0.12, 0.2, "triangle"]],
  love: [[784, 0, 0.1, "sine"], [988, 0.1, 0.1, "sine"], [1319, 0.2, 0.18, "sine"]],
  pop: [[1047, 0, 0.05, "sine"]],
  annoyed: [[330, 0, 0.08, "square"], [294, 0.08, 0.1, "square"]],
  dizzy: [[880, 0, 0.08, "sine"], [740, 0.08, 0.08, "sine"], [880, 0.16, 0.08, "sine"], [622, 0.24, 0.14, "sine"]],
  timer: [[1047, 0, 0.12, "sine"], [1047, 0.25, 0.12, "sine"], [1047, 0.5, 0.2, "sine"]],
};

export function play(name: Sfx): void {
  if (muted || volume <= 0) return;
  const ac = audio();
  if (!ac) return;
  const gainLevel = 0.09 * volume;
  for (const [freq, start, length, wave] of SOUNDS[name]) {
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    const t0 = ac.currentTime + start;
    osc.type = wave;
    osc.frequency.setValueAtTime(freq, t0);
    gain.gain.setValueAtTime(0, t0);
    gain.gain.linearRampToValueAtTime(wave === "square" ? gainLevel * 0.35 : gainLevel, t0 + 0.008);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + length);
    osc.connect(gain).connect(ac.destination);
    osc.start(t0);
    osc.stop(t0 + length + 0.02);
  }
}
