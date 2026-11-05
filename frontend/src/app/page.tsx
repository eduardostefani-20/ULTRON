"use client";

import { Activity, AlertTriangle, Dna, MessageSquare, Plug, Smartphone, Target } from "lucide-react";
import Link from "next/link";

import { Meter } from "@/components/charts";
import { QrCode } from "@/components/qrcode";
import Shell from "@/components/Shell";
import { Badge, Button, Card, Empty, ErrorNote, Note, PageHeader, Spinner, Stat, StatusPill } from "@/components/ui";
import { ago, brl, num, pct, usd } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Overview = {
  user: { name: string };
  providers: string[];
  budget: { limit_brl: number; spent_brl: number; spent_usd: number; usage_ratio: number; projected_month_brl: number; alert: boolean };
  counts: Record<string, number>;
  llm_24h: { calls: number; failures: number; error_rate: number; cost_usd: number };
  missions_24h: { by_status: Record<string, number>; success_rate: number | null };
  provider_health: Record<string, { open: boolean; last_error: string; latency_ema_ms: number; calls: number; failures: number }>;
  recent_missions: { id: string; title: string; status: string; cost_usd: number; created_at: string }[];
  diagnostics: { id: string; title: string; severity: string; category: string }[];
  evolution: { enabled: boolean; paused: boolean; auto_publish: boolean; last_cycle: { number: number; status: string; summary: string; started_at: string; phase: string } | null };
  system: { uptime_s: number; max_rss_mb: number; disk_free_gb: number };
};

/** Instalação no notebook: link e QR do túnel HTTPS atual, para abrir o app no celular. */
function PhoneAccess() {
  const { data } = useApi<{ tunnel_url: string | null }>("/api/system/access", 60000);
  const url = data?.tunnel_url;
  if (!url || (typeof window !== "undefined" && window.location.origin === url)) return null;
  return (
    <Card className="mb-4" title={<span className="flex items-center gap-2"><Smartphone className="h-4 w-4 text-lime" /> Abrir no celular</span>}>
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center">
        <QrCode value={url} />
        <div className="min-w-0 text-sm">
          <p className="text-ink-2">Aponte a câmera do celular para o código, ou abra este endereço:</p>
          <a href={url} target="_blank" rel="noopener noreferrer" className="mt-1 block break-all font-medium text-lime underline">{url}</a>
          <p className="mt-2 text-xs text-muted">
            No celular, use &quot;Adicionar à tela inicial&quot; para instalar o app. O endereço muda quando o
            computador reinicia; esta tela sempre mostra o atual.
          </p>
        </div>
      </div>
    </Card>
  );
}

const SEV: Record<string, string> = { critical: "critical", high: "serious", medium: "warning", low: "info", info: "neutral" };

