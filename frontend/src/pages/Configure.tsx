import { useEffect, useMemo, useState } from "react";
import {
  ArchiveRestore, Code2, FileCode2, Globe2, KeyRound, Lock, Plus, Power, Puzzle, RotateCcw, SlidersHorizontal, Trash2,
} from "lucide-react";
import {
  api, type ApplyResult, type ConfigPatch, type Engine, type GeneralSettings, type Hostnames,
} from "../api";
import { ago, dateTime } from "../format";
import { usePoll } from "../hooks";
import { ApplyFlow } from "../components/ApplyFlow";
import { Button, Callout, Card, ChipList, DiffView, Empty, ErrorBox, Loading, Modal, Tabs, Toggle, TokenBox, useToast } from "../components/ui";

type Tab = "general" | "sites" | "api" | "custom" | "raw" | "backups";

interface ConfigResp {
  general: GeneralSettings;
  hostnames: Hostnames;
  file: { path: string; mtime: number; size: number };
  modules: string[];
  custom_engines: Record<string, unknown>[];
  private_token: string | null;
  options: { autocomplete: string[]; favicon_resolver: string[]; safe_search: number[] };
}

export default function Configure({ tab, go }: { tab: string | null; go: (r: string) => void }) {
  const t = (tab as Tab) || "general";
  const { data, error, reload } = usePoll<ConfigResp>("/config", 0);
  const [review, setReview] = useState<{ patch?: ConfigPatch; raw?: string; title?: string } | null>(null);
  const toast = useToast();

  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;

  const restart = async () => {
    const r = await api.post<ApplyResult>("/searxng/restart");
    toast(r.ok ? "ok" : "bad", r.message);
  };
  const onApplied = (r: ApplyResult) => { if (r.ok) reload(); };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Configure</h1>
          <div className="page-sub">Edits go to <span className="mono">{data.file.path}</span> (changed {ago(data.file.mtime)}). Every apply is backed up and verified.</div>
        </div>
        <Button onClick={restart}><Power size={15} /> Restart SearXNG</Button>
      </div>
      <Tabs<Tab> value={t} onChange={(v) => go(`configure/${v}`)} tabs={[
        { value: "general", label: "Search behaviour", icon: <SlidersHorizontal size={14} /> },
        { value: "sites", label: "Site rules", icon: <Globe2 size={14} /> },
        { value: "api", label: "API engines", icon: <KeyRound size={14} /> },
        { value: "custom", label: "Custom engines", icon: <Puzzle size={14} /> },
        { value: "raw", label: "settings.yml", icon: <FileCode2 size={14} /> },
        { value: "backups", label: "Backups", icon: <ArchiveRestore size={14} /> },
      ]} />
      {t === "general" && <GeneralTab cfg={data} onReview={(patch) => setReview({ patch })} />}
      {t === "sites" && <SitesTab cfg={data} onReview={(patch) => setReview({ patch })} />}
      {t === "api" && <ApiTab cfg={data} onReview={(patch) => setReview({ patch })} go={go} />}
      {t === "custom" && <CustomTab cfg={data} onReview={(patch, title) => setReview({ patch, title })} />}
      {t === "raw" && <RawTab onReview={(raw) => setReview({ raw, title: "Review settings.yml" })} />}
      {t === "backups" && <BackupsTab onRestored={reload} />}
      {review && <ApplyFlow patch={review.patch} raw={review.raw} title={review.title} onClose={() => setReview(null)} onApplied={onApplied} />}
    </>
  );
}

/* ---------------- general ---------------- */
const SUSPEND_LABELS: Record<string, string> = {
  SearxEngineCaptcha: "CAPTCHA", SearxEngineAccessDenied: "Access denied (403)", SearxEngineTooManyRequests: "Too many requests (429)",
  cf_SearxEngineCaptcha: "Cloudflare CAPTCHA", cf_SearxEngineAccessDenied: "Cloudflare access denied", recaptcha_SearxEngineCaptcha: "Google reCAPTCHA",
};

