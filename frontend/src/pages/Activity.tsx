import { useEffect, useMemo, useRef, useState } from "react";
import { Ban, Filter, Flame, History, ScrollText, Pause, Play } from "lucide-react";
import { api, type Bucket, type EventRow } from "../api";
import { ago, dateTime, KIND_COLOR } from "../format";
import { usePoll, useStream, useTick } from "../hooks";
import { ActivityChart, BarList, Heatmap } from "../components/charts";
import { Button, Card, Empty, ErrorBox, Loading, Segmented, Tabs } from "../components/ui";

type Range = "48h" | "7d" | "30d";
interface ActivityResp {
  heatmap: { start: number; bucket_s: number; buckets: number; rows: { engine: string; cells: number[]; total: number }[] };
  series: Bucket[];
  kinds: { kind: string; n: number; last: number; label: string }[];
  by_engine: { engine: string; kind: string; n: number }[];
  lifecycle: { ts: number; kind: string; detail: string }[];
  labels: Record<string, string>;
}

export default function ActivityPage({ onEngine }: { onEngine: (n: string) => void }) {
  const [range, setRange] = useState<Range>("48h");
  const [tab, setTab] = useState<"events" | "logs">("events");
  const { data, error } = usePoll<ActivityResp>(`/activity?range=${range}`, 30000);
  useTick();

  const engineTable = useMemo(() => {
    const m = new Map<string, Record<string, number>>();
    data?.by_engine.forEach((r) => {
      const row = m.get(r.engine) ?? {};
      row[r.kind] = r.n;
      m.set(r.engine, row);
    });
    return [...m.entries()].map(([engine, kinds]) => ({ engine, kinds, total: Object.values(kinds).reduce((a, b) => a + b, 0) }))
      .sort((a, b) => b.total - a.total);
  }, [data]);

  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  const kindsShown = data.kinds.map((k) => k.kind);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Blocking &amp; logs</h1>
          <div className="page-sub">Which upstreams are refusing your instance, how often, and what SearXNG is logging.</div>
        </div>
        <Segmented<Range> value={range} onChange={setRange} options={[{ value: "48h", label: "48 hours" }, { value: "7d", label: "7 days" }, { value: "30d", label: "30 days" }]} />
      </div>

      <div className="grid" style={{ gap: 16 }}>
        <Card title="Block heatmap" icon={<Flame size={16} />} actions={<span className="small muted">CAPTCHA · 403 · 429 · bot challenges, per engine</span>}>
          {data.heatmap.rows.length === 0 ? <Empty icon={<Ban size={22} />}>No blocks in this window.</Empty> :
            <Heatmap rows={data.heatmap.rows} buckets={data.heatmap.buckets} start={data.heatmap.start} bucketS={data.heatmap.bucket_s} onPick={onEngine} />}
        </Card>

        <div className="grid g-main">
          <Card title="Volume vs. failures">
            <ActivityChart data={data.series} daily={range !== "48h"} />
          </Card>
          <Card title="Error types">
            {data.kinds.length === 0 ? <Empty>Nothing recorded.</Empty> :
              <BarList items={data.kinds.map((k) => ({ label: k.label, value: k.n, color: KIND_COLOR[k.kind] ?? "#94a3b8", sub: `last ${ago(k.last)}` }))} />}
          </Card>
        </div>

        <div className="grid g-main">
          <Card title="By engine" flush>
            {engineTable.length === 0 ? <Empty>No engine errors.</Empty> : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Engine</th>{kindsShown.map((k) => <th key={k} className="num">{data.labels[k] ?? k}</th>)}<th className="num">Total</th></tr></thead>
                  <tbody>
                    {engineTable.map((r) => (
                      <tr key={r.engine} className="clickable" onClick={() => onEngine(r.engine)}>
                        <td className="strong">{r.engine}</td>
                        {kindsShown.map((k) => <td key={k} className="num" style={{ color: r.kinds[k] ? KIND_COLOR[k] : "var(--muted)" }}>{r.kinds[k] ?? "·"}</td>)}
                        <td className="num strong">{r.total}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          <Card title="Lifecycle" icon={<History size={16} />} flush>
            {data.lifecycle.length === 0 ? <Empty>No restarts, applies or updates in this window.</Empty> : (
              <div className="feed" style={{ maxHeight: 360, overflow: "auto" }}>
                {data.lifecycle.map((l, i) => (
                  <div key={i} className="feed-item" style={{ gridTemplateColumns: "auto 1fr auto" }}>
                    <span className={`badge ${l.kind === "rollback" ? "red" : l.kind === "apply" ? "green" : l.kind === "update" ? "accent" : ""}`}>{l.kind}</span>
                    <div className="feed-detail">{l.detail}</div>
                    <div className="feed-time" title={dateTime(l.ts)}>{ago(l.ts)}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <div>
          <Tabs value={tab} onChange={setTab} tabs={[{ value: "events", label: "Engine events", icon: <Filter size={14} /> }, { value: "logs", label: "Live container log", icon: <ScrollText size={14} /> }]} />
          {tab === "events" ? <EventsTable labels={data.labels} onEngine={onEngine} /> : <LiveLog />}
        </div>
      </div>
    </>
  );
}

function EventsTable({ labels, onEngine }: { labels: Record<string, string>; onEngine: (n: string) => void }) {
  const [kind, setKind] = useState("");
  const [engine, setEngine] = useState("");
  const [rows, setRows] = useState<EventRow[] | null>(null);
  const [more, setMore] = useState(true);
  const load = async (before?: number) => {
    const params = new URLSearchParams({ limit: "150" });
    if (kind) params.set("kind", kind);
    if (engine) params.set("engine", engine);
    if (before) params.set("before", String(before));
    const r = await api.get<{ events: EventRow[] }>(`/events?${params}`);
    setRows((prev) => (before && prev ? [...prev, ...r.events] : r.events));
    setMore(r.events.length === 150);
  };
  useEffect(() => { setRows(null); load(); }, [kind, engine]); // eslint-disable-line react-hooks/exhaustive-deps
  useStream((m) => {
    if (m.type !== "event") return;
    const ev = m as unknown as EventRow;
    if ((kind && kind !== ev.kind && !(kind === "blocks" && ["captcha", "rate_limited", "blocked", "challenge"].includes(ev.kind))) || (engine && engine !== ev.engine)) return;
    setRows((prev) => (prev ? [ev, ...prev] : prev));
  });
  return (
    <div className="card">
      <div className="card-head">
        <select className="select" style={{ width: 200 }} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All kinds</option>
          <option value="blocks">Blocks only</option>
          {Object.entries(labels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input className="input" style={{ width: 220 }} placeholder="Engine name" value={engine} onChange={(e) => setEngine(e.target.value)} />
      </div>
      {!rows ? <Loading /> : rows.length === 0 ? <Empty>No matching events.</Empty> : (
        <div className="table-wrap" style={{ maxHeight: 560 }}>
          <table className="table">
            <thead><tr><th>When</th><th>Engine</th><th>Kind</th><th>Upstream</th><th>Detail</th></tr></thead>
            <tbody>
              {rows.map((e, i) => (
                <tr key={`${e.id ?? e.ts}-${i}`}>
                  <td className="small" title={dateTime(e.ts)}>{dateTime(e.ts)}</td>
                  <td>{e.engine ? <a onClick={() => onEngine(e.engine!)} style={{ cursor: "pointer" }}>{e.engine}</a> : <span className="muted">system</span>}</td>
                  <td><span className="badge" style={{ color: KIND_COLOR[e.kind], borderColor: "transparent", background: `${KIND_COLOR[e.kind] ?? "#64748b"}1f` }}>{labels[e.kind] ?? e.kind}</span></td>
                  <td className="small subtle">{e.host ?? "—"}</td>
                  <td className="small subtle" style={{ maxWidth: 520, overflowWrap: "anywhere" }}>{e.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {more && <div style={{ padding: 12, textAlign: "center" }}><Button small onClick={() => load(rows[rows.length - 1]?.ts)}>Load older</Button></div>}
        </div>
      )}
    </div>
  );
}

function LiveLog() {
  const [lines, setLines] = useState<{ ts: number; line: string }[] | null>(null);
  const [paused, setPaused] = useState(false);
  const [hideNoise, setHideNoise] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  useEffect(() => { api.get<{ lines: { ts: number; line: string }[] }>("/logs?lines=400").then((r) => setLines(r.lines)); }, []);
  useStream((m) => {
    if (m.type !== "log" || pausedRef.current) return;
    setLines((prev) => [...(prev ?? []), { ts: m.ts as number, line: m.line as string }].slice(-1500));
  });
  useEffect(() => { if (!paused && box.current) box.current.scrollTop = box.current.scrollHeight; }, [lines, paused]);
  const shown = (lines ?? []).filter((l) => !hideNoise || !/X-Forwarded-For nor X-Real-IP|^\s+(File|\^|~)|Traceback/.test(l.line));
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title"><ScrollText size={15} /> docker logs searxng</div>
        <div className="card-actions">
          <label className="row small subtle" style={{ gap: 6 }}><input type="checkbox" checked={hideNoise} onChange={(e) => setHideNoise(e.target.checked)} /> hide noise</label>
          <Button small onClick={() => setPaused(!paused)}>{paused ? <><Play size={13} /> Resume</> : <><Pause size={13} /> Pause</>}</Button>
        </div>
      </div>
      <div className="logbox" ref={box}>
        {!lines ? "Loading…" : shown.map((l, i) => {
          const cls = /ERROR|CRITICAL/.test(l.line) ? "err" : /WARNING/.test(l.line) ? "warn" : "info";
          return <div key={i} className={`logline ${cls}`}><span className="ts">{new Date(l.ts * 1000).toLocaleTimeString()}</span>{l.line}</div>;
        })}
      </div>
    </div>
  );
}
