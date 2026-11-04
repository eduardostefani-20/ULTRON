"use client";

import { Network, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import Shell from "@/components/Shell";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, Spinner, Stat, inputCls } from "@/components/ui";
import { post } from "@/lib/api";
import { ago, num } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";

type Module = { path: string; language: string; lines: number; symbols: string[]; imports: string[]; imported_by: number;
  functions: number; classes: number; max_complexity: number; is_test: boolean; todo: number };
type Snap = { available: boolean; commit_sha?: string; created_at?: string; summary?: Record<string, number>; modules?: Module[];
  edges?: { from: string; to: string }[]; findings?: { severity: string; kind: string; title: string; path: string }[] };

const SEV: Record<string, string> = { high: "serious", medium: "warning", low: "info", info: "neutral" };

function pkgOf(p: string) {
  const parts = p.split("/");
  return parts[0] === "backend" && parts.length > 3 ? parts.slice(0, 3).join("/") : parts.slice(0, Math.min(3, parts.length - 1)).join("/") || parts[0];
}

function Architecture() {
  const { data, error, loading, setData } = useApi<Snap>("/api/system/architecture");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const act = useAction();
  const groups = useMemo(() => {
    const g: Record<string, Module[]> = {};
    for (const m of data?.modules || []) {
      if (q && !m.path.toLowerCase().includes(q.toLowerCase())) continue;
      (g[pkgOf(m.path)] ||= []).push(m);
    }
    return Object.entries(g).sort((a, b) => a[0].localeCompare(b[0]));
  }, [data, q]);
  const selected = data?.modules?.find((m) => m.path === sel);
  const dependents = (data?.edges || []).filter((e) => e.to === sel).map((e) => e.from);
  if (loading && !data) return <Spinner />;
  return (
    <>
      <PageHeader icon={<Network className="h-6 w-6 text-lime" />} title="Arquitetura do sistema"
        subtitle="Mapa gerado pela inteligência de código do ULTRON a partir do próprio repositório."
        actions={<Button busy={act.busy} onClick={() => act.run(async () => setData(await post<Snap>("/api/system/architecture/refresh")))}><RefreshCw className="h-4 w-4" /> Atualizar mapa</Button>} />
      <ErrorNote error={error || act.error} />
      {!data?.available ? <Empty title="Mapa ainda não gerado">Toque em “Atualizar mapa” ou aguarde o primeiro ciclo de evolução.</Empty> : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Stat label="Arquivos" value={num(data.summary?.files)} hint={`${num(data.summary?.lines)} linhas`} accent />
            <Stat label="Módulos Python" value={num(data.summary?.python_modules)} hint={`${num(data.summary?.functions)} funções`} />
            <Stat label="Módulos TS" value={num(data.summary?.typescript_modules)} />
            <Stat label="Testes" value={num(data.summary?.test_functions)} hint={`${num(data.summary?.test_files)} arquivos`} />
            <Stat label="Dependências" value={num(data.summary?.dependencies)} hint={`${num(data.summary?.import_cycles)} ciclos`} />
          </div>
          <p className="mt-2 text-xs text-muted">Commit {data.commit_sha?.slice(0, 10)} · gerado {ago(data.created_at)}</p>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card title="Módulos" className="lg:col-span-2" action={<input className={`${inputCls} w-40`} placeholder="filtrar" value={q} onChange={(e) => setQ(e.target.value)} />}>
              <div className="space-y-3">
                {groups.map(([pkg, mods]) => (
                  <details key={pkg} open={groups.length < 6}>
                    <summary className="cursor-pointer text-sm font-medium">{pkg} <span className="text-xs text-muted">· {mods.length} · {num(mods.reduce((s, m) => s + m.lines, 0))} linhas</span></summary>
                    <ul className="mt-1 grid gap-1 sm:grid-cols-2">
                      {mods.map((m) => (
                        <li key={m.path}><button onClick={() => setSel(m.path)} className={`w-full rounded-lg border px-2 py-1 text-left text-xs hover:border-lime/40 ${sel === m.path ? "border-lime/50" : "border-line"}`}>
                          <div className="truncate font-mono">{m.path.split("/").pop()}</div>
                          <div className="text-[10px] text-muted">{m.lines} linhas · usado por {m.imported_by}{m.is_test ? " · teste" : ""}</div>
                        </button></li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
            </Card>
            <div className="min-w-0 space-y-4">
              <Card title={selected ? selected.path : "Detalhes do módulo"}>
                {selected ? (
                  <div className="space-y-2 text-xs">
                    <div className="flex flex-wrap gap-1"><Badge>{selected.language}</Badge><Badge>{selected.lines} linhas</Badge><Badge>{selected.functions} funções</Badge>
                      {selected.max_complexity > 0 && <Badge tone={selected.max_complexity > 20 ? "warning" : "neutral"}>complexidade máx. {selected.max_complexity}</Badge>}</div>
                    {selected.symbols.length > 0 && <p className="text-ink-2">Símbolos: {selected.symbols.slice(0, 20).join(", ")}</p>}
                    <div><b className="text-muted">Importa</b><ul className="font-mono">{selected.imports.map((x) => <li key={x}><button className="hover:text-lime" onClick={() => setSel(x)}>{x}</button></li>)}</ul></div>
                    <div><b className="text-muted">Usado por</b><ul className="font-mono">{dependents.map((x) => <li key={x}><button className="hover:text-lime" onClick={() => setSel(x)}>{x}</button></li>)}</ul></div>
                  </div>
                ) : <p className="text-sm text-muted">Selecione um módulo para ver suas dependências.</p>}
              </Card>
              <Card title="Achados da análise">
                {data.findings?.length ? (
                  <ul className="space-y-1.5">{data.findings.slice(0, 40).map((f, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs"><Badge tone={SEV[f.severity]}>{f.kind}</Badge><span className="min-w-0 break-words text-ink-2">{f.title}</span></li>))}</ul>
                ) : <Empty title="Nenhum achado" />}
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
}

export default function Page() {
  return <Shell><Architecture /></Shell>;
}
