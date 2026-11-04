"use client";

import { CheckCircle2, Dna, Pause, Play, Plus, RotateCcw, ShieldCheck, Undo2, XCircle, Zap } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { LineChart } from "@/components/charts";
import Shell from "@/components/Shell";
import {
  Badge, Button, Card, Empty, ErrorNote, Field, JsonBlock, KV, Markdown, Note, PageHeader, Sheet, Spinner, Stat, StatusPill,
  Tabs, Toggle, cx, inputCls,
} from "@/components/ui";
import { get, post } from "@/lib/api";
import { ago, dateTime, num, pct, pt, usd } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";

type Cycle = { id: string; number: number; trigger: string; status: string; phase: string; completed_phases: string[];
  summary: string; cost_usd: number; budget_usd: number; started_at: string; finished_at: string | null; error: string;
  log?: { ts: string; phase: string; message: string }[]; checkpoint?: Record<string, unknown> };
type Status = { enabled: boolean; paused: boolean; interval_minutes: number; auto_publish_low_risk: boolean;
  safety_selftest: { passed: boolean; at: string | null; details: { checks?: { name: string; passed: boolean; detail: string }[] } };
  current_cycle: Cycle | null; last_cycle: Cycle | null; phases: { id: string; label: string }[];
  proposals_by_status: Record<string, number>; pending_approvals: number; open_diagnostics: number;
  scheduler: { running: boolean; jobs: Record<string, { last_run_at: string | null; last_status: string; running: boolean }> };
  sandbox: { isolation: string; capabilities: Record<string, boolean> };
  budget: { evolution_spent_usd: number; evolution_limit_usd: number } };
type Diagnostic = { id: string; category: string; severity: string; title: string; detail: string; suggestion: string; research: string;
  occurrences: number; last_seen_at: string; status: string; evidence: Record<string, unknown> };
type Proposal = { id: string; code: string; title: string; kind: string; strategy: string; source: string; status: string; risk_level: string;
  priority_score: number; cost_usd: number; created_at: string; branch: string; error: string; pr_url: string;
  diff_stats: { files?: number; added?: number; removed?: number } };
type Gate = { name: string; passed: boolean; detail: string; hard: boolean };
type Evaluation = { id: string; verdict: string; gates: Gate[]; baseline: Record<string, number>; candidate: Record<string, number>;
  audit: { approve?: boolean; summary?: string; model?: string; issues?: string[]; independent_provider?: boolean }; risk_level: string;
  scores: Record<string, unknown>; created_at: string };
type ProposalDetail = Proposal & { problem: string; diagnosis: string; objective: string; solution: string; affected_files: string[];
  dependencies: string[]; benefits: string; risks: string; cost_estimate_usd: number; tests_required: string[]; acceptance_criteria: string[];
  rollback_strategy: string; risk_reasons: string[]; changed_files: { path: string; status: string }[]; dev_log: Record<string, unknown>[];
  evaluations: Evaluation[]; sandbox_runs: { id: string; label: string; status: string; duration_ms: number; isolation: Record<string, unknown>;
  stdout_tail: string; created_at: string }[]; publications: Publication[]; approvals: Approval[];
  tests: { baseline?: Record<string, number>; candidate?: Record<string, number> } | null };
type Approval = { id: string; kind: string; target_id: string; risk: string; title: string; summary: string; status: string; created_at: string;
  requested_by: string; decided_by: string };
type Publication = { id: string; proposal_id: string; code?: string; title?: string; mode: string; status: string; risk_level: string;
  merge_sha: string; pushed: boolean; pr_url: string; approved_by: string; published_at: string; rolled_back_at: string | null;
  rollback_reason: string; monitor: Record<string, unknown> };

const SEV: Record<string, string> = { critical: "critical", high: "serious", medium: "warning", low: "info", info: "neutral" };
const RISK: Record<string, string> = { low: "good", medium: "warning", high: "serious" };

