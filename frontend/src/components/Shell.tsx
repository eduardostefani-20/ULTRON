"use client";

import {
  Bot, Brain, Code, Dna, LayoutDashboard, LogOut, Menu, MessageSquare, Network, Plug, Search, Settings, ShieldCheck,
  Target, Users, Wallet, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { getSession, logout } from "@/lib/api";
import { useApi } from "@/lib/hooks";

import { cx } from "./ui";

export const NAV = [
  { href: "/", label: "Painel", icon: LayoutDashboard },
  { href: "/chat/", label: "Chat", icon: MessageSquare },
  { href: "/council/", label: "Conselho", icon: Users },
  { href: "/agents/", label: "Agentes", icon: Bot },
  { href: "/missions/", label: "Missões", icon: Target },
  { href: "/memory/", label: "Memória", icon: Brain },
  { href: "/research/", label: "Pesquisa", icon: Search },
  { href: "/evolution/", label: "Autoevolução", icon: Dna },
  { href: "/integrations/", label: "Integrações", icon: Plug },
  { href: "/usage/", label: "Uso e custos", icon: Wallet },
  { href: "/settings/", label: "Configurações", icon: Settings },
  { href: "/security/", label: "Segurança e auditoria", icon: ShieldCheck },
  { href: "/architecture/", label: "Arquitetura", icon: Network },
  { href: "/workspace/", label: "Workspace", icon: Code },
];

const MOBILE = ["/", "/chat/", "/missions/", "/evolution/"];

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <rect width="64" height="64" rx="16" fill="#0a1428" />
      <circle cx="32" cy="32" r="19" fill="none" stroke="#b8f53b" strokeWidth="4" />
      <circle cx="32" cy="32" r="9" fill="#b8f53b" />
      <circle cx="32" cy="32" r="4" fill="#0a1428" />
    </svg>
  );
}

function isActive(path: string, href: string) {
  const p = path.endsWith("/") ? path : path + "/";
  return href === "/" ? p === "/" : p.startsWith(href);
}

export default function Shell({ children }: { children: ReactNode }) {
  const path = usePathname() || "/";
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const session = typeof window !== "undefined" ? getSession() : null;
  const pending = useApi<unknown[]>(ready ? "/api/approvals?status=pending" : null, 30000);

  useEffect(() => {
    if (!getSession()) router.replace("/login/");
    else setReady(true);
  }, [router]);
  useEffect(() => setDrawer(false), [path]);

  if (!ready) return <div className="min-h-dvh" />;
  const approvals = pending.data?.length ?? 0;

  const navList = (
    <nav className="space-y-0.5">
      {NAV.map(({ href, label, icon: Icon }) => (
        <Link key={href} href={href}
          className={cx("flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-colors",
            isActive(path, href) ? "bg-lime/12 text-lime border border-lime/30" : "border border-transparent text-ink-2 hover:bg-surface-3 hover:text-ink")}>
          <Icon className="h-4 w-4 shrink-0" aria-hidden />
          <span className="truncate">{label}</span>
          {href === "/evolution/" && approvals > 0 && (
            <span className="ml-auto rounded-full bg-warning/20 px-1.5 text-[10px] font-semibold text-warning">{approvals}</span>
          )}
        </Link>
      ))}
    </nav>
  );

  return (
    <div className="min-h-dvh lg:pl-64">
      {/* barra lateral (computador) */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-line bg-surface/90 backdrop-blur lg:flex">
        <Link href="/" className="flex items-center gap-2.5 px-5 py-5">
          <Logo />
          <div>
            <div className="text-base font-bold tracking-[0.25em] text-ink">ULTRON</div>
            <div className="text-[10px] uppercase tracking-wider text-muted">central de inteligência</div>
          </div>
        </Link>
        <div className="flex-1 overflow-y-auto px-3">{navList}</div>
        <div className="border-t border-line p-3">
          <div className="mb-2 truncate px-2 text-xs text-muted">{session?.user?.email}</div>
          <button onClick={logout} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-ink-2 hover:bg-surface-3">
            <LogOut className="h-4 w-4" /> Sair
          </button>
        </div>
      </aside>

      {/* topo (celular) */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-bg/85 px-4 py-3 backdrop-blur lg:hidden"
        style={{ paddingTop: "max(0.75rem, env(safe-area-inset-top))" }}>
        <Link href="/" className="flex items-center gap-2">
          <Logo size={26} />
          <span className="text-sm font-bold tracking-[0.25em]">ULTRON</span>
        </Link>
        <div className="flex items-center gap-2">
          {approvals > 0 && (
            <Link href="/evolution/?tab=approvals" className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-xs text-warning">
              {approvals} aprovação{approvals > 1 ? "ões" : ""}
            </Link>
          )}
          <button onClick={() => setDrawer(true)} className="rounded-lg p-1.5 text-ink-2 hover:bg-surface-3" aria-label="Abrir menu">
            <Menu className="h-5 w-5" />
          </button>
        </div>
      </header>

      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button className="absolute inset-0 bg-black/60" aria-label="Fechar menu" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 right-0 flex w-[82%] max-w-xs flex-col border-l border-line bg-surface p-3 fade-up">
            <div className="mb-2 flex items-center justify-between px-2 py-1">
              <span className="text-sm font-semibold">Menu</span>
              <button onClick={() => setDrawer(false)} className="rounded-lg p-1.5 hover:bg-surface-3" aria-label="Fechar"><X className="h-5 w-5" /></button>
            </div>
            <div className="flex-1 overflow-y-auto">{navList}</div>
            <button onClick={logout} className="mt-2 flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-ink-2 hover:bg-surface-3">
              <LogOut className="h-4 w-4" /> Sair
            </button>
          </div>
        </div>
      )}

      <main className="mx-auto w-full max-w-6xl px-4 pb-28 pt-4 sm:px-6 lg:pb-10 lg:pt-8">{children}</main>

      {/* navegação inferior (celular) */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-line bg-surface/95 backdrop-blur lg:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        {NAV.filter((n) => MOBILE.includes(n.href)).map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href} className={cx("flex flex-col items-center gap-0.5 py-2 text-[10px]",
            isActive(path, href) ? "text-lime" : "text-muted")}>
            <Icon className="h-5 w-5" aria-hidden />
            {label === "Autoevolução" ? "Evolução" : label}
          </Link>
        ))}
        <button onClick={() => setDrawer(true)} className="flex flex-col items-center gap-0.5 py-2 text-[10px] text-muted">
          <Menu className="h-5 w-5" aria-hidden /> Mais
        </button>
      </nav>
    </div>
  );
}
