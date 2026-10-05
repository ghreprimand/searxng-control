import { useEffect, useState } from "react";
import { ExternalLink, FlaskConical, KeyRound, Lock, Save, X } from "lucide-react";
import { api, type Bucket, type ConfigPatch, type Engine, type EnginePatch, type EventRow } from "../api";
import { ago, dateTime, KIND_COLOR, num, pct, secs, until } from "../format";
import { usePoll } from "../hooks";
import { ApplyFlow } from "../components/ApplyFlow";
import { ActivityChart, BarList } from "../components/charts";
import { Button, Callout, Card, Drawer, Empty, Loading, StatusPill, Toggle, TokenBox } from "../components/ui";

interface Detail {
  engine: Engine;
  series: Bucket[];
  kinds_7d: { kind: string; n: number; last: number; label: string }[];
  events: (EventRow & { label: string })[];
  probes: { ts: number; kind: string; query: string; status: string; results: number; detail: string | null }[];
  settings_entry: Record<string, unknown> | null;
  default_entry: Record<string, unknown> | null;
  private_token: string | null;
  public_url: string;
}

interface TestResult { status: string; detail: string | null; duration_ms: number; results: number; top: { title: string; url: string; content: string }[] }

export function EngineDrawer({ name, onClose }: { name: string; onClose: () => void }) {
  const { data, reload } = usePoll<Detail>(`/engines/${encodeURIComponent(name)}`, 20000);
  const [form, setForm] = useState<EnginePatch>({});
  const [review, setReview] = useState<ConfigPatch | null>(null);
  const [query, setQuery] = useState("open source search engine");
  const [test, setTest] = useState<TestResult | null>(null);
  const [testErr, setTestErr] = useState<string | null>(null);

  useEffect(() => { setForm({}); setTest(null); }, [name]);

  const e = data?.engine;
  const runTest = async () => {
    setTestErr(null);
    try {
      setTest(await api.post<TestResult>(`/engines/${encodeURIComponent(name)}/test`, { query }));
      reload();
    } catch (err) { setTestErr((err as Error).message); }
  };

  const dirty = Object.keys(form).length > 0;
  const val = <K extends keyof EnginePatch>(k: K, fallback: EnginePatch[K]) => (k in form ? form[k] : fallback);

  return (
    <Drawer onClose={onClose}>
      <div className="modal-head" style={{ background: "var(--bg-2)" }}>
        <div>
          <div className="modal-title row" style={{ gap: 8 }}>{name} {e && <StatusPill status={e.status} />}</div>
          {e && <div className="small muted">{e.module ? <span className="mono">{e.module}</span> : null}{e.categories.length ? ` · ${e.categories.join(", ")}` : ""}</div>}
        </div>
        <button className="btn ghost sm" style={{ marginLeft: "auto" }} onClick={onClose}><X size={16} /></button>
      </div>
      {!data || !e ? <Loading /> : (
        <div className="modal-body grid" style={{ gap: 16 }}>
          {e.status === "blocked" && (
            <Callout kind="bad">
              <b>{e.last_error?.label ?? "Blocked"}</b> — SearXNG suspended this engine{e.blocked_until ? `; it retries in ~${until(e.blocked_until)}` : ""}.
              <div className="small subtle">{e.last_error?.detail}</div>
            </Callout>
          )}
          {e.private && data.private_token && <Callout kind="info"><TokenBox token={data.private_token} publicUrl={data.public_url} /></Callout>}
          {e.requires_api_key && !e.has_api_key && <Callout kind="warn">This engine uses an official API and needs an API key before it can be enabled.</Callout>}

          <div className="grid g4">
            <MiniStat label="Requests 24h" value={num(e.sent_24h)} />
            <MiniStat label="Success 24h" value={pct(e.success_24h)} />
            <MiniStat label="Blocks 24h" value={num(e.blocks_24h)} color={e.blocks_24h ? "var(--block)" : undefined} />
            <MiniStat label="Median time" value={secs(e.median_s)} />
          </div>

          <Card title="Last 48 hours">
            <ActivityChart data={data.series} height={140} />
            <div className="small muted" style={{ marginTop: 6 }}>Last success: {ago(e.last_ok)}{e.website && <> · <a href={e.website} target="_blank" rel="noreferrer">{e.website.replace(/^https?:\/\//, "")} <ExternalLink size={11} /></a></>}</div>
          </Card>

          <Card title="Settings" icon={<Save size={15} />} actions={dirty && <Button small kind="ghost" onClick={() => setForm({})}>Reset</Button>}>
            <div className="grid" style={{ gap: 14 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div><div className="strong">Enabled by default</div><div className="small muted">Off engines still work with their bang{e.shortcut ? ` (!${e.shortcut})` : ""}.</div></div>
                <Toggle checked={!!val("enabled", e.enabled)} changed={"enabled" in form} onChange={(v) => setForm({ ...form, enabled: v })} />
              </div>
              <div className="form-grid">
                <label className="field"><span className="field-label">Shortcut (bang)</span>
                  <input className="input mono" value={String(val("shortcut", e.shortcut ?? "") ?? "")} onChange={(x) => setForm({ ...form, shortcut: x.target.value })} /></label>
                <label className="field"><span className="field-label">Weight</span>
                  <input className="input" type="number" step="0.1" placeholder="1.0" value={String(val("weight", e.weight ?? "") ?? "")} onChange={(x) => setForm({ ...form, weight: x.target.value })} />
                  <span className="field-help">Ranking multiplier: 1.0 = normal, 1.5 = favour, 0.5 = demote.</span></label>
                <label className="field"><span className="field-label">Timeout (s)</span>
                  <input className="input" type="number" step="0.5" placeholder="default" value={String(val("timeout", e.timeout ?? "") ?? "")} onChange={(x) => setForm({ ...form, timeout: x.target.value })} /></label>
              </div>
              {e.requires_api_key && (
                <label className="field"><span className="field-label row" style={{ gap: 6 }}><KeyRound size={13} /> API key {e.has_api_key && <span className="badge green">set</span>}</span>
                  <input className="input mono" type="password" autoComplete="off" placeholder={e.has_api_key ? "•••••••• (leave blank to keep)" : "paste key"}
                    value={String(form.api_key ?? "")} onChange={(x) => {
                      const { api_key: _drop, ...rest } = form;
                      setForm(x.target.value ? { ...rest, api_key: x.target.value } : rest);
                    }} />
                  <span className="field-help">Stored in SearXNG's settings.yml on the server. Clear it by applying an empty value with “Remove key”.</span>
                  {e.has_api_key && <div><Button small kind="ghost" onClick={() => setForm({ ...form, api_key: "" })}>Remove key</Button></div>}
                </label>
              )}
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div><div className="strong row" style={{ gap: 6 }}><Lock size={13} /> Private (token-gated)</div>
                  <div className="small muted">Only browsers that saved the engine token use it. Keeps paid APIs away from AI tools and probes.</div></div>
                <Toggle checked={!!val("private", e.private)} changed={"private" in form} onChange={(v) => setForm({ ...form, private: v })} />
              </div>
              <div className="row" style={{ justifyContent: "flex-end" }}>
                <Button kind="primary" disabled={!dirty} onClick={() => setReview({ engines: { [name]: cleanPatch(form, e) } })}>Review &amp; apply</Button>
              </div>
            </div>
          </Card>

          <Card title="Test this engine" icon={<FlaskConical size={15} />}>
            <div className="row">
              <input className="input grow" value={query} onChange={(x) => setQuery(x.target.value)} onKeyDown={(x) => x.key === "Enter" && runTest()} />
              <Button kind="primary" onClick={runTest}>Run</Button>
            </div>
            {testErr && <div style={{ marginTop: 10 }}><Callout kind="bad">{testErr}</Callout></div>}
            {test && (
              <div style={{ marginTop: 12 }} className="grid">
                <div className="row"><StatusPill status={test.status === "ok" ? "healthy" : test.status === "empty" ? "idle" : "failing"} label={test.status === "ok" ? `${test.results} results` : test.status} />
                  <span className="small muted">{test.duration_ms} ms{test.detail ? ` · ${test.detail}` : ""}</span></div>
                {test.top.map((r) => (
                  <div key={r.url} style={{ minWidth: 0 }}>
                    <a href={r.url} target="_blank" rel="noreferrer" className="strong">{r.title || r.url}</a>
                    <div className="tiny muted" style={{ overflowWrap: "anywhere" }}>{r.url}</div>
                    <div className="small subtle">{r.content}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <div className="grid g2">
            <Card title="Error types · 7 days">
              {data.kinds_7d.length === 0 ? <Empty>No errors in 7 days.</Empty> :
                <BarList items={data.kinds_7d.map((k) => ({ label: k.label, value: k.n, color: KIND_COLOR[k.kind] ?? "#94a3b8", sub: `last ${ago(k.last)}` }))} />}
            </Card>
            <Card title="Probe history" flush>
              {data.probes.length === 0 ? <Empty>Not probed yet.</Empty> : (
                <div className="feed" style={{ maxHeight: 260, overflow: "auto" }}>
                  {data.probes.map((p, i) => (
                    <div key={i} className="feed-item" style={{ gridTemplateColumns: "auto 1fr auto" }}>
                      <StatusPill status={p.status === "ok" ? "healthy" : p.status === "empty" ? "idle" : "failing"} label={p.status === "ok" ? String(p.results) : p.status} />
                      <div className="feed-detail" title={p.detail ?? ""}>{p.kind}: “{p.query}”{p.detail ? ` — ${p.detail}` : ""}</div>
                      <div className="feed-time">{ago(p.ts)}</div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <Card title="Recent events" flush>
            {data.events.length === 0 ? <Empty>No events recorded for this engine.</Empty> : (
              <div className="feed" style={{ maxHeight: 320, overflow: "auto" }}>
                {data.events.map((ev, i) => (
                  <div key={i} className="feed-item">
                    <div className="feed-icon" style={{ background: `${KIND_COLOR[ev.kind] ?? "#64748b"}22`, color: KIND_COLOR[ev.kind] }}>•</div>
                    <div style={{ minWidth: 0 }}><div className="feed-title">{ev.label}{ev.suspended_s ? <span className="muted"> · suspended {Math.round(ev.suspended_s / 60)}m</span> : null}</div>
                      <div className="feed-detail">{ev.host ? `${ev.host} — ` : ""}{ev.detail}</div></div>
                    <div className="feed-time" title={dateTime(ev.ts)}>{ago(ev.ts)}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {(data.settings_entry || data.default_entry) && (
            <div className="grid g2">
              <Card title="Your override (settings.yml)"><pre className="mono small" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{data.settings_entry ? JSON.stringify(data.settings_entry, null, 2) : "— none —"}</pre></Card>
              <Card title="Image default"><pre className="mono small" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(data.default_entry, null, 2)}</pre></Card>
            </div>
          )}
        </div>
      )}
      {review && <ApplyFlow patch={review} onClose={() => setReview(null)} onApplied={(r) => { if (r.ok) setForm({}); reload(); }} />}
    </Drawer>
  );
}

function cleanPatch(form: EnginePatch, e: Engine): EnginePatch {
  const p: EnginePatch = { ...form };
  if (p.api_key === undefined) delete p.api_key;
  if (typeof p.shortcut === "string" && p.shortcut === (e.shortcut ?? "")) delete p.shortcut;
  for (const k of ["weight", "timeout"] as const) {
    if (k in p) {
      const v = p[k];
      p[k] = v === "" || v == null ? null : Number(v);
    }
  }
  return p;
}

function MiniStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="card stat" style={{ padding: "12px 14px" }}>
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ fontSize: 20, color }}>{value}</div>
    </div>
  );
}
