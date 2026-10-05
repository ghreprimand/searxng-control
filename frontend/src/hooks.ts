import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Fetch a GET endpoint and re-fetch every `intervalMs` while the tab is visible. */
export function usePoll<T>(path: string | null, intervalMs = 15000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const pathRef = useRef(path);
  pathRef.current = path;

  const reload = useCallback(async () => {
    if (!pathRef.current) return;
    try {
      const d = await api.get<T>(pathRef.current);
      setData(d);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    reload();
    if (!intervalMs) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, intervalMs);
    return () => clearInterval(id);
  }, [path, intervalMs, reload]);

  return { data, error, loading, reload, setData };
}

export interface StreamMsg { type: string; [k: string]: unknown }

/** Subscribe to the server-sent event stream. */
export function useStream(onMessage: (m: StreamMsg) => void) {
  const cb = useRef(onMessage);
  cb.current = onMessage;
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    const es = new EventSource("/api/stream");
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      try { cb.current(JSON.parse(e.data)); } catch { /* ignore */ }
    };
    return () => es.close();
  }, []);
  return connected;
}

export function useHashRoute(): [string, string | null, (r: string) => void] {
  const parse = () => {
    const h = window.location.hash.replace(/^#\/?/, "");
    const [page, ...rest] = h.split("/");
    return [page || "overview", rest.length ? decodeURIComponent(rest.join("/")) : null] as [string, string | null];
  };
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = (r: string) => { window.location.hash = `/${r}`; };
  return [route[0], route[1], go];
}

/** Re-render periodically so relative timestamps stay fresh. */
export function useTick(ms = 30000) {
  const [, set] = useState(0);
  useEffect(() => {
    const id = setInterval(() => set((n) => n + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
}
