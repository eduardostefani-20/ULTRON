"use client";

import { useState } from "react";

/* Gráficos leves em SVG. Série única → sem legenda (o título nomeia a série).
   Cor da série validada para o fundo azul-marinho (#6fa312, contraste ≥ 3:1). */

type Point = { label: string; value: number; display?: string };

export function BarChart({ data, height = 160, format = (v: number) => String(v), ariaLabel }: {
  data: Point[]; height?: number; format?: (v: number) => string; ariaLabel: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (!data.length) return <p className="py-6 text-center text-sm text-muted">Sem dados no período.</p>;
  const max = Math.max(...data.map((d) => d.value), 0) || 1;
  const w = 100 / data.length;
  const ticks = [max, max / 2, 0];
  return (
    <div className="relative">
      <div className="flex gap-2">
        <div className="flex flex-col justify-between py-0.5 text-right text-[10px] tabular-nums text-muted" style={{ height }}>
          {ticks.map((t, i) => <span key={i}>{format(t)}</span>)}
        </div>
        <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }} role="img"
          aria-label={ariaLabel} onMouseLeave={() => setHover(null)}>
          {ticks.map((_, i) => (
            <line key={i} x1="0" x2="100" y1={(i / 2) * (height - 1) + 0.5} y2={(i / 2) * (height - 1) + 0.5}
              stroke="var(--color-line)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
          ))}
          {data.map((d, i) => {
            const h = (d.value / max) * (height - 4);
            const gap = Math.min(0.8, w * 0.15);
            return (
              <g key={i} onMouseEnter={() => setHover(i)} onTouchStart={() => setHover(i)}>
                <rect x={i * w} y="0" width={w} height={height} fill="transparent" />
                <rect x={i * w + gap} y={height - h} width={Math.max(0.4, w - 2 * gap)} height={h} rx="0.6"
                  fill={hover === i ? "var(--color-lime)" : "var(--color-series-1)"} />
              </g>
            );
          })}
        </svg>
      </div>
      <div className="mt-1 flex justify-between pl-8 text-[10px] text-muted">
        <span>{data[0].label}</span>
        <span>{data[data.length - 1].label}</span>
      </div>
      {hover !== null && (
        <div className="pointer-events-none absolute top-0 rounded-lg border border-line-strong bg-surface-3 px-2 py-1 text-xs shadow-lg"
          style={{ left: `calc(${Math.min(80, (hover / data.length) * 100)}% + 2rem)` }}>
          <div className="text-muted">{data[hover].label}</div>
          <div className="font-semibold tabular-nums text-ink">{data[hover].display ?? format(data[hover].value)}</div>
        </div>
      )}
    </div>
  );
}

export function HBars({ rows, format }: { rows: { key: string; value: number; extra?: string }[]; format: (v: number) => string }) {
  if (!rows.length) return <p className="py-4 text-center text-sm text-muted">Sem dados.</p>;
  const max = Math.max(...rows.map((r) => r.value), 0) || 1;
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.key}>
          <div className="mb-1 flex justify-between gap-2 text-xs">
            <span className="min-w-0 truncate text-ink-2">{r.key}</span>
            <span className="shrink-0 tabular-nums text-ink">{format(r.value)}{r.extra ? <span className="text-muted"> · {r.extra}</span> : null}</span>
          </div>
          <div className="h-2 rounded-full bg-surface-3">
            <div className="h-2 rounded-full" style={{ width: `${Math.max(2, (r.value / max) * 100)}%`, background: "var(--color-series-1)" }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function LineChart({ points, height = 120, format = (v: number) => v.toFixed(2), ariaLabel }: {
  points: { ts: string; value: number }[]; height?: number; format?: (v: number) => string; ariaLabel: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return <p className="py-6 text-center text-sm text-muted">Histórico insuficiente (aparece após alguns ciclos).</p>;
  const vals = points.map((p) => p.value);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const x = (i: number) => (i / (points.length - 1)) * 100;
  const y = (v: number) => height - 6 - ((v - min) / span) * (height - 12);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(p.value).toFixed(2)}`).join(" ");
  return (
    <div className="relative">
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }} role="img" aria-label={ariaLabel}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          setHover(Math.round(((e.clientX - rect.left) / rect.width) * (points.length - 1)));
        }}>
        <path d={d} fill="none" stroke="var(--color-series-1)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1="0" y2={height} stroke="var(--color-line-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      {hover !== null && points[hover] && (
        <div className="pointer-events-none absolute top-0 rounded-lg border border-line-strong bg-surface-3 px-2 py-1 text-xs"
          style={{ left: `${Math.min(75, x(hover))}%` }}>
          <div className="text-muted">{new Date(points[hover].ts).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</div>
          <div className="font-semibold tabular-nums">{format(points[hover].value)}</div>
        </div>
      )}
    </div>
  );
}

export function Meter({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(1, value));
  const tone = v >= 0.9 ? "var(--color-critical)" : v >= 0.75 ? "var(--color-warning)" : "var(--color-series-1)";
  return (
    <div>
      <div className="h-2.5 rounded-full bg-surface-3" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)} aria-label={label}>
        <div className="h-2.5 rounded-full transition-all" style={{ width: `${Math.max(1.5, v * 100)}%`, background: tone }} />
      </div>
    </div>
  );
}