function Dashboard() {
  const { data, error, loading } = useApi<Overview>("/api/system/overview", 15000);
  if (loading && !data) return <Spinner />;
  if (!data) return <ErrorNote error={error} />;
  const c = data.counts;
  const ev = data.evolution;
  return (
    <>
      <PageHeader title={`Olá, ${data.user.name}`} subtitle="Visão geral da central de inteligência"
        actions={<Link href="/chat/"><Button variant="primary"><MessageSquare className="h-4 w-4" /> Conversar</Button></Link>} />

      <PhoneAccess />

      {data.providers.length === 0 && (
        <div className="mb-4">
          <Note tone="warning">
            Nenhum provedor de IA conectado. <Link href="/integrations/" className="underline">Abra Integrações</Link> e adicione
            uma chave (ex.: Anthropic, Gemini ou DeepSeek) para ativar chat, agentes e desenvolvimento autônomo.
          </Note>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Gasto no mês" value={brl(data.budget.spent_brl)} hint={`de ${brl(data.budget.limit_brl)} · projeção ${brl(data.budget.projected_month_brl)}`}
          accent={!data.budget.alert} href="/usage/" />
        <Stat label="Missões ativas" value={num(c.active_missions)} hint={`sucesso 24h: ${pct(data.missions_24h.success_rate)}`} href="/missions/" />
        <Stat label="Aprovações pendentes" value={num(c.pending_approvals)} hint="publicações e ações sensíveis" href="/evolution/?tab=approvals" />
        <Stat label="Diagnósticos abertos" value={num(c.open_diagnostics)} hint={`${num(c.proposals_queued)} propostas na fila`} href="/evolution/?tab=diagnostics" />
      </div>

      <div className="mt-3"><Meter value={data.budget.usage_ratio} label="Uso do orçamento mensal" /></div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title={<span className="flex items-center gap-2"><Dna className="h-4 w-4 text-lime" /> Autoevolução</span>}
          action={<Link href="/evolution/"><Button variant="ghost">Abrir</Button></Link>}>
          <div className="mb-3 flex flex-wrap gap-2">
            <StatusPill status={ev.enabled ? (ev.paused ? "interrupted" : "active") : "disabled"}
              label={ev.enabled ? (ev.paused ? "Pausada" : "Contínua (ativa)") : "Desativada"} />
            <Badge tone={ev.auto_publish ? "lime" : "neutral"}>Publicação automática: {ev.auto_publish ? "baixo risco" : "desligada"}</Badge>
            <Badge>{num(c.published)} melhorias publicadas</Badge>
          </div>
          {ev.last_cycle ? (
            <div className="rounded-xl border border-line bg-surface-2 p-3">
              <div className="mb-1 flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium">Ciclo #{ev.last_cycle.number}</span>
                <StatusPill status={ev.last_cycle.status} />
                <span className="text-xs text-muted">{ago(ev.last_cycle.started_at)}</span>
              </div>
              <p className="text-sm text-ink-2">{ev.last_cycle.summary || `Fase atual: ${ev.last_cycle.phase}`}</p>
            </div>
          ) : (
            <Empty title="Nenhum ciclo executado ainda">O primeiro ciclo roda automaticamente poucos minutos após o servidor iniciar.</Empty>
          )}
        </Card>

        <Card title={<span className="flex items-center gap-2"><Activity className="h-4 w-4 text-lime" /> Últimas 24h</span>}>
          <ul className="space-y-2 text-sm">
            <li className="flex justify-between"><span className="text-ink-2">Chamadas de IA</span><span className="tabular-nums">{num(data.llm_24h.calls)}</span></li>
            <li className="flex justify-between"><span className="text-ink-2">Taxa de erro</span><span className="tabular-nums">{pct(data.llm_24h.error_rate, 1)}</span></li>
            <li className="flex justify-between"><span className="text-ink-2">Custo</span><span className="tabular-nums">{usd(data.llm_24h.cost_usd)}</span></li>
            <li className="flex justify-between"><span className="text-ink-2">Memórias</span><span className="tabular-nums">{num(c.memories)}</span></li>
            <li className="flex justify-between"><span className="text-ink-2">Agentes ativos</span><span className="tabular-nums">{num(c.agents_active)}</span></li>
          </ul>
        </Card>

        <Card title={<span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-lime" /> Diagnósticos automáticos</span>}
          className="lg:col-span-2" action={<Link href="/evolution/?tab=diagnostics"><Button variant="ghost">Ver todos</Button></Link>}>
          {data.diagnostics.length ? (
            <ul className="divide-y divide-line">
              {data.diagnostics.map((d) => (
                <li key={d.id} className="flex items-start justify-between gap-3 py-2">
                  <span className="min-w-0 text-sm text-ink">{d.title}</span>
                  <Badge tone={SEV[d.severity]}>{d.severity}</Badge>
                </li>
              ))}
            </ul>
          ) : <Empty title="Nenhum problema detectado" />}
        </Card>

        <Card title={<span className="flex items-center gap-2"><Plug className="h-4 w-4 text-lime" /> Provedores</span>}
          action={<Link href="/integrations/"><Button variant="ghost">Gerenciar</Button></Link>}>
          {data.providers.length ? (
            <ul className="space-y-2">
              {data.providers.map((p) => {
                const h = data.provider_health[p];
                return (
                  <li key={p} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${h?.open ? "bg-critical" : "bg-good pulse-dot"}`} />{p}</span>
                    <span className="text-xs text-muted">{h ? `${h.calls} chamadas · ${h.latency_ema_ms} ms` : "sem uso ainda"}</span>
                  </li>
                );
              })}
            </ul>
          ) : <Empty title="Nenhum provedor" />}
        </Card>

        <Card title={<span className="flex items-center gap-2"><Target className="h-4 w-4 text-lime" /> Missões recentes</span>} className="lg:col-span-3"
          action={<Link href="/missions/"><Button variant="ghost">Todas</Button></Link>}>
          {data.recent_missions.length ? (
            <ul className="divide-y divide-line">
              {data.recent_missions.map((m) => (
                <li key={m.id}>
                  <Link href={`/missions/?id=${m.id}`} className="flex items-center justify-between gap-3 py-2 hover:text-lime">
                    <span className="min-w-0 truncate text-sm">{m.title}</span>
                    <span className="flex shrink-0 items-center gap-2"><span className="hidden text-xs text-muted sm:inline">{ago(m.created_at)}</span><StatusPill status={m.status} /></span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : <Empty title="Nenhuma missão ainda">Crie uma em Missões ou escolha o modo “Missão” no chat.</Empty>}
        </Card>
      </div>
      <p className="mt-4 text-center text-[11px] text-muted">
        Servidor ativo há {Math.round(data.system.uptime_s / 60)} min · memória {data.system.max_rss_mb} MB · disco livre {data.system.disk_free_gb} GB
      </p>
    </>
  );
}

export default function Page() {
  return <Shell><Dashboard /></Shell>;
}
