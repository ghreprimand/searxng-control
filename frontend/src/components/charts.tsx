import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Bucket } from "../api";
import { clock, dateTime } from "../format";

/** Success-ratio sparkline: bars per hour, colored by ratio, gaps for no traffic. */
export function Sparkline({ values, height = 26 }: { values: (number | null)[] | null; height?: number }) {
  if (!values || values.length === 0) return null;
  const w = 100 / values.length;
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" width="100%" height={height} style={{ display: "block" }}>
      {values.map((v, i) => {
        if (v == null) return <rect key={i} x={i * w + 0.4} y={height - 2} width={w - 0.8} height={2} rx={0.6} fill="#232c3d" />;
        const h = Math.max(3, v * (height - 2));
        const color = v >= 0.8 ? "var(--ok)" : v >= 0.4 ? "var(--warn)" : "var(--bad)";
        return <rect key={i} x={i * w + 0.4} y={height - h} width={w - 0.8} height={h} rx={0.8} fill={color} opacity={0.85} />;
      })}
    </svg>
  );
}

/** Donut ring with a big number in the middle. */
export function Ring({ value, total, color, size = 88, label }: { value: number; total: number; color: string; size?: number; label?: ReactNode }) {
  const r = size / 2 - 7;
  const c = 2 * Math.PI * r;
  const frac = total ? value / total : 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="hero-ring">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1f2838" strokeWidth={9} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={9} strokeLinecap="round"
        strokeDasharray={`${c * frac} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} style={{ transition: "stroke-dasharray .6s" }} />
      <text x="50%" y="47%" textAnchor="middle" dominantBaseline="middle" fill="var(--text)" fontSize={size * 0.26} fontWeight={700}>{value}/{total}</text>
      <text x="50%" y="70%" textAnchor="middle" dominantBaseline="middle" fill="var(--muted)" fontSize={size * 0.12}>{label}</text>
    </svg>
  );
}

/** Track an element's rendered width so SVGs draw at real pixels (no stretched text). */
function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => setW(Math.round(entries[0].contentRect.width)));
    ro.observe(el);
    setW(Math.round(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** Stacked hourly bars: searches (bg) with blocks/errors overlaid. */
export function ActivityChart({ data, height = 190, daily }: { data: Bucket[]; height?: number; daily?: boolean }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const max = useMemo(() => Math.max(1, ...data.map((d) => Math.max(d.searches, d.blocks + d.errors))), [data]);
  const W = Math.max(width, 1), H = height, padB = 22, padT = 8;
  const bw = W / data.length;
  const y = (v: number) => H - padB - (v / max) * (H - padB - padT);
  // ~90px per time label keeps them readable on any width.
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor(W / 90))));
  const barW = Math.min(bw * 0.64, 28);
  const overW = Math.min(bw * 0.4, 16);
  return (
    <div className="tooltip-host" ref={ref} onMouseLeave={() => setHover(null)} style={{ height: H }}>
      {width > 0 && <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display: "block" }}>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={0} x2={W} y1={y(max * f)} y2={y(max * f)} stroke="#1c2433" strokeDasharray="3 5" />
        ))}
        {data.map((d, i) => {
          const x = i * bw;
          const errH = (d.errors / max) * (H - padB - padT);
          const blkH = (d.blocks / max) * (H - padB - padT);
          return (
            <g key={d.t} onMouseEnter={() => setHover(i)}>
              <rect x={x} y={0} width={bw} height={H} fill={hover === i ? "rgba(94,179,255,0.06)" : "transparent"} />
              <rect x={x + (bw - barW) / 2} y={y(d.searches)} width={barW} height={H - padB - y(d.searches)} rx={3} fill="url(#gSearch)" />
              {d.blocks > 0 && <rect x={x + (bw - overW) / 2} y={H - padB - blkH} width={overW} height={blkH} rx={2} fill="var(--block)" />}
              {d.errors > 0 && <rect x={x + (bw - overW) / 2} y={H - padB - blkH - errH} width={overW} height={errH} rx={2} fill="var(--warn)" opacity={0.9} />}
              {i % labelEvery === 0 && (
                <text x={Math.min(Math.max(x + bw / 2, 24), W - 24)} y={H - 6} textAnchor="middle" fill="var(--muted)" fontSize={11}>
                  {daily ? new Date(d.t * 1000).toLocaleDateString([], { weekday: "short" }) : clock(d.t)}
                </text>
              )}
            </g>
          );
        })}
        <defs>
          <linearGradient id="gSearch" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#5eb3ff" stopOpacity={0.85} />
            <stop offset="1" stopColor="#8b8cff" stopOpacity={0.35} />
          </linearGradient>
        </defs>
      </svg>}
      {hover != null && data[hover] && (
        <div className="chart-tip" style={{ left: `${((hover + 0.5) / data.length) * 100}%`, top: 10 }}>
          <div className="strong">{dateTime(data[hover].t)}</div>
          <div>~{data[hover].searches} searches · {data[hover].requests} engine requests</div>
          <div style={{ color: "var(--block)" }}>{data[hover].blocks} blocks</div>
          <div style={{ color: "var(--warn)" }}>{data[hover].errors} other errors</div>
        </div>
      )}
    </div>
  );
}

/** Engine x time heatmap of block events. */
export function Heatmap({ rows, buckets, start, bucketS, onPick }: {
  rows: { engine: string; cells: number[]; total: number }[]; buckets: number; start: number; bucketS: number; onPick?: (engine: string) => void;
}) {
  const [hover, setHover] = useState<{ r: number; c: number } | null>(null);
  const max = Math.max(1, ...rows.flatMap((r) => r.cells));
  const cols = `160px repeat(${buckets}, minmax(4px, 1fr)) 48px`;
  return (
    <div className="tooltip-host" onMouseLeave={() => setHover(null)}>
      <div className="heat" style={{ gridTemplateColumns: cols }}>
        {rows.map((r, ri) => (
          <HeatRow key={r.engine} row={r} ri={ri} max={max} setHover={setHover} onPick={onPick} />
        ))}
        <div />
        {Array.from({ length: buckets }, (_, i) => (
          <div key={i} className="tiny muted" style={{ textAlign: "center", overflow: "visible", whiteSpace: "nowrap" }}>
            {i % Math.ceil(buckets / 6) === 0 ? (bucketS >= 86400 ? new Date((start + i * bucketS) * 1000).toLocaleDateString([], { month: "short", day: "numeric" }) : clock(start + i * bucketS)) : ""}
          </div>
        ))}
        <div />
      </div>
      {hover && rows[hover.r] && (
        <div className="chart-tip" style={{ left: `calc(160px + (100% - 208px) * ${(hover.c + 0.5) / buckets})`, top: hover.r * 21 }}>
          <b>{rows[hover.r].engine}</b> · {rows[hover.r].cells[hover.c]} block events
          <div className="muted">{dateTime(start + hover.c * bucketS)} – {clock(start + (hover.c + 1) * bucketS)}</div>
        </div>
      )}
    </div>
  );
}

function HeatRow({ row, ri, max, setHover, onPick }: {
  row: { engine: string; cells: number[]; total: number }; ri: number; max: number;
  setHover: (h: { r: number; c: number } | null) => void; onPick?: (e: string) => void;
}) {
  return (
    <>
      <div className="heat-label" style={{ cursor: onPick ? "pointer" : undefined }} onClick={() => onPick?.(row.engine)}>{row.engine}</div>
      {row.cells.map((v, ci) => (
        <div key={ci} className="heat-cell" onMouseEnter={() => setHover({ r: ri, c: ci })}
          style={v ? { background: `rgba(251, 113, 133, ${0.18 + 0.82 * Math.sqrt(v / max)})` } : undefined} />
      ))}
      <div className="tiny muted num">{row.total}</div>
    </>
  );
}

/** Horizontal bar list (e.g. error kinds). */
export function BarList({ items }: { items: { label: string; value: number; color: string; sub?: string }[] }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="grid" style={{ gap: 10 }}>
      {items.map((i) => (
        <div key={i.label}>
          <div className="row small" style={{ justifyContent: "space-between" }}>
            <span><i style={{ display: "inline-block", width: 8, height: 8, borderRadius: 3, background: i.color, marginRight: 8 }} />{i.label}</span>
            <span className="muted">{i.sub} <b style={{ color: "var(--text)" }}>{i.value}</b></span>
          </div>
          <div className="progress" style={{ marginTop: 5 }}><div style={{ width: `${(i.value / max) * 100}%`, background: i.color }} /></div>
        </div>
      ))}
    </div>
  );
}
