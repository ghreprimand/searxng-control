import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, Check, CheckCircle2, Copy, Info, Loader2, X, XCircle } from "lucide-react";
import { STATUS_LABEL } from "../format";

export function StatusPill({ status, label }: { status: string; label?: string }) {
  return (
    <span className={`pill ${status}`}>
      <span className="dot" />
      {label ?? STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function SeverityPill({ severity }: { severity: string }) {
  return <span className={`pill ${severity}`}><span className="dot" />{severity}</span>;
}

export function Card({ title, icon, actions, children, flush, className = "" }: {
  title?: ReactNode; icon?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean; className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title !== undefined && (
        <div className="card-head">
          <div className="card-title">{icon}{title}</div>
          {actions && <div className="card-actions">{actions}</div>}
        </div>
      )}
      <div className={flush ? "card-flush" : "card-body"}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, foot, icon, color }: { label: string; value: ReactNode; foot?: ReactNode; icon?: ReactNode; color?: string }) {
  return (
    <div className="card stat">
      <div className="stat-label">{icon}{label}</div>
      <div className="stat-value" style={color ? { color } : undefined}>{value}</div>
      {foot && <div className="stat-foot">{foot}</div>}
    </div>
  );
}

export function Button({ children, onClick, kind = "", busy, disabled, small, title, type = "button" }: {
  children: ReactNode; onClick?: () => void | Promise<unknown>; kind?: "" | "primary" | "danger" | "ghost"; busy?: boolean;
  disabled?: boolean; small?: boolean; title?: string; type?: "button" | "submit";
}) {
  const [running, setRunning] = useState(false);
  const isBusy = busy || running;
  return (
    <button
      type={type}
      title={title}
      className={`btn ${kind} ${small ? "sm" : ""}`}
      disabled={disabled || isBusy}
      onClick={async () => {
        if (!onClick) return;
        const r = onClick();
        if (r instanceof Promise) {
          setRunning(true);
          try { await r; } finally { setRunning(false); }
        }
      }}
    >
      {isBusy && <Loader2 size={14} className="spin" />}
      {children}
    </button>
  );
}

export function Toggle({ checked, onChange, changed, disabled, title }: {
  checked: boolean; onChange: (v: boolean) => void; changed?: boolean; disabled?: boolean; title?: string;
}) {
  return (
    <label className={`toggle ${changed ? "changed" : ""}`} title={title} onClick={(e) => e.stopPropagation()}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span />
    </label>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void }) {
  return (
    <div className="segmented">
      {options.map((o) => (
        <button key={o.value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, tabs, onChange }: { value: T; tabs: { value: T; label: ReactNode; icon?: ReactNode }[]; onChange: (v: T) => void }) {
  return (
    <div className="tabs">
      {tabs.map((t) => (
        <div key={t.value} className={`tab ${t.value === value ? "on" : ""}`} onClick={() => onChange(t.value)}>{t.icon}{t.label}</div>
      ))}
    </div>
  );
}

export function Modal({ title, onClose, children, footer, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal ${wide ? "wide" : ""}`}>
        <div className="modal-head">
          <div className="modal-title">{title}</div>
          <button className="btn ghost sm" style={{ marginLeft: "auto" }} onClick={onClose}><X size={16} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Drawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="drawer">{children}</div>
    </div>
  );
}

export function Empty({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return <div className="empty">{icon}<div>{children}</div></div>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="loading"><div className="row"><Loader2 size={18} className="spin" /> {label}</div></div>;
}

export function Callout({ kind = "info", children, icon }: { kind?: "info" | "warn" | "bad" | "ok"; children: ReactNode; icon?: ReactNode }) {
  const ic = icon ?? (kind === "ok" ? <CheckCircle2 size={18} color="var(--ok)" /> : kind === "bad" ? <XCircle size={18} color="var(--bad)" />
    : kind === "warn" ? <AlertTriangle size={18} color="var(--warn)" /> : <Info size={18} color="var(--accent)" />);
  return <div className={`callout ${kind}`}>{ic}<div style={{ minWidth: 0 }}>{children}</div></div>;
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <Callout kind="bad"><b>Couldn't load data.</b> <span className="subtle">{error}</span></Callout>;
}

export function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) return <Empty>No differences.</Empty>;
  return (
    <div className="diff">
      {diff.split("\n").map((l, i) => {
        const cls = l.startsWith("+++") || l.startsWith("---") ? "meta" : l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "";
        return <div key={i} className={cls}>{l || " "}</div>;
      })}
    </div>
  );
}

export function ChipList({ values, onChange, placeholder, mono = true }: { values: string[]; onChange: (v: string[]) => void; placeholder?: string; mono?: boolean }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  };
  return (
    <div className="chip-input">
      {values.map((v) => (
        <span key={v} className="chip" style={mono ? undefined : { fontFamily: "var(--sans)" }}>
          {v}
          <button onClick={() => onChange(values.filter((x) => x !== v))} title="Remove"><X size={12} /></button>
        </span>
      ))}
      <input
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } if (e.key === "Backspace" && !draft && values.length) onChange(values.slice(0, -1)); }}
        onBlur={add}
      />
    </div>
  );
}

/* ---------------- toasts ---------------- */
interface Toast { id: number; kind: "ok" | "bad" | "info"; text: ReactNode }
const ToastCtx = createContext<(kind: Toast["kind"], text: ReactNode) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: ReactNode) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "bad" ? 9000 : 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.kind === "ok" ? <CheckCircle2 size={18} /> : t.kind === "bad" ? <XCircle size={18} /> : <Info size={18} />}
            <div style={{ minWidth: 0 }}>{t.text}</div>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setDone(true);
    setTimeout(() => setDone(false), 1500);
  };
  return <button className="btn sm" onClick={copy}>{done ? <Check size={13} /> : <Copy size={13} />}{done ? "Copied" : label}</button>;
}

/** Shows the private-engine token with a copy button and where to paste it. */
export function TokenBox({ token, publicUrl }: { token: string; publicUrl: string }) {
  return (
    <div className="row" style={{ gap: 10 }}>
      <span>Engine token:</span>
      <span className="mono strong" style={{ padding: "3px 8px", background: "var(--bg-2)", borderRadius: 6, border: "1px solid var(--border-2)" }}>{token}</span>
      <CopyButton text={token} />
      <span className="small subtle">Paste it in <a href={`${publicUrl}/preferences`} target="_blank" rel="noreferrer">SearXNG Preferences</a> → General → <i>Engine tokens</i> → Save, on each browser.</span>
    </div>
  );
}
