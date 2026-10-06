/** Browser speech-to-text for dictation and lecture mode.
 *
 * Audio never reaches Nyx's disk: the browser's own speech service turns sound
 * into words and only the words come back. Chrome and Edge stop listening after
 * a pause, so a lecture session restarts recognition until the student presses Stop.
 */

export type Recognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  start: () => void;
  stop: () => void;
};

export function speechRecognition(): (new () => Recognition) | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export interface Listener {
  stop: () => void;
}

/** Listen until stopped. `onFinal` gets each finished phrase; `onInterim` the words still forming. */
export function listen({ lang, onFinal, onInterim, onError, keepAlive }: {
  lang: string;
  onFinal: (text: string) => void;
  onInterim?: (text: string) => void;
  onError?: (message: string) => void;
  keepAlive: boolean;
}): Listener | null {
  const Speech = speechRecognition();
  if (!Speech) return null;
  let stopped = false;
  let recognition: Recognition | null = null;

  const begin = () => {
    recognition = new Speech();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = lang;
    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) onFinal(result[0].transcript.trim());
        else interim += result[0].transcript;
      }
      onInterim?.(interim);
    };
    recognition.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        stopped = true;
        onError?.("Microphone access was blocked. Allow it in the browser's address bar, then try again.");
      } else if (e.error === "network") {
        onError?.("The browser's speech service could not be reached — check the internet connection.");
      }
    };
    recognition.onend = () => {
      onInterim?.("");
      if (!stopped && keepAlive) {
        try { begin(); } catch { /* the page lost focus; the Stop button still works */ }
      }
    };
    recognition.start();
  };

  begin();
  return {
    stop: () => {
      stopped = true;
      recognition?.stop();
    },
  };
}
