/** Normal chat's voice, in Equalize's look (owner, 2026-10-10: "equalize … I want to be how the normal voice looks";
 * "its amazing voice features are added to the normal chat").
 *
 * While voice is on, a band above the chat shows the voice face — a particle swarm while it listens, Möbius strips
 * while it thinks, an equalizer globe while it speaks — with what Ichos heard and one Stop button. It also tells the
 * engine the state, so the desktop notch (notch.py) can show it on top of the screen when Ichos is behind other apps,
 * and it obeys the notch's Talk button.
 */

import { setVoiceMode } from "../../voice/voiceBus";
import { useVoiceState } from "./notchBridge";
import { VoiceFace, FACE_WORDS } from "./VoiceFace";
import "./voicestage.css";

export function VoiceStage() {
  const { orb, heard, on, drafting } = useVoiceState();
  if (!on) return null;
  const line = orb === "listening" && drafting >= 1 ? "Listening — answer already drafted" : FACE_WORDS[orb];
  return (
    <section className={`voice-stage is-${orb}`} aria-label="Voice">
      <div className="voice-stage__orb"><VoiceFace state={orb} drafting={drafting} /></div>
      <div className="voice-stage__words">
        <p className="voice-stage__state" aria-live="polite">{line}</p>
        {heard && <p className="voice-stage__heard">“{heard}”</p>}
      </div>
      <button type="button" className="btn btn-secondary" onClick={() => setVoiceMode("off")}>Stop listening</button>
    </section>
  );
}
