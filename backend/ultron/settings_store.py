"""Configurações do sistema persistidas no banco, com valores padrão seguros.

Chaves protegidas (governance.*, autonomy.*, publication.*, budget.*, security.*) só podem
ser alteradas pelo proprietário humano autenticado.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.governance import audit
from ultron.governance.permissions import DEFAULT_GRANTED_SCOPES, sanitize_granted_scopes
from ultron.governance.policy import is_protected_setting
from ultron.models import SystemSetting

DEFAULTS: dict[str, Any] = {
    # Autoevolução
    "evolution.enabled": True,
    "evolution.paused": False,
    "evolution.interval_minutes": 360,
    "evolution.max_proposals_per_cycle": 3,
    "evolution.max_developments_per_cycle": 1,
    "evolution.cycle_budget_usd": 0.40,
    "evolution.cycle_max_minutes": 25,
    "evolution.monthly_budget_share": 0.35,
    "evolution.research_enabled": True,
    "evolution.dev_max_iterations": 3,
    "evolution.monitor_minutes": 60,
    # Publicação LIMITED — começa DESABILITADA até a validação de segurança
    "publication.auto_publish_low_risk": False,
    "publication.safety_selftest": {"passed": False, "at": None, "details": {}},
    "publication.require_ci_when_github": True,
    "publication.auto_rollback": True,
    # Autonomia: escopos concedidos aos agentes (PUBLISH nunca entra aqui)
    "autonomy.granted_scopes": DEFAULT_GRANTED_SCOPES,
    "autonomy.allow_agent_creation": True,
    # Orçamento
    "budget.monthly_brl": None,  # None = usa ULTRON_MONTHLY_BUDGET_BRL
    "budget.per_mission_usd": 0.30,
    "budget.per_agent_run_usd": 0.10,
    "budget.per_model_monthly_usd": {},
    "budget.alert_threshold": 0.8,
    "budget.hard_stop": True,
    # Roteamento
    "routing.preferred_providers": [],
    "routing.disabled_models": [],
    "routing.cache_ttl_minutes": 720,
    "routing.price_overrides": {},
    # Memória
    "memory.auto_extract": True,
    "memory.retention_days": {"conversation": 180, "operational": 90, "task": 120},
    "memory.agents_can_read_personal": True,
    # Pesquisa
    "research.max_sources": 6,
    # Geral
    "general.assistant_name": "ULTRON",
    "general.language": "pt-BR",
}


async def get_setting(session: AsyncSession, key: str) -> Any:
    row = await session.get(SystemSetting, key)
    if row is None:
        return DEFAULTS.get(key)
    return row.value


async def get_many(session: AsyncSession, prefix: str = "") -> dict[str, Any]:
    out = {k: v for k, v in DEFAULTS.items() if k.startswith(prefix)}
    rows = (await session.execute(select(SystemSetting))).scalars().all()
    for r in rows:
        if r.key.startswith(prefix):
            out[r.key] = r.value
    return out


class SettingPermissionError(PermissionError):
    pass


async def _write(session: AsyncSession, key: str, value: Any, actor: str) -> None:
    old = await get_setting(session, key)
    row = await session.get(SystemSetting, key)
    if row is None:
        session.add(SystemSetting(key=key, value=value, updated_by=actor))
    else:
        row.value = value
        row.updated_by = actor
    await session.flush()
    await audit.record(actor, "settings.update", key, {"old": old, "new": value}, session=session)


async def set_setting(session: AsyncSession, key: str, value: Any, *, actor: str, actor_is_human_owner: bool) -> None:
    """Altera uma configuração. Agentes e o motor de evolução não alteram chaves protegidas."""
    if key not in DEFAULTS:
        raise KeyError(f"configuração desconhecida: {key}")
    if is_protected_setting(key) and not actor_is_human_owner:
        await audit.record(actor, "settings.denied", key, {"reason": "chave protegida"}, session=session)
        raise SettingPermissionError(f"a configuração '{key}' só pode ser alterada pelo proprietário")
    if key == "publication.safety_selftest":
        raise SettingPermissionError("o resultado do autoteste de segurança só é gravado pelo próprio autoteste")
    if key == "publication.auto_publish_low_risk" and value is True:
        st = await get_setting(session, "publication.safety_selftest") or {}
        if not st.get("passed"):
            raise SettingPermissionError(
                "execute e aprove o autoteste de segurança antes de ativar a publicação automática"
            )
    if key == "autonomy.granted_scopes":
        value = sanitize_granted_scopes(list(value or []))
    await _write(session, key, value, actor)


async def record_selftest(session: AsyncSession, passed: bool, at: str, details: dict) -> None:
    """Usado exclusivamente pelo autoteste de segurança."""
    await _write(session, "publication.safety_selftest", {"passed": passed, "at": at, "details": details},
                 "system:selftest")
    if not passed:
        # falha no autoteste desliga a publicação automática imediatamente
        current = await get_setting(session, "publication.auto_publish_low_risk")
        if current:
            await _write(session, "publication.auto_publish_low_risk", False, "system:selftest")


async def system_set(session: AsyncSession, key: str, value: Any, actor: str) -> None:
    """Escrita pelo próprio sistema em chaves NÃO protegidas (ex.: pausa automática por orçamento)."""
    if key not in DEFAULTS:
        raise KeyError(key)
    if is_protected_setting(key) and key not in ("publication.auto_publish_low_risk",):
        raise SettingPermissionError(f"o sistema não pode alterar '{key}'")
    if key == "publication.auto_publish_low_risk" and value is not False:
        raise SettingPermissionError("o sistema só pode DESATIVAR a publicação automática")
    await _write(session, key, value, actor)