function GeneralTab({ cfg, onReview }: { cfg: ConfigResp; onReview: (p: ConfigPatch) => void }) {
  const [g, setG] = useState<GeneralSettings>(cfg.general);
  useEffect(() => setG(cfg.general), [cfg]);
  const changed = useMemo(() => {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(g) as (keyof GeneralSettings)[]) {
      if (k === "suspended_times") {
        const diff = Object.fromEntries(Object.entries(g.suspended_times).filter(([kk, v]) => cfg.general.suspended_times[kk] !== v));
        if (Object.keys(diff).length) out.suspended_times = diff;
      } else if (g[k] !== cfg.general[k]) out[k] = g[k];
    }
    return out;
  }, [g, cfg]);
  const set = <K extends keyof GeneralSettings>(k: K, v: GeneralSettings[K]) => setG({ ...g, [k]: v });

  return (
    <div className="grid" style={{ gap: 16 }}>
      <Card title="Search">
        <div className="form-grid">
          <label className="field"><span className="field-label">Instance name</span>
            <input className="input" value={g.instance_name ?? ""} onChange={(e) => set("instance_name", e.target.value)} /></label>
          <label className="field"><span className="field-label">Autocomplete</span>
            <select className="select" value={g.autocomplete ?? ""} onChange={(e) => set("autocomplete", e.target.value)}>
              {cfg.options.autocomplete.map((o) => <option key={o} value={o}>{o || "off"}</option>)}
            </select><span className="field-help">Suggestions are fetched by the server, not your device.</span></label>
          <label className="field"><span className="field-label">Safe search</span>
            <select className="select" value={g.safe_search ?? 0} onChange={(e) => set("safe_search", Number(e.target.value))}>
              <option value={0}>Off</option><option value={1}>Moderate</option><option value={2}>Strict</option>
            </select></label>
          <label className="field"><span className="field-label">Default language</span>
            <input className="input mono" value={g.default_lang ?? ""} onChange={(e) => set("default_lang", e.target.value)} />
            <span className="field-help">“auto” follows the browser. Region codes like en-US silently skip engines without that region.</span></label>
          <label className="field"><span className="field-label">Favicons</span>
            <select className="select" value={g.favicon_resolver ?? ""} onChange={(e) => set("favicon_resolver", e.target.value)}>
              {cfg.options.favicon_resolver.map((o) => <option key={o} value={o}>{o || "off"}</option>)}
            </select></label>
        </div>
      </Card>
      <Card title="Network">
        <div className="form-grid">
          <label className="field"><span className="field-label">Engine timeout (s)</span>
            <input className="input" type="number" step="0.5" value={g.request_timeout ?? ""} onChange={(e) => set("request_timeout", Number(e.target.value))} />
            <span className="field-help">How long a search waits for slow engines.</span></label>
          <label className="field"><span className="field-label">Max timeout for API clients (s)</span>
            <input className="input" type="number" step="0.5" value={g.max_request_timeout ?? ""} onChange={(e) => set("max_request_timeout", Number(e.target.value))} /></label>
        </div>
        <div className="hr" />
        <div className="grid" style={{ gap: 12 }}>
          <ToggleRow label="Image proxy" help="Thumbnails are fetched by the server so sites never see your device." v={!!g.image_proxy} on={(v) => set("image_proxy", v)} />
          <ToggleRow label="Open results in new tab" v={!!g.results_on_new_tab} on={(v) => set("results_on_new_tab", v)} />
          <ToggleRow label="Infinite scroll" v={!!g.infinite_scroll} on={(v) => set("infinite_scroll", v)} />
          <ToggleRow label="Center results" v={!!g.center_alignment} on={(v) => set("center_alignment", v)} />
        </div>
      </Card>
      <Card title="Suspension after a block">
        <Callout kind="info">When an engine answers with a CAPTCHA/403/429, SearXNG stops using it for this long. Shorter recovers faster; longer is gentler on your IP's reputation.</Callout>
        <div className="form-grid" style={{ marginTop: 14 }}>
          {Object.entries(g.suspended_times).map(([k, v]) => (
            <label key={k} className="field"><span className="field-label">{SUSPEND_LABELS[k] ?? k}</span>
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <input className="input" type="number" step="60" min={0} value={v} onChange={(e) => set("suspended_times", { ...g.suspended_times, [k]: Number(e.target.value) })} />
                <span className="small muted" style={{ whiteSpace: "nowrap" }}>{Math.round(v / 60)} min</span>
              </div></label>
          ))}
        </div>
      </Card>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <Button kind="ghost" disabled={!Object.keys(changed).length} onClick={() => setG(cfg.general)}>Reset</Button>
        <Button kind="primary" disabled={!Object.keys(changed).length} onClick={() => onReview({ general: changed })}>Review &amp; apply</Button>
      </div>
    </div>
  );
}

