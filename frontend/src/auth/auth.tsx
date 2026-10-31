import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Navigate, Outlet, useLocation, useNavigate, type Location } from "react-router";

import { setUnauthorizedHandler } from "../api/client";
import { getToken } from "../api/token";

/** Where login sends the user afterwards: the page they asked for, if it was one of ours. */
export function returnTo(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  return typeof from === "string" && from.startsWith("/") && !from.startsWith("//") && from !== "/login"
    ? from
    : "/home";
}

function here(location: Location): string {
  return `${location.pathname}${location.search}`;
}

/** Signed-in pages. Without a token, go to login and remember where the user was going. */
export function RequireAuth() {
  const location = useLocation();
  if (getToken() === null) return <Navigate to="/login" replace state={{ from: here(location) }} />;
  return <Outlet />;
}

/**
 * A 401 from any call (an expired or revoked token): the client has already cleared the token; drop cached data
 * and go to login, keeping the current page to return to.
 */
export function AuthBridge() {
  const navigate = useNavigate();
  const location = useLocation();
  const queries = useQueryClient();
  const from = here(location);
  useEffect(() => {
    setUnauthorizedHandler(() => {
      queries.clear();
      navigate("/login", { replace: true, state: { from } });
    });
  }, [navigate, queries, from]);
  return null;
}
