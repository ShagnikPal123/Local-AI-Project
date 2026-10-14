/** Hand words to the chat even when the chat is not on screen.
 *
 * What the microphone hears (and what a taught clap says to do) reaches the chat as a window event that the chat
 * panel listens for. The panel only exists while the Chat tab is open, so anything said from the Equalize tab, the
 * notch or any other tab used to vanish: the owner talked and nothing answered (Fixer Upper S33/S34, "it doesn't
 * respond at all"). Now, when no chat pane is on the page, the Chat tab is opened first and the words are handed
 * over once its panel is listening.
 */

/** How long to wait for the Chat tab to appear before giving up. */
const OPEN_WAIT_MS = 5000;
/** The panel adds its listeners just after it appears; give it this long. */
const SETTLE_MS = 150;

function chatOnScreen(): boolean {
  return document.querySelector("[data-chat-pane]") !== null;
}

/** Dispatch `event` with `detail` to the chat, opening the Chat tab first when it is closed. */
export function sendToChat(event: "nyx:voice-send" | "nyx:chat-send", detail: Record<string, unknown>): void {
  const dispatch = () => window.dispatchEvent(new CustomEvent(event, { detail }));
  if (chatOnScreen()) { dispatch(); return; }
  window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "nyx" } }));
  const started = Date.now();
  const wait = () => {
    if (chatOnScreen()) { window.setTimeout(dispatch, SETTLE_MS); return; }
    if (Date.now() - started > OPEN_WAIT_MS) { dispatch(); return; }   // last try; a panel may still pick it up
    window.setTimeout(wait, 100);
  };
  wait();
}