function ToggleRow({ label, help, v, on }: { label: string; help?: string; v: boolean; on: (v: boolean) => void }) {
  return (
    <div className="row" style={{ justifyContent: "space-between" }}>
      <div><div className="strong">{label}</div>{help && <div className="small muted">{help}</div>}</div>
      <Toggle checked={v} onChange={on} />
    </div>
  );
}

/* ---------------- site rules ---------------- */
function toPattern(v: string): string {
  const s = v.trim();
  if (/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(s)) return `(.*\\.)?${s.replace(/\./g, "\\.")}$`;
  return s;
}

function SitesTab({ cfg, onReview }: { cfg: ConfigResp; onReview: (p: ConfigPatch) => void }) {
  const [h, setH] = useState<Hostnames>(cfg.hostnames);
  useEffect(() => setH(cfg.hostnames), [cfg]);
  const dirty = JSON.stringify(h) !== JSON.stringify(cfg.hostnames);
  const list = (k: "remove" | "low_priority" | "high_priority", title: string, help: string, color: string) => (
    <Card title={<span style={{ color }}>{title}</span>}>
      <div className="small muted" style={{ marginBottom: 10 }}>{help}</div>
      <ChipList values={h[k]} onChange={(v) => setH({ ...h, [k]: v.map(toPattern) })} placeholder="example.com or a regex, then Enter" />
    </Card>
  );
  return (
    <div className="grid" style={{ gap: 16 }}>
      <Callout kind="info">Type a plain domain (e.g. <span className="mono">pinterest.com</span>) and it becomes a regex matching the domain and its subdomains. Advanced: enter any Python regex matched against the result's hostname.</Callout>
      <div className="grid g3">
        {list("remove", "Remove", "Never show results from these sites.", "var(--bad)")}
        {list("low_priority", "Push down", "Rank these sites lower.", "var(--warn)")}
        {list("high_priority", "Boost", "Rank these sites higher.", "var(--ok)")}
      </div>
      <Card title="Rewrite hostnames" actions={<Button small onClick={() => setH({ ...h, replace: [...h.replace, { pattern: "", replacement: "" }] })}><Plus size={13} /> Add rule</Button>}>
        <div className="small muted" style={{ marginBottom: 10 }}>e.g. send <span className="mono">(.*\.)?reddit\.com$</span> → <span className="mono">old.reddit.com</span>, or YouTube to an Invidious instance.</div>
        {h.replace.length === 0 ? <Empty>No rewrite rules.</Empty> : h.replace.map((r, i) => (
          <div key={i} className="row" style={{ marginBottom: 8, flexWrap: "nowrap" }}>
            <input className="input mono" placeholder="pattern" value={r.pattern} onChange={(e) => setH({ ...h, replace: h.replace.map((x, j) => j === i ? { ...x, pattern: e.target.value } : x) })} />
            <span className="muted">→</span>
            <input className="input mono" placeholder="replacement host" value={r.replacement} onChange={(e) => setH({ ...h, replace: h.replace.map((x, j) => j === i ? { ...x, replacement: e.target.value } : x) })} />
            <Button small kind="ghost" onClick={() => setH({ ...h, replace: h.replace.filter((_, j) => j !== i) })}><Trash2 size={13} /></Button>
          </div>
        ))}
      </Card>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <Button kind="ghost" disabled={!dirty} onClick={() => setH(cfg.hostnames)}>Reset</Button>
        <Button kind="primary" disabled={!dirty} onClick={() => onReview({ hostnames: h })}>Review &amp; apply</Button>
      </div>
    </div>
  );
}

