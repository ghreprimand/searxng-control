import { useEffect, useState } from "react";
import {
  Activity, Bell, Boxes, ExternalLink, FlaskConical, Gauge, RefreshCcw, Search, Settings2, Wifi, WifiOff,
} from "lucide-react";
import type { Overview as OverviewData } from "./api";
import { api } from "./api";
import { useHashRoute, useStream } from "./hooks";
import { ToastProvider } from "./components/ui";
import { EngineDrawer } from "./pages/EngineDrawer";
import Overview from "./pages/Overview";
import Engines from "./pages/Engines";
import ActivityPage from "./pages/Activity";
import Probes from "./pages/Probes";
import Configure from "./pages/Configure";
import Updates from "./pages/Updates";
import Alerts from "./pages/Alerts";

const NAV = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "engines", label: "Engines", icon: Boxes },
  { id: "activity", label: "Blocking & logs", icon: Activity },
  { id: "probes", label: "Probes", icon: FlaskConical },
  { id: "configure", label: "Configure", icon: Settings2 },
  { id: "updates", label: "Updates", icon: RefreshCcw },
  { id: "alerts", label: "Alerts", icon: Bell },
];

interface Meta { user: string | null; name: string | null; public_url: string; label: string; update_method: string }

export default function App() {
  const [page, arg, go] = useHashRoute();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [badges, setBadges] = useState<{ alerts: number; update: boolean }>({ alerts: 0, update: false });
  const [engine, setEngine] = useState<string | null>(null);
  const connected = useStream(() => {});

  useEffect(() => {
    api.get<Meta>("/meta").then(setMeta).catch(() => {});
    const load = () => api.get<OverviewData>("/overview").then((o) =>
      setBadges({ alerts: o.alerts.length, update: !!o.update.available })).catch(() => {});
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => { if (page === "engine" && arg) { setEngine(arg); } }, [page, arg]);

  const openEngine = (name: string) => setEngine(name);
  const closeEngine = () => { setEngine(null); if (page === "engine") go("engines"); };

  return (
    <ToastProvider>
      <div className="app">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-logo"><Search size={19} strokeWidth={2.6} /></div>
            <div>
              <div className="brand-name">SearXNG Control</div>
              <div className="brand-sub">{meta?.label || (meta?.public_url ? safeHost(meta.public_url) : "SearXNG")}</div>
            </div>
          </div>
          <div className="nav-section">Monitor</div>
          {NAV.slice(0, 4).map((n) => <NavItem key={n.id} {...n} active={page === n.id} onClick={() => go(n.id)} />)}
          <div className="nav-section">Manage</div>
          {NAV.slice(4).map((n) => (
            <NavItem key={n.id} {...n} active={page === n.id} onClick={() => go(n.id)}
              count={n.id === "alerts" && badges.alerts ? String(badges.alerts) : n.id === "updates" && badges.update ? "new" : undefined} />
          ))}
          <div className="sidebar-foot">
            {meta?.public_url && <a href={meta.public_url} target="_blank" rel="noreferrer" className="row" style={{ gap: 6 }}><ExternalLink size={13} /> Open search</a>}
            <span className="row" style={{ gap: 6 }}>{connected ? <Wifi size={13} color="var(--ok)" /> : <WifiOff size={13} />} {connected ? "Live" : "Reconnecting…"}</span>
            {meta?.user && <span title={meta.name ?? ""}>{meta.user}</span>}
          </div>
        </aside>
        <main className="main">
          {page === "overview" && <Overview onEngine={openEngine} go={go} />}
          {(page === "engines" || page === "engine") && <Engines onEngine={openEngine} />}
          {page === "activity" && <ActivityPage onEngine={openEngine} />}
          {page === "probes" && <Probes onEngine={openEngine} />}
          {page === "configure" && <Configure tab={arg} go={go} />}
          {page === "updates" && <Updates />}
          {page === "alerts" && <Alerts />}
        </main>
      </div>
      {engine && <EngineDrawer name={engine} onClose={closeEngine} />}
    </ToastProvider>
  );
}

function NavItem({ label, icon: Icon, active, onClick, count }: {
  label: string; icon: typeof Gauge; active: boolean; onClick: () => void; count?: string;
}) {
  return (
    <div className={`nav-item ${active ? "active" : ""}`} onClick={onClick}>
      <Icon size={17} /> {label}
      {count && <span className="count" style={count === "new" ? { background: "var(--accent-soft)", color: "var(--accent)" } : undefined}>{count}</span>}
    </div>
  );
}

function safeHost(url: string): string {
  try { return new URL(url).host; } catch { return url; }
}
