import { useMemo, useState } from "react";
import { FlaskConical, KeyRound, Lock, Search, Undo2 } from "lucide-react";
import { api, type ApplyResult, type ConfigPatch, type Engine, type EnginePatch } from "../api";
import { ago, num, pct, secs } from "../format";
import { usePoll, useTick } from "../hooks";
import { ApplyFlow } from "../components/ApplyFlow";
import { Button, Callout, Empty, ErrorBox, Loading, Segmented, StatusPill, Toggle, TokenBox, useToast } from "../components/ui";

type Filter = "enabled" | "web" | "problems" | "api" | "all";

interface EnginesResp { engines: Engine[]; catalog_loaded: boolean; private_token: string[] | null; public_url: string }

export default function Engines({ onEngine }: { onEngine: (n: string) => void }) {
  const { data, error, reload } = usePoll<EnginesResp>("/engines", 30000);
  const [filter, setFilter] = useState<Filter>("enabled");
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [pending, setPending] = useState<Record<string, EnginePatch>>({});
  const [review, setReview] = useState<ConfigPatch | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const toast = useToast();
  useTick();

  const categories = useMemo(() => {
    const s = new Set<string>();
    data?.engines.forEach((e) => e.categories.forEach((c) => s.add(c)));
    return [...s].sort();
  }, [data]);

  const rows = useMemo(() => {
    if (!data) return [];
    const ql = q.trim().toLowerCase();
    return data.engines.filter((e) => {
      const enabled = pending[e.name]?.enabled ?? e.enabled;
      if (filter === "enabled" && !enabled) return false;
      if (filter === "web" && !(e.web || (enabled && e.categories.includes("general")))) return false;
      if (filter === "problems" && !(["blocked", "failing", "degraded"].includes(e.status) || (e.enabled && e.errors_24h > 0))) return false;
      if (filter === "api" && !e.requires_api_key) return false;
      if (cat && !e.categories.includes(cat)) return false;
      if (ql && !(`${e.name} ${e.shortcut ?? ""} ${e.module ?? ""}`.toLowerCase().includes(ql))) return false;
      return true;
    }).sort((a, b) => Number(b.enabled) - Number(a.enabled) || Number(b.web) - Number(a.web) || a.name.localeCompare(b.name));
  }, [data, filter, q, cat, pending]);

  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;

  const setEnabled = (e: Engine, v: boolean) => {
    setPending((p) => {
      const next = { ...p };
      if (v === e.enabled) delete next[e.name];
      else next[e.name] = { ...next[e.name], enabled: v };
      return next;
    });
  };

  const test = async (e: Engine) => {
    setTesting(e.name);
    try {
      const r = await api.post<{ status: string; results: number; detail: string | null; duration_ms: number }>(`/engines/${encodeURIComponent(e.name)}/test`, { query: "open source search engine" });
      toast(r.status === "ok" ? "ok" : "bad", <><b>{e.name}</b>: {r.status === "ok" ? `${r.results} results in ${r.duration_ms} ms` : `${r.status}${r.detail ? ` — ${r.detail}` : ""}`}</>);
    } catch (err) {
      toast("bad", (err as Error).message);
    } finally {
      setTesting(null);
    }
  };

  const nPending = Object.keys(pending).length;
  const counts = {
    enabled: data.engines.filter((e) => e.enabled).length,
    problems: data.engines.filter((e) => ["blocked", "failing", "degraded"].includes(e.status)).length,
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Engines</h1>
          <div className="page-sub">{counts.enabled} enabled of {data.engines.length} available · toggle engines, then review and apply in one restart.</div>
        </div>
      </div>

      {data.private_token?.[0] && (
        <div style={{ marginBottom: 14 }}>
          <Callout kind="info"><TokenBox token={data.private_token[0]} publicUrl={data.public_url} /></Callout>
        </div>
      )}
      {!data.catalog_loaded && <div style={{ marginBottom: 14 }}><ErrorBox error="Engine catalog not loaded yet (needs Docker access to read the SearXNG image). Showing loaded engines only." /></div>}

      <div className="card">
        <div className="card-head" style={{ flexWrap: "wrap" }}>
          <Segmented<Filter> value={filter} onChange={setFilter} options={[
            { value: "enabled", label: `Enabled` }, { value: "web", label: "Web" },
            { value: "problems", label: `Problems${counts.problems ? ` (${counts.problems})` : ""}` },
            { value: "api", label: "API engines" }, { value: "all", label: "All" },
          ]} />
          <select className="select" style={{ width: 160 }} value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">All categories</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <div className="search-input grow" style={{ minWidth: 200 }}>
            <Search size={15} />
            <input className="input" placeholder="Search engines, shortcuts, modules…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
        <div className="table-wrap">
          {rows.length === 0 ? <Empty>No engines match.</Empty> : (
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 54 }}>On</th><th>Engine</th><th>Status</th><th>Categories</th>
                  <th className="num">Req 24h</th><th className="num">Success</th><th className="num">Median</th><th className="num" title="Ranking multiplier (default 1.0). Click an engine to change it.">Weight</th><th>Last error</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => {
                  const p = pending[e.name];
                  const enabled = p?.enabled ?? e.enabled;
                  return (
                    <tr key={e.name} className={`clickable ${p ? "changed" : ""}`} onClick={() => onEngine(e.name)}>
                      <td><Toggle checked={enabled} changed={!!p} onChange={(v) => setEnabled(e, v)}
                        title={e.requires_api_key && !e.has_api_key ? "Needs an API key - set it in the engine panel" : undefined} /></td>
                      <td>
                        <div className="row" style={{ gap: 6 }}>
                          <span className="strong">{e.name}</span>
                          {e.shortcut && <span className="badge">!{e.shortcut}</span>}
                          {e.requires_api_key && <span className={`badge ${e.has_api_key ? "green" : "amber"}`}><KeyRound size={10} />{e.has_api_key ? "key set" : "needs key"}</span>}
                          {e.private && <span className="badge purple"><Lock size={10} />private</span>}
                          {e.custom && <span className="badge accent">custom</span>}
                          {e.overridden.length > 0 && !e.custom && <span className="badge" title={`Overrides: ${e.overridden.join(", ")}`}>customized</span>}
                        </div>
                        {e.module && <div className="tiny muted mono">{e.module}</div>}
                      </td>
                      <td><StatusPill status={e.status} /></td>
                      <td className="small subtle">{e.categories.slice(0, 3).join(", ")}</td>
                      <td className="num">{num(e.sent_24h)}</td>
                      <td className="num">{pct(e.success_24h)}</td>
                      <td className="num">{secs(e.median_s)}</td>
                      <td className="num" style={{ color: e.weight != null && e.weight !== 1 ? "var(--accent)" : "var(--muted)" }}>{(e.weight ?? 1).toFixed(1)}</td>
                      <td className="small subtle" style={{ maxWidth: 240 }}>
                        {e.last_error ? <span title={e.last_error.detail ?? ""}>{e.last_error.kind.replace("_", " ")} · {ago(e.last_error.ts)}</span> : <span className="muted">—</span>}
                      </td>
                      <td onClick={(ev) => ev.stopPropagation()}>
                        <Button small kind="ghost" busy={testing === e.name} onClick={() => test(e)} title="Run a test search with only this engine"><FlaskConical size={13} /> Test</Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {nPending > 0 && (
        <div className="pending-bar">
          <span><b>{nPending}</b> pending change{nPending > 1 ? "s" : ""}</span>
          <Button kind="ghost" small onClick={() => setPending({})}><Undo2 size={13} /> Discard</Button>
          <Button kind="primary" onClick={() => setReview({ engines: pending })}>Review &amp; apply</Button>
        </div>
      )}
      {review && (
        <ApplyFlow patch={review} onClose={() => setReview(null)}
          onApplied={(r: ApplyResult) => { if (r.ok) { setPending({}); } reload(); }} />
      )}
    </>
  );
}
