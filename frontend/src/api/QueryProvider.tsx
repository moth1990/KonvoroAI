import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError, fetchHomeSummary, fetchMe, fetchQuotes } from "./client";
import { getToken } from "./token";

/** Client errors (4xx) won't fix themselves on a retry; network and server errors get one more try. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < 1;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: shouldRetry, staleTime: 30_000, refetchOnWindowFocus: false } },
  });
}

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** The signed-in user, tenant, plan, evaluated flags and quota. Disabled until there is a token. */
export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => fetchMe(), enabled: getToken() !== null });
}

/** Recent quotes for the home screen, newest first. */
export function useQuotes(limit = 10) {
  return useQuery({ queryKey: ["quotes", limit], queryFn: () => fetchQuotes(limit), enabled: getToken() !== null });
}

/** The "waiting for you" counts, and the approval-queue badge. */
export function useHomeSummary() {
  return useQuery({ queryKey: ["home-summary"], queryFn: () => fetchHomeSummary(), enabled: getToken() !== null });
}
