import { useEffect, useState } from "react";
import { CheckCircle2, RotateCcw, ShieldCheck } from "lucide-react";
import { api, type ApplyResult, type ConfigPatch } from "../api";
import { Button, Callout, DiffView, Loading, Modal, useToast } from "./ui";

/**
 * Review -> apply -> verify flow shared by every settings editor.
 * Pass either a structured `patch` or a full `raw` settings.yml text.
 */
export function ApplyFlow({ patch, raw, title = "Review changes", onClose, onApplied }: {
  patch?: ConfigPatch; raw?: string; title?: string; onClose: () => void; onApplied?: (r: ApplyResult) => void;
}) {
  const toast = useToast();
  const [diff, setDiff] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<"review" | "applying" | "done">("review");
  const [result, setResult] = useState<ApplyResult | null>(null);

  useEffect(() => {
    const run = async () => {
      try {
        if (raw !== undefined) {
          const r = await api.post<{ diff: string }>("/config/raw/preview", { text: raw });
          setDiff(r.diff);
        } else {
          const r = await api.post<{ diff: string; note: string }>("/config/preview", patch);
          setDiff(r.diff);
          setNote(r.note);
        }
      } catch (e) {
        setError((e as Error).message);
      }
    };
    run();
  }, [patch, raw]);

  const apply = async () => {
    setPhase("applying");
    try {
      const r = raw !== undefined
        ? await api.put<ApplyResult>("/config/raw", { text: raw, note: note || "raw edit" })
        : await api.post<ApplyResult>("/config/apply", { ...patch, note: note || undefined });
      setResult(r);
      setPhase("done");
      if (r.ok) toast("ok", <><b>Applied.</b> {r.message} ({r.duration_s}s)</>);
      else toast("bad", <><b>Rolled back.</b> {r.message}</>);
      onApplied?.(r);
    } catch (e) {
      setError((e as Error).message);
      setPhase("review");
    }
  };

  return (
    <Modal
      wide
      title={title}
      onClose={phase === "applying" ? () => {} : onClose}
      footer={
        phase === "review" ? (
          <>
            <Button kind="ghost" onClick={onClose}>Cancel</Button>
            <Button kind="primary" onClick={apply} disabled={!diff || !!error}><ShieldCheck size={15} /> Apply &amp; restart SearXNG</Button>
          </>
        ) : phase === "done" ? <Button kind="primary" onClick={onClose}>Close</Button> : null
      }
    >
      {phase === "review" && (
        <div className="grid" style={{ gap: 14 }}>
          {error && <Callout kind="bad">{error}</Callout>}
          {!error && diff === null && <Loading label="Building preview…" />}
          {diff !== null && (
            <>
              <Callout kind="info">
                A backup is taken first. SearXNG restarts (≈10 s) and is verified with a health check and a test search;
                if it doesn't come back healthy the previous settings are restored automatically.
              </Callout>
              <div className="field">
                <div className="field-label">Change note (kept with the backup)</div>
                <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What and why" />
              </div>
              <DiffView diff={diff} />
            </>
          )}
        </div>
      )}
      {phase === "applying" && <Loading label="Writing settings, restarting SearXNG and verifying…" />}
      {phase === "done" && result && (
        <div className="grid" style={{ gap: 14 }}>
          <Callout kind={result.ok ? "ok" : "bad"} icon={result.ok ? <CheckCircle2 size={18} color="var(--ok)" /> : <RotateCcw size={18} color="var(--bad)" />}>
            <b>{result.message}</b>
            <div className="small subtle">Took {result.duration_s}s{result.backup ? ` · backup ${result.backup}` : ""}</div>
          </Callout>
          {result.log_tail.length > 0 && (
            <div className="card">
              <div className="card-head"><div className="card-title">SearXNG log at failure</div></div>
              <div className="logbox">{result.log_tail.join("\n")}</div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
