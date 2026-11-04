"use client";

import { ArrowLeft, Plus, RotateCcw, Target, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import Shell from "@/components/Shell";
import { Badge, Button, Card, Empty, ErrorNote, Field, KV, Markdown, PageHeader, Sheet, Spinner, StatusPill, cx, inputCls } from "@/components/ui";
import { post } from "@/lib/api";
import { ago, dateTime, pt, usd } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";

type Mission = { id: string; title: string; objective: string; status: string; priority: number; source: string; cost_usd: number;
  budget_usd: number; created_at: string; finished_at: string | null; tasks: number; result_preview: string };
type Task = { id: string; key: string; title: string; agent_id: string; status: string; depends_on: string[]; output: string; error: string;
  cost_usd: number; attempts: number };
type Event = { id: string; ts: string; type: string; message: string };
type Detail = Mission & { plan: { title?: string; strategy?: string; planner_model?: string }; result: string; error: string;
  review: { meets_objective?: boolean; score?: number; issues?: string[] }; tasks: Task[]; events: Event[] };

const ACTIVE = ["RECEIVED", "PLANNING", "RUNNING", "REVIEWING"];

function MissionDetail({ id }: { id: string }) {
  const { data, error, reload } = useApi<Detail>(`/api/missions/${id}`, 3000);
  const act = useAction();
  const [task, setTask] = useState<Task | null>(null);
  if (!data) return error ? <ErrorNote error={error} /> : <Spinner />;
  const active = ACTIVE.includes(data.status);
  return (
    <>
      <Link href="/missions/" className="mb-3 inline-flex items-center gap-1 text-sm text-ink-2 hover:text-lime"><ArrowLeft className="h-4 w-4" /> Missões</Link>
      <PageHeader title={data.title || "Missão"} subtitle={data.plan?.strategy}
        actions={<>
          {active || data.status === "WAITING_APPROVAL" ? (
            <Button variant="danger" busy={act.busy} onClick={() => act.run(async () => { await post(`/api/missions/${id}/cancel`); reload(); })}><XCircle className="h-4 w-4" /> Cancelar</Button>
          ) : null}
          {(data.status === "FAILED" || data.status === "CANCELLED") && (
            <Button busy={act.busy} onClick={() => act.run(async () => { await post(`/api/missions/${id}/retry`); reload(); })}><RotateCcw className="h-4 w-4" /> Tentar novamente</Button>
          )}
        </>} />
      <ErrorNote error={act.error} />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="min-w-0 space-y-4 lg:col-span-2">
          <Card title="Objetivo"><p className="whitespace-pre-wrap text-sm text-ink-2">{data.objective}</p></Card>
          <Card title="Plano (grafo de tarefas)" subtitle={data.plan?.planner_model ? `planejado por ${data.plan.planner_model}` : undefined}>
            {data.tasks.length ? (
              <ol className="space-y-2">
                {data.tasks.map((t) => (
                  <li key={t.id}>
                    <button onClick={() => setTask(t)} className={cx("w-full rounded-xl border p-3 text-left transition-colors hover:border-lime/40",
                      t.key.startsWith("x_") ? "border-line opacity-50" : "border-line")}>
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-sm font-medium">{t.title}</div>
                          <div className="text-xs text-muted">{t.agent_id} {t.depends_on.length > 0 && `· depende de ${t.depends_on.join(", ")}`}</div>
                        </div>
                        <StatusPill status={t.status} />
                      </div>
                    </button>
                  </li>
                ))}
              </ol>
            ) : <Empty title={active ? "Planejando…" : "Sem tarefas"} />}
          </Card>
          {data.result && <Card title="Resultado"><Markdown text={data.result} /></Card>}
          {data.error && <ErrorNote error={data.error} />}
        </div>
        <div className="min-w-0 space-y-4">
          <Card title="Estado">
            <KV items={[["Status", <StatusPill key="s" status={data.status} />], ["Custo", `${usd(data.cost_usd)} de ${usd(data.budget_usd, 2)}`],
              ["Criada", dateTime(data.created_at)], ["Fim", dateTime(data.finished_at)], ["Origem", data.source], ["Prioridade", data.priority]]} />
            {data.review?.score !== undefined && (
              <div className="mt-3 rounded-xl border border-line p-2 text-xs">
                Revisão independente: <b>{data.review.meets_objective ? "atende ao objetivo" : "não atende"}</b> · nota {data.review.score}
                {data.review.issues?.length ? <ul className="mt-1 list-disc pl-4 text-muted">{data.review.issues.map((x, i) => <li key={i}>{x}</li>)}</ul> : null}
              </div>
            )}
          </Card>
          <Card title="Linha do tempo">
            <ol className="space-y-2 border-l border-line pl-3">
              {data.events.map((e) => (
                <li key={e.id} className="relative text-xs">
                  <span className="absolute -left-[17px] top-1 h-2 w-2 rounded-full bg-lime" />
                  <div className="text-muted">{dateTime(e.ts)}</div>
                  <div className="text-ink-2">{e.message}</div>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
      {task && (
        <Sheet open onClose={() => setTask(null)} title={task.title} wide>
          <div className="mb-2 flex flex-wrap gap-2"><StatusPill status={task.status} /><Badge>{task.agent_id}</Badge><Badge>{usd(task.cost_usd, 5)}</Badge><Badge>{task.attempts} tentativa(s)</Badge></div>
          {task.output ? <Markdown text={task.output} /> : <p className="text-sm text-muted">{task.error || pt(task.status)}</p>}
        </Sheet>
      )}
    </>
  );
}

function MissionList() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi<Mission[]>("/api/missions", 5000);
  const [open, setOpen] = useState(false);
  const [objective, setObjective] = useState("");
  const [budget, setBudget] = useState("0.30");
  const act = useAction();
  async function create() {
    const m = await act.run(() => post<Mission>("/api/missions", { objective, budget_usd: Number(budget) || undefined }));
    if (m) { setOpen(false); setObjective(""); reload(); router.push(`/missions/?id=${m.id}`); }
  }
  return (
    <>
      <PageHeader icon={<Target className="h-6 w-6 text-lime" />} title="Missões"
        subtitle="Objetivos longos executados em segundo plano: planejamento, delegação, execução, revisão e entrega."
        actions={<Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Nova missão</Button>} />
      <ErrorNote error={error} />
      {loading && !data ? <Spinner /> : data?.length ? (
        <div className="space-y-2">
          {data.map((m) => (
            <Link key={m.id} href={`/missions/?id=${m.id}`} className="block rounded-2xl border border-line bg-surface/80 p-3 transition-colors hover:border-lime/40">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{m.title}</div>
                  <div className="mt-0.5 text-xs text-muted">{ago(m.created_at)} · {m.tasks} tarefas · {usd(m.cost_usd)}</div>
                </div>
                <StatusPill status={m.status} />
              </div>
              {m.result_preview && <p className="mt-2 line-clamp-2 text-xs text-ink-2">{m.result_preview}</p>}
            </Link>
          ))}
        </div>
      ) : <Empty title="Nenhuma missão">Crie uma missão para que o Director Agent planeje e distribua o trabalho entre os agentes.</Empty>}
      <Sheet open={open} onClose={() => setOpen(false)} title="Nova missão">
        <div className="space-y-3">
          <Field label="Objetivo" hint="Descreva o resultado esperado. O ULTRON divide em tarefas e escolhe os agentes.">
            <textarea className={`${inputCls} min-h-32`} value={objective} onChange={(e) => setObjective(e.target.value)} />
          </Field>
          <Field label="Orçamento máximo (US$)" hint="A missão para automaticamente se atingir este valor.">
            <input className={inputCls} value={budget} onChange={(e) => setBudget(e.target.value)} inputMode="decimal" />
          </Field>
          <ErrorNote error={act.error} />
          <Button variant="primary" onClick={create} busy={act.busy} disabled={objective.trim().length < 5} className="w-full">Iniciar missão</Button>
        </div>
      </Sheet>
    </>
  );
}

function Router() {
  const id = useSearchParams().get("id");
  return id ? <MissionDetail id={id} /> : <MissionList />;
}

export default function Page() {
  return <Shell><Suspense fallback={<Spinner />}><Router /></Suspense></Shell>;
}
