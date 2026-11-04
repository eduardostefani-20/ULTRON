"use client";

import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react";
import { useState } from "react";

import Shell from "@/components/Shell";
import { Badge, Button, Card, ErrorNote, JsonBlock, KV, PageHeader, Sheet, Spinner, Stat } from "@/components/ui";
import { get } from "@/lib/api";
import { dateTime, num } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Sec = { governance_fingerprint: string; governance_files: Record<string, string>;
  audit_chain: { valid: boolean; entries: number; message: string }; granted_scopes: string[]; forbidden_paths: string[];
  sandbox: { isolation: string; capabilities: Record<string, boolean> }; selftest: { passed: boolean; at: string | null };
  auto_publish: boolean; denied_tool_calls_7d: number; failed_logins_7d: number; production: boolean; secret_key_from_env: boolean;
  setup_token_configured: boolean };
type Entry = { seq: number; ts: string; actor: string; action: string; target: string; details: Record<string, unknown>; hash: string };

function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      {ok ? <CheckCircle2 className="h-4 w-4 text-good" /> : <XCircle className="h-4 w-4 text-critical" />} {label}
    </li>
  );
}

function Security() {
  const sec = useApi<Sec>("/api/security/status", 30000);
  const [filter, setFilter] = useState("");
  const audit = useApi<Entry[]>(`/api/audit?limit=150&action=${encodeURIComponent(filter)}`, 15000);
  const [sel, setSel] = useState<Entry | null>(null);
  const [verify, setVerify] = useState<string | null>(null);
  if (!sec.data) return sec.error ? <ErrorNote error={sec.error} /> : <Spinner />;
  const s = sec.data;
  return (
    <>
      <PageHeader icon={<ShieldCheck className="h-6 w-6 text-lime" />} title="Segurança e auditoria"
        subtitle="Proteções independentes dos agentes: política em código, auditoria encadeada, sandbox e permissões." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Auditoria" value={s.audit_chain.valid ? "Íntegra" : "QUEBRADA"} hint={`${num(s.audit_chain.entries)} registros`} accent={s.audit_chain.valid} />
        <Stat label="Autoteste" value={s.selftest.passed ? "Aprovado" : "Pendente"} hint={dateTime(s.selftest.at)} />
        <Stat label="Ferramentas negadas (7d)" value={num(s.denied_tool_calls_7d)} />
        <Stat label="Logins falhos (7d)" value={num(s.failed_logins_7d)} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Postura">
          <ul className="space-y-1.5">
            <Check ok={s.audit_chain.valid} label="Cadeia de auditoria íntegra (hash encadeado + banco recusa UPDATE/DELETE)" />
            <Check ok={s.sandbox.capabilities.unshare_net || s.sandbox.capabilities.docker} label={`Sandbox com rede isolada (${s.sandbox.isolation})`} />
            <Check ok={s.selftest.passed} label="Autoteste de segurança aprovado" />
            <Check ok={!s.granted_scopes.includes("publish")} label="Agentes sem permissão de publicar" />
            <Check ok={!s.production || s.secret_key_from_env} label="Chave mestra definida no ambiente" />
            <Check ok={!s.production || s.setup_token_configured} label="Token de configuração inicial definido" />
          </ul>
          <div className="mt-3 flex flex-wrap gap-1.5">{s.granted_scopes.map((x) => <Badge key={x} tone="info">{x}</Badge>)}<Badge tone={s.auto_publish ? "lime" : "neutral"}>auto-publicação: {s.auto_publish ? "baixo risco" : "desligada"}</Badge></div>
          <div className="mt-3 flex items-center gap-2">
            <Button onClick={async () => { const r = await get<{ message: string }>("/api/audit/verify"); setVerify(r.message); }}>Verificar cadeia agora</Button>
            {verify && <span className="text-sm text-ink-2">{verify}</span>}
          </div>
        </Card>
        <Card title="Integridade da governança" subtitle="Hash dos arquivos que implementam as proteções (registrado a cada inicialização).">
          <p className="mb-2 break-all font-mono text-[11px] text-lime">{s.governance_fingerprint}</p>
          <details><summary className="cursor-pointer text-xs text-ink-2">Arquivos protegidos ({Object.keys(s.governance_files).length})</summary>
            <KV items={Object.entries(s.governance_files).map(([k, v]) => [k, <span key={k} className="font-mono text-[10px] text-muted">{v.slice(0, 16)}…</span>])} /></details>
          <details className="mt-2"><summary className="cursor-pointer text-xs text-ink-2">Caminhos que nenhum agente pode alterar</summary>
            <ul className="mt-1 font-mono text-[11px] text-ink-2">{s.forbidden_paths.map((p) => <li key={p}>{p}</li>)}</ul></details>
        </Card>
        <Card title="Registro de auditoria" className="lg:col-span-2"
          action={<select className="rounded-lg border border-line bg-surface-2 px-2 py-1 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">todos</option><option value="auth.">autenticação</option><option value="proposal.">propostas</option><option value="approval.">aprovações</option>
            <option value="settings.">configurações</option><option value="tool.">ferramentas</option><option value="integration.">integrações</option>
            <option value="security.">segurança</option><option value="governance.">governança</option></select>}>
          {audit.loading && !audit.data ? <Spinner /> : (
            <ul className="divide-y divide-line">
              {(audit.data || []).map((e) => (
                <li key={e.seq}><button onClick={() => setSel(e)} className="flex w-full items-center justify-between gap-2 py-2 text-left text-xs hover:text-lime">
                  <span className="min-w-0 truncate"><span className="text-muted">#{e.seq} {dateTime(e.ts)}</span> <b>{e.action}</b> {e.target}</span>
                  <span className="shrink-0 text-muted">{e.actor}</span>
                </button></li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {sel && <Sheet open onClose={() => setSel(null)} title={`#${sel.seq} ${sel.action}`}><JsonBlock value={sel} /></Sheet>}
    </>
  );
}

export default function Page() {
  return <Shell><Security /></Shell>;
}
