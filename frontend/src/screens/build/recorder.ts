/**
 * The microphone for the chat builder (13 §4.2, S27; prototype `startRec`, line 1322): `MediaRecorder` with the
 * browser's permission, a stop on the second click or at a minute, and the recording handed over as one Blob. The
 * server transcribes it and drops it; nothing is kept here either.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export const MAX_RECORDING_MS = 60_000;

export type RecorderState = "idle" | "recording";

/** A type the server reads (`services/transcribe.py`), the first the browser can record. */
export function recordingType(isSupported: (t: string) => boolean): string | undefined {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((t) => isSupported(t));
}

export function canRecord(): boolean {
  return typeof window !== "undefined" && "MediaRecorder" in window && !!navigator.mediaDevices?.getUserMedia;
}

export const NO_MIC = "אין גישה למיקרופון. אפשר להרשות אותה בהגדרות הדפדפן, או לכתוב";

export function useRecorder(onDone: (audio: Blob, seconds: number) => void, onError: (text: string) => void) {
  const [state, setState] = useState<RecorderState>("idle");
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | null>(null);
  const done = useRef(onDone);
  const failed = useRef(onError);
  useEffect(() => {
    done.current = onDone;
    failed.current = onError;
  });

  const stop = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    if (recorder.current?.state === "recording") recorder.current.stop();
  }, []);

  const start = useCallback(async () => {
    if (recorder.current?.state === "recording") return;
    if (!canRecord()) {
      failed.current(NO_MIC);
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      failed.current(NO_MIC);
      return;
    }
    const type = recordingType((t) => MediaRecorder.isTypeSupported(t));
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    const began = performance.now();
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.onstop = () => {
      for (const t of stream.getTracks()) t.stop();
      recorder.current = null;
      setState("idle");
      const blob = new Blob(chunks, { type: rec.mimeType || type || "audio/webm" });
      if (blob.size) done.current(blob, (performance.now() - began) / 1000);
    };
    recorder.current = rec;
    rec.start();
    setState("recording");
    timer.current = window.setTimeout(stop, MAX_RECORDING_MS);
  }, [stop]);

  useEffect(() => () => stop(), [stop]);

  return { state, start, stop, toggle: () => (state === "recording" ? stop() : void start()) };
}
