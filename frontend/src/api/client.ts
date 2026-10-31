/**
 * Typed API client. Types come from `make gen-client` (FastAPI's OpenAPI -> schema.ts); never edit them by hand.
 *
 * - Every request carries the bearer token.
 * - A 401 on any route but login clears the token and sends the user to the login screen.
 * - Errors arrive as `{error: {code, message}}`: `code` is for code, `message` is Hebrew for the user.
 */
import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";
import { clearToken, getToken, setToken } from "./token";

export type Schemas = components["schemas"];
export type Me = Schemas["MeOut"];
export type Quota = Schemas["QuotaOut"];
export type TenantSettings = Schemas["SettingsOut"];

const FALLBACK_MESSAGE = "משהו השתבש אצלנו. נסו שוב בעוד רגע";
const LOGIN_PATH = "/auth/login";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** The prototype shows login whenever the user is not signed in (konboro-app.html `vLogin`). */
let onUnauthorized: () => void = () => {
  window.location.hash = "login";
};

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

const auth: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ request, response }) {
    if (response.status === 401 && !new URL(request.url).pathname.endsWith(LOGIN_PATH)) {
      clearToken();
      onUnauthorized();
    }
    return response;
  },
};

export function createApiClient(options: { baseUrl?: string; fetch?: typeof fetch } = {}) {
  const client = createClient<paths>({
    baseUrl: options.baseUrl ?? import.meta.env.VITE_API_URL ?? "http://localhost:8000",
    fetch: options.fetch,
  });
  client.use(auth);
  return client;
}

export const api = createApiClient();

/** openapi-fetch returns `{data}` or `{error}`. This returns the data or throws an ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error === undefined && result.response.ok) return result.data as T;
  const body = (result.error ?? {}) as { error?: { code?: string; message?: string } };
  throw new ApiError(
    result.response.status,
    body.error?.code ?? "internal_error",
    body.error?.message ?? FALLBACK_MESSAGE,
  );
}

export async function login(email: string, password: string, client = api): Promise<void> {
  const data = unwrap(await client.POST("/auth/login", { body: { email, password } }));
  setToken(data.access_token);
}

export async function logout(client = api): Promise<void> {
  try {
    await client.POST("/auth/logout");
  } finally {
    clearToken();
  }
}

export async function fetchMe(client = api): Promise<Me> {
  return unwrap(await client.GET("/me"));
}
