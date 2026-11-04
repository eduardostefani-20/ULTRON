"use client";

import { ChevronDown, Dna, History, Loader2, Plus, Send, ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import Shell from "@/components/Shell";
import { Badge, Button, ErrorNote, JsonBlock, Markdown, Sheet, cx } from "@/components/ui";
import { ApiError, del, get, post } from "@/lib/api";
import { ago, usd } from "@/lib/format";

type Msg = { id: string; role: string; content: string; mode: string; model: string; meta: Record<string, unknown>;
  cost_usd: number; feedback: number | null; created_at: string; pending?: boolean };
type Conv = { id: string; title: string; messages?: number; updated_at?: string };

const MODES = [
  { id: "AUTO", label: "Automático", hint: "o ULTRON escolhe" },
  { id: "QUICK", label: "Rápido", hint: "barato e direto" },
  { id: "STANDARD", label: "Padrão", hint: "com memória e ferramentas" },
  { id: "COUNCIL", label: "Conselho", hint: "vários modelos" },
  { id: "DEEP_RESEARCH", label: "Pesquisa", hint: "fontes e citações" },
  { id: "ENGINEERING", label: "Engenharia", hint: "decisão técnica" },
  { id: "MISSION", label: "Missão", hint: "tarefa longa em 2º plano" },
];

function CouncilDetails({ meta }: { meta: Record<string, unknown> }) {
  const members = (meta.members as { member: string; model: string; answer: string }[]) || [];
  const critique = (meta.critique as { divergences?: { topic: string; assessment?: string; positions?: Record<string, string> }[];
    consensus?: string[]; errors?: string[] }) || {};
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted">Diversidade: {String(meta.diversity ?? "—")} · {String(meta.note ?? "")}</p>
      {critique.consensus?.length ? (<div><h4 className="mb-1 text-xs font-semibold uppercase text-muted">Consenso</h4>
        <ul className="list-disc pl-5">{critique.consensus.map((c, i) => <li key={i}>{c}</li>)}</ul></div>) : null}
      {critique.divergences?.length ? (<div><h4 className="mb-1 text-xs font-semibold uppercase text-muted">Divergências registradas</h4>
        <ul className="space-y-2">{critique.divergences.map((d, i) => (
          <li key={i} className="rounded-xl border border-line p-2"><div className="font-medium">{d.topic}</div>
            {d.positions && <ul className="mt-1 text-xs text-ink-2">{Object.entries(d.positions).map(([k, v]) => <li key={k}><b>{k}:</b> {v}</li>)}</ul>}
            {d.assessment && <p className="mt-1 text-xs text-muted">Avaliação: {d.assessment}</p>}</li>))}</ul></div>) : null}
      {critique.errors?.length ? (<div><h4 className="mb-1 text-xs font-semibold uppercase text-muted">Erros apontados</h4>
        <ul className="list-disc pl-5">{critique.errors.map((c, i) => <li key={i}>{c}</li>)}</ul></div>) : null}
      {members.map((m) => (
        <details key={m.member} className="rounded-xl border border-line p-2">
          <summary className="cursor-pointer text-xs text-ink-2">Membro {m.member} — {m.model}</summary>
          <div className="mt-2"><Markdown text={m.answer} /></div>
        </details>
      ))}
    </div>
  );
}

