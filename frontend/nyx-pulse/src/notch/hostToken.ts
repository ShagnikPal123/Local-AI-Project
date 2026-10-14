/** The owner's session for the desktop windows (the notch and the hands-off sidebar). They have no login screen: the
 * host hands the session over through pywebview's bridge, so the token never travels in a URL. */

type Bridge = { token?: () => Promise<string> };

export async function hostToken(): Promise<string> {
  const bridge = () => (window as unknown as { pywebview?: { api?: Bridge } }).pywebview?.api;
  // The bridge's functions arrive a moment after the page; a normal browser tab (testing) never gets them.
  return new Promise((resolve) => {
    const started = Date.now();
    const check = () => {
      const api = bridge();
      if (api?.token) void api.token().then(resolve);
      else if (Date.now() - started > 4000) resolve("");
      else window.setTimeout(check, 50);
    };
    check();
  });
}
