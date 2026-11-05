# Arquitetura gerada automaticamente

> Documento mantido pelo Documentation Agent do ULTRON a partir da análise estática do código.
> Não edite manualmente: ele é regenerado quando o código muda.

## Resumo

| Métrica | Valor |
|---|---|
| Arquivos de código | 121 |
| Linhas | 17161 |
| Módulos Python | 94 |
| Módulos TypeScript | 27 |
| Funções (Python) | 693 |
| Classes | 111 |
| Arquivos de teste | 12 |
| Funções de teste | 107 |
| Dependências internas | 568 |
| Ciclos de importação | 0 |

## Módulos por pacote

### `backend/alembic` — 1 arquivo(s), 44 linhas

- `backend/alembic/env.py` · 44 linhas · usado por 0 · run_migrations_offline, do_run_migrations, run_async_migrations

### `backend/alembic/versions` — 1 arquivo(s), 682 linhas

- `backend/alembic/versions/0001_esquema_inicial_do_ultron.py` · 682 linhas · usado por 0 · upgrade, downgrade

### `backend/tests` — 9 arquivo(s), 1449 linhas

- `backend/tests/__init__.py` · 0 linhas · usado por 0
- `backend/tests/conftest.py` · 170 linhas · usado por 5 · FakeProvider, install_fake, last_user, system_of, _git, mini_repo
- `backend/tests/test_auth.py` · 89 linhas · usado por 0 · test_setup_once_and_login, test_setup_token_enforced, test_lockout_after_failed_attempts, test_refresh_rotation_and_reuse_detection, test_invalid_tokens_rejected, test_change_password_revokes_sessions
- `backend/tests/test_deploy_scripts.py` · 183 linhas · usado por 0 · _git, test_scripts_have_valid_syntax, test_cloud_init_refuses_unfilled_token, deploy, _run, test_update_deploys_only_when_needed_and_never_stores_token
- `backend/tests/test_evolution.py` · 272 linhas · usado por 0 · test_codeintel_maps_imports_cycles_and_renders_stable_doc, _approve_publication, test_full_cycle_deterministic_docs_approval_publish_and_rollback, _dev_responder, _new_proposal, test_llm_developer_change_is_tested_audited_and_waits_for_approval
- `backend/tests/test_intelligence.py` · 247 linhas · usado por 0 · test_memory_recall_ranks_relevant_and_respects_status, test_memory_dedupes_and_expires, test_memory_api_crud, test_agent_uses_tool_then_answers, test_agent_tool_outside_its_list_is_denied, test_sensitive_action_requires_approval
- `backend/tests/test_notebook.py` · 191 linhas · usado por 0 · _FakeTunnelClient, test_access_info_shows_only_valid_tunnel_address, test_notebook_files_are_consistent, test_shell_scripts_have_valid_syntax, _tarball, fake_github
- `backend/tests/test_providers.py` · 171 linhas · usado por 0 · test_split_system_merges_and_starts_with_user, test_openai_request_format_and_parsing, test_openai_compatible_errors_are_classified, test_ollama_uses_v1_path, test_gemini_parsing_excludes_thoughts_and_counts_tokens, test_gemini_block_is_refusal
- `backend/tests/test_routing_budget.py` · 126 linhas · usado por 0 · _h, test_fast_tier_prefers_cheaper_model, test_preferred_provider_and_diversity, test_circuit_breaker_excludes_failing_provider, test_no_provider_configured_is_explicit, test_fallback_to_second_provider

### `backend/tests/e2e` — 1 arquivo(s), 69 linhas

- `backend/tests/e2e/fake_llm_server.py` · 69 linhas · usado por 0 · responder, main

### `backend/tests/security` — 2 arquivo(s), 405 linhas

