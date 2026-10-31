import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient, fetchMe, login, logout, setUnauthorizedHandler, unwrap } from "./client";
import { shouldRetry } from "./QueryProvider";
import { clearToken, getToken, resetTokenCacheForTests, setToken } from "./token";

type Call = { url: string; method: string; auth: string | null; body: string };

function fakeFetch(responses: Record<string, { status: number; body?: unknown }>) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: Request) => {
    const url = new URL(input.url);
    calls.push({
      url: url.pathname,
      method: input.method,
      auth: input.headers.get("Authorization"),
      body: input.method === "GET" ? "" : await input.text(),
    });
    const r = responses[`${input.method} ${url.pathname}`] ?? {
      status: 404,
      body: { error: { code: "not_found", message: "לא מצאנו" } },
    };
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), {
      status: r.status,
      headers: { "Content-Type": "application/json" },
    });
  });
  return { calls, client: createApiClient({ baseUrl: "http://api.test", fetch: fn as unknown as typeof fetch }) };
}

const UNAUTHORIZED = { status: 401, body: { error: { code: "unauthorized", message: "צריך להתחבר מחדש" } } };

beforeEach(() => {
  window.sessionStorage.clear();
  resetTokenCacheForTests();
});

afterEach(() => {
  clearToken();
});

describe("token", () => {
  it("is kept in memory and in sessionStorage", () => {
    setToken("t1");
    expect(getToken()).toBe("t1");
    expect(window.sessionStorage.getItem("konboro:token")).toBe("t1");
  });

  it("survives a reload in the same tab", () => {
    window.sessionStorage.setItem("konboro:token", "from-storage");
    resetTokenCacheForTests();
    expect(getToken()).toBe("from-storage");
  });

  it("works when sessionStorage throws", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    setToken("memory-only");
    expect(getToken()).toBe("memory-only");
    spy.mockRestore();
  });
});

describe("client", () => {
  it("logs in, stores the token and sends it on the next request", async () => {
    const { calls, client } = fakeFetch({
      "POST /auth/login": { status: 200, body: { access_token: "tok", token_type: "bearer", expires_in: 60 } },
      "GET /me": { status: 200, body: { user: { id: "usr_1" } } },
    });
    await login("demo@konboro.local", "pw", client);
    expect(getToken()).toBe("tok");
    expect(JSON.parse(calls[0]?.body ?? "")).toEqual({ email: "demo@konboro.local", password: "pw" });

    const me = await fetchMe(client);
    expect(me.user.id).toBe("usr_1");
    expect(calls[1]?.auth).toBe("Bearer tok");
  });

  it("sends no Authorization header without a token", async () => {
    const { calls, client } = fakeFetch({ "GET /health": { status: 200, body: { status: "ok" } } });
    await client.GET("/health");
    expect(calls[0]?.auth).toBeNull();
  });

  it("a 401 clears the token and goes to login", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    setToken("expired");
    const { client } = fakeFetch({ "GET /me": UNAUTHORIZED });
    await expect(fetchMe(client)).rejects.toMatchObject({ status: 401, code: "unauthorized" });
    expect(getToken()).toBeNull();
    expect(handler).toHaveBeenCalledOnce();
  });

  it("a wrong password stays on the login screen", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    const { client } = fakeFetch({
      "POST /auth/login": {
        status: 401,
        body: { error: { code: "invalid_credentials", message: "האימייל או הסיסמה לא נכונים" } },
      },
    });
    const error = await login("a@b.co", "bad", client).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("האימייל או הסיסמה לא נכונים");
    expect(handler).not.toHaveBeenCalled();
  });

  it("the default 401 handler opens the login route", async () => {
    setUnauthorizedHandler(() => {
      window.location.hash = "login";
    });
    window.location.hash = "home";
    const { client } = fakeFetch({ "GET /me": UNAUTHORIZED });
    await fetchMe(client).catch(() => undefined);
    expect(window.location.hash).toBe("#login");
  });

  it("logout clears the token even when the call fails", async () => {
    setToken("tok");
    const { calls, client } = fakeFetch({ "POST /auth/logout": { status: 500, body: {} } });
    await logout(client);
    expect(calls[0]?.auth).toBe("Bearer tok");
    expect(getToken()).toBeNull();
  });
});

describe("unwrap", () => {
  it("uses the Hebrew fallback when the body has no error envelope", () => {
    const error = (() => {
      try {
        unwrap({ error: "oops", response: new Response(null, { status: 502 }) });
      } catch (e) {
        return e as ApiError;
      }
    })();
    expect(error).toMatchObject({ status: 502, code: "internal_error", message: "משהו השתבש אצלנו. נסו שוב בעוד רגע" });
  });
});

describe("retry policy", () => {
  it("never retries client errors, retries a server error once", () => {
    expect(shouldRetry(0, new ApiError(404, "not_found", ""))).toBe(false);
    expect(shouldRetry(0, new ApiError(503, "internal_error", ""))).toBe(true);
    expect(shouldRetry(1, new ApiError(503, "internal_error", ""))).toBe(false);
    expect(shouldRetry(0, new TypeError("network"))).toBe(true);
  });
});
