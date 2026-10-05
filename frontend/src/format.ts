export function ago(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (!ts) return "never";
  const s = Math.max(0, now - ts);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function until(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (!ts) return "";
  const s = ts - now;
  if (s <= 0) return "now";
  if (s < 3600) return `${Math.ceil(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${s}s`;
}

export function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function dateTime(ts: number | string | null | undefined): string {
  if (!ts) return "—";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function num(n: number | null | undefined): string {
  if (n == null) return "—";
  return n >= 10000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString();
}

export function pct(r: number | null | undefined): string {
  return r == null ? "—" : `${Math.round(r * 100)}%`;
}

export function secs(s: number | null | undefined): string {
  return s == null ? "—" : s < 1 ? `${Math.round(s * 1000)} ms` : `${s.toFixed(1)} s`;
}

export const STATUS_COLOR: Record<string, string> = {
  healthy: "var(--ok)", degraded: "var(--warn)", failing: "var(--bad)", blocked: "var(--block)",
  idle: "var(--text-2)", unknown: "var(--muted)", disabled: "var(--off)",
};

export const STATUS_LABEL: Record<string, string> = {
  healthy: "Healthy", degraded: "Degraded", failing: "Failing", blocked: "Blocked", idle: "No results", unknown: "No data", disabled: "Off",
};

export const KIND_COLOR: Record<string, string> = {
  captcha: "#fb7185", challenge: "#f472b6", rate_limited: "#fb923c", blocked: "#f87171", timeout: "#fbbf24",
  parse_error: "#a78bfa", http_error: "#60a5fa", network: "#38bdf8", ssl: "#22d3ee", api_error: "#c084fc", error: "#94a3b8",
  load_error: "#64748b", system: "#64748b",
};
