/**
 * The run the user started and may have left (01 §4.6 "ביטול והתראה", `live_run`): the decoding goes on on another
 * screen, and the app tells them when it ends. One run at a time, this browser's only: kept in `localStorage`, a
 * convenience that may be missing (a private window), so every read and write is guarded.
 */
import { useSyncExternalStore } from "react";

export interface WatchedRun {
  drawingId: string;
  name: string;
  kind: "quote" | "audit";
  /** "הודע לי כשמסתיים": a browser notification when the tab is hidden at the end */
  notify: boolean;
}

const KEY = "konboro:run";
const listeners = new Set<() => void>();
let cached: WatchedRun | null | undefined;

function read(): WatchedRun | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as WatchedRun) : null;
  } catch {
    return null;
  }
}

function write(run: WatchedRun | null): void {
  cached = run;
  try {
    if (run) window.localStorage.setItem(KEY, JSON.stringify(run));
    else window.localStorage.removeItem(KEY);
  } catch {
    // no storage: the watch lasts until the page is reloaded
  }
  for (const listener of listeners) listener();
}

export function watchedRun(): WatchedRun | null {
  if (cached === undefined) cached = read();
  return cached;
}

export function watchRun(run: Omit<WatchedRun, "notify">): void {
  const same = watchedRun()?.drawingId === run.drawingId;
  write({ ...run, notify: same ? (watchedRun()?.notify ?? false) : false });
}

export function setNotify(drawingId: string, notify: boolean): void {
  const run = watchedRun();
  if (run && run.drawingId === drawingId) write({ ...run, notify });
}

export function endWatch(drawingId?: string): void {
  if (!drawingId || watchedRun()?.drawingId === drawingId) write(null);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useWatchedRun(): WatchedRun | null {
  return useSyncExternalStore(subscribe, watchedRun, () => null);
}

/** For tests: forget what was read. */
export function resetWatch(): void {
  cached = undefined;
}
