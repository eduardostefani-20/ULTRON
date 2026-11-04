"""PUBLICAÇÃO LIMITADA (CÓDIGO DE GOVERNANÇA) — baseada em risco, com rollback e monitoramento.

- Baixo risco: publicação automática SOMENTE se habilitada pelo proprietário, após autoteste de
  segurança aprovado, avaliação aprovada, auditor disponível, sandbox com rede isolada e CI verde
  (quando há GitHub).
- Médio/alto risco: sempre aprovação humana.
- Toda publicação registra o ponto de retorno; rollback = revert do merge (histórico preservado).
- Após publicar, as métricas são monitoradas; regressão → rollback automático (se habilitado).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from ultron.db import session_scope
from ultron.evolution.github import GitHubError, client_from_settings
from ultron.evolution.observability import snapshot
from ultron.evolution.workspace import get_workspace
from ultron.governance import audit
from ultron.governance.approvals import is_approved, request_approval
from ultron.governance.policy import Risk, assess_changes, requires_human_approval
from ultron.models import Evaluation, Proposal, Publication
from ultron.utils import utcnow

log = logging.getLogger("ultron.publisher")


class PublishError(Exception):
    pass


async def _latest_eval(session, proposal_id: str) -> Evaluation | None:
    return (await session.execute(select(Evaluation).where(Evaluation.proposal_id == proposal_id)
                                  .order_by(Evaluation.created_at.desc()).limit(1))).scalar_one_or_none()


async def auto_publish_allowed(session, ev: Evaluation) -> tuple[bool, list[str]]:
    from ultron.settings_store import get_setting

    reasons: list[str] = []
    if not await get_setting(session, "publication.auto_publish_low_risk"):
        reasons.append("publicação automática desabilitada")
    st = await get_setting(session, "publication.safety_selftest") or {}
    if not st.get("passed"):
        reasons.append("autoteste de segurança não aprovado")
    if ev.risk_level != Risk.LOW.value:
        reasons.append(f"risco {ev.risk_level} exige aprovação humana")
    if ev.verdict != "pass":
        reasons.append("avaliação reprovada")
    if not (ev.scores or {}).get("auditor_available"):
        reasons.append("auditor independente indisponível")
    if (ev.scores or {}).get("requires_ci"):
        reasons.append("frontend exige validação por CI")
    net = ((ev.candidate or {}).get("isolation") or {}).get("network")
    if net != "isolated":
        reasons.append("sandbox sem isolamento de rede")
    soft_failed = [g["name"] for g in ev.gates or [] if not g["passed"]]
    if soft_failed:
        reasons.append("portões não aprovados: " + ", ".join(soft_failed))
    return not reasons, reasons


async def decide(proposal_id: str) -> str:
    """Após a avaliação: publica automaticamente (se permitido) ou solicita aprovação humana."""
    async with session_scope() as s:
        p = await s.get(Proposal, proposal_id)
        ev = await _latest_eval(s, proposal_id)
        if ev is None or ev.verdict != "pass":
            return "failed"
        allowed, reasons = await auto_publish_allowed(s, ev)
        if not allowed:
            risk = ev.risk_level if requires_human_approval(Risk(ev.risk_level)) else "low"
            ap = await request_approval(
                s, kind="publication", target_type="proposal", target_id=p.id, risk=risk,
                title=f"{p.code}: {p.title}",
                summary=f"Risco calculado: {ev.risk_level}. Avaliação aprovada. Motivos para revisão humana: "
                        + "; ".join(reasons),
                details={"code": p.code, "reasons": reasons, "branch": p.branch}, requested_by="evolution_engine")
            p.status = "awaiting_approval"
            await audit.record("evolution_engine", "publication.approval_requested", p.code,
                               {"approval_id": ap.id, "reasons": reasons}, session=s)
            code, branch, title = p.code, p.branch, p.title
        else:
            code = None
    if code:
        await _open_pr_quietly(proposal_id, branch, f"{code}: {title}")
        return "awaiting_approval"
    pub = await publish(proposal_id, mode="auto", approved_by="politica:baixo-risco")
    return "published" if pub.status == "published" else "failed"


async def _open_pr_quietly(proposal_id: str, branch: str, title: str) -> None:
    """Com GitHub configurado, abre um PR para revisão pelo celular (app do GitHub)."""
    gh = await client_from_settings()
    if gh is None:
        return
    ws = await get_workspace()
    try:
        await ws.push(branch, force=True)
        async with session_scope() as s:
            p = await s.get(Proposal, proposal_id)
            body = (f"## {p.code} — {p.title}\n\n**Problema:** {p.problem}\n\n**Solução:** {p.solution}\n\n"
                    f"**Risco calculado:** {p.risk_level}\n\n**Critérios de aceitação:**\n"
                    + "\n".join(f"- {c}" for c in p.acceptance_criteria or [])
                    + "\n\n**Rollback:** " + (p.rollback_strategy or "git revert do merge")
                    + "\n\n---\n_Gerado pelo Self-Evolution Engine do ULTRON. Aprovação humana necessária._")
        pr = await gh.create_pr(branch, ws.base_branch, title, body)
        async with session_scope() as s:
            p = await s.get(Proposal, proposal_id)
            p.pr_url = pr.get("html_url", "")
            p.payload = {**(p.payload or {}), "pr_number": pr.get("number")}
    except Exception as e:  # PR é conveniência: falha não bloqueia a aprovação no app
        log.info("PR não criado: %s", e)


async def publish(proposal_id: str, *, mode: str, approved_by: str) -> Publication:
    async with session_scope() as s:
        p = await s.get(Proposal, proposal_id)
        ev = await _latest_eval(s, proposal_id)
        if p is None or ev is None or ev.verdict != "pass":
            raise PublishError("somente propostas com avaliação aprovada podem ser publicadas")
        if p.status == "published":
            raise PublishError("proposta já publicada")
        if mode != "auto" and not await is_approved(s, "proposal", p.id):
            raise PublishError("publicação exige aprovação humana registrada")
        if mode == "auto":
            allowed, reasons = await auto_publish_allowed(s, ev)
            if not allowed:
                raise PublishError("publicação automática não permitida: " + "; ".join(reasons))
        snap = {k: getattr(p, k) for k in ("code", "title", "branch", "base_sha", "tree_sha", "payload")}
        risk = ev.risk_level
        metrics_before = await snapshot(s, hours=6)

    ws = await get_workspace()
    await ws.sync()
    # defesa em profundidade: revalida árvore, base e política imediatamente antes do merge
    if await ws.tree(snap["branch"]) != snap["tree_sha"]:
        raise PublishError("a branch foi alterada após a avaliação — reavaliação necessária")
    current_base = await ws.head()
    if current_base != snap["base_sha"]:
        async with session_scope() as s:
            p = await s.get(Proposal, proposal_id)
            p.status = "queued"
            p.error = "o branch base mudou desde a avaliação; a proposta voltará para a fila"
        raise PublishError("o branch base mudou desde a avaliação — a proposta voltou para a fila")
    assessment = assess_changes(await ws.diff_changes(snap["base_sha"], snap["branch"]))
    if assessment.blocked:
        raise PublishError("bloqueado pela governança: " + "; ".join(assessment.blocked_reasons))
    if assessment.level.value != risk:
        raise PublishError("classificação de risco divergente da avaliação — reavaliação necessária")

    pushed, pr_url, merge_sha = False, "", ""
    gh = await client_from_settings()
    message = f"Publica {snap['code']}: {snap['title']} ({mode}; aprovado por {approved_by})"
    if gh is not None:
        from ultron.settings_store import get_setting

        await ws.push(snap["branch"], force=True)
        async with session_scope() as s:
            p = await s.get(Proposal, proposal_id)
            body = f"{p.problem}\n\n{p.solution}\n\n_Publicação {mode} pelo ULTRON._"
            require_ci = await get_setting(s, "publication.require_ci_when_github")
        try:
            pr = await gh.create_pr(snap["branch"], ws.base_branch, f"{snap['code']}: {snap['title']}", body)
            pr_url = pr.get("html_url", "")
            if require_ci:
                ci = await gh.checks(pr["head"]["sha"])
                if ci["state"] in ("pending", "failure"):
                    raise PublishError(f"CI do GitHub não está verde ({ci['state']}) — tente novamente após o CI")
            merged = await gh.merge_pr(pr["number"], message, pr["head"]["sha"])
            merge_sha = merged.get("sha", "")
            pushed = True
            await ws.sync()
        except GitHubError as e:
            raise PublishError(f"falha ao publicar no GitHub: {e}") from e
    else:
        merge_sha = await ws.merge_into_base(snap["branch"], message)
    async with session_scope() as s:
        from ultron.settings_store import get_setting

        monitor_min = int(await get_setting(s, "evolution.monitor_minutes") or 60)
        pub = Publication(proposal_id=proposal_id, mode=mode, risk_level=risk, base_sha_before=snap["base_sha"],
                          merge_sha=merge_sha, pushed=pushed, pr_url=pr_url, approved_by=approved_by,
                          metrics_before={"llm_error_rate": metrics_before["llm"]["error_rate"],
                                          "llm_calls": metrics_before["llm"]["calls"],
                                          "mission_success_rate": metrics_before["missions"]["success_rate"],
                                          "errors": sum(e["count"] for e in metrics_before["errors"])},
                          monitor_until=utcnow() + timedelta(minutes=monitor_min))
        s.add(pub)
        p = await s.get(Proposal, proposal_id)
        p.status = "published"
        p.pr_url = pr_url or p.pr_url
        await s.flush()
        await audit.record(approved_by if mode != "auto" else "publisher:auto", "proposal.published", snap["code"],
                           {"mode": mode, "risk": risk, "merge_sha": merge_sha, "pushed": pushed,
                            "rollback_point": snap["base_sha"]}, session=s)
        s.expunge(pub)
    return pub


async def rollback(publication_id: str, *, actor: str, reason: str) -> Publication:
    async with session_scope() as s:
        pub = await s.get(Publication, publication_id)
        if pub is None or pub.status != "published":
            raise PublishError("publicação inexistente ou já revertida")
        p = await s.get(Proposal, pub.proposal_id)
        code, merge_sha = p.code, pub.merge_sha
    ws = await get_workspace()
    await ws.sync()
    msg = f"Rollback de {code}: {reason[:120]}"
    gh = await client_from_settings()
    if gh is not None:
        branch = f"rollback/{code.lower()}"
        wt = await ws.create_worktree(branch, ws.base_branch)
        try:
            from ultron.evolution.workspace import git

            parents = (await git("rev-list", "--parents", "-n", "1", merge_sha, cwd=wt)).out.split()
            await git("revert", "--no-edit", *(["-m", "1"] if len(parents) > 2 else []), merge_sha, cwd=wt)
            await ws.push(branch, force=True)
            pr = await gh.create_pr(branch, ws.base_branch, msg, f"Rollback automático/manual.\n\nMotivo: {reason}")
            merged = await gh.merge_pr(pr["number"], msg, pr["head"]["sha"])
            rb_sha = merged.get("sha", "")
            await ws.sync()
        finally:
            await ws.remove_worktree(wt)
    else:
        rb_sha = await ws.revert_merge(merge_sha, msg)
    async with session_scope() as s:
        pub = await s.get(Publication, publication_id)
        pub.status = "rolled_back"
        pub.rolled_back_at = utcnow()
        pub.rollback_sha = rb_sha
        pub.rollback_reason = reason
        p = await s.get(Proposal, pub.proposal_id)
        p.status = "rolled_back"
        await audit.record(actor, "proposal.rolled_back", code, {"reason": reason, "rollback_sha": rb_sha}, session=s)
        s.expunge(pub)
    return pub


async def monitor() -> list[dict]:
    """Compara métricas após publicações; regressão clara → rollback automático."""
    from ultron.settings_store import get_setting

    results = []
    async with session_scope() as s:
        pubs = (await s.execute(select(Publication).where(Publication.status == "published",
                                                          Publication.monitor_until.is_not(None)))).scalars().all()
        auto_rb = await get_setting(s, "publication.auto_rollback")
        snap = await snapshot(s, hours=1) if pubs else None
        items = [(p.id, p.metrics_before or {}, p.monitor_until, p.published_at) for p in pubs]
    for pid, before, until, _published_at in items:
        after = {"llm_error_rate": snap["llm"]["error_rate"], "llm_calls": snap["llm"]["calls"],
                 "errors": sum(e["count"] for e in snap["errors"])}
        regression = (after["llm_calls"] >= 10 and after["llm_error_rate"] > (before.get("llm_error_rate") or 0) + 0.25) \
            or (after["errors"] > max(20, 3 * (before.get("errors") or 0)))
        verdict = {"publication_id": pid, "before": before, "after": after, "regression": regression}
        if regression and auto_rb:
            try:
                await rollback(pid, actor="monitor:auto", reason="regressão detectada nas métricas após publicação")
                verdict["action"] = "rolled_back"
            except Exception as e:
                verdict["action"] = f"rollback falhou: {e}"
        elif utcnow() >= until:
            verdict["action"] = "monitoring_finished"
        async with session_scope() as s:
            pub = await s.get(Publication, pid)
            if pub and pub.status == "published":
                pub.monitor = verdict
                if verdict.get("action") == "monitoring_finished":
                    pub.monitor_until = None
        results.append(verdict)
    return results
