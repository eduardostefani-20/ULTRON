"use client";

import { Bot, Play } from "lucide-react";
import { useState } from "react";

import Shell from "@/components/Shell";
import { Badge, Button, Card, ErrorNote, JsonBlock, Markdown, PageHeader, Sheet, Spinner, StatusPill, Toggle, inputCls } from "@/components/ui";
import { get, patch, post } from "@/lib/api";
import { ago, usd } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";

type Agent = { id: string; name: string; role: string; description: string; purpose: string; tools: string[]; scopes: string[];
  model_tier: string; max_steps: number; budget_usd_per_run: number; builtin: boolean; status: string; created_by: string;
  generation: number; working: boolean; stats: { runs: number; failed: number; cost_usd: number; last_run?: string };
  tool_details: { name: string; scope: string; description: string }[] };
type Run = { id: string; status: string; input: string; output: string; steps: Record<string, unknown>[]; models: string[];
  cost_usd: number; started_at: string; error: string };

const SCOPE: Record<string, string> = { read_analyze: "ler/analisar", develop_sandbox: "sandbox", external_access: "acesso externo",
  memory_write: "gravar memória", publish: "publicar" };

function AgentSheet({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const runs = useApi<Run[]>(`/api/agents/${agent.id}/runs`);
  const [task, setTask] = useState("");
  const [result, setResult] = useState<Run | null>(null);
  const [detail, setDetail] = useState<Run | null>(null);
  const act = useAction();
  async function run() {
    const r = await act.run(() => post<{ run_id: string }>(`/api/agents/${agent.id}/run`, { task }));
    if (r) { setResult(await get<Run>(`/api/agent-runs/${r.run_id}`)); runs.reload(); }
  }
  return (
    <Sheet open onClose={onClose} title={agent.name} wide>
      <p className="text-sm text-ink-2">{agent.description}</p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {agent.scopes.map((s) => <Badge key={s} tone="info">{SCOPE[s] ?? s}</Badge>)}
        <Badge>camada {agent.model_tier}</Badge><Badge>até {agent.max_steps} passos</Badge><Badge>{usd(agent.budget_usd_per_run, 3)}/execução</Badge>
      </div>
      <h4 className="mb-1 mt-4 text-xs font-semibold uppercase text-muted">Ferramentas</h4>
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {agent.tool_details.map((t) => <li key={t.name} className="rounded-lg border border-line px-2 py-1.5 text-xs"><b className="text-ink">{t.name}</b> <span className="text-muted">· {t.description}</span></li>)}
      </ul>
      <h4 className="mb-1 mt-4 text-xs font-semibold uppercase text-muted">Executar tarefa direta</h4>
      <textarea className={`${inputCls} min-h-20`} value={task} onChange={(e) => setTask(e.target.value)} placeholder="Descreva a tarefa para este agente…" />
      <div className="mt-2"><Button variant="primary" onClick={run} busy={act.busy} disabled={task.trim().length < 3}><Play className="h-4 w-4" /> Executar</Button></div>
      <div className="mt-2"><ErrorNote error={act.error} /></div>
      {result && (
        <div className="mt-3 rounded-xl border border-line p-3">
          <div className="mb-2 flex gap-2"><StatusPill status={result.status} /><span className="text-xs text-muted">{usd(result.cost_usd, 5)}</span></div>
          <Markdown text={result.output} />
        </div>
      )}
      <h4 className="mb-1 mt-4 text-xs font-semibold uppercase text-muted">Execuções recentes</h4>
      {runs.loading ? <Spinner /> : (
        <ul className="divide-y divide-line">
          {(runs.data || []).map((r) => (
            <li key={r.id}><button onClick={() => setDetail(r)} className="flex w-full items-center justify-between gap-2 py-2 text-left text-sm hover:text-lime">
              <span className="min-w-0 truncate">{r.input}</span>
              <span className="flex shrink-0 items-center gap-2 text-xs text-muted">{ago(r.started_at)} <StatusPill status={r.status} /></span>
            </button></li>
          ))}
          {!runs.data?.length && <li className="py-2 text-xs text-muted">Nenhuma execução.</li>}
        </ul>
      )}
      {detail && (
        <Sheet open onClose={() => setDetail(null)} title="Execução do agente" wide>
          <p className="mb-2 text-xs text-muted">Modelos: {detail.models.join(", ") || "—"} · {usd(detail.cost_usd, 5)}</p>
          <Markdown text={detail.output || detail.error} />
          <h4 className="mb-1 mt-3 text-xs font-semibold uppercase text-muted">Passos (raciocínio → ferramenta → observação)</h4>
          <JsonBlock value={detail.steps} />
        </Sheet>
      )}
    </Sheet>
  );
}

function Agents() {
  const { data, error, loading, reload } = useApi<Agent[]>("/api/agents", 10000);
  const [sel, setSel] = useState<Agent | null>(null);
  if (loading && !data) return <Spinner />;
  return (
    <>
      <PageHeader icon={<Bot className="h-6 w-6 text-lime" />} title="Agentes"
        subtitle="Especialistas que trabalham em paralelo, com ferramentas e permissões definidas pela governança." />
      <ErrorNote error={error} />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {(data || []).map((a) => (
          <Card key={a.id} className="flex flex-col">
            <div className="flex items-start justify-between gap-2">
              <button onClick={() => setSel(a)} className="min-w-0 text-left">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  {a.working && <span className="h-2 w-2 rounded-full bg-lime pulse-dot" title="trabalhando" />}
                  <span className="truncate hover:text-lime">{a.name}</span>
                </div>
                <div className="text-xs text-ink-2">{a.role}</div>
              </button>
              {a.status === "pending_approval" ? <StatusPill status="pending_approval" /> : (
                <Toggle checked={a.status === "active"} label={`Ativar ${a.name}`}
                  onChange={async (v) => { await patch(`/api/agents/${a.id}`, { status: v ? "active" : "disabled" }); reload(); }} />
              )}
            </div>
            <p className="mt-2 line-clamp-2 text-xs text-muted">{a.description}</p>
            <div className="mt-auto flex flex-wrap gap-1.5 pt-3 text-[11px]">
              <Badge>{a.stats.runs} execuções</Badge>
              {a.stats.failed > 0 && <Badge tone="serious">{a.stats.failed} falhas</Badge>}
              <Badge>{usd(a.stats.cost_usd, 4)}</Badge>
              {!a.builtin && <Badge tone="lime">criado por {a.created_by}</Badge>}
            </div>
          </Card>
        ))}
      </div>
      {sel && <AgentSheet agent={sel} onClose={() => setSel(null)} />}
    </>
  );
}

export default function Page() {
  return <Shell><Agents /></Shell>;
}