- `backend/tests/security/test_controls.py` · 186 linhas · usado por 0 · test_agent_cannot_write_protected_or_unsafe_paths, test_risk_classification, test_diff_touching_governance_is_blocked_even_if_small, test_rename_out_of_protected_path_is_blocked, test_secret_in_diff_is_blocked, test_dangerous_code_in_low_risk_area_becomes_high
- `backend/tests/security/test_runtime_controls.py` · 219 linhas · usado por 0 · test_audit_log_rejects_update_and_delete, test_audit_chain_detects_tampering, test_audit_redacts_secrets, test_non_human_cannot_change_protected_settings, test_auto_publish_requires_selftest_even_for_owner, test_system_can_only_disable_auto_publish

### `backend/ultron` — 10 arquivo(s), 1526 linhas

- `backend/ultron/__init__.py` · 3 linhas · usado por 12
- `backend/ultron/admin.py` · 71 linhas · usado por 1 · reset_password, github_token, main
- `backend/ultron/config.py` · 156 linhas · usado por 22 · normalize_database_url, Settings, get_settings, reset_settings_cache
- `backend/ultron/db.py` · 87 linhas · usado por 38 · Base, _configure_sqlite, init_engine, get_engine, get_sessionmaker, session_scope
- `backend/ultron/doctor.py` · 85 linhas · usado por 0 · run
- `backend/ultron/main.py` · 180 linhas · usado por 3 · run_migrations, bootstrap, protect_process, harden_data_dir, lifespan, create_app
- `backend/ultron/models.py` · 524 linhas · usado por 38 · _id, _created, User, RefreshToken, SystemSetting, ProviderCredential
- `backend/ultron/settings_store.py` · 135 linhas · usado por 19 · get_setting, get_many, SettingPermissionError, _write, set_setting, record_selftest
- `backend/ultron/telemetry.py` · 138 linhas · usado por 12 · _dims, pending, record_llm_call, record_tool_call, record_metric, error_signature
- `backend/ultron/utils.py` · 147 linhas · usado por 34 · utcnow, new_id, sha256, canonical_json, truncate, tail

### `backend/ultron/agents` — 4 arquivo(s), 356 linhas

- `backend/ultron/agents/__init__.py` · 0 linhas · usado por 0
- `backend/ultron/agents/definitions.py` · 105 linhas · usado por 1
- `backend/ultron/agents/factory.py` · 84 linhas · usado por 2 · seed_builtin_agents, propose_agent
- `backend/ultron/agents/runtime.py` · 167 linhas · usado por 4 · AgentResult, load_agent, build_system_prompt, run_agent

### `backend/ultron/api` — 10 arquivo(s), 1554 linhas

- `backend/ultron/api/__init__.py` · 0 linhas · usado por 2
- `backend/ultron/api/agents.py` · 147 linhas · usado por 1 · AgentRunIn, AgentPatch, MissionIn, list_agents, agent_runs, get_run
- `backend/ultron/api/auth.py` · 172 linhas · usado por 1 · SetupIn, LoginIn, RefreshIn, ChangePasswordIn, user_out, _issue
- `backend/ultron/api/chat.py` · 147 linhas · usado por 1 · ChatIn, FeedbackIn, TitleIn, CouncilIn, list_conversations, get_conversation
- `backend/ultron/api/common.py` · 23 linhas · usado por 6 · iso, row
- `backend/ultron/api/deps.py` · 67 linhas · usado por 8 · current_user, owner, RateLimiter, client_ip
- `backend/ultron/api/evolution.py` · 441 linhas · usado por 2 · _spawn, ProposalIn, EngineeringIn, ToggleIn, DecisionIn, RollbackIn
- `backend/ultron/api/integrations.py` · 160 linhas · usado por 1 · CredentialIn, list_integrations, save_integration, delete_integration, test_integration
- `backend/ultron/api/knowledge.py` · 154 linhas · usado por 1 · MemoryIn, MemoryPatch, ResearchIn, mem_out, list_memory, memory_stats
- `backend/ultron/api/settings.py` · 243 linhas · usado por 2 · SettingsIn, health_check, access_info, get_settings_api, put_settings, usage

### `backend/ultron/core` — 2 arquivo(s), 145 linhas

