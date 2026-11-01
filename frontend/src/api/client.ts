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
export type QuoteListItem = Schemas["QuoteListItem"];
export type HomeSummary = Schemas["HomeSummaryOut"];
export type Progress = Schemas["ProgressOut"];
export type Revisable = Schemas["RevisableOut"];
export type UploadedFile = Schemas["UploadedFileOut"];
export type Quote = Schemas["QuoteOut"];
export type QuoteLine = Schemas["LineOut"];
export type Finding = Schemas["FindingOut"];

const FALLBACK_MESSAGE = "משהו השתבש אצלנו. נסו שוב בעוד רגע";
const LOGIN_PATH = "/auth/login";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>[];

  constructor(status: number, code: string, message: string, details: Record<string, unknown>[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** The prototype shows login whenever the user is not signed in (konboro-app.html `vLogin`). The app's router
 * replaces this with a navigation that keeps the page to return to (`AuthBridge`). */
let onUnauthorized: () => void = () => {
  window.location.assign("/login");
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
  const body = (result.error ?? {}) as {
    error?: { code?: string; message?: string; details?: Record<string, unknown>[] | null };
  };
  throw new ApiError(
    result.response.status,
    body.error?.code ?? "internal_error",
    body.error?.message ?? FALLBACK_MESSAGE,
    body.error?.details ?? [],
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

/** Always succeeds (202), whether or not the email is registered, so nothing is revealed. */
export async function requestPasswordReset(email: string, client = api): Promise<void> {
  unwrap(await client.POST("/auth/password-reset", { body: { email } }));
}

export async function fetchQuotes(limit: number, client = api): Promise<QuoteListItem[]> {
  return unwrap(await client.GET("/quotes", { params: { query: { limit } } })).items;
}

export async function fetchHomeSummary(client = api): Promise<HomeSummary> {
  return unwrap(await client.GET("/home/summary"));
}

export interface UploadForm {
  files: File[];
  customer?: string;
  project?: string;
  revisionOf?: string;
}

/** POST /drawings as multipart. A rejected upload throws ApiError("upload_rejected") with one detail per file. */
export async function uploadDrawing(form: UploadForm, client = api) {
  const data = new FormData();
  for (const f of form.files) data.append("files", f, f.name);
  if (form.revisionOf) data.append("revision_of", form.revisionOf);
  else {
    if (form.customer?.trim()) data.append("customer", form.customer.trim());
    if (form.project?.trim()) data.append("project", form.project.trim());
  }
  return unwrap(
    await client.POST("/drawings", {
      // openapi-fetch types the multipart body as its fields; the FormData built above is what goes out.
      body: data as unknown as Schemas["Body_upload_drawings_post"],
      bodySerializer: (body) => body as unknown as FormData,
    }),
  );
}

export async function fetchProgress(drawingId: string, client = api): Promise<Progress> {
  return unwrap(await client.GET("/drawings/{drawing_id}/progress", { params: { path: { drawing_id: drawingId } } }));
}

export async function cancelDrawing(drawingId: string, client = api): Promise<Progress> {
  return unwrap(await client.POST("/drawings/{drawing_id}/cancel", { params: { path: { drawing_id: drawingId } } }));
}

export async function confirmDrawing(drawingId: string, client = api): Promise<Progress> {
  return unwrap(await client.POST("/drawings/{drawing_id}/confirm", { params: { path: { drawing_id: drawingId } } }));
}

export type PageKind = Schemas["PageKindIn"]["page_kind"];

export async function changePageKind(
  drawingId: string,
  pageId: string,
  pageKind: PageKind,
  client = api,
): Promise<Progress> {
  return unwrap(
    await client.PATCH("/drawings/{drawing_id}/pages/{page_id}", {
      params: { path: { drawing_id: drawingId, page_id: pageId } },
      body: { page_kind: pageKind },
    }),
  );
}

export async function fetchRevisable(client = api): Promise<Revisable[]> {
  return unwrap(await client.GET("/drawings/revisable"));
}

/** The review screen's quote (09 §4). 404 when it is another tenant's, does not exist, or `review_screen` is off. */
export async function fetchQuote(quoteId: string, client = api): Promise<Quote> {
  return unwrap(await client.GET("/quotes/{quote_id}", { params: { path: { quote_id: quoteId } } }));
}
