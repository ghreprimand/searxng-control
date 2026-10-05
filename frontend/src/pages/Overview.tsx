import { useState } from "react";
import {
  AlertTriangle, ArrowUpRight, Ban, BarChart3, Clock, Container, FlaskConical, GitBranch, Radar, Search, ShieldAlert, Timer, Zap,
} from "lucide-react";
import { api, type EventRow, type Overview as OverviewData, type OverviewEngine, type Probe } from "../api";
import { ago, duration, KIND_COLOR, num, pct, secs, STATUS_COLOR, until } from "../format";
import { usePoll, useStream, useTick } from "../hooks";
import { ActivityChart, Ring, Sparkline } from "../components/charts";
import { Button, Callout, Card, Empty, ErrorBox, Loading, SeverityPill, Stat, StatusPill, useToast } from "../components/ui";

export default function Overview({ onEngine, go }: { onEngine: (n: string) => void; go: (r: string) => void }) {
  const { data, error, reload } = usePoll<OverviewData>("/overview", 15000);
  const [fresh, setFresh] = useState<EventRow[]>([]);
  const toast = useToast();
  useTick();
  useStream((m) => {
    if (m.type === "event") setFresh((f) => [m as unknown as EventRow, ...f].slice(0, 12));
    if (m.type === "probe" || m.type === "lifecycle") reload();
  });

  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  const { searxng, summary } = data;
  const web = data.engines.filter((e) => e.web);
  const other = data.engines.filter((e) => !e.web && (e.sent_24h > 0 || e.errors_24h > 0 || e.status === "blocked"));
  const quiet = data.engines.filter((e) => !e.web).length - other.length;
  const ratio = summary.web_total ? summary.web_working / summary.web_total : 0;
  const tone = !searxng.healthy ? "var(--bad)" : ratio >= 0.7 ? "var(--ok)" : ratio >= 0.4 ? "var(--warn)" : "var(--bad)";
  const started = searxng.container?.started_at ? Date.parse(searxng.container.started_at) / 1000 : null;
  const events = mergeEvents(fresh, data.recent_events).slice(0, 12);

  const runProbe = async () => {
    const p = await api.post<Probe>("/probes/run", {});
    toast("info", <><b>Probe finished:</b> {p.ok_engines}/{p.web_engines} web engines returned results for “{p.query}”.</>);
    reload();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Overview</h1>
          <div className="page-sub">What your SearXNG instance is doing right now.</div>
        </div>
        <div className="row">
          <Button onClick={runProbe}><FlaskConical size={15} /> Run probe</Button>
          <a className="btn primary" href={searxng.public_url} target="_blank" rel="noreferrer"><Search size={15} /> Open search</a>
        </div>
      </div>

      <div className="grid" style={{ gap: 16 }}>
        <div className="card hero" style={{ ["--glow" as string]: tone === "var(--ok)" ? "rgba(52,211,153,.13)" : tone === "var(--warn)" ? "rgba(251,191,36,.13)" : "rgba(248,113,113,.15)" }}>
          <Ring value={summary.web_working} total={summary.web_total} color={tone} label="web engines" />
          <div className="hero-main">
            <div className="hero-title">
              {!searxng.healthy ? "SearXNG is not responding" : ratio >= 0.7 ? "Search is healthy" : ratio >= 0.4 ? "Search is degraded" : "Most web engines are failing"}
            </div>
            <div className="subtle" style={{ marginTop: 2 }}>
              {summary.web_working} of {summary.web_total} web engines are answering
              {data.last_probe && <> · last probe {ago(data.last_probe.ts)} ({data.last_probe.ok_engines}/{data.last_probe.web_engines} returned results)</>}
            </div>
            <div className="hero-meta">
              <span><Container size={14} /> {searxng.container?.state ?? "unknown"}{started ? ` · up ${duration(Date.now() / 1000 - started)}` : ""}</span>
              <span><GitBranch size={14} /> {searxng.version ?? "unknown version"}</span>
              {data.update.available
                ? <span style={{ color: "var(--accent)", cursor: "pointer" }} onClick={() => go("updates")}><ArrowUpRight size={14} /> Update available: {data.update.latest} ({data.update.behind} commits{data.update.relevant ? `, ${data.update.relevant} touch your engines` : ""})</span>
                : data.update.latest && <span><ArrowUpRight size={14} /> Up to date</span>}
              {!searxng.docker_ok && <span style={{ color: "var(--warn)" }}><AlertTriangle size={14} /> Docker not reachable</span>}
            </div>
          </div>
        </div>

        {data.setup.length > 0 && (
          <Callout kind="warn">
            <b>Finish setup</b>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{data.setup.map((s) => <li key={s.id} className="small">{s.text}</li>)}</ul>
          </Callout>
        )}

        {data.alerts.length > 0 && (
          <Card title="Active alerts" icon={<ShieldAlert size={16} />} actions={<Button small kind="ghost" onClick={() => go("alerts")}>All alerts</Button>} flush>
            {data.alerts.map((a) => (
              <div key={a.id} className="feed-item" style={{ gridTemplateColumns: "auto 1fr auto" }}>
                <SeverityPill severity={a.severity} />
                <div><div className="feed-title">{a.title}</div><div className="feed-detail">{a.detail}</div></div>
                <div className="feed-time">{ago(a.opened)}</div>
              </div>
            ))}
          </Card>
        )}

        <div className="grid g4">
          <Stat label="Searches · 24h" icon={<Search size={13} />} value={num(summary.searches_24h)} foot={`${num(summary.requests_24h)} engine requests`} />
          <Stat label="Blocks · 24h" icon={<Ban size={13} />} value={num(summary.blocks_24h)} color={summary.blocks_24h ? "var(--block)" : undefined} foot="CAPTCHA, 403, 429, challenges" />
          <Stat label="Other errors · 24h" icon={<Zap size={13} />} value={num(summary.errors_24h)} color={summary.errors_24h ? "var(--warn)" : undefined} foot="timeouts, parse errors" />
          <Stat label="Median latency" icon={<Timer size={13} />} value={secs(summary.median_latency_s)} foot="across web engines, 24h" />
        </div>

        <div className="grid g-main">
          <Card title="Web engines" icon={<Radar size={16} />} actions={<Button small kind="ghost" onClick={() => go("engines")}>Manage engines</Button>}>
            {web.length === 0 ? <Empty>No web engines enabled.</Empty> : (
              <div className="engine-grid">{web.map((e) => <EngineTile key={e.name} e={e} onClick={() => onEngine(e.name)} />)}</div>
            )}
            {other.length > 0 && (
              <>
                <div className="hr" />
                <div className="small muted" style={{ marginBottom: 10 }}>Other engines with activity (images, news, IT, …) · {quiet} quiet engines hidden</div>
                <div className="engine-grid">{other.map((e) => <EngineTile key={e.name} e={e} onClick={() => onEngine(e.name)} compact />)}</div>
              </>
            )}
          </Card>

          <Card title="Live engine events" icon={<Clock size={16} />} actions={<Button small kind="ghost" onClick={() => go("activity")}>Logs</Button>} flush>
            {events.length === 0 ? <Empty>No engine errors recorded yet. 🎉</Empty> : (
              <div className="feed">
                {events.map((ev, i) => (
                  <div key={`${ev.ts}-${ev.engine}-${i}`} className={`feed-item ${fresh.includes(ev) ? "fresh" : ""}`}>
                    <div className="feed-icon" style={{ background: `${KIND_COLOR[ev.kind] ?? "#64748b"}22`, color: KIND_COLOR[ev.kind] }}><Ban size={12} /></div>
                    <div style={{ minWidth: 0 }}>
                      <div className="feed-title"><span style={{ cursor: "pointer" }} onClick={() => ev.engine && onEngine(ev.engine)}>{ev.engine}</span> <span className="muted" style={{ fontWeight: 500 }}>· {ev.label}</span></div>
                      <div className="feed-detail">{ev.host ? `${ev.host} — ` : ""}{ev.detail}</div>
                    </div>
                    <div className="feed-time">{ago(ev.ts)}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <Card title="Last 24 hours" icon={<BarChart3 size={16} />} actions={
          <div className="legend"><span><i style={{ background: "#6fa6ff" }} />searches (est.)</span><span><i style={{ background: "var(--block)" }} />blocks</span><span><i style={{ background: "var(--warn)" }} />other errors</span></div>
        }>
          <ActivityChart data={data.series} />
        </Card>
      </div>
    </>
  );
}

function mergeEvents(fresh: EventRow[], recent: EventRow[]): EventRow[] {
  const seen = new Set<string>();
  return [...fresh, ...recent].filter((e) => {
    const k = `${Math.round(e.ts)}-${e.engine}-${e.kind}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function EngineTile({ e, onClick, compact }: { e: OverviewEngine; onClick: () => void; compact?: boolean }) {
  const err = e.last_error;
  return (
    <div className="engine-card" style={{ ["--c" as string]: STATUS_COLOR[e.status] }} onClick={onClick}>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
        <div className="name" style={{ minWidth: 0 }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.name}</span>
          {e.shortcut && <span className="badge">!{e.shortcut}</span>}
          {e.private && <span className="badge purple">private</span>}
        </div>
        <StatusPill status={e.status} />
      </div>
      {!compact && <div style={{ marginTop: 10 }}><Sparkline values={e.spark} /></div>}
      <div className="meta">
        <span>{num(e.sent_24h)} req · {pct(e.success_24h)} ok</span>
        <span>{e.median_s != null ? secs(e.median_s) : ""}</span>
      </div>
      {e.status === "blocked" && e.blocked_until && <div className="err" style={{ color: "var(--block)" }}>Suspended by SearXNG for ~{until(e.blocked_until)} · {err?.label ?? err?.kind}</div>}
      {e.status !== "blocked" && err && e.errors_24h > 0 && <div className="err">Last error {ago(err.ts)}: {err.kind.replace("_", " ")}</div>}
      {e.status === "idle" && <div className="err">Answered the last probe but returned no results</div>}
    </div>
  );
}