- `backend/ultron/core/__init__.py` · 0 linhas · usado por 0
- `backend/ultron/core/chat.py` · 145 linhas · usado por 2 · choose_mode, _spawn, handle_message, _save_answer, serialize_message

### `backend/ultron/council` — 2 arquivo(s), 209 linhas

- `backend/ultron/council/__init__.py` · 0 linhas · usado por 2
- `backend/ultron/council/engine.py` · 209 linhas · usado por 3 · CouncilResult, _history_messages, _choices, quick, standard, council

### `backend/ultron/evolution` — 16 arquivo(s), 3427 linhas

- `backend/ultron/evolution/__init__.py` · 0 linhas · usado por 9
- `backend/ultron/evolution/codeintel.py` · 366 linhas · usado por 6 · _complexity, _py_module_name, _iter, analyze_repo, security_scan, refresh
- `backend/ultron/evolution/cycle.py` · 334 linhas · usado por 4 · CycleStop, create_cycle, _log, _checkpoint, _guard, _observe
- `backend/ultron/evolution/developer.py` · 213 linhas · usado por 1 · _related_tests, _file_context, _quick_checks, develop
- `backend/ultron/evolution/diagnostics.py` · 201 linhas · usado por 2 · Finding, analyze, upsert
- `backend/ultron/evolution/evaluation.py` · 252 linhas · usado por 2 · _baseline, requeue_missing_branch, test_candidate, _added_insecure, _frontend_check, finalize
- `backend/ultron/evolution/github.py` · 90 linhas · usado por 3 · GitHubError, repo_slug, GitHub, client_from_settings
- `backend/ultron/evolution/guard.py` · 88 linhas · usado por 3 · EditRejected, _resolve_inside, apply_edits
- `backend/ultron/evolution/observability.py` · 166 linhas · usado por 6 · ApiStats, _pct, snapshot, record_history
- `backend/ultron/evolution/proposals.py` · 184 linhas · usado por 3 · estimate_risk, priority, next_code, create_proposal, has_active_for, recently_failed
- `backend/ultron/evolution/publisher.py` · 318 linhas · usado por 4 · PublishError, _latest_eval, _approved_for_tree, auto_publish_allowed, decide, _open_pr_quietly
- `backend/ultron/evolution/runner.py` · 83 linhas · usado por 1 · _prepare, run_cycle_once, run_selftest, main
- `backend/ultron/evolution/sandbox.py` · 343 linhas · usado por 10 · _uid_mapped, drops_privileges, _chown_tree, _ensure_traversable, capabilities, isolation_level
- `backend/ultron/evolution/scheduler.py` · 279 linhas · usado por 4 · _acquire, _release, _due, job_provider_health, job_memory_retention, job_cache_purge
- `backend/ultron/evolution/selftest.py` · 140 linhas · usado por 2 · run_selftest
- `backend/ultron/evolution/workspace.py` · 370 linhas · usado por 13 · GitError, GitResult, _auth_header, git, GitWorkspace, get_workspace

### `backend/ultron/governance` — 7 arquivo(s), 688 linhas

- `backend/ultron/governance/__init__.py` · 0 linhas · usado por 20
- `backend/ultron/governance/approvals.py` · 66 linhas · usado por 6 · ApprovalError, request_approval, decide, is_approved
- `backend/ultron/governance/audit.py` · 84 linhas · usado por 21 · compute_hash, _sanitize, _insert, record, verify_chain
- `backend/ultron/governance/ci_guard.py` · 60 linhas · usado por 0 · _git, collect, main
- `backend/ultron/governance/integrity.py` · 69 linhas · usado por 2 · governance_fingerprint, check_and_record
- `backend/ultron/governance/permissions.py` · 94 linhas · usado por 8 · Scope, Decision, authorize_tool, validate_new_agent, sanitize_granted_scopes
- `backend/ultron/governance/policy.py` · 315 linhas · usado por 12 · Risk, max_risk, _glob_to_regex, path_matches, normalize_rel_path, PathDecision

### `backend/ultron/llm` — 3 arquivo(s), 351 linhas

