"use client";

import { Code, File, Folder, GitBranch, RefreshCw } from "lucide-react";
import { useState } from "react";

import Shell from "@/components/Shell";
import { Badge, Button, Card, Empty, ErrorNote, Note, PageHeader, Sheet, Spinner, StatusPill } from "@/components/ui";
import { get, post } from "@/lib/api";
import { ago, dateTime } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";

type WS = { ready: boolean; error?: string; base_branch: string; head: string; remote: boolean; push_enabled: boolean;
  branches: { name: string; sha: string; date: string; subject: string }[]; log: { sha: string; author: string; date: string; subject: string }[];
  sandbox: { isolation: string; capabilities: Record<string, boolean> } };
type Run = { id: string; label: string; command: string[]; status: string; exit_code: number | null; duration_ms: number;
  stdout_tail: string; stderr_tail: string; isolation: Record<string, unknown>; parsed: Record<string, unknown>; created_at: string };

function Workspace() {
  const ws = useApi<WS>("/api/workspace/status", 15000);
  const runs = useApi<Run[]>("/api/workspace/sandbox-runs", 10000);
  const [path, setPath] = useState(".");
  const tree = useApi<{ entries: string[] }>(`/api/workspace/tree?path=${encodeURIComponent(path)}`);
  const [file, setFile] = useState<{ path: string; content: string } | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const act = useAction();
  const w = ws.data;
  return (
    <>
      <PageHeader icon={<Code className="h-6 w-6 text-lime" />} title="Workspace de desenvolvimento"
        subtitle="Clone isolado do repositório do ULTRON: branches de evolução, código (somente leitura) e execuções do sandbox."
        actions={<Button busy={act.busy} onClick={() => act.run(async () => { await post("/api/workspace/sync"); ws.reload(); })}><RefreshCw className="h-4 w-4" /> Sincronizar</Button>} />
      <ErrorNote error={act.error} />
      {!w ? <Spinner /> : !w.ready ? <Note tone="warning">Workspace indisponível: {w.error}</Note> : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Repositório">
            <ul className="space-y-1 text-sm">
              <li>Branch estável: <b className="font-mono">{w.base_branch}</b></li>
              <li>HEAD: <span className="font-mono text-xs text-lime">{w.head.slice(0, 12)}</span></li>
              <li>Remoto: {w.remote ? "configurado" : "não"} · Push: {w.push_enabled ? <Badge tone="good">habilitado</Badge> : <Badge>sem token</Badge>}</li>
              <li>Sandbox: <Badge tone={w.sandbox.capabilities.unshare_net ? "good" : "warning"}>{w.sandbox.isolation}</Badge></li>
            </ul>
            <h4 className="mb-1 mt-4 text-xs font-semibold uppercase text-muted">Histórico recente</h4>
            <ul className="space-y-1">{w.log.map((c) => <li key={c.sha} className="text-xs"><span className="font-mono text-lime">{c.sha}</span> {c.subject} <span className="text-muted">· {c.author}</span></li>)}</ul>
          </Card>
          <Card title={<span className="flex items-center gap-2"><GitBranch className="h-4 w-4" /> Branches de evolução</span>}>
            {w.branches.length ? <ul className="space-y-2">{w.branches.map((b) => (
              <li key={b.name} className="text-xs"><div className="truncate font-mono text-ink">{b.name}</div><div className="text-muted">{b.subject} · {b.date.slice(0, 16)}</div></li>))}</ul>
              : <Empty title="Nenhuma branch de evolução" />}
          </Card>
          <Card title="Arquivos (somente leitura)">
            <div className="mb-2 flex items-center gap-2 text-xs">
              <span className="font-mono text-ink-2">{path}</span>
              {path !== "." && <button className="text-lime" onClick={() => setPath(path.includes("/") ? path.split("/").slice(0, -1).join("/") : ".")}>voltar</button>}
            </div>
            {tree.loading ? <Spinner /> : (
              <ul className="max-h-80 space-y-0.5 overflow-y-auto">
                {(tree.data?.entries || []).map((e) => (
                  <li key={e}><button className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-surface-3"
                    onClick={async () => e.endsWith("/") ? setPath(e.slice(0, -1)) : setFile(await get(`/api/workspace/file?path=${encodeURIComponent(e)}`))}>
                    {e.endsWith("/") ? <Folder className="h-3.5 w-3.5 text-lime" /> : <File className="h-3.5 w-3.5 text-muted" />}
                    <span className="truncate font-mono">{e.split("/").filter(Boolean).pop()}</span>
                  </button></li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Execuções no sandbox" className="lg:col-span-3" subtitle="Testes, compilação e lint executados em ambiente isolado, sem segredos.">
            {runs.data?.length ? (
              <ul className="divide-y divide-line">
                {runs.data.map((r) => (
                  <li key={r.id}><button onClick={() => setRun(r)} className="flex w-full items-center justify-between gap-2 py-2 text-left text-xs hover:text-lime">
                    <span className="min-w-0 truncate"><b>{r.label}</b> <span className="text-muted">{dateTime(r.created_at)} · {(r.duration_ms / 1000).toFixed(1)}s · rede {String(r.isolation?.network)}</span></span>
                    <StatusPill status={r.status === "ok" ? "ok" : "failed"} label={r.status} />
                  </button></li>
                ))}
              </ul>
            ) : <Empty title="Nenhuma execução ainda" />}
          </Card>
        </div>
      )}
      {file && <Sheet open onClose={() => setFile(null)} title={file.path} wide><pre className="overflow-x-auto whitespace-pre text-[11px] leading-relaxed text-ink-2">{file.content}</pre></Sheet>}
      {run && (
        <Sheet open onClose={() => setRun(null)} title={run.label} wide>
          <p className="mb-2 font-mono text-[11px] text-muted">{run.command.join(" ")} · saída {String(run.exit_code)} · {ago(run.created_at)}</p>
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap text-[11px] text-ink-2">{run.stdout_tail}{run.stderr_tail && `\n--- stderr ---\n${run.stderr_tail}`}</pre>
        </Sheet>
      )}
    </>
  );
}

export default function Page() {
  return <Shell><Workspace /></Shell>;
}
