"use client";

import { Wallet } from "lucide-react";
import { useState } from "react";

import { BarChart, HBars, Meter } from "@/components/charts";
import Shell from "@/components/Shell";
import { Button, Card, ErrorNote, Field, Note, PageHeader, Spinner, Stat, Toggle, inputCls } from "@/components/ui";
import { put } from "@/lib/api";
import { brl, num, pct, usd } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";

type Row = { key: string; calls: number; cost_usd: number; tokens?: number };
type Usage = {
  budget: { limit_usd: number; limit_brl: number; spent_usd: number; spent_brl: number; usage_ratio: number; projected_month_brl: number;
    evolution_spent_usd: number; evolution_limit_usd: number; alert: boolean; usd_brl_rate: number };
  budgets: Record<string, unknown>; by_provider: Row[]; by_agent: Row[]; by_purpose: Row[]; by_model: Row[];
  daily: { date: string; cost_usd: number; calls: number }[]; cache_hits: number;
  top_missions: { id: string; title: string; cost_usd: number; budget_usd: number }[];
};

function Usage() {
  const { data, error, loading, reload } = useApi<Usage>("/api/usage", 20000);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const act = useAction();
  if (loading && !data) return <Spinner />;
  if (!data) return <ErrorNote error={error} />;
  const b = data.budget;
  const rate = b.usd_brl_rate;
  const bud = data.budgets;
  const val = (k: string, d: unknown) => edit[k] ?? String(d ?? "");
  async function save() {
    const values: Record<string, unknown> = {};
    if (edit["budget.monthly_brl"] !== undefined) values["budget.monthly_brl"] = Number(edit["budget.monthly_brl"]) || null;
    if (edit["budget.per_mission_usd"] !== undefined) values["budget.per_mission_usd"] = Number(edit["budget.per_mission_usd"]);
    if (edit["budget.alert_threshold"] !== undefined) values["budget.alert_threshold"] = Number(edit["budget.alert_threshold"]) / 100;
    await act.run(async () => { await put("/api/settings", { values }); setEdit({}); reload(); });
  }
  return (
    <>
      <PageHeader icon={<Wallet className="h-6 w-6 text-lime" />} title="Uso e custos" subtitle={`Meta mensal ${brl(b.limit_brl)} · câmbio de referência R$ ${rate.toFixed(2)}`} />
      {b.alert && <div className="mb-4"><Note tone="warning">O gasto passou do limite de alerta. Ajuste o orçamento ou prefira modelos rápidos.</Note></div>}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Gasto no mês" value={brl(b.spent_brl)} hint={usd(b.spent_usd)} accent />
        <Stat label="Projeção do mês" value={brl(b.projected_month_brl)} hint={pct(b.projected_month_brl / (b.limit_brl || 1))} />
        <Stat label="Autoevolução" value={usd(b.evolution_spent_usd)} hint={`limite ${usd(b.evolution_limit_usd, 2)}`} />
        <Stat label="Respostas do cache" value={num(data.cache_hits)} hint="chamadas economizadas" />
      </div>
      <div className="mt-3"><Meter value={b.usage_ratio} label="Uso do orçamento" /></div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Custo diário (US$)" className="lg:col-span-2">
          <BarChart ariaLabel="Custo diário em dólares" data={data.daily.map((d) => ({ label: d.date.slice(5).split("-").reverse().join("/"), value: d.cost_usd,
            display: `${usd(d.cost_usd, 5)} · ${d.calls} chamadas` }))} format={(v) => `$${v.toFixed(3)}`} />
        </Card>
        <Card title="Por provedor"><HBars rows={data.by_provider.map((r) => ({ key: r.key, value: r.cost_usd, extra: `${r.calls}x` }))} format={(v) => usd(v)} /></Card>
        <Card title="Por modelo"><HBars rows={data.by_model.slice(0, 8).map((r) => ({ key: r.key, value: r.cost_usd, extra: `${r.calls}x` }))} format={(v) => usd(v)} /></Card>
        <Card title="Por agente"><HBars rows={data.by_agent.slice(0, 10).map((r) => ({ key: r.key, value: r.cost_usd, extra: `${r.calls}x` }))} format={(v) => usd(v)} /></Card>
        <Card title="Por finalidade"><HBars rows={data.by_purpose.slice(0, 10).map((r) => ({ key: r.key, value: r.cost_usd, extra: `${r.calls}x` }))} format={(v) => usd(v)} /></Card>
        <Card title="Limites" className="lg:col-span-2" subtitle="Aplicados antes de cada chamada. Ao estourar a fatia da evolução, ela pausa sozinha.">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Orçamento mensal (R$)" hint="vazio = valor do servidor">
              <input className={inputCls} inputMode="decimal" value={val("budget.monthly_brl", bud["budget.monthly_brl"] ?? b.limit_brl)} onChange={(e) => setEdit({ ...edit, "budget.monthly_brl": e.target.value })} />
            </Field>
            <Field label="Máximo por missão (US$)">
              <input className={inputCls} inputMode="decimal" value={val("budget.per_mission_usd", bud["budget.per_mission_usd"])} onChange={(e) => setEdit({ ...edit, "budget.per_mission_usd": e.target.value })} />
            </Field>
            <Field label="Alerta em (% do orçamento)">
              <input className={inputCls} inputMode="numeric" value={val("budget.alert_threshold", Math.round(Number(bud["budget.alert_threshold"] ?? 0.8) * 100))} onChange={(e) => setEdit({ ...edit, "budget.alert_threshold": e.target.value })} />
            </Field>
          </div>
          <div className="mt-3 flex items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-sm">
              <Toggle checked={Boolean(bud["budget.hard_stop"])} label="Parada obrigatória"
                onChange={(v) => act.run(async () => { await put("/api/settings", { values: { "budget.hard_stop": v } }); reload(); })} />
              Bloquear chamadas ao atingir o orçamento
            </label>
            <Button variant="primary" onClick={save} busy={act.busy} disabled={!Object.keys(edit).length}>Salvar limites</Button>
          </div>
          <div className="mt-2"><ErrorNote error={act.error} /></div>
        </Card>
        {data.top_missions.length > 0 && (
          <Card title="Missões mais caras do mês" className="lg:col-span-2">
            <HBars rows={data.top_missions.map((m) => ({ key: m.title, value: m.cost_usd, extra: `limite ${usd(m.budget_usd, 2)}` }))} format={(v) => usd(v)} />
          </Card>
        )}
      </div>
    </>
  );
}

export default function Page() {
  return <Shell><Usage /></Shell>;
}