- `backend/ultron/llm/__init__.py` · 0 linhas · usado por 5
- `backend/ultron/llm/budget.py` · 159 linhas · usado por 17 · BudgetExceeded, BudgetContext, month_start, _db_sum, clear_cache, monthly_limit_usd
- `backend/ultron/llm/service.py` · 192 linhas · usado por 11 · NoProviderConfigured, AllProvidersFailed, LLMResult, _cache_key, _settings, available_choices

### `backend/ultron/memory` — 3 arquivo(s), 293 linhas

- `backend/ultron/memory/__init__.py` · 0 linhas · usado por 0
- `backend/ultron/memory/embeddings.py` · 81 linhas · usado por 2 · normalize, tokenize, _h, local_embedding, cosine, bm25_scores
- `backend/ultron/memory/service.py` · 212 linhas · usado por 8 · MemoryError_, remember, recall, format_for_context, update_status, forget

### `backend/ultron/missions` — 2 arquivo(s), 544 linhas

- `backend/ultron/missions/__init__.py` · 0 linhas · usado por 0
- `backend/ultron/missions/engine.py` · 544 linhas · usado por 6 · MissionError, add_event, create_mission, validate_plan, _ResourceLocks, _claim

### `backend/ultron/providers` — 8 arquivo(s), 951 linhas

- `backend/ultron/providers/__init__.py` · 0 linhas · usado por 8
- `backend/ultron/providers/anthropic_provider.py` · 113 linhas · usado por 2 · AnthropicProvider
- `backend/ultron/providers/base.py` · 84 linhas · usado por 8 · ChatMessage, ChatRequest, ChatResult, ProviderError, LLMProvider, split_system
- `backend/ultron/providers/catalog.py` · 204 linhas · usado por 6 · ModelSpec, ProviderInfo, get_model, models_for, default_model, embedding_model
- `backend/ultron/providers/gemini.py` · 99 linhas · usado por 2 · GeminiProvider
- `backend/ultron/providers/openai_compat.py` · 106 linhas · usado por 2 · OpenAICompatProvider
- `backend/ultron/providers/registry.py` · 154 linhas · usado por 13 · ProviderHandle, Credential, set_override, invalidate, load_credentials, build_llm_provider
- `backend/ultron/providers/router.py` · 191 linhas · usado por 7 · TaskProfile, ModelChoice, _Health, HealthTracker, _resolve_model, rank

### `backend/ultron/research` — 4 arquivo(s), 338 linhas

- `backend/ultron/research/__init__.py` · 0 linhas · usado por 0
- `backend/ultron/research/extract.py` · 51 linhas · usado por 2 · reliability, html_to_text, wrap_untrusted
- `backend/ultron/research/search.py` · 138 linhas · usado por 4 · SearchHit, _clean, _tavily, _brave, _serper, _searxng
- `backend/ultron/research/service.py` · 149 linhas · usado por 4 · fetch_source, deep_research

### `backend/ultron/security` — 4 arquivo(s), 128 linhas

- `backend/ultron/security/__init__.py` · 0 linhas · usado por 0
- `backend/ultron/security/passwords.py` · 38 linhas · usado por 3 · hash_password, verify_password, validate_password_strength
- `backend/ultron/security/tokens.py` · 47 linhas · usado por 2 · _signing_key, create_access_token, decode_access_token, new_refresh_token
- `backend/ultron/security/vault.py` · 43 linhas · usado por 2 · _fernet, encrypt_secret, decrypt_secret, mask

### `backend/ultron/tools` — 4 arquivo(s), 593 linhas

- `backend/ultron/tools/__init__.py` · 0 linhas · usado por 0
- `backend/ultron/tools/base.py` · 109 linhas · usado por 4 · ToolContext, ToolOutcome, Tool, register, get_tool, all_tools
- `backend/ultron/tools/netguard.py` · 128 linhas · usado por 4 · BlockedURL, FetchResult, _ip_blocked, validate_url, safe_get
- `backend/ultron/tools/registry.py` · 356 linhas · usado por 1 · _web_search, _fetch_url, _wikipedia, _deep_research, _memory_search, _memory_write