function MessageBubble({ m, onFeedback, onPropose }: { m: Msg; onFeedback: (v: number) => void; onPropose: () => void }) {
  const [open, setOpen] = useState(false);
  const mine = m.role === "user";
  const sources = (m.meta?.sources as { title?: string; url: string }[]) || [];
  const hasDetails = m.mode === "COUNCIL" || m.mode === "ENGINEERING" || Boolean(m.meta?.tools_used);
  return (
    <div className={cx("flex fade-up", mine ? "justify-end" : "justify-start")}>
      <div className={cx("max-w-[92%] rounded-2xl px-4 py-3 sm:max-w-[80%]", mine ? "bg-lime/12 border border-lime/30" : "border border-line bg-surface")}>
        {m.pending ? (
          <div className="flex items-center gap-2 text-sm text-ink-2"><Loader2 className="h-4 w-4 animate-spin" /> {m.content}</div>
        ) : mine ? <p className="whitespace-pre-wrap text-sm">{m.content}</p> : <Markdown text={m.content} />}
        {!mine && !m.pending && (
          <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-2 text-[11px] text-muted">
            <Badge tone="lime">{m.mode}</Badge>
            {m.model && <span className="truncate">{m.model}</span>}
            {m.cost_usd > 0 && <span>{usd(m.cost_usd, 5)}</span>}
            {sources.length > 0 && <span>{sources.length} fontes</span>}
            <span className="ml-auto flex items-center gap-1">
              {hasDetails && <button onClick={() => setOpen(true)} className="rounded-md px-1.5 py-0.5 hover:bg-surface-3 hover:text-ink">detalhes</button>}
              <button aria-label="Resposta útil" onClick={() => onFeedback(m.feedback === 1 ? 0 : 1)}
                className={cx("rounded-md p-1 hover:bg-surface-3", m.feedback === 1 && "text-good")}><ThumbsUp className="h-3.5 w-3.5" /></button>
              <button aria-label="Resposta ruim" onClick={() => onFeedback(m.feedback === -1 ? 0 : -1)}
                className={cx("rounded-md p-1 hover:bg-surface-3", m.feedback === -1 && "text-critical")}><ThumbsDown className="h-3.5 w-3.5" /></button>
            </span>
          </div>
        )}
        {m.mode === "ENGINEERING" && Boolean(m.meta?.decision_record) && (
          <Button className="mt-2" onClick={onPropose}><Dna className="h-4 w-4" /> Criar proposta de evolução</Button>
        )}
        {open && (
          <Sheet open onClose={() => setOpen(false)} title={`Detalhes — ${m.mode}`} wide>
            {m.mode === "COUNCIL" ? <CouncilDetails meta={m.meta} /> : <JsonBlock value={m.meta} />}
          </Sheet>
        )}
      </div>
    </div>
  );
}