/* ---------------- API engines ---------------- */
const API_INFO: Record<string, { blurb: string; price: string; signup: string }> = {
  braveapi: { blurb: "Brave's own 30B-page index via the official API. Never CAPTCHAs.", price: "$5 / 1,000 queries · $5 free credit each month (~1,000 searches)", signup: "https://brave.com/search/api/" },
  exaapi: { blurb: "Exa neural search - good for research-y and AI-tool queries.", price: "Pay as you go; free starter credit", signup: "https://exa.ai/" },
  marginalia: { blurb: "Independent small-web index; surfaces non-commercial sites.", price: "Free key on request", signup: "https://about.marginalia-search.com/article/api/" },
  jina: { blurb: "Jina search API (returns LLM-friendly content).", price: "Free tier, then pay as you go", signup: "https://jina.ai/" },
  "yandex api": { blurb: "Yandex Search API via Yandex Cloud.", price: "Paid (Yandex Cloud)", signup: "https://yandex.cloud/" },
};

function ApiTab({ cfg, onReview, go }: { cfg: ConfigResp; onReview: (p: ConfigPatch) => void; go: (r: string) => void }) {
  const { data } = usePoll<{ engines: Engine[]; public_url: string }>("/engines", 0);
  const [drafts, setDrafts] = useState<Record<string, { api_key?: string; enabled?: boolean; private?: boolean }>>({});
  if (!data) return <Loading />;
  const apiEngines = data.engines.filter((e) => e.requires_api_key)
    .sort((a, b) => Number(!!API_INFO[b.name]) - Number(!!API_INFO[a.name]) || a.name.localeCompare(b.name));

  return (
    <div className="grid" style={{ gap: 16 }}>
      <Callout kind="info">
        API engines use an official, paid-or-keyed API instead of scraping, so they don't get CAPTCHA'd. Turn on <b>Private</b> to keep
        a paid engine for your own searches only: SearXNG then uses it only when the browser sends the engine token.
        {cfg.private_token && <div style={{ marginTop: 10 }}><TokenBox token={cfg.private_token} publicUrl={data.public_url} /></div>}
      </Callout>
      <div className="grid g2">
        {apiEngines.map((e) => {
          const d = drafts[e.name] ?? {};
          const info = API_INFO[e.name];
          const dirty = Object.keys(d).length > 0;
          const enabled = d.enabled ?? e.enabled;
          return (
            <div key={e.name} className="card card-pad">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div className="strong row" style={{ gap: 8 }}>{e.name}
                  {e.has_api_key ? <span className="badge green">key set</span> : <span className="badge amber">no key</span>}
                  {e.private && <span className="badge purple"><Lock size={10} /> private</span>}
                </div>
                <span className="small muted">{e.categories.join(", ")}</span>
              </div>
              <div className="small subtle" style={{ marginTop: 6 }}>{info?.blurb ?? `Uses the ${e.module} module.`}</div>
              {info && <div className="small" style={{ marginTop: 4 }}><span className="muted">Pricing:</span> {info.price} · <a href={info.signup} target="_blank" rel="noreferrer">get a key</a></div>}
              <div className="row" style={{ marginTop: 12, flexWrap: "nowrap" }}>
                <input className="input mono" type="password" autoComplete="off" placeholder={e.has_api_key ? "•••••• (unchanged)" : "API key"} value={d.api_key ?? ""}
                  onChange={(x) => setDrafts({ ...drafts, [e.name]: { ...d, api_key: x.target.value } })} />
              </div>
              <div className="row" style={{ marginTop: 12, justifyContent: "space-between" }}>
                <label className="row small" style={{ gap: 8 }}><Toggle checked={enabled} onChange={(v) => setDrafts({ ...drafts, [e.name]: { ...d, enabled: v } })} /> Enabled</label>
                <label className="row small" style={{ gap: 8 }}><Toggle checked={d.private ?? e.private} onChange={(v) => setDrafts({ ...drafts, [e.name]: { ...d, private: v } })} /> Private</label>
                <Button small kind="primary" disabled={!dirty || (enabled && !e.has_api_key && !d.api_key)}
                  onClick={() => {
                    const p: Record<string, unknown> = { ...d };
                    if (!d.api_key) delete p.api_key;
                    onReview({ engines: { [e.name]: p } });
                  }}>Review</Button>
              </div>
            </div>
          );
        })}
      </div>
      <Card title="Not listed?" icon={<Code2 size={15} />}>
        <div className="small subtle">Kagi's API, any JSON API and site scrapers can be added as custom engines.</div>
        <div style={{ marginTop: 10 }}><Button small onClick={() => go("configure/custom")}><Plus size={13} /> Add a custom engine</Button></div>
      </Card>
    </div>
  );
}

