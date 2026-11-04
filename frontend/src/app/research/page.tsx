"use client";

import { ArrowLeft, ExternalLink, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import Shell from "@/components/Shell";
import { Badge, Button, Card, Empty, ErrorNote, Markdown, Note, PageHeader, Spinner, StatusPill, inputCls } from "@/components/ui";
import { post } from "@/lib/api";
import { ago, usd } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";

type Source = { title: string; url: string; snippet: string; provider: string; reliability: number; fetched: boolean; error: string };
type Report = { id: string; query: string; status: string; summary: string; sub_queries: string[]; sources: Source[];
  search_provider: string; cost_usd: number; error: string; origin: string; created_at: string; sources_count?: number; summary_preview?: string };

function ReportView({ id }: { id: string }) {
  const { data } = useApi<Report>(`/api/research/${id}`, 3000);
  if (!data) return <Spinner />;
  return (
    <>
      <Link href="/research/" className="mb-3 inline-flex items-center gap-1 text-sm text-ink-2 hover:text-lime"><ArrowLeft className="h-4 w-4" /> Pesquisas</Link>
      <PageHeader title={data.query} subtitle={`${data.search_provider || "—"} · ${usd(data.cost_usd)} · ${ago(data.created_at)}`}
        actions={<StatusPill status={data.status} />} />
      {data.status === "running" && <Spinner label="Pesquisando, lendo fontes e sintetizando…" />}
      {data.error && <div className="mb-3"><Note tone="warning">{data.error}</Note></div>}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Relatório" className="lg:col-span-2">{data.summary ? <Markdown text={data.summary} /> : <p className="text-sm text-muted">Sem síntese.</p>}</Card>
        <Card title="Fontes" subtitle="Conteúdo externo é tratado como dado não confiável.">
          <ol className="space-y-3">
            {data.sources.map((s, i) => (
              <li key={i} className="text-sm">
                <a href={s.url} target="_blank" rel="noopener noreferrer nofollow" className="flex items-start gap-1 text-lime hover:underline">
                  <span className="shrink-0">[{i + 1}]</span><span className="min-w-0 break-words">{s.title || s.url}</span><ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
                </a>
                <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
                  <Badge tone={s.reliability >= 0.8 ? "good" : s.reliability >= 0.6 ? "info" : "neutral"}>confiabilidade {Math.round(s.reliability * 100)}%</Badge>
                  <Badge>{s.fetched ? "lida" : s.error || "não lida"}</Badge>
                </div>
              </li>
            ))}
          </ol>
          {data.sub_queries?.length > 0 && <p className="mt-3 text-xs text-muted">Consultas: {data.sub_queries.join(" · ")}</p>}
        </Card>
      </div>
    </>
  );
}

function ResearchList() {
  const router = useRouter();
  const { data, loading, reload } = useApi<Report[]>("/api/research", 5000);
  const [q, setQ] = useState("");
  const act = useAction();
  async function start() {
    const r = await act.run(() => post<{ id: string }>("/api/research", { query: q }));
    if (r) { setQ(""); reload(); router.push(`/research/?id=${r.id}`); }
  }
  return (
    <>
      <PageHeader icon={<Search className="h-6 w-6 text-lime" />} title="Pesquisa"
        subtitle="Pesquisa profunda: sub-consultas, leitura de fontes, comparação e relatório com citações." />
      <Card>
        <form onSubmit={(e) => { e.preventDefault(); start(); }} className="flex flex-col gap-2 sm:flex-row">
          <input className={inputCls} value={q} onChange={(e) => setQ(e.target.value)} placeholder="O que você quer investigar?" />
          <Button type="submit" variant="primary" busy={act.busy} disabled={q.trim().length < 3}>Pesquisar</Button>
        </form>
        <div className="mt-2"><ErrorNote error={act.error} /></div>
      </Card>
      <div className="mt-4 space-y-2">
        {loading && !data ? <Spinner /> : data?.length ? data.map((r) => (
          <Link key={r.id} href={`/research/?id=${r.id}`} className="block rounded-2xl border border-line bg-surface/80 p-3 hover:border-lime/40">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0"><div className="truncate text-sm font-medium">{r.query}</div>
                <div className="text-xs text-muted">{ago(r.created_at)} · {r.sources_count} fontes · {r.origin}</div></div>
              <StatusPill status={r.status} />
            </div>
            {r.summary_preview && <p className="mt-1 line-clamp-2 text-xs text-ink-2">{r.summary_preview}</p>}
          </Link>
        )) : <Empty title="Nenhuma pesquisa ainda" />}
      </div>
    </>
  );
}

function Router() {
  const id = useSearchParams().get("id");
  return id ? <ReportView id={id} /> : <ResearchList />;
}

export default function Page() {
  return <Shell><Suspense fallback={<Spinner />}><Router /></Suspense></Shell>;
}
