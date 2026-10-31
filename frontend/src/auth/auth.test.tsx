import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearToken, setToken } from "../api/token";
import { RequireAuth, returnTo } from "./auth";

function LoginProbe() {
  const location = useLocation();
  return <p>{`login, back to ${returnTo(location.state)}`}</p>;
}

function at(path: string) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginProbe />} />
          <Route element={<RequireAuth />}>
            <Route path="/prices" element={<p>prices</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RequireAuth", () => {
  beforeEach(() => clearToken());
  afterEach(() => {
    cleanup();
    clearToken();
  });

  it("without a token, a protected page goes to login and remembers where it was going", () => {
    at("/prices?q=abb");
    expect(screen.getByText("login, back to /prices?q=abb")).toBeDefined();
  });

  it("with a token, the page renders", () => {
    setToken("tok");
    at("/prices");
    expect(screen.getByText("prices")).toBeDefined();
  });
});

describe("returnTo", () => {
  it.each([
    [{ from: "/audit" }, "/audit"],
    [null, "/home"],
    [{ from: "/login" }, "/home"],
    [{ from: "https://evil.example/x" }, "/home"],
    [{ from: "//evil.example/x" }, "/home"],
    [{ from: 42 }, "/home"],
  ])("%j -> %s", (state, path) => {
    expect(returnTo(state)).toBe(path);
  });
});
