"use client";

import { Dna, Users } from "lucide-react";
import { useState } from "react";

import Shell from "@/components/Shell";
import { Badge, Button, Card, ErrorNote, Field, JsonBlock, Markdown, Note, PageHeader, cx, inputCls } from "@/components/ui";
import { post } from "@/lib/api";
import { usd } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";

type Mode = { id: string; name: string; description: string };
type Result = { mode: string; answer: string; cost_usd: number; models: string[]; details: Record<string, unknown>;
  sources: { title?: string; url: string }[] };

function Council() {
  const modes = useApi<Mode[]>("/api/council/modes");
  const [mode, setMode] = useState("COUNCIL");
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Result | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const act = useAction();

  async function run() {
    setRes(null);
    setCreated(null);
    const r = await act.run(() => post<Result>("/api/council", { question: q, mode }));
    if (r) setRes(r);
  }

  async function propose() {
    const r = await act.run(() => post<{ code: string }>("/api/evolution/proposals/from-engineering",
      { question: q, decision_record: res?.details.decision_record }));
    if (r) setCreated(r.code);
  }

  const members = (res?.details.members as { member: string; model: string; answer: string }[]) || [];
  const critique = res?.details.critique as Record<string, unknown> | undefined;
  return (
    <>
      <PageHeader icon={<Users className="h-6 w-6 text-lime" />} title="Conselho de IAs"
        subtitle="Várias inteligências analisam de forma independente; divergências e evidências ficam registradas." />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Modo" className="lg:col-span-1">
          <div className="space-y-2">
            {(modes.data || []).map((m) => (
              <button key={m.id} onClick={() => setMode(m.id)}
                className={cx("w-full rounded-xl border p-3 text-left transition-colors", mode === m.id ? "border-lime/50 bg-lime/10" : "border-line hover:border-line-strong")}>
                <div className={cx("text-sm font-medium", mode === m.id && "text-lime")}>{m.name}</div>
                <div className="mt-0.5 text-xs text-ink-2">{m.description}</div>
              </button>
            ))}
          </div>
        </Card>
        <div className="min-w-0 space-y-4 lg:col-span-2">
          <Card title="Pergunta ou decisão">
            <Field label="O que o Conselho deve analisar?">
              <textarea className={cx(inputCls, "min-h-28")} value={q} onChange={(e) => setQ(e.target.value)}
                placeholder="Ex.: Qual a melhor estratégia para reduzir os custos do ULTRON sem perder qualidade?" />
            </Field>
            <div className="mt-3 flex items-center gap-2">
              <Button variant="primary" onClick={run} busy={act.busy} disabled={q.trim().length < 3}>Convocar</Button>
              {act.busy && <span className="text-xs text-muted">Os modelos estão deliberando — pode levar alguns minutos.</span>}
            </div>
            <div className="mt-3"><ErrorNote error={act.error} /></div>
          </Card>
          {res && (
            <>
              <Card title="Resposta consolidada" action={<Badge tone="lime">{usd(res.cost_usd, 5)}</Badge>}
                subtitle={res.models.length ? `Modelos: ${Array.from(new Set(res.models)).join(", ")}` : undefined}>
                <Markdown text={res.answer} />
                {res.mode === "COUNCIL" && <div className="mt-3"><Note>{String(res.details.note)} Diversidade: {String(res.details.diversity)}.</Note></div>}
                {res.mode === "ENGINEERING" && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button onClick={propose} busy={act.busy}><Dna className="h-4 w-4" /> Criar proposta de evolução</Button>
                    {created && <span className="text-sm text-lime">Proposta {created} criada.</span>}
                  </div>
                )}
              </Card>
              {members.length > 0 && (
                <Card title="Respostas independentes">
                  <div className="space-y-2">
                    {members.map((m) => (
                      <details key={m.member} className="rounded-xl border border-line p-3">
                        <summary className="cursor-pointer text-sm">Membro {m.member} <span className="text-xs text-muted">· {m.model}</span></summary>
                        <div className="mt-2"><Markdown text={m.answer} /></div>
                      </details>
                    ))}
                  </div>
                </Card>
              )}
              {critique && (
                <Card title="Crítica e divergências" subtitle={critique.model ? `crítico: ${String(critique.model)}` : undefined}>
                  {Array.isArray(critique.consensus) && critique.consensus.length > 0 && (
                    <><h4 className="mb-1 text-xs font-semibold uppercase text-muted">Consenso</h4>
                      <ul className="mb-3 list-disc pl-5 text-sm">{(critique.consensus as string[]).map((x, i) => <li key={i}>{x}</li>)}</ul></>
                  )}
                  {Array.isArray(critique.divergences) && critique.divergences.length > 0 && (
                    <><h4 className="mb-1 text-xs font-semibold uppercase text-muted">Divergências registradas</h4>
                      <ul className="mb-3 space-y-2">{(critique.divergences as { topic: string; positions?: Record<string, string>; assessment?: string }[]).map((d, i) => (
                        <li key={i} className="rounded-xl border border-line p-2 text-sm"><div className="font-medium">{d.topic}</div>
                          {d.positions && <ul className="mt-1 text-xs text-ink-2">{Object.entries(d.positions).map(([k, v]) => <li key={k}><b>{k}:</b> {v}</li>)}</ul>}
                          {d.assessment && <p className="mt-1 text-xs text-muted">Avaliação do crítico: {d.assessment}</p>}</li>))}</ul></>
                  )}
                  {Array.isArray(critique.errors) && critique.errors.length > 0 && (
                    <><h4 className="mb-1 text-xs font-semibold uppercase text-muted">Erros apontados</h4>
                      <ul className="mb-3 list-disc pl-5 text-sm">{(critique.errors as string[]).map((x, i) => <li key={i}>{x}</li>)}</ul></>
                  )}
                  <details><summary className="cursor-pointer text-xs text-muted">dados completos</summary><JsonBlock value={critique} /></details>
                </Card>
              )}
              {res.mode === "ENGINEERING" && (
                <Card title="Registro de decisão técnica"><JsonBlock value={res.details.decision_record} /></Card>
              )}
              {res.sources.length > 0 && (
                <Card title="Fontes">
                  <ol className="list-decimal space-y-1 pl-5 text-sm">
                    {res.sources.map((s, i) => <li key={i}><a href={s.url} target="_blank" rel="noopener noreferrer nofollow" className="text-lime underline">{s.title || s.url}</a></li>)}
                  </ol>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}

export default function Page() {
  return <Shell><Council /></Shell>;
}
