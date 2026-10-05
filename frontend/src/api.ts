export type Status = "healthy" | "degraded" | "failing" | "blocked" | "idle" | "unknown" | "disabled";

export interface EventRow {
  id?: number;
  ts: number;
  engine: string | null;
  kind: string;
  label?: string;
  detail: string | null;
  host: string | null;
  suspended_s?: number | null;
}

export interface EngineState {
  status: Status;
  sent_1h: number;
  errors_1h: number;
  sent_24h: number;
  errors_24h: number;
  blocks_24h: number;
  success_24h: number | null;
  median_s: number | null;
  last_error: (EventRow & { suspended_s?: number }) | null;
  last_ok: number | null;
  probe: { status: string; results: number; detail: string | null; ts: number } | null;
  blocked_until: number | null;
}

export interface OverviewEngine extends EngineState {
  name: string;
  shortcut: string | null;
  categories: string[];
  private: boolean;
  module: string | null;
  web: boolean;
  spark: (number | null)[] | null;
}

export interface Bucket { t: number; requests: number; searches: number; blocks: number; errors: number }

export interface ProbeResult { engine: string; status: string; results: number; detail: string | null }
export interface Probe {
  id: number; ts: number; kind: string; query: string; target?: string | null; duration_ms: number; ok: number;
  total_results: number; error: string | null; results: ProbeResult[]; ok_engines: number; web_engines?: number;
}

export interface Alert { id: number; key: string; severity: string; title: string; detail: string; opened: number; resolved: number | null; notified: number }

export interface Container {
  name: string; state: string; status?: string; running?: boolean; started_at?: string; restart_count?: number;
  image?: string; image_id?: string; image_created?: string;
}

export interface Overview {
  now: number;
  searxng: { version: string | null; parsed: { date: string; commit: string } | null; image: string | null; image_created: string | null;
    container: Container; healthy: boolean; docker_ok: boolean; public_url: string };
  summary: { web_total: number; web_working: number; searches_24h: number; requests_24h: number; blocks_24h: number; errors_24h: number;
    median_latency_s: number | null; engines_enabled: number };
  engines: OverviewEngine[];
  series: Bucket[];
  last_probe: Probe | null;
  alerts: Alert[];
  setup: { id: string; text: string }[];
  update: { available: boolean | null; latest: string | null; behind: number; relevant: number };
  recent_events: EventRow[];
}

export interface Engine extends EngineState {
  name: string; module: string | null; shortcut: string | null; categories: string[]; enabled: boolean; loaded: boolean;
  disabled: boolean; inactive: boolean; default_disabled: boolean; default_inactive: boolean; timeout: number | null; weight: number | null;
  requires_api_key: boolean; has_api_key: boolean; private: boolean; official_api: boolean; website: string | null;
  overridden: string[]; custom: boolean; web: boolean;
}

export interface EnginePatch { enabled?: boolean; weight?: number | null | string; timeout?: number | null | string; shortcut?: string; api_key?: string; private?: boolean }

export interface ApplyResult { ok: boolean; message: string; rolled_back: boolean; backup: string | null; log_tail: string[]; duration_s: number }

export interface ConfigPatch {
  engines?: Record<string, EnginePatch>;
  general?: Record<string, unknown>;
  hostnames?: Hostnames;
  add_engine?: string;
  remove_engine?: string;
  note?: string;
}

export interface Hostnames { remove: string[]; low_priority: string[]; high_priority: string[]; replace: { pattern: string; replacement: string }[] }

export interface GeneralSettings {
  instance_name: string; autocomplete: string; safe_search: number; default_lang: string; favicon_resolver: string;
  request_timeout: number; max_request_timeout: number; image_proxy: boolean; infinite_scroll: boolean; results_on_new_tab: boolean;
  center_alignment: boolean; suspended_times: Record<string, number>;
}

export interface Commit { sha: string; short: string; title: string; body: string; date: string; author: string; url: string;
  files?: string[]; engines?: string[]; relevant?: boolean; is_fix?: boolean }
export interface CompareSection { ahead_by: number; commits: Commit[]; relevant_engines?: string[]; relevant_count?: number; error?: string }
export interface UpstreamReport {
  checked?: number; running?: string; error?: string | null; update_available?: boolean;
  latest?: { tag: string; pushed: string; digest: string; recent_tags: string[] } | null;
  image_behind?: CompareSection; upcoming?: CompareSection;
}

export interface NotifySettings {
  unraid: boolean; ntfy_url: string; ntfy_token: string; min_severity: string; notify_resolved: boolean;
  min_web_engines: number; engine_blocked_hours: number; update_stale_hours: number; probe_interval_min: number;
  auto_update: "always" | "fixes" | "off"; auto_update_min_hours: number; notify_updates: boolean;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* not json */ }
    throw new ApiError(msg, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(p: string) => req<T>("GET", p),
  post: <T>(p: string, b: unknown = {}) => req<T>("POST", p, b),
  put: <T>(p: string, b: unknown) => req<T>("PUT", p, b),
};

export const enc = encodeURIComponent;