/* ---------------- custom engines ---------------- */
const TEMPLATES: Record<string, { label: string; yaml: string }> = {
  kagi: { label: "Kagi Search API (paid, $12/1k)", yaml: `name: kagi
engine: kagi
shortcut: kg
categories: [general, web]
api_key: "YOUR-KAGI-API-KEY"
kagi_categ: search
timeout: 4.0
disabled: false
tokens: ["make-this-private-token"]  # optional: only browsers with this token use it
` },
  json: { label: "Any JSON search API", yaml: `name: my json api
engine: json_engine
shortcut: mja
categories: [general]
paging: false
search_url: https://api.example.com/search?q={query}
results_query: results
url_query: url
title_query: title
content_query: snippet
disabled: false
` },
  xpath: { label: "Scrape a site's search page (XPath)", yaml: `name: my site
engine: xpath
shortcut: ms
categories: [general]
search_url: https://example.com/search?q={query}
results_xpath: //div[@class="result"]
url_xpath: .//a/@href
title_xpath: .//a
content_xpath: .//p
disabled: false
` },
  mediawiki: { label: "A MediaWiki site (e.g. a game wiki)", yaml: `name: my wiki
engine: mediawiki
shortcut: mw
categories: [general]
base_url: https://wiki.example.org/
search_type: text
disabled: false
` },
  discourse: { label: "A Discourse forum", yaml: `name: some forum
engine: discourse
shortcut: sf
categories: [general, social media]
base_url: https://forum.example.org
disabled: false
` },
};

function CustomTab({ cfg, onReview }: { cfg: ConfigResp; onReview: (p: ConfigPatch, title?: string) => void }) {
  const [tpl, setTpl] = useState("json");
  const [yaml, setYaml] = useState(TEMPLATES.json.yaml);
  return (
    <div className="grid g-main">
      <Card title="Add engine">
        <div className="grid" style={{ gap: 12 }}>
          <label className="field"><span className="field-label">Start from a template</span>
            <select className="select" value={tpl} onChange={(e) => { setTpl(e.target.value); setYaml(TEMPLATES[e.target.value].yaml); }}>
              {Object.entries(TEMPLATES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select></label>
          <textarea className="textarea mono" style={{ minHeight: 300 }} value={yaml} onChange={(e) => setYaml(e.target.value)} spellCheck={false} />
          <div className="small muted">Must have a unique <span className="mono">name</span> and a valid <span className="mono">engine</span> module ({cfg.modules.length} available in this image). Options per module are in the <a href="https://docs.searxng.org/dev/engines/index.html" target="_blank" rel="noreferrer">SearXNG engine docs</a>.</div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <Button kind="primary" onClick={() => onReview({ add_engine: yaml }, "Add custom engine")}><Plus size={14} /> Review &amp; add</Button>
          </div>
        </div>
      </Card>
      <Card title="Your custom engines" flush>
        {cfg.custom_engines.length === 0 ? <Empty>None yet.</Empty> : cfg.custom_engines.map((e) => (
          <div key={String(e.name)} className="feed-item" style={{ gridTemplateColumns: "1fr auto" }}>
            <div><div className="feed-title">{String(e.name)}</div><div className="feed-detail mono">{String(e.engine)}{e.shortcut ? ` · !${String(e.shortcut)}` : ""}</div></div>
            <Button small kind="danger" onClick={() => onReview({ remove_engine: String(e.name) }, `Remove ${String(e.name)}`)}><Trash2 size={13} /></Button>
          </div>
        ))}
      </Card>
    </div>
  );
}

/* ---------------- raw yaml ---------------- */
function RawTab({ onReview }: { onReview: (raw: string) => void }) {
  const { data, reload } = usePoll<{ text: string }>("/config/raw", 0);
  const [text, setText] = useState<string | null>(null);
  useEffect(() => { if (data) setText(data.text); }, [data]);
  if (!data || text === null) return <Loading />;
  const lines = text.split("\n").length;
  const dirty = text !== data.text;
  return (
    <div className="grid" style={{ gap: 12 }}>
      <Callout kind="warn">Full control. The file is validated (YAML, secret key, json output kept on) and SearXNG is rolled back automatically if it won't start.</Callout>
      <div className="code-editor" style={{ maxHeight: "70vh", overflow: "auto" }}>
        <div className="gutter">{Array.from({ length: lines }, (_, i) => i + 1).join("\n")}</div>
        <textarea value={text} spellCheck={false} rows={lines + 1} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Tab") {
              e.preventDefault();
              const el = e.currentTarget, s = el.selectionStart;
              const v = text.slice(0, s) + "  " + text.slice(el.selectionEnd);
              setText(v);
              requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = s + 2; });
            }
          }} />
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <Button kind="ghost" onClick={() => { reload(); setText(data.text); }} disabled={!dirty}><RotateCcw size={14} /> Revert</Button>
        <Button kind="primary" disabled={!dirty} onClick={() => onReview(text)}>Review &amp; apply</Button>
      </div>
    </div>
  );
}

