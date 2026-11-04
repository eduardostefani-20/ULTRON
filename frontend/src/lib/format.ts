export const usd = (v: number | null | undefined, digits = 4) =>
  `US$ ${(v ?? 0).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: digits })}`;

export const brl = (v: number | null | undefined) =>
  (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export const num = (v: number | null | undefined) => (v ?? 0).toLocaleString("pt-BR");

export const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "—" : `${(v * 100).toLocaleString("pt-BR", { maximumFractionDigits: digits })}%`;

export function ago(iso?: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 0) return "agora";
  if (s < 60) return `há ${s}s`;
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  if (s < 86400) return `há ${Math.round(s / 3600)} h`;
  return `há ${Math.round(s / 86400)} d`;
}

export const dateTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";

export const short = (id?: string | null) => (id ? id.slice(0, 8) : "");

export const STATUS_PT: Record<string, string> = {
  RECEIVED: "Recebida", PLANNING: "Planejando", RUNNING: "Executando", REVIEWING: "Revisando",
  WAITING_APPROVAL: "Aguardando aprovação", COMPLETED: "Concluída", FAILED: "Falhou", CANCELLED: "Cancelada",
  PENDING: "Pendente", DONE: "Concluída", SKIPPED: "Pulada",
  queued: "Na fila", proposed: "Proposta", developing: "Desenvolvendo", testing: "Testando",
  evaluating: "Avaliando", evaluated: "Avaliada", awaiting_approval: "Aguardando aprovação", approved: "Aprovada",
  published: "Publicada", rejected: "Rejeitada", failed: "Falhou", rolled_back: "Revertida",
  running: "Em execução", completed: "Concluído", interrupted: "Interrompido", cancelled: "Cancelado",
  pending: "Pendente", open: "Aberto", resolved: "Resolvido", ignored: "Ignorado", active: "Ativo",
  disabled: "Desativado", pending_approval: "Aguardando aprovação", trial: "Em teste", partial: "Parcial",
  low: "Baixo", medium: "Médio", high: "Alto", critical: "Crítico", info: "Info",
};

export const pt = (s?: string | null) => (s ? STATUS_PT[s] ?? s : "—");
