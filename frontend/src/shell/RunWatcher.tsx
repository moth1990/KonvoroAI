import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useLocation } from "react-router";

import { fetchProgress, type Progress } from "../api/client";
import { useMe } from "../api/QueryProvider";
import { announceHidden, finishedText, LIVE_POLL_MS } from "../screens/newQuote/live";
import { useToast } from "../ui/Toast";
import { endWatch, useWatchedRun } from "./runWatch";

const running = (p: Progress | undefined) => p !== undefined && ["uploaded", "processing"].includes(p.status);

/**
 * The run goes on when the user leaves its screen (01 §4.6 "ביטול והתראה", `live_run`): this keeps asking for it on
 * every screen, and at the end shows a message wherever the user is (not on the run's own screen, which shows the
 * done step), changes the tab's title to "✓ מוכן" while the tab is hidden, and with "הודע לי" a notification.
 * It shares the run screen's query, so the two never ask twice.
 */
export function RunWatcher() {
  const me = useMe();
  const run = useWatchedRun();
  const location = useLocation();
  const toast = useToast();
  const queries = useQueryClient();
  const on = !!me.data?.flags.live_run && run !== null;
  const id = run?.drawingId ?? null;
  const progress = useQuery({
    queryKey: ["progress", id],
    queryFn: () => fetchProgress(id ?? "", queries.getQueryData<Progress>(["progress", id])?.live?.seconds_left),
    enabled: on,
    refetchInterval: (q) => (running(q.state.data) ? LIVE_POLL_MS : false),
  });
  const p = progress.data;
  const seenRunning = useRef<string | null>(null);
  const here = location.search.includes(id ?? "~");

  useEffect(() => {
    if (!run || !p || p.drawing_id !== run.drawingId) return;
    if (running(p) || p.status === "awaiting_confirmation") {
      seenRunning.current = run.drawingId;
      return;
    }
    endWatch(run.drawingId);
    // a run that had ended before this page saw it run is not news; a cancelled one the user cancelled
    if (seenRunning.current !== run.drawingId || p.status === "cancelled") return;
    const text = finishedText(run.kind, p);
    if (!here) toast(text);
    announceHidden(text, run.notify);
    for (const key of ["me", "quotes", "home-summary"]) void queries.invalidateQueries({ queryKey: [key] });
  }, [run, p, here, toast, queries]);

  return null;
}