### `deploy/huggingface` — 1 arquivo(s), 170 linhas

- `deploy/huggingface/deploy.py` · 170 linhas · usado por 0 · space_url, stage_files, validate_database_url, check_database, deploy, ping

### `frontend/next.config.ts` — 1 arquivo(s), 14 linhas

- `frontend/next.config.ts` · 14 linhas · usado por 0

### `frontend/postcss.config.mjs` — 1 arquivo(s), 1 linhas

- `frontend/postcss.config.mjs` · 1 linhas · usado por 0

### `frontend/public` — 1 arquivo(s), 39 linhas

- `frontend/public/sw.js` · 39 linhas · usado por 0

### `frontend/src` — 24 arquivo(s), 3185 linhas

- `frontend/src/app/agents/page.tsx` · 120 linhas · usado por 0 · Page
- `frontend/src/app/architecture/page.tsx` · 102 linhas · usado por 0 · Page
- `frontend/src/app/chat/page.tsx` · 240 linhas · usado por 0 · Page
- `frontend/src/app/council/page.tsx` · 132 linhas · usado por 0 · Page
- `frontend/src/app/evolution/page.tsx` · 475 linhas · usado por 0 · Page
- `frontend/src/app/integrations/page.tsx` · 125 linhas · usado por 0 · Page
- `frontend/src/app/layout.tsx` · 32 linhas · usado por 0 · metadata, viewport, RootLayout
- `frontend/src/app/login/page.tsx` · 111 linhas · usado por 0 · LoginPage
- `frontend/src/app/memory/page.tsx` · 109 linhas · usado por 0 · Page
- `frontend/src/app/missions/page.tsx` · 159 linhas · usado por 0 · Page
- `frontend/src/app/page.tsx` · 172 linhas · usado por 0 · Page
- `frontend/src/app/research/page.tsx` · 94 linhas · usado por 0 · Page
- `frontend/src/app/security/page.tsx` · 92 linhas · usado por 0 · Page
- `frontend/src/app/settings/page.tsx` · 108 linhas · usado por 0 · Page
- `frontend/src/app/sw-register.tsx` · 12 linhas · usado por 1 · ServiceWorker
- `frontend/src/app/usage/page.tsx` · 93 linhas · usado por 0 · Page
- `frontend/src/app/workspace/page.tsx` · 94 linhas · usado por 0 · Page
- `frontend/src/components/Shell.tsx` · 157 linhas · usado por 15 · NAV, Logo, Shell
- `frontend/src/components/charts.tsx` · 129 linhas · usado por 3 · BarChart, HBars, LineChart, Meter
- `frontend/src/components/qrcode.tsx` · 29 linhas · usado por 1 · QrCode
- `frontend/src/components/ui.tsx` · 345 linhas · usado por 16 · cx, Card, Button, Badge, StatusPill, Stat
- `frontend/src/lib/api.ts` · 150 linhas · usado por 16 · User, apiBase, setApiBase, getSession, saveSession, clearSession
- `frontend/src/lib/format.ts` · 42 linhas · usado por 14 · usd, brl, num, pct, ago, dateTime
- `frontend/src/lib/hooks.ts` · 63 linhas · usado por 14 · useApi, useAction

## Módulos mais centrais (mais importados)

1. `backend/ultron/db.py` — importado por 38
2. `backend/ultron/models.py` — importado por 38
3. `backend/ultron/utils.py` — importado por 34
4. `backend/ultron/config.py` — importado por 22
5. `backend/ultron/governance/audit.py` — importado por 21
6. `backend/ultron/governance/__init__.py` — importado por 20
7. `backend/ultron/settings_store.py` — importado por 19
8. `backend/ultron/llm/budget.py` — importado por 17
9. `frontend/src/components/ui.tsx` — importado por 16
10. `frontend/src/lib/api.ts` — importado por 16

## Achados da análise estática

- complexity: 26
- large_file: 1
- untested_module: 22
- unused_module: 2
