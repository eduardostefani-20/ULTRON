"use client";

import { Brain, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";

import Shell from "@/components/Shell";
import { Badge, Button, Card, Empty, ErrorNote, Field, PageHeader, Sheet, Spinner, Stat, inputCls } from "@/components/ui";
import { del, patch, post } from "@/lib/api";
import { ago, num } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";

type Item = { id: string; kind: string; status: string; content: string; tags: string[]; source: string; importance: number;
  access_count: number; updated_at: string; expires_at: string | null; score?: number; access_scope: string };
type Stats = { total: number; by_kind: Record<string, number>; by_status: Record<string, number>; ever_recalled: number;
  embedding: string; kinds: string[]; statuses: string[]; retention_days: Record<string, number> };

const KIND_PT: Record<string, string> = { conversation: "conversa", personal: "pessoal", operational: "operacional", semantic: "semântica",
  document: "documento", decision: "decisão", task: "tarefa", learning: "aprendizado", technical: "técnica" };
const STATUS_PT: Record<string, [string, string]> = { confirmed: ["confirmada", "good"], hypothesis: ["hipótese", "warning"],
  outdated: ["desatualizada", "neutral"], unverified: ["não verificada", "info"], preference: ["preferência", "lime"], decision: ["decisão técnica", "info"] };

function Memory() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const stats = useApi<Stats>("/api/memory/stats");
  const list = useApi<Item[]>(`/api/memory?limit=100&kind=${kind}&q=${encodeURIComponent(query)}`);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ content: "", kind: "personal", status: "confirmed" });
  const act = useAction();

  async function add() {
    const r = await act.run(() => post("/api/memory", form));
    if (r) { setOpen(false); setForm({ content: "", kind: "personal", status: "confirmed" }); list.reload(); stats.reload(); }
  }
  const s = stats.data;
  return (
    <>
      <PageHeader icon={<Brain className="h-6 w-6 text-lime" />} title="Memória"
        subtitle="Conhecimento persistente com status de confiabilidade. O ULTRON recupera só o que é relevante para cada tarefa."
        actions={<Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Adicionar</Button>} />
      {s && (
        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Memórias" value={num(s.total)} accent />
          <Stat label="Já recuperadas" value={num(s.ever_recalled)} />
          <Stat label="Confirmadas" value={num(s.by_status.confirmed)} />
          <Stat label="Hipóteses / não verificadas" value={num((s.by_status.hypothesis ?? 0) + (s.by_status.unverified ?? 0))} />
        </div>
      )}
      <Card>
        <form onSubmit={(e) => { e.preventDefault(); setQuery(q); }} className="flex flex-wrap gap-2">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" />
            <input className={`${inputCls} pl-9`} placeholder="Buscar por significado (ex.: minhas preferências)" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <select className={`${inputCls} w-auto`} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Tipo">
            <option value="">todos os tipos</option>
            {(s?.kinds || []).map((k) => <option key={k} value={k}>{KIND_PT[k] ?? k}</option>)}
          </select>
          <Button type="submit">Buscar</Button>
        </form>
        <div className="mt-4">
          {list.loading && !list.data ? <Spinner /> : list.data?.length ? (
            <ul className="divide-y divide-line">
              {list.data.map((m) => (
                <li key={m.id} className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 whitespace-pre-wrap text-sm">{m.content}</p>
                    <button onClick={async () => { await del(`/api/memory/${m.id}`); list.reload(); stats.reload(); }}
                      aria-label="Apagar memória" className="shrink-0 rounded-lg p-1.5 text-muted hover:text-critical"><Trash2 className="h-4 w-4" /></button>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
                    <Badge>{KIND_PT[m.kind] ?? m.kind}</Badge>
                    <select value={m.status} aria-label="Status"
                      onChange={async (e) => { await patch(`/api/memory/${m.id}`, { status: e.target.value }); list.reload(); }}
                      className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[11px]">
                      {Object.entries(STATUS_PT).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
                    </select>
                    {m.score !== undefined && <Badge tone="lime">relevância {m.score.toFixed(2)}</Badge>}
                    <span className="text-muted">{ago(m.updated_at)} · {m.source || "—"} · usada {m.access_count}x{m.expires_at ? " · expira" : ""}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : <Empty title="Nenhuma memória encontrada">O ULTRON aprende fatos duráveis das conversas automaticamente (pode ser desativado em Configurações).</Empty>}
          <ErrorNote error={list.error} />
        </div>
      </Card>
      {s && <p className="mt-3 text-xs text-muted">Busca: {s.embedding}. Retenção (dias): {Object.entries(s.retention_days || {}).map(([k, v]) => `${KIND_PT[k] ?? k} ${v}`).join(", ")}.</p>}
      <Sheet open={open} onClose={() => setOpen(false)} title="Nova memória">
        <div className="space-y-3">
          <Field label="Conteúdo"><textarea className={`${inputCls} min-h-24`} value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Tipo"><select className={inputCls} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {(s?.kinds || []).map((k) => <option key={k} value={k}>{KIND_PT[k] ?? k}</option>)}</select></Field>
            <Field label="Confiabilidade"><select className={inputCls} value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              {Object.entries(STATUS_PT).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          </div>
          <ErrorNote error={act.error} />
          <Button variant="primary" className="w-full" onClick={add} busy={act.busy} disabled={form.content.trim().length < 2}>Salvar</Button>
        </div>
      </Sheet>
    </>
  );
}

export default function Page() {
  return <Shell><Memory /></Shell>;
}
