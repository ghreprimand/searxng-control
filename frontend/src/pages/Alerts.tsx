import { useEffect, useState } from "react";
import { BellRing, Send, ShieldCheck } from "lucide-react";
import { api, type Alert, type NotifySettings } from "../api";
import { ago, dateTime, duration } from "../format";
import { usePoll, useTick } from "../hooks";
import { Button, Callout, Card, Empty, ErrorBox, Loading, SeverityPill, Toggle, useToast } from "../components/ui";

interface AlertsResp { active: Alert[]; history: Alert[]; settings: NotifySettings; agent_heartbeat: number | null; update_method: string }

export default function Alerts() {
  const { data, error, reload } = usePoll<AlertsResp>("/alerts", 20000);
  const [s, setS] = useState<NotifySettings | null>(null);
  const toast = useToast();
  useTick();
  useEffect(() => { if (data && !s) setS(data.settings); }, [data, s]);
  if (!data || !s) return error ? <ErrorBox error={error} /> : <Loading />;
  const dirty = JSON.stringify(s) !== JSON.stringify(data.settings);

  const save = async () => {
    const saved = await api.put<NotifySettings>("/alerts/settings", s);
    setS(saved);
    toast("ok", "Alert settings saved.");
    reload();
  };
  const test = async () => {
    const r = await api.post<{ sent: string[] }>("/alerts/test");
    toast(r.sent.length ? "ok" : "bad", r.sent.length ? `Test sent via ${r.sent.join(" + ")}.` : "No channel is enabled.");
  };
  const set = <K extends keyof NotifySettings>(k: K, v: NotifySettings[K]) => setS({ ...s, [k]: v });

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Alerts</h1>
          <div className="page-sub">Conditions are checked every minute; you're notified when one opens and when it clears.</div>
        </div>
      </div>
      <div className="grid g-main">
        <div className="grid" style={{ gap: 16, alignContent: "start" }}>
          <Card title="Active" icon={<BellRing size={16} />} flush>
            {data.active.length === 0 ? <Empty icon={<ShieldCheck size={22} />}>All clear.</Empty> : data.active.map((a) => <AlertRow key={a.id} a={a} />)}
          </Card>
          <Card title="History" flush>
            {data.history.filter((a) => a.resolved).length === 0 ? <Empty>No resolved alerts yet.</Empty> :
              data.history.filter((a) => a.resolved).map((a) => <AlertRow key={a.id} a={a} />)}
          </Card>
        </div>
        <div className="grid" style={{ gap: 16, alignContent: "start" }}>
          <Card title="Notification channels">
            <div className="grid" style={{ gap: 14 }}>
              {data.update_method === "agent" && (
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div><div className="strong">Host notifications</div><div className="small muted">Delivered by the host agent (on Unraid: the built-in notification system, and onward to email/Pushover/etc.).</div></div>
                  <Toggle checked={s.unraid} onChange={(v) => set("unraid", v)} />
                </div>
              )}
              <label className="field"><span className="field-label">ntfy topic URL (optional)</span>
                <input className="input mono" placeholder="https://ntfy.sh/your-topic" value={s.ntfy_url} onChange={(e) => set("ntfy_url", e.target.value)} />
                <span className="field-help">Push to your phone via ntfy.</span></label>
              <label className="field"><span className="field-label">ntfy access token (optional)</span>
                <input className="input mono" type="password" value={s.ntfy_token} onChange={(e) => set("ntfy_token", e.target.value)} /></label>
              <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
                <label className="field"><span className="field-label">Minimum severity</span>
                  <select className="select" value={s.min_severity} onChange={(e) => set("min_severity", e.target.value)}>
                    <option value="info">info</option><option value="warning">warning</option><option value="critical">critical</option>
                  </select></label>
                <label className="field"><span className="field-label">Notify when resolved</span>
                  <div style={{ paddingTop: 6 }}><Toggle checked={s.notify_resolved} onChange={(v) => set("notify_resolved", v)} /></div></label>
              </div>
              {data.update_method === "agent" && !data.agent_heartbeat && s.unraid && <Callout kind="warn">The host agent hasn't checked in yet, so host notifications will queue until it does.</Callout>}
            </div>
          </Card>
          <Card title="Thresholds">
            <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
              <label className="field"><span className="field-label">Min. working web engines</span>
                <input className="input" type="number" min={1} value={s.min_web_engines} onChange={(e) => set("min_web_engines", Number(e.target.value))} /></label>
              <label className="field"><span className="field-label">Engine down for (h)</span>
                <input className="input" type="number" step="0.5" min={0.5} value={s.engine_blocked_hours} onChange={(e) => set("engine_blocked_hours", Number(e.target.value))} /></label>
              <label className="field"><span className="field-label">Update pending for (h)</span>
                <input className="input" type="number" min={6} value={s.update_stale_hours} onChange={(e) => set("update_stale_hours", Number(e.target.value))} /></label>
              <label className="field"><span className="field-label">Probe every (min)</span>
                <input className="input" type="number" min={5} value={s.probe_interval_min} onChange={(e) => set("probe_interval_min", Number(e.target.value))} /></label>
            </div>
          </Card>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <Button onClick={test}><Send size={14} /> Send test</Button>
            <Button kind="primary" disabled={!dirty} onClick={save}>Save</Button>
          </div>
        </div>
      </div>
    </>
  );
}

function AlertRow({ a }: { a: Alert }) {
  return (
    <div className="feed-item" style={{ gridTemplateColumns: "auto 1fr auto" }}>
      <SeverityPill severity={a.severity} />
      <div style={{ minWidth: 0 }}>
        <div className="feed-title">{a.title}</div>
        <div className="feed-detail">{a.detail}</div>
        <div className="tiny muted">opened {dateTime(a.opened)}{a.resolved ? ` · resolved after ${duration(a.resolved - a.opened)}` : ""}{a.notified ? " · notified" : ""}</div>
      </div>
      <div className="feed-time">{ago(a.resolved ?? a.opened)}</div>
    </div>
  );
}
