"""Modelos de dados persistentes do ULTRON.

Os tipos são portáveis entre PostgreSQL e SQLite. Campos estruturados usam JSON.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ultron.db import Base
from ultron.utils import new_id, utcnow


def _id() -> Mapped[str]:
    return mapped_column(String(32), primary_key=True, default=new_id)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime, default=utcnow, nullable=False)


# --------------------------------------------------------------------------- identidade


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = _id()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="owner")
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = _created()
    user_agent: Mapped[str] = mapped_column(String(255), default="")


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str] = mapped_column(String(120), default="system")


class ProviderCredential(Base):
    """Credenciais de provedores (LLM, busca, GitHub) — sempre cifradas."""

    __tablename__ = "provider_credentials"
    id: Mapped[str] = _id()
    provider: Mapped[str] = mapped_column(String(40), unique=True)
    encrypted_key: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    last4: Mapped[str] = mapped_column(String(8), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


# --------------------------------------------------------------------------- conversas


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Nova conversa")
    mode: Mapped[str] = mapped_column(String(30), default="AUTO")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = _id()
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(30), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[int | None] = mapped_column(Integer, nullable=True)  # +1 / -1
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- agentes


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)  # slug
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    tools: Mapped[list] = mapped_column(JSON, default=list)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    model_tier: Mapped[str] = mapped_column(String(20), default="balanced")
    task_type: Mapped[str] = mapped_column(String(30), default="chat")
    max_steps: Mapped[int] = mapped_column(Integer, default=6)
    budget_usd_per_run: Mapped[float] = mapped_column(Float, default=0.05)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|trial|disabled
    created_by: Mapped[str] = mapped_column(String(120), default="system")
    parent_agent: Mapped[str] = mapped_column(String(60), default="")
    generation: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = _id()
    agent_id: Mapped[str] = mapped_column(String(60), index=True)
    mission_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    input: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list] = mapped_column(JSON, default=list)
    models: Mapped[list] = mapped_column(JSON, default=list)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# --------------------------------------------------------------------------- missões


class Mission(Base):
    __tablename__ = "missions"
    id: Mapped[str] = _id()
    user_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    source: Mapped[str] = mapped_column(String(30), default="api")
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[str] = mapped_column(Text, default="")
    review: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    budget_usd: Mapped[float] = mapped_column(Float, default=0.30)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    lease_owner: Mapped[str] = mapped_column(String(64), default="")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MissionTask(Base):
    __tablename__ = "mission_tasks"
    id: Mapped[str] = _id()
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    agent_id: Mapped[str] = mapped_column(String(60))
    instructions: Mapped[str] = mapped_column(Text, default="")
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    resources: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    agent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MissionEvent(Base):
    __tablename__ = "mission_events"
    id: Mapped[str] = _id()
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


# --------------------------------------------------------------------------- memória


class MemoryItem(Base):
    __tablename__ = "memory_items"
    id: Mapped[str] = _id()
    user_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), default="unverified", index=True)
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(String(400), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(200), default="")
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    embedding_local: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(120), default="")
    access_scope: Mapped[str] = mapped_column(String(20), default="agents")  # private|agents
    content_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- pesquisa


class ResearchReport(Base):
    __tablename__ = "research_reports"
    id: Mapped[str] = _id()
    user_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="running")
    summary: Mapped[str] = mapped_column(Text, default="")
    sub_queries: Mapped[list] = mapped_column(JSON, default=list)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    search_provider: Mapped[str] = mapped_column(String(40), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(40), default="user")
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# --------------------------------------------------------------------------- observabilidade


class LLMCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[str] = _id()
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(120), index=True)
    purpose: Mapped[str] = mapped_column(String(60), default="")
    agent_id: Mapped[str] = mapped_column(String(60), default="", index=True)
    mission_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    cycle_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")
    price_known: Mapped[bool] = mapped_column(Boolean, default=True)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = _id()
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    tool: Mapped[str] = mapped_column(String(60), index=True)
    agent_id: Mapped[str] = mapped_column(String(60), default="")
    mission_id: Mapped[str] = mapped_column(String(32), default="")
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    denied: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    args_summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")


class MetricPoint(Base):
    __tablename__ = "metric_points"
    id: Mapped[str] = _id()
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[float] = mapped_column(Float)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)


class ErrorEvent(Base):
    __tablename__ = "error_events"
    id: Mapped[str] = _id()
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(60), index=True)
    signature: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="")


class ResponseCache(Base):
    __tablename__ = "response_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(120))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- governança


class AuditLog(Base):
    """Registro de auditoria append-only com encadeamento de hashes.

    UPDATE e DELETE são bloqueados por triggers no banco (ver migração inicial).
    """

    __tablename__ = "audit_log"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(80), index=True)
    target: Mapped[str] = mapped_column(String(200), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = _id()
    kind: Mapped[str] = mapped_column(String(40))  # publication|mission_action|agent_creation|config
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    risk: Mapped[str] = mapped_column(String(10), default="medium")
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(120), default="ultron")
    decided_by: Mapped[str] = mapped_column(String(120), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- autoevolução


class EvolutionCycle(Base):
    __tablename__ = "evolution_cycles"
    id: Mapped[str] = _id()
    number: Mapped[int] = mapped_column(Integer, default=0)
    trigger: Mapped[str] = mapped_column(String(20), default="scheduled")
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    phase: Mapped[str] = mapped_column(String(40), default="OBSERVE")
    completed_phases: Mapped[list] = mapped_column(JSON, default=list)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    log: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    budget_usd: Mapped[float] = mapped_column(Float, default=0.5)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    lease_owner: Mapped[str] = mapped_column(String(64), default="")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Diagnostic(Base):
    __tablename__ = "diagnostics"
    id: Mapped[str] = _id()
    signature: Mapped[str] = mapped_column(String(120), index=True)
    cycle_id: Mapped[str] = mapped_column(String(32), default="")
    category: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(10))  # info|low|medium|high|critical
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    suggestion: Mapped[str] = mapped_column(Text, default="")
    research: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open|resolved|ignored
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = _id()
    code: Mapped[str] = mapped_column(String(20), unique=True)  # EVO-0001
    cycle_id: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(30), default="diagnostic")  # diagnostic|human|agent
    kind: Mapped[str] = mapped_column(String(20), default="code")  # code|docs|config|agent|tool|test
    strategy: Mapped[str] = mapped_column(String(30), default="llm")  # llm|deterministic
    title: Mapped[str] = mapped_column(String(300))
    problem: Mapped[str] = mapped_column(Text, default="")
    diagnosis: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    solution: Mapped[str] = mapped_column(Text, default="")
    affected_files: Mapped[list] = mapped_column(JSON, default=list)
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    benefits: Mapped[str] = mapped_column(Text, default="")
    risks: Mapped[str] = mapped_column(Text, default="")
    cost_estimate_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tests_required: Mapped[list] = mapped_column(JSON, default=list)
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list)
    rollback_strategy: Mapped[str] = mapped_column(Text, default="")
    declared_risk: Mapped[str] = mapped_column(String(10), default="")
    risk_level: Mapped[str] = mapped_column(String(10), default="medium")
    risk_reasons: Mapped[list] = mapped_column(JSON, default=list)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    diagnostic_ids: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    branch: Mapped[str] = mapped_column(String(200), default="")
    base_sha: Mapped[str] = mapped_column(String(64), default="")
    commit_sha: Mapped[str] = mapped_column(String(64), default="")
    tree_sha: Mapped[str] = mapped_column(String(64), default="")
    pr_url: Mapped[str] = mapped_column(String(500), default="")
    changed_files: Mapped[list] = mapped_column(JSON, default=list)
    diff_stats: Mapped[dict] = mapped_column(JSON, default=dict)
    dev_log: Mapped[list] = mapped_column(JSON, default=list)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(120), default="ultron")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SandboxRun(Base):
    __tablename__ = "sandbox_runs"
    id: Mapped[str] = _id()
    proposal_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    label: Mapped[str] = mapped_column(String(60), default="")
    command: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="running")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    stdout_tail: Mapped[str] = mapped_column(Text, default="")
    stderr_tail: Mapped[str] = mapped_column(Text, default="")
    isolation: Mapped[dict] = mapped_column(JSON, default=dict)
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[str] = _id()
    proposal_id: Mapped[str] = mapped_column(String(32), index=True)
    verdict: Mapped[str] = mapped_column(String(10))  # pass|fail
    gates: Mapped[list] = mapped_column(JSON, default=list)
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)
    candidate: Mapped[dict] = mapped_column(JSON, default=dict)
    audit: Mapped[dict] = mapped_column(JSON, default=dict)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(10), default="medium")
    created_at: Mapped[datetime] = _created()


class Publication(Base):
    __tablename__ = "publications"
    id: Mapped[str] = _id()
    proposal_id: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(20))  # auto|approved
    status: Mapped[str] = mapped_column(String(20), default="published")  # published|rolled_back|failed
    risk_level: Mapped[str] = mapped_column(String(10), default="low")
    base_sha_before: Mapped[str] = mapped_column(String(64), default="")
    merge_sha: Mapped[str] = mapped_column(String(64), default="")
    pushed: Mapped[bool] = mapped_column(Boolean, default=False)
    pr_url: Mapped[str] = mapped_column(String(500), default="")
    approved_by: Mapped[str] = mapped_column(String(120), default="")
    metrics_before: Mapped[dict] = mapped_column(JSON, default=dict)
    monitor: Mapped[dict] = mapped_column(JSON, default=dict)
    monitor_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rollback_sha: Mapped[str] = mapped_column(String(64), default="")
    rollback_reason: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = _created()
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CodeMapSnapshot(Base):
    __tablename__ = "code_map_snapshots"
    id: Mapped[str] = _id()
    commit_sha: Mapped[str] = mapped_column(String(64), default="")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    modules: Mapped[list] = mapped_column(JSON, default=list)
    edges: Mapped[list] = mapped_column(JSON, default=list)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = _created()


class JobLease(Base):
    """Arrendamento de trabalhos em segundo plano (evita execução duplicada)."""

    __tablename__ = "job_leases"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default="")
    last_message: Mapped[str] = mapped_column(Text, default="")
    runs: Mapped[int] = mapped_column(Integer, default=0)


Index("ix_llm_calls_ts_success", LLMCall.ts, LLMCall.success)
