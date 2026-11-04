"use client";

import { ChevronDown, Server } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { Logo } from "@/components/Shell";
import { Button, ErrorNote, Field, Note, inputCls } from "@/components/ui";
import { ApiError, apiBase, getSession, post, saveSession, setApiBase } from "@/lib/api";

type Status = { setup_required: boolean; setup_token_required: boolean };

export default function LoginPage() {
  const router = useRouter();
  const [status, setStatus] = useState<Status | null>(null);
  const [server, setServer] = useState("");
  const [showServer, setShowServer] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadStatus() {
    setError(null);
    try {
      const r = await fetch(`${apiBase()}/api/auth/status`);
      if (!r.ok) throw new Error(`servidor respondeu ${r.status}`);
      setStatus(await r.json());
    } catch (e) {
      setStatus(null);
      setShowServer(true);
      setError(`Não foi possível falar com o servidor do ULTRON (${apiBase() || "mesma origem"}): ${String(e)}`);
    }
  }

  useEffect(() => {
    if (getSession()) router.replace("/");
    setServer(apiBase());
    loadStatus();
  }, [router]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = status?.setup_required
        ? await post<Parameters<typeof saveSession>[0]>("/api/auth/setup", { email, password, name, setup_token: token })
        : await post<Parameters<typeof saveSession>[0]>("/api/auth/login", { email, password });
      saveSession(data);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid-bg flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-3 text-center">
          <Logo size={56} />
          <div>
            <h1 className="text-2xl font-bold tracking-[0.3em]">ULTRON</h1>
            <p className="mt-1 text-sm text-ink-2">Central de inteligência autônoma</p>
          </div>
        </div>
        <form onSubmit={submit} className="space-y-3 rounded-3xl border border-line bg-surface/90 p-5 backdrop-blur">
          {status?.setup_required && (
            <Note>Primeiro acesso: crie a conta do proprietário. Ela controla aprovações, chaves e publicações.</Note>
          )}
          {status?.setup_required && (
            <Field label="Seu nome">
              <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </Field>
          )}
          <Field label="E-mail">
            <input className={inputCls} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </Field>
          <Field label="Senha" hint={status?.setup_required ? "Mínimo de 10 caracteres, com letras e números ou símbolos." : undefined}>
            <input className={inputCls} type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={status?.setup_required ? "new-password" : "current-password"} />
          </Field>
          {status?.setup_required && status.setup_token_required && (
            <Field label="Token de configuração" hint="O valor de ULTRON_SETUP_TOKEN definido no painel da hospedagem.">
              <input className={inputCls} value={token} onChange={(e) => setToken(e.target.value)} />
            </Field>
          )}
          <ErrorNote error={error} />
          <Button type="submit" variant="primary" busy={busy} disabled={!status} className="w-full">
            {status?.setup_required ? "Criar conta e entrar" : "Entrar"}
          </Button>
          <button type="button" onClick={() => setShowServer((v) => !v)} className="flex w-full items-center justify-center gap-1 pt-1 text-xs text-muted hover:text-ink-2">
            <Server className="h-3.5 w-3.5" /> Servidor <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showServer ? "rotate-180" : ""}`} />
          </button>
          {showServer && (
            <div className="space-y-2 rounded-2xl border border-line p-3">
              <Field label="Endereço do backend" hint="Deixe vazio quando a interface é servida pelo próprio backend. Ex.: https://ultron.onrender.com">
                <input className={inputCls} value={server} onChange={(e) => setServer(e.target.value)} placeholder="https://..." inputMode="url" />
              </Field>
              <Button onClick={() => { setApiBase(server); loadStatus(); }} className="w-full">Salvar e testar conexão</Button>
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
