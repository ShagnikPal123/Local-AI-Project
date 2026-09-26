/** A tiny external store: module-level state that outlives every component.
 *
 * Panels unmount on every tab switch; anything they hold in useState is lost.
 * State that must survive (chats, in-flight turns, the team) lives here and
 * components read slices with `useStore(store, selector)`. Selectors must
 * return values that keep their identity until the data really changes —
 * return a stored object, not a freshly built one.
 */

import { useSyncExternalStore } from "react";

export interface Store<S> {
  get(): S;
  set(update: Partial<S> | ((state: S) => Partial<S> | S)): void;
  subscribe(listener: () => void): () => void;
}

export function createStore<S extends object>(initial: S): Store<S> {
  let state = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set(update) {
      const patch = typeof update === "function" ? update(state) : update;
      if (patch === state) return;
      let changed = false;
      for (const key of Object.keys(patch) as (keyof S)[]) {
        if (state[key] !== (patch as S)[key]) {
          changed = true;
          break;
        }
      }
      if (!changed) return;
      state = { ...state, ...patch };
      listeners.forEach((listener) => listener());
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export function useStore<S extends object, T>(store: Store<S>, selector: (state: S) => T): T {
  return useSyncExternalStore(
    store.subscribe,
    () => selector(store.get()),
    () => selector(store.get()),
  );
}

export function uid(prefix = "id"): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Trailing debounce with an explicit flush, for saves that must not be lost on unload. */
export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number) {
  let timer: number | undefined;
  let lastArgs: A | null = null;
  const run = () => {
    timer = undefined;
    if (lastArgs) {
      const args = lastArgs;
      lastArgs = null;
      fn(...args);
    }
  };
  const call = (...args: A) => {
    lastArgs = args;
    if (timer !== undefined) window.clearTimeout(timer);
    timer = window.setTimeout(run, ms);
  };
  call.flush = () => {
    if (timer !== undefined) window.clearTimeout(timer);
    run();
  };
  return call;
}
