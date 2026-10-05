import { useEffect, useState } from "react";
import { ArrowUpCircle, Bot, CheckCircle2, CloudDownload, GitCommitHorizontal, RefreshCw, Server, Wrench } from "lucide-react";
import { api, type CompareSection, type NotifySettings, type UpstreamReport } from "../api";
import { ago, dateTime } from "../format";
import { usePoll, useStream, useTick } from "../hooks";
import { Button, Callout, Card, Empty, ErrorBox, Loading, Segmented, Toggle, useToast } from "../components/ui";

type AutoSettings = Pick<NotifySettings, "auto_update" | "auto_update_min_hours" | "notify_updates">;

interface UpdatesResp {
  running: { version: string | null; parsed: { date: string; commit: string } | null; image: string | null; image_created: string | null };
  report: UpstreamReport;
  update_log: string[];
  pending: boolean;
  method: "docker" | "agent" | "none";
  results: { ts: number | null; finished?: string; ok: boolean; message: string; reason?: string; rolled_back?: boolean }[];
  agent_heartbeat: number | null;
  auto: AutoSettings;
  auto_last: number | null;
  lifecycle: { ts: number; kind: string; detail: string }[];
}

export default function Updates() {
  const { data, error, reload } = usePoll<UpdatesResp>("/updates", 20000);
  const toast = useToast();
  useTick();
  useStream((m) => { if (m.type === "upstream" || m.type === "lifecycle") reload(); });
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  const r = data.report;
  const behind = r.image_behind;
  const agentMode = data.method === "agent";
  const agentOk = !agentMode || (data.agent_heartbeat != null && Date.now() / 1000 - data.agent_heartbeat < 15 * 60);
  const canUpdate = data.method !== "none" && agentOk && !data.pending;

  const check = async () => {
    await api.post("/updates/check");
    toast("info", "Checked Docker Hub and GitHub for new SearXNG builds.");
    reload();
  };
  const apply = async () => {
    const res = await api.post<{ queued: boolean; message: string }>("/updates/apply");
    toast(res.queued ? "ok" : "info", res.message);
    reload();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Updates</h1>
          <div className="page-sub">SearXNG ships several builds a day, mostly fixes for engines that started getting blocked. Staying current is the best defence against blocks.</div>
        </div>
        <div className="row">
          <Button onClick={check}><RefreshCw size={15} /> Check now</Button>
          <Button kind="primary" onClick={apply} disabled={!canUpdate}
            title={data.method === "none" ? "Updates are disabled (UPDATE_METHOD=none)" : agentOk ? undefined : "Host agent is not running"}><CloudDownload size={15} /> Update SearXNG now</Button>
        </div>
      </div>

      <div className="grid" style={{ gap: 16 }}>
        {data.pending && <Callout kind="info"><b>Update in progress</b> — {agentMode ? "queued for the host agent (runs within a minute)" : "pulling the image and recreating the container"}; SearXNG restarts and is health-checked, with automatic rollback on failure.</Callout>}
        {!agentOk && <Callout kind="warn"><b>Host agent offline.</b> It hasn't checked in{data.agent_heartbeat ? ` since ${ago(data.agent_heartbeat)}` : ""}, so updates and host notifications are paused.</Callout>}

        <div className="grid g3">
          <div className="card card-pad">
            <div className="stat-label"><Server size={13} /> Running now</div>
            <div className="stat-value mono" style={{ fontSize: 18 }}>{data.running.version ?? "unknown"}</div>
            <div className="stat-foot">image built {dateTime(data.running.image_created)}</div>
          </div>
          <div className="card card-pad">
            <div className="stat-label"><ArrowUpCircle size={13} /> Newest image</div>
            <div className="stat-value mono" style={{ fontSize: 18 }}>{r.latest?.tag ?? "—"}</div>
            <div className="stat-foot">{r.latest ? `published ${ago(Date.parse(r.latest.pushed) / 1000)}` : "not checked yet"} · checked {ago(r.checked)}</div>
          </div>
          <div className="card card-pad">
            <div className="stat-label"><Wrench size={13} /> Status</div>
            {r.update_available ? (
              <>
                <div className="stat-value" style={{ fontSize: 18, color: "var(--accent)" }}>{behind?.ahead_by ?? 0} commits behind</div>
                <div className="stat-foot">{behind?.relevant_count ? <b style={{ color: "var(--warn)" }}>{behind.relevant_count} touch engines you use ({behind.relevant_engines?.join(", ")})</b> : "none touch your enabled engines"}</div>
              </>
            ) : (
              <>
                <div className="stat-value row" style={{ fontSize: 18, color: "var(--ok)", gap: 8 }}><CheckCircle2 size={18} /> Up to date</div>
                <div className="stat-foot">{r.upcoming?.ahead_by ? `${r.upcoming.ahead_by} newer commits on master, not yet in an image` : "nothing newer on master"}</div>
              </>
            )}
          </div>
        </div>
        {r.error && <Callout kind="bad">Last check failed: {r.error}</Callout>}

        <AutoUpdateCard auto={data.auto} last={data.auto_last} onSaved={reload} />

        {r.update_available && <CommitList title="In the newer image (what an update brings)" section={behind} />}
        <CommitList title="On master, not yet built into an image" section={r.upcoming} muted />

        <div className="grid g2">
          <Card title="Update log" flush>
            {data.update_log.length === 0 ? <Empty>No update log found.</Empty> : <div className="logbox" style={{ maxHeight: 300 }}>{data.update_log.slice().reverse().join("\n")}</div>}
          </Card>
          <Card title="Recent updates from this dashboard" flush>
            {data.results.length === 0 ? <Empty>None yet.</Empty> : data.results.map((x, i) => (
              <div key={i} className="feed-item" style={{ gridTemplateColumns: "auto 1fr auto" }}>
                <span className={`badge ${x.ok ? "green" : "red"}`}>{x.ok ? "ok" : x.rolled_back ? "rolled back" : "failed"}</span>
                <div className="feed-detail mono">{x.message.split("\n").slice(-3).join("\n")}{x.reason ? <div className="tiny muted">{x.reason}</div> : null}</div>
                <div className="feed-time">{ago(x.ts ?? (x.finished ? Date.parse(x.finished) / 1000 : null))}</div>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </>
  );
}

function CommitList({ title, section, muted }: { title: string; section?: CompareSection; muted?: boolean }) {
  const commits = section?.commits ?? [];
  return (
    <Card title={title} icon={<GitCommitHorizontal size={16} />} flush actions={section?.relevant_count ? <span className="badge accent">{section.relevant_count} relevant</span> : null}>
      {commits.length === 0 ? <Empty>No commits.</Empty> : (
        <div style={{ maxHeight: muted ? 300 : 460, overflow: "auto" }}>
          {commits.map((c) => (
            <div key={c.sha} className={`commit ${c.relevant ? "relevant" : ""}`}>
              <a className="sha" href={c.url} target="_blank" rel="noreferrer">{c.short}</a>
              <div style={{ minWidth: 0 }}>
                <div className={c.relevant ? "strong" : ""}>{c.title}</div>
                {c.engines && c.engines.length > 0 && <div className="row" style={{ gap: 5, marginTop: 4 }}>{c.engines.map((e) => <span key={e} className="badge accent">{e}</span>)}</div>}
              </div>
              <div className="feed-time">{ago(Date.parse(c.date) / 1000)}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function AutoUpdateCard({ auto, last, onSaved }: { auto: AutoSettings; last: number | null; onSaved: () => void }) {
  const [a, setA] = useState<AutoSettings>(auto);
  const toast = useToast();
  useEffect(() => setA(auto), [auto]);
  const dirty = JSON.stringify(a) !== JSON.stringify(auto);
  const save = async () => {
    await api.put("/alerts/settings", a);
    toast("ok", "Update settings saved.");
    onSaved();
  };
  return (
    <Card title="Automatic updates" icon={<Bot size={16} />} actions={last ? <span className="small muted">last auto-update {ago(last)}</span> : null}>
      <div className="grid" style={{ gap: 14 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div style={{ maxWidth: 620 }}>
            <div className="strong">When a new SearXNG image appears</div>
            <div className="small muted">
              {a.auto_update === "always" && <>Install it automatically (checked hourly, at most every {a.auto_update_min_hours}h). If it fixes an engine that is failing here, install it right away.</>}
              {a.auto_update === "fixes" && <>Only install early when the new image changes an engine that is currently failing here. Everything else waits for the nightly update.</>}
              {a.auto_update === "off" && <>Don't install automatically from the dashboard. You'll still get an alert when an update is overdue or fixes a failing engine.</>}
              {" "}Every update is health-checked and rolled back automatically if SearXNG doesn't come back healthy.
            </div>
          </div>
          <Segmented value={a.auto_update} onChange={(v) => setA({ ...a, auto_update: v })} options={[
            { value: "always", label: "Always" }, { value: "fixes", label: "Fixes only" }, { value: "off", label: "Off" }]} />
        </div>
        <div className="row" style={{ gap: 24 }}>
          <label className="field" style={{ width: 220 }}><span className="field-label">Minimum hours between auto-updates</span>
            <input className="input" type="number" min={1} step={1} value={a.auto_update_min_hours}
              onChange={(e) => setA({ ...a, auto_update_min_hours: Number(e.target.value) })} disabled={a.auto_update !== "always"} /></label>
          <label className="row" style={{ gap: 10 }}><Toggle checked={a.notify_updates} onChange={(v) => setA({ ...a, notify_updates: v })} />
            <span><span className="strong">Notify me when SearXNG is updated</span><div className="small muted">Version, number of upstream changes and which of your engines they touch.</div></span></label>
          <div className="grow" />
          <Button kind="primary" disabled={!dirty} onClick={save}>Save</Button>
        </div>
      </div>
    </Card>
  );
}
