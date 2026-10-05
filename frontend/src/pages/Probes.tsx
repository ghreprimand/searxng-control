import { useState } from "react";
import { FlaskConical, Timer } from "lucide-react";
import { api, type Probe } from "../api";
import { ago, dateTime } from "../format";
import { usePoll, useStream, useTick } from "../hooks";
import { Button, Card, Empty, ErrorBox, Loading, StatusPill, useToast } from "../components/ui";

interface ProbesResp { probes: Probe[]; interval_min: number; web_engines: string[] }

export default function Probes({ onEngine }: { onEngine: (n: string) => void }) {
  const { data, error, reload } = usePoll<ProbesResp>("/probes?limit=60", 30000);
  const [query, setQuery] = useState("");
  const toast = useToast();
  useTick();
  useStream((m) => { if (m.type === "probe") reload(); });
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;

  const canaries = data.probes.filter((p) => p.kind === "canary");
  const engines = [...new Set([...data.web_engines, ...canaries.flatMap((p) => p.results.map((r) => r.engine))])]
    .filter((e) => data.web_engines.includes(e) || canaries.some((p) => p.results.some((r) => r.engine === e && r.status !== "empty")));
  const recent = canaries.slice(0, 24).reverse();

  const run = async () => {
    const p = await api.post<Probe>("/probes/run", { query: query || null });
    toast("info", <><b>{p.ok_engines}/{p.web_engines}</b> web engines returned results for “{p.query}” in {p.duration_ms} ms.</>);
    reload();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Probes</h1>
          <div className="page-sub">
            A real search every {data.interval_min} min (change it under Alerts) shows which engines are answering,
            even when nobody is searching.
          </div>
        </div>
        <div className="row">
          <input className="input" style={{ width: 260 }} placeholder="Custom query (optional)" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} />
          <Button kind="primary" onClick={run}><FlaskConical size={15} /> Probe now</Button>
        </div>
      </div>

      <div className="grid" style={{ gap: 16 }}>
        <Card title="Engine × probe matrix" icon={<Timer size={16} />} actions={<span className="small muted">oldest → newest</span>}>
          {recent.length === 0 ? <Empty>No probes yet — the first runs a minute after startup.</Empty> : (
            <div className="heat" style={{ gridTemplateColumns: `170px repeat(${recent.length}, minmax(10px, 1fr))` }}>
              {engines.map((eng) => (
                <MatrixRow key={eng} engine={eng} probes={recent} onEngine={onEngine} />
              ))}
            </div>
          )}
          <div className="legend" style={{ marginTop: 12 }}>
            <span><i style={{ background: "var(--ok)" }} />results</span><span><i style={{ background: "var(--bad)" }} />error</span>
            <span><i style={{ background: "#3a4357" }} />no results</span><span><i style={{ background: "var(--panel-3)" }} />not queried</span>
          </div>
        </Card>

        <Card title="History" flush>
          {data.probes.length === 0 ? <Empty>Nothing yet.</Empty> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>When</th><th>Type</th><th>Query</th><th className="num">Time</th><th>Web engines</th><th>Failures</th></tr></thead>
                <tbody>
                  {data.probes.map((p) => {
                    const fails = p.results.filter((r) => r.status === "error");
                    return (
                      <tr key={p.id}>
                        <td className="small" title={dateTime(p.ts)}>{ago(p.ts)}</td>
                        <td><span className={`badge ${p.kind === "manual" ? "purple" : ""}`}>{p.kind === "manual" ? `test: ${p.target}` : "canary"}</span></td>
                        <td className="small">“{p.query}”</td>
                        <td className="num small">{p.duration_ms} ms</td>
                        <td>{p.kind === "canary" ? <StatusPill status={p.ok_engines >= Math.max(3, data.web_engines.length * 0.7) ? "healthy" : p.ok_engines >= 2 ? "degraded" : "failing"} label={`${p.ok_engines}/${data.web_engines.length}`} />
                          : <StatusPill status={p.ok ? "healthy" : "failing"} label={p.ok ? `${p.total_results} results` : "failed"} />}</td>
                        <td className="small subtle">{fails.length ? fails.map((f) => `${f.engine} (${f.detail})`).join(", ") : p.error ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function MatrixRow({ engine, probes, onEngine }: { engine: string; probes: Probe[]; onEngine: (n: string) => void }) {
  return (
    <>
      <div className="heat-label" style={{ cursor: "pointer" }} onClick={() => onEngine(engine)}>{engine}</div>
      {probes.map((p) => {
        const r = p.results.find((x) => x.engine === engine);
        const bg = !r ? "var(--panel-3)" : r.status === "ok" ? "var(--ok)" : r.status === "error" ? "var(--bad)" : "#3a4357";
        return <div key={p.id} className="heat-cell" style={{ background: bg, opacity: r ? 0.85 : 1 }}
          title={`${dateTime(p.ts)} · “${p.query}”\n${r ? `${r.status}${r.results ? ` (${r.results})` : ""}${r.detail ? ` — ${r.detail}` : ""}` : "not queried"}`} />;
      })}
    </>
  );
}