function Chat() {
  const [convs, setConvs] = useState<Conv[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [mode, setMode] = useState("AUTO");
  const [modeOpen, setModeOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const loadConvs = useCallback(async () => {
    try { setConvs(await get<Conv[]>("/api/conversations")); } catch { /* ignora */ }
  }, []);
  useEffect(() => { loadConvs(); }, [loadConvs]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function open(id: string) {
    setCurrent(id);
    setListOpen(false);
    const c = await get<{ messages: Msg[] }>(`/api/conversations/${id}`);
    setMessages(c.messages);
  }

  async function send() {
    const content = text.trim();
    if (!content || sending) return;
    setText("");
    setError(null);
    setSending(true);
    const label = MODES.find((m) => m.id === mode)?.label ?? mode;
    setMessages((ms) => [...ms, { id: `u${Date.now()}`, role: "user", content, mode, model: "", meta: {}, cost_usd: 0, feedback: null, created_at: "" },
      { id: "pending", role: "assistant", content: mode === "DEEP_RESEARCH" || mode === "COUNCIL" || mode === "ENGINEERING"
        ? `ULTRON trabalhando (${label}) — pode levar até alguns minutos…` : "ULTRON pensando…", mode, model: "", meta: {}, cost_usd: 0,
        feedback: null, created_at: "", pending: true }]);
    try {
      const r = await post<{ conversation: Conv; message: Msg }>("/api/chat", { message: content, conversation_id: current, mode });
      if (!current) { setCurrent(r.conversation.id); loadConvs(); }
      const c = await get<{ messages: Msg[] }>(`/api/conversations/${r.conversation.id}`);
      setMessages(c.messages);
    } catch (e) {
      setMessages((ms) => ms.filter((m) => !m.pending));
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  async function feedback(m: Msg, v: number) {
    await post(`/api/messages/${m.id}/feedback`, { value: v });
    setMessages((ms) => ms.map((x) => (x.id === m.id ? { ...x, feedback: v || null } : x)));
  }

  async function propose(m: Msg) {
    try {
      const question = [...messages].reverse().find((x) => x.role === "user")?.content ?? "";
      const r = await post<{ code: string }>("/api/evolution/proposals/from-engineering", { question, decision_record: m.meta.decision_record });
      setNotice(`Proposta ${r.code} criada — veja em Autoevolução.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function remove(id: string) {
    await del(`/api/conversations/${id}`);
    if (current === id) { setCurrent(null); setMessages([]); }
    loadConvs();
  }

  const list = (
    <div className="space-y-1">
      <Button variant="primary" className="mb-2 w-full" onClick={() => { setCurrent(null); setMessages([]); setListOpen(false); }}>
        <Plus className="h-4 w-4" /> Nova conversa
      </Button>
      {convs.map((c) => (
        <div key={c.id} className={cx("group flex items-center gap-1 rounded-xl", current === c.id ? "bg-surface-3" : "hover:bg-surface-2")}>
          <button onClick={() => open(c.id)} className="min-w-0 flex-1 px-3 py-2 text-left">
            <div className="truncate text-sm">{c.title}</div>
            <div className="text-[11px] text-muted">{ago(c.updated_at)}</div>
          </button>
          <button onClick={() => remove(c.id)} aria-label="Apagar conversa" className="p-2 text-muted opacity-60 hover:text-critical group-hover:opacity-100">
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ))}
      {!convs.length && <p className="px-3 py-2 text-xs text-muted">Nenhuma conversa ainda.</p>}
    </div>
  );
  const modeInfo = MODES.find((m) => m.id === mode)!;

  return (
    <div className="flex h-[calc(100dvh-9.5rem)] gap-4 lg:h-[calc(100dvh-4.5rem)]">
      <aside className="hidden w-64 shrink-0 overflow-y-auto rounded-2xl border border-line bg-surface/70 p-3 md:block">{list}</aside>
      <section className="flex min-w-0 flex-1 flex-col rounded-2xl border border-line bg-surface/40">
        <div className="flex items-center gap-2 border-b border-line px-3 py-2">
          <button className="rounded-lg p-1.5 text-ink-2 hover:bg-surface-3 md:hidden" onClick={() => setListOpen(true)} aria-label="Conversas"><History className="h-5 w-5" /></button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium">{convs.find((c) => c.id === current)?.title ?? "Nova conversa"}</h1>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-3 sm:p-4">
          {!messages.length && (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              <div className="text-lg font-semibold">Como posso ajudar?</div>
              <p className="max-w-md text-sm text-ink-2">Converse, peça uma pesquisa com fontes, convoque o Conselho de IAs, discuta engenharia do próprio ULTRON ou crie uma missão longa.</p>
              <div className="flex flex-wrap justify-center gap-2">
                {["Pesquise as novidades sobre IA multiagente e compare fontes", "Quais são as suas limitações atuais?", "Me ajude a planejar minha semana"].map((s) => (
                  <button key={s} onClick={() => setText(s)} className="rounded-xl border border-line px-3 py-1.5 text-xs text-ink-2 hover:border-lime/50 hover:text-ink">{s}</button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m) => <MessageBubble key={m.id} m={m} onFeedback={(v) => feedback(m, v)} onPropose={() => propose(m)} />)}
          <div ref={endRef} />
        </div>
        <div className="border-t border-line p-2 sm:p-3">
          <ErrorNote error={error} />
          {notice && <p className="mb-2 text-xs text-lime">{notice}</p>}
          <div className="relative mb-2">
            <button onClick={() => setModeOpen((v) => !v)} className="flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-xs text-ink-2 hover:border-lime/50">
              Modo: <span className="text-lime">{modeInfo.label}</span> <span className="hidden text-muted sm:inline">· {modeInfo.hint}</span> <ChevronDown className="h-3 w-3" />
            </button>
            {modeOpen && (
              <div className="absolute bottom-8 left-0 z-20 w-64 rounded-xl border border-line-strong bg-surface-2 p-1 shadow-xl">
                {MODES.map((m) => (
                  <button key={m.id} onClick={() => { setMode(m.id); setModeOpen(false); }}
                    className={cx("flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-3", m.id === mode && "text-lime")}>
                    <span>{m.label}</span><span className="text-[11px] text-muted">{m.hint}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-end gap-2">
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={1} placeholder="Mensagem para o ULTRON…"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && window.innerWidth > 768) { e.preventDefault(); send(); } }}
              className="max-h-40 min-h-11 flex-1 resize-none rounded-xl border border-line bg-surface-2 px-3 py-2.5 text-sm focus:border-lime/60 focus:outline-none" />
            <Button variant="primary" onClick={send} busy={sending} disabled={!text.trim()} className="h-11 w-11 !px-0" title="Enviar">
              {!sending && <Send className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </section>
      <Sheet open={listOpen} onClose={() => setListOpen(false)} title="Conversas">{list}</Sheet>
    </div>
  );
}

export default function Page() {
  return <Shell><Chat /></Shell>;
}
