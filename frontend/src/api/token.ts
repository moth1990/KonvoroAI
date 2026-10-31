/**
 * The access token: kept in memory, mirrored to sessionStorage so a reload in the same tab stays signed in.
 * sessionStorage can be missing or throw (private mode, blocked storage), so every access is guarded.
 */
const KEY = "konboro:token";

let current: string | null = null;
let loaded = false;

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  if (!loaded) {
    loaded = true;
    try {
      current = storage()?.getItem(KEY) ?? null;
    } catch {
      current = null;
    }
  }
  return current;
}

export function setToken(token: string): void {
  current = token;
  loaded = true;
  try {
    storage()?.setItem(KEY, token);
  } catch {
    // memory only
  }
}

export function clearToken(): void {
  current = null;
  loaded = true;
  try {
    storage()?.removeItem(KEY);
  } catch {
    // nothing stored
  }
}

/** Tests only: forget the in-memory copy so the next read goes to sessionStorage again. */
export function resetTokenCacheForTests(): void {
  current = null;
  loaded = false;
}