function PhaseTrack({ cycle, phases }: { cycle: Cycle; phases: { id: string; label: string }[] }) {
  return (
    <ol className="grid grid-cols-3 gap-1.5 sm:grid-cols-9">
      {phases.map((p) => {
        const done = cycle.completed_phases?.includes(p.id);
        const current = cycle.phase === p.id && cycle.status === "running";
        return (
          <li key={p.id} className={cx("rounded-lg border px-2 py-1.5 text-center text-[11px]",
            done ? "border-lime/40 bg-lime/10 text-lime" : current ? "border-info/50 bg-info/10 text-info" : "border-line text-muted")}>
            {current && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-info pulse-dot" />}{p.label}
          </li>
        );
      })}
    </ol>
  );
}

function Overview({ st, reload }: { st: Status; reload: () => void }) {
  const act = useAction();
  const [pw, setPw] = useState("");
  const [askPw, setAskPw] = useState(false);
  const [selftest, setSelftest] = useState<Status["safety_selftest"]["details"] | null>(null);
  const cycles = useApi<Cycle[]>("/api/evolution/cycles", 8000);
  const history = useApi<{ ts: string; value: number }[]>("/api/evolution/history?name=kpi.llm_error_rate");
  const [cycleSel, setCycleSel] = useState<Cycle | null>(null);
  const cycle = st.current_cycle || st.last_cycle;
  const ps = st.proposals_by_status;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Estado" value={!st.enabled ? "Desativada" : st.paused ? "Pausada" : "Contínua"} accent={st.enabled && !st.paused}
          hint={`ciclo a cada ${Math.round(st.interval_minutes / 60)} h`} />
        <Stat label="Diagnósticos abertos" value={num(st.open_diagnostics)} />
        <Stat label="Em andamento" value={num((ps.queued ?? 0) + (ps.developing ?? 0) + (ps.testing ?? 0) + (ps.evaluating ?? 0))}
          hint={`${num(ps.awaiting_approval ?? 0)} aguardando aprovação`} />
        <Stat label="Publicadas" value={num(ps.published ?? 0)} hint={`${num(ps.rolled_back ?? 0)} revertidas · ${num(ps.failed ?? 0)} reprovadas`} />
      </div>

      <Card title="Controles" subtitle={`Gasto da evolução no mês: ${usd(st.budget.evolution_spent_usd)} de ${usd(st.budget.evolution_limit_usd, 2)}`}>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" busy={act.busy} onClick={() => act.run(async () => { await post("/api/evolution/run"); reload(); cycles.reload(); })}>
            <Zap className="h-4 w-4" /> Rodar ciclo agora</Button>
          {st.paused ? (
            <Button busy={act.busy} onClick={() => act.run(async () => { await post("/api/evolution/resume"); reload(); })}><Play className="h-4 w-4" /> Retomar</Button>
          ) : (
            <Button busy={act.busy} onClick={() => act.run(async () => { await post("/api/evolution/pause"); reload(); })}><Pause className="h-4 w-4" /> Pausar</Button>
          )}
          <Button busy={act.busy} onClick={() => act.run(async () => {
            const r = await post<Status["safety_selftest"]["details"] & { passed: boolean }>("/api/evolution/selftest");
            setSelftest(r); reload();
          })}><ShieldCheck className="h-4 w-4" /> Autoteste de segurança</Button>
        </div>
        <div className="mt-4 space-y-3 rounded-xl border border-line p-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium">Autoevolução contínua</div>
              <div className="text-xs text-muted">Observa, diagnostica, desenvolve e testa em segundo plano.</div>
            </div>
            <Toggle checked={st.enabled} label="Autoevolução" onChange={(v) => act.run(async () => { await post("/api/evolution/enabled", { enabled: v }); reload(); })} />
          </div>
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium">Publicação automática (somente baixo risco)</div>
              <div className="text-xs text-muted">
                Exige autoteste aprovado {st.safety_selftest.passed ? <Badge tone="good">aprovado {ago(st.safety_selftest.at)}</Badge> : <Badge tone="warning">pendente</Badge>}.
                Médio e alto risco sempre pedem sua aprovação.
              </div>
            </div>
            <Toggle checked={st.auto_publish_low_risk} label="Publicação automática"
              onChange={(v) => v ? setAskPw(true) : act.run(async () => { await post("/api/evolution/autopublish", { enabled: false }); reload(); })} />
          </div>
          {askPw && (
            <div className="flex flex-col gap-2 sm:flex-row">
              <input className={inputCls} type="password" placeholder="Confirme sua senha" value={pw} onChange={(e) => setPw(e.target.value)} />
              <Button variant="primary" busy={act.busy} onClick={() => act.run(async () => {
                await post("/api/evolution/autopublish", { enabled: true, password: pw }); setAskPw(false); setPw(""); reload();
              })}>Ativar</Button>
            </div>
          )}
        </div>
        <div className="mt-3"><ErrorNote error={act.error} /></div>
        <p className="mt-2 text-xs text-muted">Sandbox: isolamento <b>{st.sandbox.isolation}</b>
          {st.sandbox.capabilities.unshare_net ? " (rede bloqueada por namespace)" : " — sem isolamento de rede neste servidor"}.</p>
        {(selftest?.checks || st.safety_selftest.details?.checks) && (
          <details className="mt-2"><summary className="cursor-pointer text-xs text-ink-2">Resultado do último autoteste</summary>
            <ul className="mt-2 grid gap-1 sm:grid-cols-2">
              {(selftest?.checks || st.safety_selftest.details.checks || []).map((c) => (
                <li key={c.name} className="flex items-start gap-1.5 text-xs">
                  {c.passed ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-good" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-critical" />}
                  <span>{c.name}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </Card>

      {cycle && (
        <Card title={`Ciclo #${cycle.number}`} action={<StatusPill status={cycle.status} />}
          subtitle={`${cycle.trigger === "manual" ? "manual" : "agendado"} · iniciado ${ago(cycle.started_at)} · ${usd(cycle.cost_usd)}`}>
          <PhaseTrack cycle={cycle} phases={st.phases} />
          {cycle.summary && <p className="mt-3 text-sm text-ink-2">{cycle.summary}</p>}
          {cycle.error && <div className="mt-2"><ErrorNote error={cycle.error} /></div>}
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Histórico de ciclos">
          {cycles.data?.length ? (
            <ul className="divide-y divide-line">
              {cycles.data.slice(0, 12).map((c) => (
                <li key={c.id}><button onClick={async () => setCycleSel(await get<Cycle>(`/api/evolution/cycles/${c.id}`))}
                  className="flex w-full items-center justify-between gap-2 py-2 text-left text-sm hover:text-lime">
                  <span>#{c.number} <span className="text-xs text-muted">{dateTime(c.started_at)}</span></span>
                  <span className="flex items-center gap-2 text-xs text-muted">{usd(c.cost_usd)} <StatusPill status={c.status} /></span>
                </button></li>
              ))}
            </ul>
          ) : <Empty title="Nenhum ciclo ainda" />}
        </Card>
        <Card title="Taxa de erro das chamadas de IA" subtitle="Indicador histórico gravado a cada ciclo (24h)">
          <LineChart points={history.data || []} format={(v) => pct(v, 1)} ariaLabel="Taxa de erro de IA por ciclo" />
        </Card>
      </div>
      {cycleSel && (
        <Sheet open onClose={() => setCycleSel(null)} title={`Ciclo #${cycleSel.number}`} wide>
          <p className="mb-3 text-sm text-ink-2">{cycleSel.summary}</p>
          <h4 className="mb-1 text-xs font-semibold uppercase text-muted">Registro</h4>
          <ol className="mb-3 space-y-1 text-xs">{(cycleSel.log || []).map((l, i) => <li key={i}><span className="text-muted">{dateTime(l.ts)} [{l.phase}]</span> {l.message}</li>)}</ol>
          <h4 className="mb-1 text-xs font-semibold uppercase text-muted">Checkpoints por fase</h4>
          <JsonBlock value={cycleSel.checkpoint} />
        </Sheet>
      )}
    </div>
  );
}

function Diagnostics() {
  const [status, setStatus] = useState("open");
  const { data, loading, reload } = useApi<Diagnostic[]>(`/api/evolution/diagnostics?status=${status}`, 15000);
  const [sel, setSel] = useState<Diagnostic | null>(null);
  return (
    <Card title="Autodiagnóstico" subtitle="Baseado em métricas, erros, testes e no mapa do código — não em opinião de modelos."
      action={<select className="rounded-lg border border-line bg-surface-2 px-2 py-1 text-xs" value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="open">abertos</option><option value="resolved">resolvidos</option><option value="ignored">ignorados</option><option value="all">todos</option></select>}>
      {loading && !data ? <Spinner /> : data?.length ? (
        <ul className="divide-y divide-line">
          {data.map((d) => (
            <li key={d.id}><button onClick={() => setSel(d)} className="flex w-full items-start justify-between gap-3 py-2.5 text-left hover:text-lime">
              <div className="min-w-0"><div className="text-sm">{d.title}</div><div className="text-xs text-muted">{d.category} · {d.occurrences}x · {ago(d.last_seen_at)}</div></div>
              <Badge tone={SEV[d.severity]}>{pt(d.severity)}</Badge>
            </button></li>
          ))}
        </ul>
      ) : <Empty title="Nenhum diagnóstico" />}
      {sel && (
        <Sheet open onClose={() => setSel(null)} title={sel.title} wide>
          <div className="space-y-3 text-sm">
            <div className="flex gap-2"><Badge tone={SEV[sel.severity]}>{pt(sel.severity)}</Badge><Badge>{sel.category}</Badge><StatusPill status={sel.status} /></div>
            {sel.detail && <p className="text-ink-2">{sel.detail}</p>}
            {sel.suggestion && <Note>{sel.suggestion}</Note>}
            {sel.research && <div><h4 className="mb-1 text-xs font-semibold uppercase text-muted">Pesquisa de solução</h4><Markdown text={sel.research} /></div>}
            <h4 className="text-xs font-semibold uppercase text-muted">Evidência</h4>
            <JsonBlock value={Object.fromEntries(Object.entries(sel.evidence || {}).filter(([k]) => !k.startsWith("_")))} />
            {sel.status === "open" && <Button onClick={async () => { await post(`/api/evolution/diagnostics/${sel.id}/ignore`); setSel(null); reload(); }}>Ignorar</Button>}
          </div>
        </Sheet>
      )}
    </Card>
  );
}

function TestCompare({ base, cand }: { base?: Record<string, number>; cand?: Record<string, number> }) {
  if (!cand) return null;
  return (
    <div className="grid grid-cols-2 gap-2 text-center text-xs">
      {[["Versão original", base], ["Versão modificada", cand]].map(([label, r]) => {
        const x = r as Record<string, number> | undefined;
        return (
          <div key={label as string} className="rounded-xl border border-line p-2">
            <div className="text-muted">{label as string}</div>
            <div className="mt-1 text-lg font-semibold tabular-nums">{x?.passed ?? "—"}<span className="text-xs text-muted"> passaram</span></div>
            <div className={cx((x?.failed || x?.errors) ? "text-critical" : "text-muted")}>{x?.failed ?? 0} falhas · {x?.errors ?? 0} erros · {x?.time_s ?? 0}s</div>
          </div>
        );
      })}
    </div>
  );
}

function ProposalSheet({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, reload } = useApi<ProposalDetail>(`/api/evolution/proposals/${id}`, 4000);
  const [diff, setDiff] = useState<string | null>(null);
  const act = useAction();
  if (!data) return <Sheet open onClose={onClose} title="Proposta"><Spinner /></Sheet>;
  const ev = data.evaluations[0];
  return (
    <Sheet open onClose={onClose} title={`${data.code} · ${data.title}`} wide>
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap gap-2">
          <StatusPill status={data.status} /><Badge tone={RISK[data.risk_level]}>risco {pt(data.risk_level)}</Badge>
          <Badge>{data.kind}</Badge><Badge>{data.strategy === "deterministic" ? "determinística" : "IA"}</Badge><Badge>origem: {data.source}</Badge>
          <Badge>{usd(data.cost_usd)}</Badge>
        </div>
        {data.error && <ErrorNote error={data.error} />}
        <div className="flex flex-wrap gap-2">
          {["queued", "failed", "proposed"].includes(data.status) && (
            <Button variant="primary" busy={act.busy} onClick={() => act.run(async () => { await post(`/api/evolution/proposals/${id}/develop`); reload(); })}>
              <Play className="h-4 w-4" /> Desenvolver agora</Button>)}
          {["evaluated", "approved"].includes(data.status) && data.approvals?.some((a) => a.status === "approved") && (
            <Button variant="primary" busy={act.busy} onClick={() => act.run(async () => { await post(`/api/evolution/proposals/${id}/publish`); reload(); })}>
              <Zap className="h-4 w-4" /> Publicar agora</Button>)}
          {["failed", "rejected"].includes(data.status) && <Button busy={act.busy} onClick={() => act.run(async () => { await post(`/api/evolution/proposals/${id}/requeue`); reload(); })}><RotateCcw className="h-4 w-4" /> Voltar para a fila</Button>}
          {!["published", "rejected"].includes(data.status) && <Button variant="danger" busy={act.busy} onClick={() => act.run(async () => { await post(`/api/evolution/proposals/${id}/reject`); reload(); })}>Rejeitar</Button>}
          {data.branch && <Button onClick={async () => setDiff((await get<{ diff: string }>(`/api/workspace/diff/${id}`)).diff)}>Ver diff</Button>}
          {data.pr_url && <a href={data.pr_url} target="_blank" rel="noopener noreferrer" className="self-center text-xs text-lime underline">Pull request no GitHub</a>}
        </div>
        <ErrorNote error={act.error} />
        <KV items={[["Problema", data.problem || "—"], ["Diagnóstico", data.diagnosis || "—"], ["Objetivo", data.objective || "—"],
          ["Solução", data.solution || "—"], ["Benefícios", data.benefits || "—"], ["Riscos", data.risks || "—"],
          ["Custo estimado", usd(data.cost_estimate_usd)], ["Estratégia de reversão", data.rollback_strategy || "—"],
          ["Arquivos afetados", data.affected_files.join(", ") || "—"], ["Dependências", data.dependencies.join(", ") || "nenhuma"],
          ["Testes necessários", data.tests_required.join("; ") || "—"], ["Critérios de aceitação", data.acceptance_criteria.join("; ") || "—"]]} />
        {data.changed_files.length > 0 && (
          <div><h4 className="mb-1 text-xs font-semibold uppercase text-muted">Arquivos modificados ({data.diff_stats.added ?? 0}+ / {data.diff_stats.removed ?? 0}−)</h4>
            <ul className="space-y-0.5 font-mono text-xs">{data.changed_files.map((f) => <li key={f.path}><span className="text-lime">{f.status}</span> {f.path}</li>)}</ul></div>
        )}
        {data.tests?.candidate && <div><h4 className="mb-1 text-xs font-semibold uppercase text-muted">Testes no sandbox</h4><TestCompare base={data.tests.baseline} cand={data.tests.candidate} /></div>}
        {ev && (
          <div>
            <h4 className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase text-muted">Avaliação independente <StatusPill status={ev.verdict} label={ev.verdict === "pass" ? "aprovada" : "reprovada"} /></h4>
            <ul className="space-y-1">
              {ev.gates.map((g) => (
                <li key={g.name} className="flex items-start gap-2 rounded-lg border border-line px-2 py-1.5 text-xs">
                  {g.passed ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-good" /> : <XCircle className={cx("mt-0.5 h-3.5 w-3.5 shrink-0", g.hard ? "text-critical" : "text-warning")} />}
                  <div className="min-w-0"><b>{g.name}</b>{!g.hard && <span className="text-muted"> (informativo)</span>}<div className="break-words text-muted">{g.detail}</div></div>
                </li>
              ))}
            </ul>
            {ev.audit?.summary && <div className="mt-2"><Note>Auditor{ev.audit.model ? ` (${ev.audit.model}${ev.audit.independent_provider ? ", provedor independente" : ""})` : ""}: {ev.audit.summary}</Note></div>}
          </div>
        )}
        {data.dev_log.length > 0 && <details><summary className="cursor-pointer text-xs text-ink-2">Registro do desenvolvimento ({data.dev_log.length} etapas)</summary><JsonBlock value={data.dev_log} /></details>}
        {data.sandbox_runs.length > 0 && (
          <details><summary className="cursor-pointer text-xs text-ink-2">Execuções no sandbox ({data.sandbox_runs.length})</summary>
            <ul className="mt-2 space-y-1 text-xs">{data.sandbox_runs.map((r) => <li key={r.id}>{r.label} · <StatusPill status={r.status === "ok" ? "ok" : "failed"} label={r.status} /> · {(r.duration_ms / 1000).toFixed(1)}s · rede {String(r.isolation?.network)}</li>)}</ul>
          </details>
        )}
        {diff !== null && <Sheet open onClose={() => setDiff(null)} title="Diff" wide><pre className="overflow-x-auto whitespace-pre text-[11px] text-ink-2">{diff}</pre></Sheet>}
      </div>
    </Sheet>
  );
}

function Proposals() {
  const [status, setStatus] = useState("");
  const { data, loading, reload } = useApi<Proposal[]>(`/api/evolution/proposals?status=${status}`, 6000);
  const [sel, setSel] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ title: "", problem: "", solution: "", affected_files: "", develop_now: true });
  const act = useAction();
  async function create() {
    const r = await act.run(() => post<{ id: string }>("/api/evolution/proposals", { ...form, kind: "code",
      affected_files: form.affected_files.split(/[\s,]+/).filter(Boolean) }));
    if (r) { setOpen(false); reload(); setSel(r.id); }
  }
  return (
    <Card title="Melhorias propostas" subtitle="Fila priorizada por impacto, confiança, custo e risco."
      action={<div className="flex gap-2">
        <select className="rounded-lg border border-line bg-surface-2 px-2 py-1 text-xs" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">todas</option><option value="queued">na fila</option><option value="developing,testing,evaluating">em desenvolvimento</option>
          <option value="awaiting_approval">aguardando aprovação</option><option value="published">publicadas</option><option value="failed,rejected,rolled_back">reprovadas/revertidas</option>
        </select>
        <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Pedir melhoria</Button></div>}>
      {loading && !data ? <Spinner /> : data?.length ? (
        <ul className="divide-y divide-line">
          {data.map((p) => (
            <li key={p.id}><button onClick={() => setSel(p.id)} className="flex w-full items-start justify-between gap-3 py-2.5 text-left hover:text-lime">
              <div className="min-w-0"><div className="text-sm"><span className="font-mono text-xs text-muted">{p.code}</span> {p.title}</div>
                <div className="text-xs text-muted">{p.kind} · prioridade {p.priority_score} · {ago(p.created_at)}{p.diff_stats?.files ? ` · ${p.diff_stats.files} arquivos` : ""}</div></div>
              <div className="flex shrink-0 flex-col items-end gap-1"><StatusPill status={p.status} /><Badge tone={RISK[p.risk_level]}>{pt(p.risk_level)}</Badge></div>
            </button></li>
          ))}
        </ul>
      ) : <Empty title="Nenhuma proposta">Os ciclos geram propostas a partir dos diagnósticos; você também pode pedir uma melhoria.</Empty>}
      {sel && <ProposalSheet id={sel} onClose={() => { setSel(null); reload(); }} />}
      <Sheet open={open} onClose={() => setOpen(false)} title="Pedir uma melhoria ao ULTRON">
        <div className="space-y-3">
          <Note>O Developer Agent implementa numa branch isolada, testa no sandbox e o Evaluation Engine avalia. Nada é publicado sem passar pela política de risco.</Note>
          <Field label="Título"><input className={inputCls} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          <Field label="Problema"><textarea className={`${inputCls} min-h-20`} value={form.problem} onChange={(e) => setForm({ ...form, problem: e.target.value })} /></Field>
          <Field label="Solução desejada"><textarea className={`${inputCls} min-h-20`} value={form.solution} onChange={(e) => setForm({ ...form, solution: e.target.value })} /></Field>
          <Field label="Arquivos relacionados (opcional)" hint="Ex.: backend/ultron/memory/service.py"><input className={inputCls} value={form.affected_files} onChange={(e) => setForm({ ...form, affected_files: e.target.value })} /></Field>
          <label className="flex items-center gap-2 text-sm"><Toggle checked={form.develop_now} onChange={(v) => setForm({ ...form, develop_now: v })} /> Desenvolver imediatamente</label>
          <ErrorNote error={act.error} />
          <Button variant="primary" className="w-full" onClick={create} busy={act.busy} disabled={form.title.trim().length < 5}>Criar proposta</Button>
        </div>
      </Sheet>
    </Card>
  );
}

function Approvals() {
  const { data, loading, reload } = useApi<Approval[]>("/api/approvals?status=all", 8000);
  const [pw, setPw] = useState<Record<string, string>>({});
  const act = useAction();
  const decide = (a: Approval, approve: boolean) => act.run(async () => {
    await post(`/api/approvals/${a.id}/decide`, { approve, password: pw[a.id] || "" }); reload();
  });
  const pending = (data || []).filter((a) => a.status === "pending");
  const done = (data || []).filter((a) => a.status !== "pending");
  return (
    <div className="space-y-4">
      <Card title="Aguardando sua decisão" subtitle="Somente você aprova. Ações de alto risco exigem sua senha.">
        <ErrorNote error={act.error} />
        {loading && !data ? <Spinner /> : pending.length ? (
          <ul className="space-y-3">
            {pending.map((a) => (
              <li key={a.id} className="rounded-xl border border-line p-3">
                <div className="flex flex-wrap items-center gap-2"><Badge tone={RISK[a.risk]}>risco {pt(a.risk)}</Badge><Badge>{a.kind}</Badge>
                  <span className="text-xs text-muted">{ago(a.created_at)} · {a.requested_by}</span></div>
                <div className="mt-1 text-sm font-medium">{a.title}</div>
                {a.summary && <p className="mt-1 whitespace-pre-wrap text-xs text-ink-2">{a.summary}</p>}
                <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                  {a.risk === "high" && <input type="password" className={inputCls} placeholder="Senha (alto risco)" value={pw[a.id] || ""} onChange={(e) => setPw({ ...pw, [a.id]: e.target.value })} />}
                  <Button variant="primary" busy={act.busy} onClick={() => decide(a, true)}><CheckCircle2 className="h-4 w-4" /> Aprovar</Button>
                  <Button variant="danger" busy={act.busy} onClick={() => decide(a, false)}><XCircle className="h-4 w-4" /> Rejeitar</Button>
                </div>
              </li>
            ))}
          </ul>
        ) : <Empty title="Nada aguardando aprovação" />}
      </Card>
      <Card title="Decisões anteriores">
        {done.length ? <ul className="divide-y divide-line">{done.slice(0, 30).map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-2 py-2 text-sm"><span className="min-w-0 truncate">{a.title}</span>
            <span className="flex shrink-0 items-center gap-2 text-xs text-muted">{a.decided_by}<StatusPill status={a.status} /></span></li>))}</ul> : <Empty title="Sem histórico" />}
      </Card>
    </div>
  );
}

function Publications() {
  const { data, loading, reload } = useApi<Publication[]>("/api/evolution/publications", 10000);
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState<Publication | null>(null);
  const act = useAction();
  return (
    <Card title="Publicações e rollbacks" subtitle="Toda publicação guarda o ponto de retorno e é monitorada após entrar no ar.">
      {loading && !data ? <Spinner /> : data?.length ? (
        <ul className="divide-y divide-line">
          {data.map((p) => (
            <li key={p.id} className="py-2.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0"><div className="text-sm"><span className="font-mono text-xs text-muted">{p.code}</span> {p.title}</div>
                  <div className="text-xs text-muted">{p.mode === "auto" ? "automática (baixo risco)" : `aprovada por ${p.approved_by.startsWith("user:") ? "você" : p.approved_by}`} · {dateTime(p.published_at)} · {p.pushed ? "enviada ao GitHub" : "workspace local"} · {p.merge_sha.slice(0, 8)}</div>
                  {p.rollback_reason && <div className="text-xs text-serious">Revertida: {p.rollback_reason}</div>}</div>
                <div className="flex shrink-0 flex-col items-end gap-1"><StatusPill status={p.status} />
                  {p.status === "published" && <Button variant="ghost" onClick={() => setTarget(p)}><Undo2 className="h-4 w-4" /> Rollback</Button>}</div>
              </div>
            </li>
          ))}
        </ul>
      ) : <Empty title="Nenhuma publicação ainda" />}
      <Sheet open={!!target} onClose={() => setTarget(null)} title={`Reverter ${target?.code}`}>
        <Field label="Motivo"><input className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="mt-3"><ErrorNote error={act.error} /></div>
        <Button variant="danger" className="mt-3 w-full" busy={act.busy} disabled={reason.trim().length < 3}
          onClick={() => act.run(async () => { await post(`/api/evolution/publications/${target!.id}/rollback`, { reason }); setTarget(null); setReason(""); reload(); })}>Reverter publicação</Button>
      </Sheet>
    </Card>
  );
}

function Policy() {
  const { data } = useApi<{ forbidden: string[]; high: string[]; low: string[]; rules: string[] }>("/api/evolution/policy");
  if (!data) return <Spinner />;
  return (
    <Card title="Política de publicação e governança" subtitle="Aplicada por código independente dos agentes; o risco é calculado sobre o diff real.">
      <ul className="mb-4 list-disc space-y-1 pl-5 text-sm">{data.rules.map((r) => <li key={r}>{r}</li>)}</ul>
      <div className="grid gap-3 sm:grid-cols-3">
        {[["Protegidos (nenhum agente altera)", data.forbidden, "critical"], ["Alto risco", data.high, "serious"], ["Baixo risco", data.low, "good"]].map(([t, list, tone]) => (
          <div key={t as string}><Badge tone={tone as string}>{t as string}</Badge>
            <ul className="mt-2 space-y-0.5 font-mono text-[11px] text-ink-2">{(list as string[]).map((p) => <li key={p} className="break-all">{p}</li>)}</ul></div>
        ))}
      </div>
    </Card>
  );
}

type Tab = "overview" | "diagnostics" | "proposals" | "approvals" | "publications" | "policy";

function Evolution() {
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "overview");
  useEffect(() => { const t = params.get("tab") as Tab; if (t) setTab(t); }, [params]);
  const { data, error, reload } = useApi<Status>("/api/evolution/status", 5000);
  return (
    <>
      <PageHeader icon={<Dna className="h-6 w-6 text-lime" />} title="Autoevolução"
        subtitle="Observar → diagnosticar → pesquisar → planejar → desenvolver → testar → auditar → publicar ou pedir aprovação → monitorar" />
      <ErrorNote error={error} />
      <div className="mb-4">
        <Tabs value={tab} onChange={setTab} tabs={[
          { id: "overview", label: "Visão geral" }, { id: "diagnostics", label: "Diagnósticos" }, { id: "proposals", label: "Propostas" },
          { id: "approvals", label: <>Aprovações{data?.pending_approvals ? <span className="ml-1 rounded-full bg-warning/20 px-1.5 text-[10px] text-warning">{data.pending_approvals}</span> : null}</> },
          { id: "publications", label: "Publicações" }, { id: "policy", label: "Política" }]} />
      </div>
      {tab === "overview" && (data ? <Overview st={data} reload={reload} /> : <Spinner />)}
      {tab === "diagnostics" && <Diagnostics />}
      {tab === "proposals" && <Proposals />}
      {tab === "approvals" && <Approvals />}
      {tab === "publications" && <Publications />}
      {tab === "policy" && <Policy />}
    </>
  );
}

export default function Page() {
  return <Shell><Suspense fallback={<Spinner />}><Evolution /></Suspense></Shell>;
}
