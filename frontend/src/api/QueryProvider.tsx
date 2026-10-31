import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError, fetchMe } from "./client";
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
