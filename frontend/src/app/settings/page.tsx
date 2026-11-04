"use client";

import { Settings } from "lucide-react";
import { useState } from "react";

import Shell from "@/components/Shell";
import { Button, Card, ErrorNote, Field, KV, Note, PageHeader, Spinner, Toggle, inputCls } from "@/components/ui";
import { apiBase, post, put, setApiBase } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";

type SettingsData = { values: Record<string, unknown>; server: Record<string, unknown> };

const BOOL: [string, string, string][] = [
  ["memory.auto_extract", "Aprender com as conversas", "Extrai fatos e preferências duráveis com um modelo econômico."],
  ["memory.agents_can_read_personal", "Agentes podem ler memória pessoal", "Desative para que só o chat use dados pessoais."],
  ["evolution.research_enabled", "Pesquisa na autoevolução", "Pesquisa soluções na web para diagnósticos graves."],
  ["autonomy.allow_agent_creation", "Permitir que o ULTRON proponha novos agentes", "Novos agentes sempre exigem sua aprovação."],
  ["publication.require_ci_when_github", "Exigir CI verde no GitHub antes de publicar", "Recomendado."],
  ["publication.auto_rollback", "Rollback automático em regressão", "Reverte publicações se os erros subirem após o deploy."],
];
const NUMS: [string, string, string][] = [
  ["evolution.interval_minutes", "Intervalo entre ciclos (min)", "Padrão 360 (6 h)."],
  ["evolution.cycle_budget_usd", "Orçamento por ciclo (US$)", ""],
  ["evolution.monthly_budget_share", "Fatia mensal da evolução (0–1)", "Parte do orçamento mensal reservada à autoevolução."],
  ["evolution.max_proposals_per_cycle", "Propostas por ciclo", ""],
  ["evolution.max_developments_per_cycle", "Desenvolvimentos por ciclo", "Limite de concorrência da autoevolução."],
  ["evolution.cycle_max_minutes", "Duração máxima do ciclo (min)", ""],
  ["evolution.monitor_minutes", "Monitoramento pós-publicação (min)", ""],
  ["research.max_sources", "Fontes por pesquisa", ""],
];

function SettingsPage() {
  const { data, error, loading, reload } = useApi<SettingsData>("/api/settings");
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [server, setServer] = useState(apiBase());
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const act = useAction();
  if (loading && !data) return <Spinner />;
  if (!data) return <ErrorNote error={error} />;
  const v = data.values;
  const scopes = (v["autonomy.granted_scopes"] as string[]) || [];
  const setBool = (k: string, b: boolean) => act.run(async () => { await put("/api/settings", { values: { [k]: b } }); reload(); });
  async function saveNums() {
    const values = Object.fromEntries(Object.entries(edit).map(([k, x]) => [k, Number(x)]));
    await act.run(async () => { await put("/api/settings", { values }); setEdit({}); reload(); });
  }
  const SCOPES: [string, string][] = [["read_analyze", "Ler e analisar"], ["develop_sandbox", "Desenvolver no sandbox"],
    ["external_access", "Acessar a web e serviços externos"], ["memory_write", "Gravar memória"]];
  return (
    <>
      <PageHeader icon={<Settings className="h-6 w-6 text-lime" />} title="Configurações" />
      <ErrorNote error={act.error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Permissões da autonomia" subtitle="Escopos concedidos aos agentes. Publicar nunca é concedido a agentes — só à política de publicação.">
          <ul className="space-y-2">
            {SCOPES.map(([id, label]) => (
              <li key={id} className="flex items-center justify-between gap-3 text-sm">{label}
                <Toggle checked={scopes.includes(id)} label={label} onChange={(b) => act.run(async () => {
                  await put("/api/settings", { values: { "autonomy.granted_scopes": b ? [...scopes, id] : scopes.filter((s) => s !== id) } }); reload();
                })} />
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Comportamento">
          <ul className="space-y-3">
            {BOOL.map(([k, label, hint]) => (
              <li key={k} className="flex items-start justify-between gap-3">
                <div><div className="text-sm">{label}</div><div className="text-xs text-muted">{hint}</div></div>
                <Toggle checked={Boolean(v[k])} label={label} onChange={(b) => setBool(k, b)} />
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Autoevolução e pesquisa" className="lg:col-span-2">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {NUMS.map(([k, label, hint]) => (
              <Field key={k} label={label} hint={hint || undefined}>
                <input className={inputCls} inputMode="decimal" value={edit[k] ?? String(v[k] ?? "")} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} />
              </Field>
            ))}
          </div>
          <div className="mt-3 text-right"><Button variant="primary" onClick={saveNums} busy={act.busy} disabled={!Object.keys(edit).length}>Salvar</Button></div>
        </Card>
        <Card title="Conexão com o servidor">
          <Field label="Endereço do backend" hint="Vazio = mesma origem da interface.">
            <input className={inputCls} value={server} onChange={(e) => setServer(e.target.value)} />
          </Field>
          <div className="mt-2"><Button onClick={() => { setApiBase(server); location.reload(); }}>Salvar</Button></div>
          <div className="mt-3"><KV items={Object.entries(data.server).map(([k, x]) => [k, String(x)])} /></div>
        </Card>
        <Card title="Alterar senha">
          <div className="space-y-2">
            <input className={inputCls} type="password" placeholder="Senha atual" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />
            <input className={inputCls} type="password" placeholder="Nova senha" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
            <Button busy={act.busy} onClick={() => act.run(async () => { const r = await post<{ message: string }>("/api/auth/change-password", pw); setMsg(r.message); setPw({ current_password: "", new_password: "" }); })}>Alterar</Button>
            {msg && <Note tone="good">{msg}</Note>}
          </div>
        </Card>
      </div>
    </>
  );
}

export default function Page() {
  return <Shell><SettingsPage /></Shell>;
}
