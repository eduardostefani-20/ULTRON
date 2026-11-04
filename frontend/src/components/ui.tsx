"use client";

import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from "lucide-react";
import Link from "next/link";
import { Fragment, type ReactNode, useEffect } from "react";

import { pt } from "@/lib/format";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export function Card({ children, className, title, action, subtitle }: {
  children: ReactNode; className?: string; title?: ReactNode; action?: ReactNode; subtitle?: ReactNode;
}) {
  return (
    <section className={cx("rounded-2xl border border-line bg-surface/80 backdrop-blur-sm p-4 fade-up", className)}>
      {(title || action) && (
        <header className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold tracking-wide text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

type BtnVariant = "primary" | "ghost" | "danger" | "outline";
export function Button({ children, onClick, variant = "outline", disabled, busy, className, type = "button", title }: {
  children: ReactNode; onClick?: () => void; variant?: BtnVariant; disabled?: boolean; busy?: boolean;
  className?: string; type?: "button" | "submit"; title?: string;
}) {
  const styles: Record<BtnVariant, string> = {
    primary: "bg-lime text-lime-ink hover:bg-lime-2 font-semibold",
    outline: "border border-line-strong text-ink hover:border-lime/60 hover:text-lime",
    ghost: "text-ink-2 hover:text-ink hover:bg-surface-3",
    danger: "border border-critical/50 text-critical hover:bg-critical/10",
  };
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled || busy}
      className={cx("inline-flex min-h-9 items-center justify-center gap-2 rounded-xl px-3.5 py-2 text-sm transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-lime",
        styles[variant], className)}>
      {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

const TONE: Record<string, string> = {
  good: "bg-good/10 text-good border-good/30",
  warning: "bg-warning/10 text-warning border-warning/30",
  serious: "bg-serious/10 text-serious border-serious/30",
  critical: "bg-critical/10 text-critical border-critical/30",
  info: "bg-info/10 text-info border-info/30",
  lime: "bg-lime/10 text-lime border-lime/30",
  neutral: "bg-surface-3 text-ink-2 border-line-strong",
};

export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: string; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium",
      TONE[tone] ?? TONE.neutral, className)}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  COMPLETED: "good", DONE: "good", completed: "good", published: "good", resolved: "good", active: "good", approved: "good",
  ok: "good", pass: "good", evaluated: "lime",
  RUNNING: "info", PLANNING: "info", REVIEWING: "info", RECEIVED: "neutral", running: "info", developing: "info",
  testing: "info", evaluating: "info", queued: "neutral", proposed: "neutral", PENDING: "neutral",
  WAITING_APPROVAL: "warning", awaiting_approval: "warning", pending: "warning", pending_approval: "warning",
  interrupted: "warning", partial: "warning", medium: "warning", low: "info",
  FAILED: "critical", failed: "critical", fail: "critical", rejected: "serious", rolled_back: "serious",
  CANCELLED: "neutral", cancelled: "neutral", SKIPPED: "neutral", disabled: "neutral", ignored: "neutral",
  high: "serious", critical: "critical", info: "neutral", open: "warning",
};

export function StatusPill({ status, label }: { status?: string | null; label?: string }) {
  const tone = STATUS_TONE[status ?? ""] ?? "neutral";
  const Icon = tone === "good" ? CheckCircle2 : tone === "critical" ? XCircle : tone === "warning" || tone === "serious"
    ? AlertTriangle : Info;
  return (
    <Badge tone={tone}>
      <Icon className="h-3 w-3" aria-hidden />
      {label ?? pt(status)}
    </Badge>
  );
}

export function Stat({ label, value, hint, accent, href }: {
  label: string; value: ReactNode; hint?: ReactNode; accent?: boolean; href?: string;
}) {
  const body = (
    <div className={cx("rounded-2xl border bg-surface/80 p-4 transition-colors", accent ? "border-lime/40 glow" : "border-line",
      href && "hover:border-lime/50")}>
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className={cx("mt-1 text-2xl font-semibold tabular-nums", accent ? "text-lime" : "text-ink")}>{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-2">{hint}</div>}
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-line px-4 py-8 text-center">
      {icon}
      <p className="text-sm font-medium text-ink-2">{title}</p>
      {children && <div className="max-w-md text-xs text-muted">{children}</div>}
    </div>
  );
}

export function Spinner({ label = "Carregando…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}
    </div>
  );
}

export function ErrorNote({ error }: { error?: string | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-xl border border-critical/40 bg-critical/10 px-3 py-2 text-sm text-critical">
      <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> <span className="min-w-0 break-words">{error}</span>
    </div>
  );
}

export function Note({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warning" | "good" }) {
  const Icon = tone === "warning" ? AlertTriangle : tone === "good" ? CheckCircle2 : Info;
  return (
    <div className={cx("flex items-start gap-2 rounded-xl border px-3 py-2 text-sm", TONE[tone])}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> <div className="min-w-0">{children}</div>
    </div>
  );
}

export function Sheet({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true">
      <button aria-label="Fechar" className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className={cx("relative max-h-[92dvh] w-full overflow-y-auto rounded-t-3xl border border-line bg-surface p-4 sm:rounded-3xl fade-up",
        wide ? "sm:max-w-4xl" : "sm:max-w-xl")}>
        <div className="sticky -top-4 z-10 -mx-4 -mt-4 mb-3 flex items-center justify-between gap-2 border-b border-line bg-surface px-4 py-3">
          <h3 className="min-w-0 truncate text-base font-semibold">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-1.5 text-ink-2 hover:bg-surface-3" aria-label="Fechar">
            <X className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("whitespace-nowrap rounded-xl px-3 py-1.5 text-sm transition-colors",
            value === t.id ? "bg-lime/15 text-lime border border-lime/40" : "border border-transparent text-ink-2 hover:text-ink hover:bg-surface-3")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink-2">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-muted " +
  "focus:border-lime/60 focus:outline-none focus:ring-2 focus:ring-lime/20";

export function Toggle({ checked, onChange, label, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label?: string; disabled?: boolean;
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx("relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors disabled:opacity-50",
        checked ? "border-lime/60 bg-lime/30" : "border-line-strong bg-surface-3")}>
      <span className={cx("inline-block h-4 w-4 rounded-full transition-transform", checked ? "translate-x-6 bg-lime" : "translate-x-1 bg-muted")} />
    </button>
  );
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-[11px] uppercase tracking-wider text-muted">{k}</dt>
          <dd className="break-words text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PageHeader({ title, subtitle, actions, icon }: {
  title: string; subtitle?: ReactNode; actions?: ReactNode; icon?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight sm:text-2xl">{icon}{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ markdown seguro (sem innerHTML)

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const rx = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = rx.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const k = `${keyBase}-${i++}`;
    if (tok.startsWith("`")) out.push(<code key={k}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("**")) out.push(<strong key={k}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("[")) {
      const label = tok.slice(1, tok.indexOf("]"));
      out.push(<a key={k} href={m[2]} target="_blank" rel="noopener noreferrer nofollow">{label}</a>);
    } else out.push(<em key={k}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const lines = (text || "").replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++;
      blocks.push(<pre key={key++}><code>{buf.join("\n")}</code></pre>);
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      const lvl = Math.min(3, h[1].length);
      const content = inline(h[2], `h${key}`);
      blocks.push(lvl === 1 ? <h1 key={key++}>{content}</h1> : lvl === 2 ? <h2 key={key++}>{content}</h2> : <h3 key={key++}>{content}</h3>);
      i++;
      continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      const items: ReactNode[] = [];
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
        items.push(<li key={i}>{inline(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, ""), `li${i}`)}</li>);
        i++;
      }
      blocks.push(ordered ? <ol key={key++}>{items}</ol> : <ul key={key++}>{items}</ul>);
      continue;
    }
    if (line.startsWith(">")) {
      blocks.push(<blockquote key={key++}>{inline(line.replace(/^>\s?/, ""), `q${i}`)}</blockquote>);
      i++;
      continue;
    }
    if (/^\|.*\|\s*$/.test(line)) {
      const rows: string[][] = [];
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) {
        if (!/^\|[\s:|-]+\|\s*$/.test(lines[i])) rows.push(lines[i].trim().slice(1, -1).split("|").map((c) => c.trim()));
        i++;
      }
      blocks.push(
        <table key={key++}><tbody>{rows.map((r, ri) => (
          <tr key={ri}>{r.map((c, ci) => ri === 0 ? <th key={ci}>{inline(c, `t${ri}${ci}`)}</th> : <td key={ci}>{inline(c, `t${ri}${ci}`)}</td>)}</tr>
        ))}</tbody></table>,
      );
      continue;
    }
    if (/^---+\s*$/.test(line)) {
      blocks.push(<hr key={key++} />);
      i++;
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*([-*+]|\d+[.)])\s+|>|\|)/.test(lines[i])) para.push(lines[i++]);
    blocks.push(<p key={key++}>{para.map((p, pi) => <Fragment key={pi}>{pi > 0 && <br />}{inline(p, `p${key}-${pi}`)}</Fragment>)}</p>);
  }
  return <div className="prose-ultron text-sm text-ink">{blocks}</div>;
}

export function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-xl border border-line bg-[#040914] p-3 text-[11px] leading-relaxed text-ink-2">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