/* ---------------- backups ---------------- */
function BackupsTab({ onRestored }: { onRestored: () => void }) {
  const { data, reload } = usePoll<{ backups: { name: string; ts: number; reason: string; size: number }[] }>("/backups", 0);
  const [view, setView] = useState<{ name: string; diff: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ApplyResult | null>(null);
  const toast = useToast();
  if (!data) return <Loading />;
  const open = async (name: string) => {
    const r = await api.get<{ name: string; diff: string }>(`/backups/${encodeURIComponent(name)}`);
    setResult(null);
    setView(r);
  };
  const restore = async () => {
    if (!view) return;
    setBusy(true);
    try {
      const r = await api.post<ApplyResult>(`/backups/${encodeURIComponent(view.name)}/restore`);
      setResult(r);
      toast(r.ok ? "ok" : "bad", r.message);
      reload();
      onRestored();
    } catch (e) { toast("bad", (e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Card title="Backups" flush actions={<span className="small muted">taken before every apply · newest 60 kept</span>}>
      {data.backups.length === 0 ? <Empty>No backups yet — one is created on your first apply.</Empty> : (
        <table className="table">
          <thead><tr><th>Taken</th><th>Before change</th><th className="num">Size</th><th /></tr></thead>
          <tbody>
            {data.backups.map((b) => (
              <tr key={b.name} className="clickable" onClick={() => open(b.name)}>
                <td className="small">{dateTime(b.ts)} <span className="muted">({ago(b.ts)})</span></td>
                <td className="small subtle">{b.reason}</td>
                <td className="num small">{(b.size / 1024).toFixed(1)} KB</td>
                <td><Button small kind="ghost">View</Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {view && (
        <Modal wide title={`Restore ${view.name}?`} onClose={() => setView(null)} footer={<>
          <Button kind="ghost" onClick={() => setView(null)}>Close</Button>
          {!result && <Button kind="primary" busy={busy} onClick={restore}><ArchiveRestore size={14} /> Restore this version</Button>}
        </>}>
          {result ? <Callout kind={result.ok ? "ok" : "bad"}>{result.message}</Callout> : (
            <>
              <div className="small muted" style={{ marginBottom: 10 }}>Diff from the current settings to this backup:</div>
              <DiffView diff={view.diff} />
            </>
          )}
        </Modal>
      )}
    </Card>
  );
}
