"use client";

import { CheckCircle2, ExternalLink, KeyRound, Plug, Trash2, XCircle } from "lucide-react";
import { useState } from "react";

import Shell from "@/components/Shell";
import { Badge, Button, Card, ErrorNote, Field, Note, PageHeader, Sheet, Spinner, inputCls } from "@/components/ui";
import { del, post, put } from "@/lib/api";
import { ago } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";

type Integration = { id: string; name: string; kind: string; key_url: string; note: string; key_required: boolean; configured: boolean;
  source: string | null; last4: string; base_url: string; enabled: boolean; last_test_at: string | null; last_test_ok: boolean | null;
  last_test_message: string; models: Record<string, string | null>; catalog: { id: string; tier: string; input_per_m: number; output_per_m: number }[] };

const KIND: Record<string, string> = { llm: "Modelos de IA", search: "Pesquisa na web", vcs: "Repositório (autoevolução)" };

function Editor({ it, onClose }: { it: Integration; onClose: () => void }) {
  const [key, setKey] = useState("");
  const [base, setBase] = useState(it.base_url || "");
  const [models, setModels] = useState<Record<string, string>>(Object.fromEntries(Object.entries(it.models).map(([k, v]) => [k, v || ""])));
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);
  const act = useAction();
  const needsUrl = it.id === "ollama" || it.id === "searxng";
  async function save() {
    await act.run(async () => {
      await put(`/api/integrations/${it.id}`, { api_key: key || undefined, base_url: base, enabled: true, models: it.kind === "llm" ? models : undefined });
      setKey("");
      setTest(await post<{ ok: boolean; message: string }>(`/api/integrations/${it.id}/test`));
    });
  }
  return (
    <Sheet open onClose={onClose} title={it.name}>
      <div className="space-y-3">
        {it.note && <Note>{it.note}</Note>}
        {it.key_url && (
          <a href={it.key_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm text-lime underline">
            Obter uma chave <ExternalLink className="h-3.5 w-3.5" /></a>
        )}
        {it.key_required && (
          <Field label={it.configured ? `Nova chave (atual termina em …${it.last4})` : "Chave de API"}
            hint="A chave é cifrada no servidor e nunca volta para o navegador.">
            <input className={inputCls} type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="cole aqui" />
          </Field>
        )}
        {(needsUrl || it.id === "openrouter" || it.kind === "llm") && (
          <Field label="URL base" hint={needsUrl ? "Endereço do seu servidor." : "Deixe como está, salvo se usar um proxy compatível."}>
            <input className={inputCls} value={base} onChange={(e) => setBase(e.target.value)} />
          </Field>
        )}
        {it.kind === "llm" && (
          <div className="rounded-xl border border-line p-3">
            <div className="mb-2 text-xs font-medium text-ink-2">Modelos por camada (o roteador escolhe a camada pela tarefa)</div>
            {(["fast", "balanced", "premium"] as const).map((t) => (
              <Field key={t} label={{ fast: "Rápida/econômica", balanced: "Equilibrada", premium: "Premium" }[t]}>
                <input className={`${inputCls} mb-2`} value={models[t] || ""} onChange={(e) => setModels({ ...models, [t]: e.target.value })} list={`m-${it.id}`} />
              </Field>
            ))}
            <datalist id={`m-${it.id}`}>{it.catalog.map((m) => <option key={m.id} value={m.id} />)}</datalist>
          </div>
        )}
        <ErrorNote error={act.error} />
        {test && <Note tone={test.ok ? "good" : "warning"}>{test.message}</Note>}
        <div className="flex gap-2">
          <Button variant="primary" className="flex-1" busy={act.busy} onClick={save} disabled={it.key_required && !it.configured && !key}>Salvar e testar</Button>
          {it.configured && it.source === "integrations" && (
            <Button variant="danger" busy={act.busy} onClick={() => act.run(async () => { await del(`/api/integrations/${it.id}`); onClose(); })}><Trash2 className="h-4 w-4" /></Button>
          )}
        </div>
        {it.source === "env" && <p className="text-xs text-muted">Esta chave vem das variáveis de ambiente do servidor; salvar aqui a substitui.</p>}
      </div>
    </Sheet>
  );
}

function Integrations() {
  const { data, error, loading, reload } = useApi<Integration[]>("/api/integrations");
  const [sel, setSel] = useState<Integration | null>(null);
  if (loading && !data) return <Spinner />;
  const groups = ["llm", "search", "vcs"];
  return (
    <>
      <PageHeader icon={<Plug className="h-6 w-6 text-lime" />} title="Integrações"
        subtitle="Conecte provedores de IA, busca e o GitHub. Chaves ficam apenas no backend, cifradas." />
      <ErrorNote error={error} />
      <div className="space-y-5">
        {groups.map((g) => (
          <div key={g}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{KIND[g]}</h2>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {(data || []).filter((i) => i.kind === g).map((i) => (
                <button key={i.id} onClick={() => setSel(i)} className="text-left">
                  <Card className="h-full transition-colors hover:border-lime/40">
                    <div className="flex items-start justify-between gap-2">
                      <div className="text-sm font-semibold">{i.name}</div>
                      {i.configured ? <Badge tone="good"><CheckCircle2 className="h-3 w-3" /> conectado</Badge> : <Badge><KeyRound className="h-3 w-3" /> configurar</Badge>}
                    </div>
                    {i.configured && (
                      <div className="mt-2 space-y-1 text-xs text-muted">
                        <div>{i.source === "env" ? "via variável de ambiente" : `chave …${i.last4}`}</div>
                        {i.last_test_at && (
                          <div className="flex items-center gap-1">
                            {i.last_test_ok ? <CheckCircle2 className="h-3 w-3 text-good" /> : <XCircle className="h-3 w-3 text-critical" />}
                            teste {ago(i.last_test_at)}: <span className="truncate">{i.last_test_message}</span>
                          </div>
                        )}
                        {i.kind === "llm" && <div className="truncate">modelos: {Object.values(i.models).filter(Boolean).join(" · ")}</div>}
                      </div>
                    )}
                    {!i.configured && i.note && <p className="mt-2 text-xs text-muted">{i.note}</p>}
                  </Card>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      {sel && <Editor it={sel} onClose={() => { setSel(null); reload(); }} />}
    </>
  );
}

export default function Page() {
  return <Shell><Integrations /></Shell>;
}
