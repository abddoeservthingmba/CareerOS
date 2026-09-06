# Traceability — generated from docs/spec/

Do not edit. Regenerate with `make spec-trace`.

Requirement → track → acceptance criterion → test → status.

| Requirement | Track | Phase | AC | Test | Path | Status |
|---|---|---|---|---|---|---|
| `AI-01` | R1 | P0 | `AC-AI-01.1` | `T-AI-01.1` | `tests/spec/test_ai_base_purity.py` | test present |
| `AI-01` | R1 | P0 | `AC-AI-01.2` | `T-AI-01.2` | `tests/unit/test_llm_request.py` | test present |
| `AI-01` | R1 | P0 | `AC-AI-01.3` | `T-AI-01.3` | `tests/spec/test_layer_leaks.py` | test not written |
| `AI-01` | R1 | P0 | `AC-AI-01.4` | `T-AI-01.4` | `tests/ai/test_adapter_error_mapping.py` | test not written |
| `AI-01` | R1 | P0 | `AC-AI-01.5` | `T-AI-01.5` | `tests/ai/test_complete_json_contract.py` | test not written |
| `AI-02` | R1 | P0 | `AC-AI-02.1` | `T-AI-02.1` | `tests/ai/test_registry_routing.py` | test present |
| `AI-02` | R1 | P0 | `AC-AI-02.2` | `T-AI-02.2` | `tests/spec/test_no_model_literals.py` | test present |
| `AI-02` | R1 | P0 | `AC-AI-02.3` | `T-AI-02.3` | `tests/ai/test_provider_contract.py` | test present |
| `AI-02` | R1 | P0 | `AC-AI-02.4` | `T-AI-02.4` | `tests/ai/test_embedding_migration_guard.py` | test present |
| `AI-02` | R1 | P0 | `AC-AI-02.5` | `T-AI-02.5` | `tests/ai/test_registry_startup_validation.py` | test present |
| `AI-03` | R1 | P0 | `AC-AI-03.1` | `T-AI-03.1` | `tests/ai/test_degradation.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.2` | `T-AI-03.2` | `tests/ai/test_precall_budget_check.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.3` | `T-AI-03.3` | `tests/ai/test_cost_accounting.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.4` | `T-AI-03.4` | `tests/integration/test_budget_trip_e2e.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.5` | `T-AI-03.5` | `tests/ai/test_response_cache.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.6` | `T-AI-03.6` | `tests/ai/test_rate_limiter.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.7` | `T-AI-03.7` | `tests/ai/test_deny_precedence.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.8` | `T-AI-03.8` | `tests/ai/test_cache_before_budget.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.9` | `T-AI-03.9` | `tests/ai/test_budget_states.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.10` | `T-AI-03.10` | `tests/ai/test_budget_recovery.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.11` | `T-AI-03.11` | `tests/integration/test_pack_budget_refusal.py` | test not written |
| `AI-03` | R1 | P0 | `AC-AI-03.12` | `T-AI-03.12` | `tests/spec/test_budget_matrix_coverage.py` | test not written |
| `AI-04` | R1 | P0 | `AC-AI-04.1` | `T-AI-04.1` | `tests/ai/test_usage_rows.py` | test not written |
| `AI-04` | R1 | P0 | `AC-AI-04.2` | `T-AI-04.2` | `tests/spec/test_artifact_provenance.py` | test not written |
| `AI-04` | R1 | P0 | `AC-AI-04.3` | `T-AI-04.3` | `tests/ai/test_unpriced_model.py` | test not written |
| `AI-04` | R1 | P0 | `AC-AI-04.4` | `T-AI-04.4` | `tests/ai/test_usage_write_failure.py` | test not written |
| `AI-04` | R1 | P0 | `AC-AI-04.5` | `T-AI-04.5` | `tests/integration/test_admin_ai_dashboard.py` | test not written |
| `AI-05` | R1 | P0 | `AC-AI-05.1` | `T-AI-05.1` | `tests/spec/test_compliance_docs.py` | test not written |
| `AI-05` | R1 | P0 | `AC-AI-05.2` | `T-AI-05.2` | `tests/ai/test_gemini_startup_guards.py` | test not written |
| `AI-05` | R1 | P0 | `AC-AI-05.3` | `T-AI-05.3` | `tests/spec/test_import_linter_catches_violation.py` | test present |
| `AI-05` | R1 | P0 | `AC-AI-05.4` | `T-AI-05.4` | `tests/ai/test_gemini_credential_surface.py` | test not written |
| `AI-05` | R1 | P0 | `AC-AI-05.5` | `T-AI-05.5` | `.github/workflows/web-ci.yml`, `.github/workflows/mobile-ci.yml` | test not written |
| `AI-05` | R1 | P0 | `AC-AI-05.6` | `T-AI-05.6` | `tests/ai/test_structured_repair.py` | test not written |
| `AI-05` | R1 | P0 | `AC-AI-05.7` | `T-AI-05.7` | `tests/ai/test_base_url_allowlist.py` | test not written |
| `AI-05` | R1 | P0 | `AC-AI-05.8` | `T-AI-05.8` | `tests/integration/test_consent_matches_tier.py` | test not written |
| `AI-06` | R1 | P0 | `AC-AI-06.1` | `T-AI-06.1` | `tests/spec/test_untrusted_rendering.py` | test not written |
| `AI-06` | R1 | P0 | `AC-AI-06.2` | `T-AI-06.2` | `tests/ai/test_injection_corpus.py` | test not written |
| `AI-06` | R1 | P0 | `AC-AI-06.3` | `T-AI-06.3` | `tests/spec/test_no_output_driven_control_flow.py` | test not written |
| `AI-06` | R1 | P0 | `AC-AI-06.4` | `T-AI-06.4` | `tests/unit/test_delimiter_nonce.py` | test present |
| `AI-06` | R1 | P0 | `AC-AI-06.5` | `T-AI-06.5` | `apps/web/src/features/**/__tests__/ai-content.test.tsx`, `apps/mobile/test/ai_content_test.dart` | test not written |
| `AI-06` | R1 | P0 | `AC-AI-06.6` | `T-AI-06.6` | `tests/unit/test_content_caps.py` | test present |
| `AI-07` | R1 | P0 | `AC-AI-07.1` | `T-AI-07.1` | `tests/ai/test_prompt_loader.py` | test not written |
| `AI-07` | R1 | P0 | `AC-AI-07.2` | `T-AI-07.2` | `.github/workflows/api-ci.yml` | test not written |
| `AI-07` | R1 | P0 | `AC-AI-07.3` | `T-AI-07.3` | `tests/ai/test_golden_fake.py` | test not written |
| `AI-07` | R1 | P0 | `AC-AI-07.4` | `T-AI-07.4` | `.github/workflows/nightly-ai.yml` | test not written |
| `AI-07` | R1 | P0 | `AC-AI-07.5` | `T-AI-07.5` | `tests/ai/test_extraction_precision.py` | test not written |
| `AI-07` | R1 | P0 | `AC-AI-07.6` | `T-AI-07.6` | `tests/spec/test_fixture_scrub.py` | test not written |
| `DATA-01` | R1 | P0 | `AC-DATA-01.1` | `T-DATA-01.1` | `tests/unit/test_base_doc.py` | test not written |
| `DATA-01` | R1 | P0 | `AC-DATA-01.2` | `T-DATA-01.2` | `tests/unit/test_doc_hooks.py` | test not written |
| `DATA-01` | R1 | P0 | `AC-DATA-01.3` | `T-DATA-01.3` | `tests/integration/test_readyz_indexes.py` | test not written |
| `DATA-01` | R1 | P0 | `AC-DATA-01.4` | `T-DATA-01.4` | `tests/spec/test_repo_user_scoping.py` | test not written |
| `DATA-01` | R1 | P0 | `AC-DATA-01.5` | `T-DATA-01.5` | `tests/integration/test_soft_delete_default.py` | test not written |
| `DATA-02` | R1 | P0 | `AC-DATA-02.1` | `T-DATA-02.1` | `tests/spec/test_schema_snapshot.py` | test not written |
| `DATA-02` | R1 | P0 | `AC-DATA-02.2` | `T-DATA-02.2` | `tests/spec/test_collection_ownership.py` | test not written |
| `DATA-02` | R1 | P0 | `AC-DATA-02.3` | `T-DATA-02.3` | `tests/integration/test_application_job_xor.py` | test not written |
| `DATA-02` | R1 | P0 | `AC-DATA-02.4` | `T-DATA-02.4` | `tests/integration/test_audit_append_only.py` | test not written |
| `DATA-02` | R1 | P0 | `AC-DATA-02.5` | `T-DATA-02.5` | `tests/unit/test_scorer_input_type.py` | test not written |
| `DATA-02` | R1 | P0 | `AC-DATA-02.6` | `T-DATA-02.6` | `tests/unit/test_embedding_guard.py` | test not written |
| `DATA-03` | R1 | P0 | `AC-DATA-03.1` | `T-DATA-03.1` | `tests/integration/test_index_declarations.py` | test not written |
| `DATA-03` | R1 | P0 | `AC-DATA-03.2` | `T-DATA-03.2` | `tests/integration/test_index_usage.py` | test not written |
| `DATA-03` | R1 | P0 | `AC-DATA-03.3` | `T-DATA-03.3` | `tests/integration/test_index_declarations.py` | test not written |
| `DATA-03` | R1 | P0 | `AC-DATA-03.4` | `T-DATA-03.4` | `tests/integration/test_index_size_budget.py` | test not written |
| `DATA-04` | R1 | P0 | `AC-DATA-04.1` | `T-DATA-04.1` | `tests/unit/test_object_keys.py`, `tests/integration/test_key_audit.py` | test not written |
| `DATA-04` | R1 | P0 | `AC-DATA-04.2` | `T-DATA-04.2` | `tests/integration/test_presigned_urls.py` | test not written |
| `DATA-04` | R1 | P0 | `AC-DATA-04.3` | `T-DATA-04.3` | `tests/integration/test_upload_memory.py` | test not written |
| `DATA-04` | R1 | P0 | `AC-DATA-04.4` | `T-DATA-04.4` | `tests/unit/test_magic_bytes.py` | test not written |
| `DATA-04` | R1 | P0 | `AC-DATA-04.5` | `T-DATA-04.5` | `tests/integration/test_deletion_sweep.py` | test not written |
| `DATA-05` | R1 | P0 | `AC-DATA-05.1` | `T-DATA-05.1` | `tests/integration/test_ttl_indexes.py` | test not written |
| `DATA-05` | R1 | P0 | `AC-DATA-05.2` | `T-DATA-05.2` | `tests/integration/test_job_purge.py` | test not written |
| `DATA-05` | R1 | P0 | `AC-DATA-05.3` | `T-DATA-05.3` | `tests/integration/test_account_purge.py` | test not written |
| `DATA-05` | R1 | P0 | `AC-DATA-05.4` | `T-DATA-05.4` | `tests/spec/test_retention_coverage.py` | test not written |
| `DATA-05` | R1 | P0 | `AC-DATA-05.5` | `T-DATA-05.5` | `tests/integration/test_purge_isolation.py` | test not written |
| `DATA-06` | R1 | P0 | `AC-DATA-06.1` | `T-DATA-06.1` | `tests/unit/test_embedding_quantization.py` | test present |
| `DATA-06` | R1 | P0 | `AC-DATA-06.2` | `T-DATA-06.2` | `tests/integration/test_description_truncation.py` | test not written |
| `DATA-06` | R1 | P0 | `AC-DATA-06.3` | `T-DATA-06.3` | `tests/integration/test_staleness_pressure.py` | test not written |
| `DATA-06` | R1 | P0 | `AC-DATA-06.4` | `T-DATA-06.4` | `tests/integration/test_capacity_report.py` | test not written |
| `DATA-06` | R1 | P0 | `AC-DATA-06.5` | `T-DATA-06.5` | `tests/integration/test_storage_budget.py` | test not written |
| `DATA-07` | R1 | P0 | `AC-DATA-07.1` | `T-DATA-07.1` | `tests/spec/test_field_registry.py` | test not written |
| `DATA-07` | R1 | P0 | `AC-DATA-07.2` | `T-DATA-07.2` | `tests/spec/test_field_registry.py` | test not written |
| `DATA-07` | R1 | P0 | `AC-DATA-07.3` | `T-DATA-07.3` | `tests/spec/test_field_registry.py` | test not written |
| `DATA-07` | R1 | P0 | `AC-DATA-07.4` | `T-DATA-07.4` | `tests/spec/test_field_registry.py` | test not written |
| `DATA-07` | R1 | P0 | `AC-DATA-07.5` | `T-DATA-07.5` | `tests/spec/test_field_registry.py` | test not written |
| `DATA-07` | R1 | P0 | `AC-DATA-07.6` | `T-DATA-07.6` | `tests/spec/test_schema_snapshot.py` | test not written |
| `DATA-07` | R1 | P0 | `AC-DATA-07.7` | `T-DATA-07.7` | `tests/spec/test_enum_registry.py` | test not written |
| `DEP-01` | R1 | P0 | `AC-DEP-01.1` | `T-DEP-01.1` | `tests/spec/test_dependency_manifest.py` | test present |
| `DEP-01` | R1 | P0 | `AC-DEP-01.2` | `T-DEP-01.2` | `tests/spec/test_dependency_manifest.py` | test present |
| `DEP-01` | R1 | P0 | `AC-DEP-01.3` | `T-DEP-01.3` | `tests/spec/test_dependency_manifest.py` | test present |
| `DEP-01` | R1 | P0 | `AC-DEP-01.4` | `T-DEP-01.4` | `tests/spec/test_dependency_manifest.py` | test present |
| `DEP-01` | R1 | P0 | `AC-DEP-01.5` | `T-DEP-01.5` | `tests/spec/test_dependency_manifest.py` | test present |
| `DEP-01` | R1 | P0 | `AC-DEP-01.6` | `T-DEP-01.6` | `tests/spec/test_dependency_manifest.py` | test present |
| `DEP-02` | R1 | P0 | `AC-DEP-02.1` | `T-DEP-02.1` | `tests/spec/test_module_graph.py` | test present |
| `DEP-02` | R1 | P0 | `AC-DEP-02.2` | `T-DEP-02.2` | `tests/spec/test_module_graph.py` | test present |
| `DEP-02` | R1 | P0 | `AC-DEP-02.3` | `T-DEP-02.3` | `tests/spec/test_module_graph.py` | test present |
| `DEP-02` | R1 | P0 | `AC-DEP-02.4` | `T-DEP-02.4` | `tests/spec/test_module_graph.py` | test present |
| `DEP-03` | R1 | P0 | `AC-DEP-03.1` | `T-DEP-03.1` | `tests/spec/test_track_closure.py` | test present |
| `DEP-03` | R1 | P0 | `AC-DEP-03.2` | `T-DEP-03.2` | `tests/spec/test_track_closure.py` | test present |
| `DEP-03` | R1 | P0 | `AC-DEP-03.3` | `T-DEP-03.3` | `tests/spec/test_track_closure.py` | test present |
| `DEP-03` | R1 | P0 | `AC-DEP-03.4` | `T-DEP-03.4` | `tests/spec/test_track_closure.py` | test present |
| `DEP-04` | R1 | P0 | `AC-DEP-04.1` | `T-DEP-04.1` | `tests/spec/test_phase_closure.py` | test present |
| `DEP-04` | R1 | P0 | `AC-DEP-04.2` | `T-DEP-04.2` | `tests/spec/test_phase_closure.py` | test present |
| `DEP-04` | R1 | P0 | `AC-DEP-04.3` | `T-DEP-04.3` | `tests/spec/test_phase_closure.py` | test present |
| `DEP-04` | R1 | P0 | `AC-DEP-04.4` | `T-DEP-04.4` | `tests/spec/test_phase_closure.py` | test present |
| `DEP-04` | R1 | P0 | `AC-DEP-04.5` | `T-DEP-04.5` | `tests/spec/test_phase_closure.py` | test present |
| `DEP-05` | R1 | P0 | `AC-DEP-05.1` | `T-DEP-05.1` | `tests/spec/test_phase_closure.py` | test present |
| `DEP-05` | R1 | P0 | `AC-DEP-05.2` | `T-DEP-05.2` | `tests/spec/test_email_ownership.py` | test not written |
| `DEP-05` | R1 | P0 | `AC-DEP-05.3` | `T-DEP-05.3` | `tests/spec/test_phase_closure.py` | test present |
| `DEP-05` | R1 | P0 | `AC-DEP-05.4` | `T-DEP-05.4` | `tests/unit/test_embedding_quantization.py` | test present |
| `DEP-05` | R1 | P0 | `AC-DEP-05.5` | `T-DEP-05.5` | `tests/spec/test_phase_closure.py` | test present |
| `DEP-05` | R1 | P0 | `AC-DEP-05.6` | `T-DEP-05.6` | `tests/spec/test_phase_closure.py` | test present |
| `DEP-05` | R1 | P0 | `AC-DEP-05.7` | `T-DEP-05.7` | `tests/spec/test_consistency_report.py` | test not written |
| `DEP-06` | R1 | P0 | `AC-DEP-06.1` | `T-DEP-06.1` | `tests/spec/test_handoff_bundle.py` | test present |
| `DEP-06` | R1 | P0 | `AC-DEP-06.2` | `T-DEP-06.2` | `tests/spec/test_handoff_bundle.py` | test present |
| `DEP-06` | R1 | P0 | `AC-DEP-06.3` | `T-DEP-06.3` | `tests/spec/test_handoff_bundle.py` | test present |
| `DEP-06` | R1 | P0 | `AC-DEP-06.4` | `T-DEP-06.4` | `tests/spec/test_handoff_bundle.py` | test present |
| `FOUND-01` | R1 | P0 | `AC-FOUND-01.1` | `T-FOUND-01.1` | `tests/integration/test_compose_boot.py` | test not written |
| `FOUND-01` | R1 | P0 | `AC-FOUND-01.2` | `T-FOUND-01.2` | `.github/workflows/api-ci.yml` | test not written |
| `FOUND-01` | R1 | P0 | `AC-FOUND-01.3` | `T-FOUND-01.3` | `tests/spec/test_layer_leaks.py` | test not written |
| `FOUND-01` | R1 | P0 | `AC-FOUND-01.4` | `T-FOUND-01.4` | `tests/spec/test_layer_leaks.py` | test not written |
| `FOUND-01` | R1 | P0 | `AC-FOUND-01.5` | `T-FOUND-01.5` | `.github/workflows/contracts.yml` | test not written |
| `FOUND-02` | R1 | P0 | `AC-FOUND-02.1` | `T-FOUND-02.1` | `tests/unit/test_config_failfast.py` | test present |
| `FOUND-02` | R1 | P0 | `AC-FOUND-02.2` | `T-FOUND-02.2` | `tests/unit/test_config_secrets.py` | test present |
| `FOUND-02` | R1 | P0 | `AC-FOUND-02.3` | `T-FOUND-02.3` | `tests/spec/test_env_example_parity.py` | test present |
| `FOUND-02` | R1 | P0 | `AC-FOUND-02.4` | `T-FOUND-02.4` | `tests/spec/test_no_hardcoded_product_name.py` | test present |
| `FOUND-02` | R1 | P0 | `AC-FOUND-02.5` | `T-FOUND-02.5` | `tests/integration/test_feature_flags.py` | test present |
| `FOUND-03` | R1 | P0 | `AC-FOUND-03.1` | `T-FOUND-03.1` | `tests/spec/test_no_direct_clock.py` | test present |
| `FOUND-03` | R1 | P0 | `AC-FOUND-03.2` | `T-FOUND-03.2` | `tests/unit/test_time_utc.py` | test present |
| `FOUND-03` | R1 | P0 | `AC-FOUND-03.3` | `T-FOUND-03.3` | `tests/contract/test_no_objectid_in_responses.py` | test not written |
| `FOUND-03` | R1 | P0 | `AC-FOUND-03.4` | `T-FOUND-03.4` | `tests/unit/test_money.py` | test present |
| `FOUND-03` | R1 | P0 | `AC-FOUND-03.5` | `T-FOUND-03.5` | `tests/unit/test_fx.py` | test present |
| `FOUND-03` | R1 | P0 | `AC-FOUND-03.6` | `T-FOUND-03.6` | `tests/unit/test_ulid.py` | test present |
| `FOUND-04` | R1 | P0 | `AC-FOUND-04.1` | `T-FOUND-04.1` | `.github/workflows/api-ci.yml` | test not written |
| `FOUND-04` | R1 | P0 | `AC-FOUND-04.2` | `T-FOUND-04.2` | `tests/spec/test_module_anatomy.py` | test present |
| `FOUND-04` | R1 | P0 | `AC-FOUND-04.3` | `T-FOUND-04.3` | `tests/spec/test_import_linter_catches_violation.py` | test present |
| `FOUND-04` | R1 | P0 | `AC-FOUND-04.4` | `T-FOUND-04.4` | `tests/spec/test_module_readmes.py` | test present |
| `FOUND-05` | R1 | P0 | `AC-FOUND-05.1` | `T-FOUND-05.1` | `tests/spec/test_new_module_scaffold.py` | test present |
| `FOUND-05` | R1 | P0 | `AC-FOUND-05.2` | `T-FOUND-05.2` | `.github/workflows/api-ci.yml` | test not written |
| `FOUND-05` | R1 | P0 | `AC-FOUND-05.3` | `T-FOUND-05.3` | `tests/spec/test_import_contracts.py` | test present |
| `FOUND-05` | R1 | P0 | `AC-FOUND-05.4` | `T-FOUND-05.4` | `tests/contract/test_response_models.py` | test not written |
| `FOUND-05` | R1 | P0 | `AC-FOUND-05.5` | `T-FOUND-05.5` | `tests/spec/test_import_contracts.py` | test present |
| `FOUND-06` | R1 | P0 | `AC-FOUND-06.1` | `T-FOUND-06.1` | `tests/spec/test_traceability.py` | test present |
| `FOUND-06` | R1 | P0 | `AC-FOUND-06.2` | `T-FOUND-06.2` | `tests/spec/test_traceability.py` | test present |
| `FOUND-06` | R1 | P0 | `AC-FOUND-06.3` | `T-FOUND-06.3` | `tests/spec/test_traceability.py` | test present |
| `FOUND-06` | R1 | P0 | `AC-FOUND-06.4` | `T-FOUND-06.4` | `tests/spec/test_traceability.py` | test present |
| `FOUND-07` | R1 | P0 | `AC-FOUND-07.1` | `T-FOUND-07.1` | `tests/integration/test_pagination_stability.py` | test not written |
| `FOUND-07` | R1 | P0 | `AC-FOUND-07.2` | `T-FOUND-07.2` | `tests/integration/test_cursor_security.py` | test not written |
| `FOUND-07` | R1 | P0 | `AC-FOUND-07.3` | `T-FOUND-07.3` | `tests/integration/test_cursor_security.py` | test not written |
| `FOUND-07` | R1 | P0 | `AC-FOUND-07.4` | `T-FOUND-07.4` | `tests/integration/test_index_usage.py` | test not written |
| `FOUND-07` | R1 | P0 | `AC-FOUND-07.5` | `T-FOUND-07.5` | `tests/unit/test_pagination_limits.py` | test not written |
| `FOUND-08` | R1 | P0 | `AC-FOUND-08.1` | `T-FOUND-08.1` | `tests/integration/test_idempotency.py` | test not written |
| `FOUND-08` | R1 | P0 | `AC-FOUND-08.2` | `T-FOUND-08.2` | `tests/integration/test_idempotency.py` | test not written |
| `FOUND-08` | R1 | P0 | `AC-FOUND-08.3` | `T-FOUND-08.3` | `tests/integration/test_idempotency.py` | test not written |
| `FOUND-08` | R1 | P0 | `AC-FOUND-08.4` | `T-FOUND-08.4` | `tests/contract/test_idempotent_routes.py` | test not written |
| `FOUND-08` | R1 | P0 | `AC-FOUND-08.5` | `T-FOUND-08.5` | `tests/integration/test_idempotency_redis_down.py` | test not written |
| `FOUND-09` | R1 | P0 | `AC-FOUND-09.1` | `T-FOUND-09.1` | `tests/spec/test_handlers_only_enqueue.py` | test not written |
| `FOUND-09` | R1 | P0 | `AC-FOUND-09.2` | `T-FOUND-09.2` | `tests/unit/test_event_bus.py` | test not written |
| `FOUND-09` | R1 | P0 | `AC-FOUND-09.3` | `T-FOUND-09.3` | `tests/unit/test_event_payload_primitives.py` | test not written |
| `FOUND-09` | R1 | P0 | `AC-FOUND-09.4` | `T-FOUND-09.4` | `tests/integration/test_event_wiring.py` | test not written |
| `FOUND-09` | R1 | P0 | `AC-FOUND-09.5` | `T-FOUND-09.5` | `tests/spec/test_events_doc.py` | test not written |
| `FOUND-10` | R1 | P0 | `AC-FOUND-10.1` | `T-FOUND-10.1` | `tests/spec/test_task_signatures.py` | test not written |
| `FOUND-10` | R1 | P0 | `AC-FOUND-10.2` | `T-FOUND-10.2` | `tests/spec/test_task_signatures.py` | test not written |
| `FOUND-10` | R1 | P0 | `AC-FOUND-10.3` | `T-FOUND-10.3` | `tests/integration/test_task_idempotency.py` | test not written |
| `FOUND-10` | R1 | P0 | `AC-FOUND-10.4` | `T-FOUND-10.4` | `tests/integration/test_worker_restart.py` | test not written |
| `FOUND-10` | R1 | P0 | `AC-FOUND-10.5` | `T-FOUND-10.5` | `tests/integration/test_failed_tasks.py` | test not written |
| `FOUND-10` | R1 | P0 | `AC-FOUND-10.6` | `T-FOUND-10.6` | `tests/integration/test_cron_locks.py` | test not written |
| `FOUND-11` | R1 | P0 | `AC-FOUND-11.1` | `T-FOUND-11.1` | `tests/contract/test_accepted_responses.py` | test not written |
| `FOUND-11` | R1 | P0 | `AC-FOUND-11.2` | `T-FOUND-11.2` | `tests/integration/test_poll_fallback.py` | test not written |
| `FOUND-11` | R1 | P0 | `AC-FOUND-11.3` | `T-FOUND-11.3` | `tests/integration/test_sse_ownership.py` | test not written |
| `FOUND-11` | R1 | P0 | `AC-FOUND-11.4` | `T-FOUND-11.4` | `tests/integration/test_sse_lifecycle.py` | test not written |
| `FOUND-11` | R1 | P0 | `AC-FOUND-11.5` | `T-FOUND-11.5` | `tests/contract/test_sse_headers.py` | test not written |
| `FOUND-12` | R1 | P0 | `AC-FOUND-12.1` | `T-FOUND-12.1` | `tests/contract/test_problem_json.py` | test not written |
| `FOUND-12` | R1 | P0 | `AC-FOUND-12.2` | `T-FOUND-12.2` | `tests/integration/test_unhandled_exception.py` | test not written |
| `FOUND-12` | R1 | P0 | `AC-FOUND-12.3` | `T-FOUND-12.3` | `tests/integration/test_request_id_propagation.py` | test not written |
| `FOUND-12` | R1 | P0 | `AC-FOUND-12.4` | `T-FOUND-12.4` | `tests/spec/test_error_code_registry.py` | test present |
| `FOUND-12` | R1 | P0 | `AC-FOUND-12.5` | `T-FOUND-12.5` | `tests/spec/test_error_code_registry.py` | test present |
| `FOUND-13` | R1 | P0 | `AC-FOUND-13.1` | `T-FOUND-13.1` | `tests/contract/test_route_metadata.py` | test not written |
| `FOUND-13` | R1 | P0 | `AC-FOUND-13.2` | `T-FOUND-13.2` | `.github/workflows/contracts.yml` | test not written |
| `FOUND-13` | R1 | P0 | `AC-FOUND-13.3` | `T-FOUND-13.3` | `.github/workflows/contracts.yml` | test not written |
| `FOUND-13` | R1 | P0 | `AC-FOUND-13.4` | `T-FOUND-13.4` | `.github/workflows/contracts.yml` | test not written |
| `FOUND-13` | R1 | P0 | `AC-FOUND-13.5` | `T-FOUND-13.5` | `tests/contract/test_client_surface.py` | test not written |
| `FOUND-14` | R1 | P0 | `AC-FOUND-14.1` | `T-FOUND-14.1` | `tests/integration/test_log_privacy.py` | test not written |
| `FOUND-14` | R1 | P0 | `AC-FOUND-14.2` | `T-FOUND-14.2` | `tests/integration/test_request_id_propagation.py` | test not written |
| `FOUND-14` | R1 | P0 | `AC-FOUND-14.3` | `T-FOUND-14.3` | `tests/integration/test_metrics_endpoint.py` | test not written |
| `FOUND-14` | R1 | P0 | `AC-FOUND-14.4` | `T-FOUND-14.4` | `tests/unit/test_sentry_before_send.py` | test not written |
| `FOUND-14` | R1 | P0 | `AC-FOUND-14.5` | `T-FOUND-14.5` | `tests/unit/test_provider_error_logging.py` | test not written |
| `FOUND-15` | R1 | P0 | `AC-FOUND-15.1` | `T-FOUND-15.1` | `tests/spec/test_status_declared.py` | test present |
| `FOUND-15` | R1 | P0 | `AC-FOUND-15.2` | `T-FOUND-15.2` | `tests/spec/test_status_declared.py` | test present |
| `FOUND-15` | R1 | P0 | `AC-FOUND-15.3` | `T-FOUND-15.3` | `tests/integration/test_flag_flip.py` | test not written |
| `FOUND-15` | R1 | P0 | `AC-FOUND-15.4` | `T-FOUND-15.4` | `apps/web/.../flag-off-complete.test.tsx`, `apps/mobile/test/flag_off_complete_test.dart` | test not written |
| `FOUND-15` | R1 | P0 | `AC-FOUND-15.5` | `T-FOUND-15.5` | `tests/contract/test_stub_routes.py` | test not written |
| `FOUND-15` | R1 | P0 | `AC-FOUND-15.6` | `T-FOUND-15.6` | `tests/spec/test_absent_sections.py` | test present |
| `FOUND-15` | R1 | P0 | `AC-FOUND-15.7` | `T-FOUND-15.7` | `tests/spec/test_no_placeholders.py` | test present |
| `FOUND-15` | R1 | P0 | `AC-FOUND-15.8` | `T-FOUND-15.8` | `tests/spec/test_status_matches_reality.py` | test not written |
| `FOUND-15` | R1 | P0 | `AC-FOUND-15.9` | `T-FOUND-15.9` | `tests/integration/test_admin_flags.py` | test not written |
| `FOUND-16` | R1 | P0 | `AC-FOUND-16.1` | `T-FOUND-16.1` | `tests/unit/test_email_templates.py` | test not written |
| `FOUND-16` | R1 | P0 | `AC-FOUND-16.2` | `T-FOUND-16.2` | `tests/unit/test_template_registry.py` | test not written |
| `FOUND-16` | R1 | P0 | `AC-FOUND-16.3` | `T-FOUND-16.3` | `tests/integration/test_email_idempotency.py` | test not written |
| `FOUND-16` | R1 | P0 | `AC-FOUND-16.4` | `T-FOUND-16.4` | `tests/integration/test_log_privacy.py` | test not written |
| `FOUND-16` | R1 | P0 | `AC-FOUND-16.5` | `T-FOUND-16.5` | `tests/spec/test_no_live_email.py` | test not written |
| `FOUND-16` | R1 | P0 | `AC-FOUND-16.6` | `T-FOUND-16.6` | `tests/integration/test_bounce_handling.py` | test not written |
| `FOUND-16` | R1 | P0 | `AC-FOUND-16.7` | `T-FOUND-16.7` | `tests/spec/test_email_ownership.py` | test not written |
| `FOUND-16` | R1 | P0 | `AC-FOUND-16.8` | `T-FOUND-16.8` | `tests/unit/test_email_retries.py` | test not written |
| `FOUND-16` | R1 | P0 | `AC-FOUND-16.9` | `T-FOUND-16.9` | `tests/integration/test_email_adapter_contract.py` | test not written |
| `MOB-01` | R1 | P0 | `AC-MOB-01.1` | `T-MOB-01.1` | `.github/workflows/mobile-ci.yml` | test not written |
| `MOB-01` | R1 | P0 | `AC-MOB-01.2` | `T-MOB-01.2` | `.github/workflows/contracts.yml` | test not written |
| `MOB-01` | R1 | P0 | `AC-MOB-01.3` | `T-MOB-01.3` | `apps/mobile/test/architecture_test.dart` | test not written |
| `MOB-01` | R1 | P0 | `AC-MOB-01.4` | `T-MOB-01.4` | `.github/workflows/mobile-ci.yml` | test not written |
| `MOB-01` | R1 | P0 | `AC-MOB-01.5` | `T-MOB-01.5` | `tests/spec/test_no_admin_in_mobile.py` | test not written |
| `OPS-01` | R1 | P0 | `AC-OPS-01.1` | `T-OPS-01.1` | `.github/workflows/api-ci.yml` | test not written |
| `OPS-01` | R1 | P0 | `AC-OPS-01.2` | `T-OPS-01.2` | `.github/workflows/api-ci.yml` | test not written |
| `OPS-01` | R1 | P0 | `AC-OPS-01.3` | `T-OPS-01.3` | `tests/integration/test_readyz.py` | test not written |
| `OPS-01` | R1 | P0 | `AC-OPS-01.4` | `T-OPS-01.4` | `.github/workflows/api-ci.yml` | test not written |
| `OPS-01` | R1 | P0 | `AC-OPS-01.5` | `T-OPS-01.5` | `.github/workflows/api-ci.yml` | test not written |
| `OPS-01` | R1 | P0 | `AC-OPS-01.6` | `T-OPS-01.6` | `tests/integration/test_compose_boot.py` | test not written |
| `OPS-01` | R1 | P0 | `AC-OPS-01.7` | `T-OPS-01.7` | `.github/workflows/api-ci.yml` | test not written |
| `OPS-02` | R1 | P0 | `AC-OPS-02.1` | `T-OPS-02.1` | `infra/scripts/check_origin_lockdown.sh`, `tests/spec/test_origin_check_exists.py` | test not written |
| `OPS-02` | R1 | P0 | `AC-OPS-02.2` | `T-OPS-02.2` | `tests/spec/test_env_parity.py` | test not written |
| `OPS-02` | R1 | P0 | `AC-OPS-02.3` | `T-OPS-02.3` | `.github/workflows/deploy-staging.yml`, `.github/workflows/deploy-prod.yml` | test not written |
| `OPS-02` | R1 | P0 | `AC-OPS-02.4` | `T-OPS-02.4` | `.github/workflows/deploy-staging.yml`, `.github/workflows/deploy-prod.yml` | test not written |
| `OPS-02` | R1 | P0 | `AC-OPS-02.5` | `T-OPS-02.5` | `.github/workflows/deploy-staging.yml`, `.github/workflows/deploy-prod.yml` | test not written |
| `OPS-02` | R1 | P0 | `AC-OPS-02.6` | `T-OPS-02.6` | `.github/workflows/api-ci.yml` | test not written |
| `OPS-03` | R1 | P0 | `AC-OPS-03.1` | `T-OPS-03.1` | `infra/scripts/check_branch_protection.sh` | test not written |
| `OPS-03` | R1 | P0 | `AC-OPS-03.2` | `T-OPS-03.2` | `tests/spec/test_coverage_config.py` | test not written |
| `OPS-03` | R1 | P0 | `AC-OPS-03.3` | `T-OPS-03.3` | `tests/spec/test_no_live_source_calls.py` | test not written |
| `OPS-03` | R1 | P0 | `AC-OPS-03.4` | `T-OPS-03.4` | `.github/workflows/contracts.yml` | test not written |
| `OPS-03` | R1 | P0 | `AC-OPS-03.5` | `T-OPS-03.5` | `.github/workflows/deploy-prod.yml` | test not written |
| `OPS-03` | R1 | P0 | `AC-OPS-03.6` | `T-OPS-03.6` | `.github/workflows/api-ci.yml` | test not written |
| `OPS-04` | R1 | P0 | `AC-OPS-04.1` | `T-OPS-04.1` | `tests/integration/test_metrics_endpoint.py` | test not written |
| `OPS-04` | R1 | P0 | `AC-OPS-04.2` | `T-OPS-04.2` | `tests/integration/test_log_privacy.py` | test not written |
| `OPS-04` | R1 | P0 | `AC-OPS-04.3` | `T-OPS-04.3` | `tests/integration/test_tracing.py` | test not written |
| `OPS-04` | R1 | P0 | `AC-OPS-04.4` | `T-OPS-04.4` | `tests/integration/test_alert_conditions.py` | test not written |
| `OPS-04` | R1 | P0 | `AC-OPS-04.5` | `T-OPS-04.5` | `tests/spec/test_runbooks_present.py` | test not written |
| `OPS-05` | R1 | P0 | `AC-OPS-05.1` | `T-OPS-05.1` | `tests/spec/test_env_example_parity.py` | test present |
| `OPS-05` | R1 | P0 | `AC-OPS-05.2` | `T-OPS-05.2` | `tests/spec/test_env_example_no_secrets.py` | test not written |
| `OPS-05` | R1 | P0 | `AC-OPS-05.3` | `T-OPS-05.3` | `tests/ai/test_gemini_startup_guards.py` | test not written |
| `OPS-05` | R1 | P0 | `AC-OPS-05.4` | `T-OPS-05.4` | `.github/workflows/api-ci.yml` | test not written |
| `OPS-06` | R1 | P0 | `AC-OPS-06.1` | `T-OPS-06.1` | `tests/integration/test_backup_restore.py` | test not written |
| `OPS-06` | R1 | P0 | `AC-OPS-06.2` | `T-OPS-06.2` | `tests/integration/test_backup_verification.py` | test not written |
| `OPS-06` | R1 | P0 | `AC-OPS-06.3` | `T-OPS-06.3` | `infra/scripts/check_backup_retention.sh` | test not written |
| `OPS-06` | R1 | P0 | `AC-OPS-06.4` | `T-OPS-06.4` | `tests/integration/test_r2_versioning.py` | test not written |
| `OPS-06` | R1 | P0 | `AC-OPS-06.5` | `T-OPS-06.5` | `tests/spec/test_runbooks_present.py` | test not written |
| `SEC-01` | R1 | P0 | `AC-SEC-01.1` | `T-SEC-01.1` | `tests/spec/test_threat_model_doc.py`, `tests/spec/test_traceability.py` | test not written |
| `SEC-01` | R1 | P0 | `AC-SEC-01.2` | `T-SEC-01.2` | `tests/spec/test_threat_model_doc.py`, `tests/spec/test_traceability.py` | test not written |
| `SEC-01` | R1 | P0 | `AC-SEC-01.3` | `T-SEC-01.3` | `tests/spec/test_threat_model_doc.py`, `tests/spec/test_traceability.py` | test not written |
| `WEB-01` | R1 | P0 | `AC-WEB-01.1` | `T-WEB-01.1` | `.github/workflows/web-ci.yml` | test not written |
| `WEB-01` | R1 | P0 | `AC-WEB-01.2` | `T-WEB-01.2` | `.github/workflows/web-ci.yml` | test not written |
| `WEB-01` | R1 | P0 | `AC-WEB-01.3` | `T-WEB-01.3` | `.github/workflows/contracts.yml` | test not written |
| `WEB-01` | R1 | P0 | `AC-WEB-01.4` | `T-WEB-01.4` | `.github/workflows/web-ci.yml` | test not written |
| `WEB-01` | R1 | P0 | `AC-WEB-01.5` | `T-WEB-01.5` | `apps/web/scripts/check-bundle-size.mjs` | test not written |
| `WEB-01` | R1 | P0 | `AC-WEB-01.6` | `T-WEB-01.6` | `apps/web/scripts/check-admin-chunk.mjs` | test not written |
| `ADMIN-06` | R1 | P1 | `AC-ADMIN-06.1` | `T-ADMIN-06.1` | `tests/integration/test_cross_tenant_sweep.py` | test not written |
| `ADMIN-06` | R1 | P1 | `AC-ADMIN-06.2` | `T-ADMIN-06.2` | `.github/workflows/web-ci.yml`, `apps/web/scripts/check-admin-chunk.mjs` | test not written |
| `ADMIN-06` | R1 | P1 | `AC-ADMIN-06.3` | `T-ADMIN-06.3` | `tests/spec/test_no_admin_in_mobile.py` | test not written |
| `ADMIN-06` | R1 | P1 | `AC-ADMIN-06.4` | `T-ADMIN-06.4` | `tests/integration/test_admin_audit.py` | test not written |
| `ADMIN-06` | R1 | P1 | `AC-ADMIN-06.5` | `T-ADMIN-06.5` | `tests/integration/test_admin_audit.py` | test not written |
| `ADMIN-06` | R1 | P1 | `AC-ADMIN-06.6` | `T-ADMIN-06.6` | `tests/spec/test_no_role_grant_endpoint.py` | test not written |
| `ADMIN-06` | R1 | P1 | `AC-ADMIN-06.7` | `T-ADMIN-06.7` | `tests/integration/test_admin_ip_allowlist.py` | test not written |
| `AUTH-01` | R1 | P1 | `AC-AUTH-01.1` | `T-AUTH-01.1` | `tests/unit/test_password_policy.py` | test not written |
| `AUTH-01` | R1 | P1 | `AC-AUTH-01.2` | `T-AUTH-01.2` | `tests/integration/test_breach_check.py` | test not written |
| `AUTH-01` | R1 | P1 | `AC-AUTH-01.3` | `T-AUTH-01.3` | `tests/integration/test_breach_check.py` | test not written |
| `AUTH-01` | R1 | P1 | `AC-AUTH-01.4` | `T-AUTH-01.4` | `tests/integration/test_registration_enumeration.py` | test not written |
| `AUTH-01` | R1 | P1 | `AC-AUTH-01.5` | `T-AUTH-01.5` | `tests/unit/test_email_normalization.py` | test not written |
| `AUTH-01` | R1 | P1 | `AC-AUTH-01.6` | `T-AUTH-01.6` | `tests/unit/test_argon2_params.py` | test not written |
| `AUTH-01` | R1 | P1 | `AC-AUTH-01.7` | `T-AUTH-01.7` | `tests/integration/test_consent_capture.py` | test not written |
| `AUTH-02` | R1 | P1 | `AC-AUTH-02.1` | `T-AUTH-02.1` | `tests/integration/test_google_oidc.py` | test not written |
| `AUTH-02` | R1 | P1 | `AC-AUTH-02.2` | `T-AUTH-02.2` | `tests/integration/test_google_oidc.py` | test not written |
| `AUTH-02` | R1 | P1 | `AC-AUTH-02.3` | `T-AUTH-02.3` | `tests/integration/test_google_oidc.py` | test not written |
| `AUTH-02` | R1 | P1 | `AC-AUTH-02.4` | `T-AUTH-02.4` | `tests/integration/test_google_oidc.py` | test not written |
| `AUTH-02` | R1 | P1 | `AC-AUTH-02.5` | `T-AUTH-02.5` | `tests/integration/test_google_oidc.py` | test not written |
| `AUTH-02` | R1 | P1 | `AC-AUTH-02.6` | `T-AUTH-02.6` | `.github/workflows/web-ci.yml`, `.github/workflows/mobile-ci.yml` | test not written |
| `AUTH-03` | R1 | P1 | `AC-AUTH-03.1` | `T-AUTH-03.1` | `tests/integration/test_email_verification.py`, `tests/integration/test_log_privacy.py` | test not written |
| `AUTH-03` | R1 | P1 | `AC-AUTH-03.2` | `T-AUTH-03.2` | `tests/integration/test_email_verification.py`, `tests/integration/test_log_privacy.py` | test not written |
| `AUTH-03` | R1 | P1 | `AC-AUTH-03.3` | `T-AUTH-03.3` | `tests/integration/test_email_verification.py`, `tests/integration/test_log_privacy.py` | test not written |
| `AUTH-03` | R1 | P1 | `AC-AUTH-03.4` | `T-AUTH-03.4` | `tests/integration/test_email_verification.py`, `tests/integration/test_log_privacy.py` | test not written |
| `AUTH-03` | R1 | P1 | `AC-AUTH-03.5` | `T-AUTH-03.5` | `tests/integration/test_email_verification.py`, `tests/integration/test_log_privacy.py` | test not written |
| `AUTH-04` | R1 | P1 | `AC-AUTH-04.1` | `T-AUTH-04.1` | `tests/unit/test_jwt_claims.py` | test not written |
| `AUTH-04` | R1 | P1 | `AC-AUTH-04.2` | `T-AUTH-04.2` | `tests/integration/test_refresh_rotation.py` | test not written |
| `AUTH-04` | R1 | P1 | `AC-AUTH-04.3` | `T-AUTH-04.3` | `tests/integration/test_refresh_rotation.py` | test not written |
| `AUTH-04` | R1 | P1 | `AC-AUTH-04.4` | `T-AUTH-04.4` | `tests/integration/test_cookie_flags.py` | test not written |
| `AUTH-04` | R1 | P1 | `AC-AUTH-04.5` | `T-AUTH-04.5` | `tests/unit/test_clock_skew.py` | test not written |
| `AUTH-04` | R1 | P1 | `AC-AUTH-04.6` | `T-AUTH-04.6` | `tests/integration/test_refresh_rotation.py` | test not written |
| `AUTH-04` | R1 | P1 | `AC-AUTH-04.7` | `T-AUTH-04.7` | `tests/integration/test_password_change_revocation.py` | test not written |
| `AUTH-05` | R1 | P1 | `AC-AUTH-05.1` | `T-AUTH-05.1` | `tests/integration/test_password_reset.py` | test not written |
| `AUTH-05` | R1 | P1 | `AC-AUTH-05.2` | `T-AUTH-05.2` | `tests/integration/test_password_reset.py` | test not written |
| `AUTH-05` | R1 | P1 | `AC-AUTH-05.3` | `T-AUTH-05.3` | `tests/integration/test_password_reset.py` | test not written |
| `AUTH-05` | R1 | P1 | `AC-AUTH-05.4` | `T-AUTH-05.4` | `tests/integration/test_password_reset.py` | test not written |
| `AUTH-05` | R1 | P1 | `AC-AUTH-05.5` | `T-AUTH-05.5` | `tests/integration/test_password_reset.py` | test not written |
| `AUTH-07` | R1 | P1 | `AC-AUTH-07.1` | `T-AUTH-07.1` | `tests/integration/test_deletion_request.py` | test not written |
| `AUTH-07` | R1 | P1 | `AC-AUTH-07.2` | `T-AUTH-07.2` | `tests/integration/test_deletion_request.py` | test not written |
| `AUTH-07` | R1 | P1 | `AC-AUTH-07.3` | `T-AUTH-07.3` | `tests/integration/test_account_purge.py` | test not written |
| `AUTH-07` | R1 | P1 | `AC-AUTH-07.4` | `T-AUTH-07.4` | `tests/integration/test_deletion_sweep.py` | test not written |
| `AUTH-07` | R1 | P1 | `AC-AUTH-07.5` | `T-AUTH-07.5` | `tests/integration/test_deletion_audit.py` | test not written |
| `AUTH-07` | R1 | P1 | `AC-AUTH-07.6` | `T-AUTH-07.6` | `tests/integration/test_purge_failure.py` | test not written |
| `AUTH-07` | R1 | P1 | `AC-AUTH-07.7` | `T-AUTH-07.7` | `tests/integration/test_purge_isolation.py` | test not written |
| `AUTH-09` | R1 | P1 | `AC-AUTH-09.1` | `T-AUTH-09.1` | `tests/integration/test_rate_limits.py` | test not written |
| `AUTH-09` | R1 | P1 | `AC-AUTH-09.2` | `T-AUTH-09.2` | `tests/integration/test_rate_limits.py` | test not written |
| `AUTH-09` | R1 | P1 | `AC-AUTH-09.3` | `T-AUTH-09.3` | `tests/integration/test_rate_limits.py` | test not written |
| `AUTH-09` | R1 | P1 | `AC-AUTH-09.4` | `T-AUTH-09.4` | `tests/integration/test_client_ip_resolution.py` | test not written |
| `AUTH-09` | R1 | P1 | `AC-AUTH-09.5` | `T-AUTH-09.5` | `tests/integration/test_ratelimit_redis_down.py` | test not written |
| `AUTH-09` | R1 | P1 | `AC-AUTH-09.6` | `T-AUTH-09.6` | `tests/spec/test_ratelimit_config.py` | test not written |
| `AUTH-10` | R1 | P1 | `AC-AUTH-10.1` | `T-AUTH-10.1` | `tests/integration/test_cross_tenant_sweep.py` | test not written |
| `AUTH-10` | R1 | P1 | `AC-AUTH-10.2` | `T-AUTH-10.2` | `tests/integration/test_cross_tenant_sweep.py` | test not written |
| `AUTH-10` | R1 | P1 | `AC-AUTH-10.3` | `T-AUTH-10.3` | `tests/integration/test_cross_tenant_sweep.py` | test not written |
| `AUTH-10` | R1 | P1 | `AC-AUTH-10.4` | `T-AUTH-10.4` | `tests/integration/test_cross_tenant_sweep.py` | test not written |
| `AUTH-10` | R1 | P1 | `AC-AUTH-10.5` | `T-AUTH-10.5` | `tests/integration/test_ownership_timing.py` | test not written |
| `MOB-02` | R1 | P1 | `AC-MOB-02.1` | `T-MOB-02.1` | `apps/mobile/integration_test/session_persistence_test.dart` | test not written |
| `MOB-02` | R1 | P1 | `AC-MOB-02.2` | `T-MOB-02.2` | `apps/mobile/test/refresh_single_flight_test.dart` | test not written |
| `MOB-02` | R1 | P1 | `AC-MOB-02.3` | `T-MOB-02.3` | `apps/mobile/test/auth_failure_test.dart` | test not written |
| `MOB-02` | R1 | P1 | `AC-MOB-02.4` | `T-MOB-02.4` | `apps/mobile/test/manifest_test.dart` | test not written |
| `MOB-02` | R1 | P1 | `AC-MOB-02.5` | `T-MOB-02.5` | `.github/workflows/mobile-ci.yml` | test not written |
| `SEC-02` | R1 | P1 | `AC-SEC-02.1` | `T-SEC-02.1` | `tests/integration/test_cors.py` | test not written |
| `SEC-02` | R1 | P1 | `AC-SEC-02.2` | `T-SEC-02.2` | `tests/integration/test_nosql_injection.py` | test not written |
| `SEC-02` | R1 | P1 | `AC-SEC-02.3` | `T-SEC-02.3` | `tests/integration/test_clamav.py` | test not written |
| `SEC-02` | R1 | P1 | `AC-SEC-02.4` | `T-SEC-02.4` | `tests/integration/test_field_encryption.py` | test not written |
| `SEC-02` | R1 | P1 | `AC-SEC-02.5` | `T-SEC-02.5` | `tests/spec/test_asvs_checklist.py` | test not written |
| `SEC-04` | R1 | P1 | `AC-SEC-04.1` | `T-SEC-04.1` | `tests/integration/test_consent_capture.py` | test not written |
| `SEC-04` | R1 | P1 | `AC-SEC-04.2` | `T-SEC-04.2` | `tests/integration/test_consent_append_only.py` | test not written |
| `SEC-04` | R1 | P1 | `AC-SEC-04.3` | `T-SEC-04.3` | `tests/spec/test_notice_parity.py` | test not written |
| `SEC-04` | R1 | P1 | `AC-SEC-04.4` | `T-SEC-04.4` | `tests/spec/test_consent_data_parity.py` | test not written |
| `SEC-04` | R1 | P1 | `AC-SEC-04.5` | `T-SEC-04.5` | `tests/integration/test_consent_gating.py` | test not written |
| `SEC-04` | R1 | P1 | `AC-SEC-04.6` | `T-SEC-04.6` | `tests/spec/test_retention_coverage.py` | test not written |
| `SEC-04` | R1 | P1 | `AC-SEC-04.7` | `T-SEC-04.7` | `apps/web/e2e/data-rights.spec.ts`, `apps/mobile/integration_test/data_rights_test.dart` | test not written |
| `SEC-04` | R1 | P1 | `AC-SEC-04.8` | `T-SEC-04.8` | `apps/web/.../ai-label.test.tsx`, `apps/mobile/test/ai_label_test.dart` | test not written |
| `WEB-02` | R1 | P1 | `AC-WEB-02.1` | `T-WEB-02.1` | `apps/web/e2e/auth-storage.spec.ts` | test not written |
| `WEB-02` | R1 | P1 | `AC-WEB-02.2` | `T-WEB-02.2` | `apps/web/src/lib/__tests__/refresh-single-flight.test.ts` | test not written |
| `WEB-02` | R1 | P1 | `AC-WEB-02.3` | `T-WEB-02.3` | `apps/web/e2e/auth-redirect.spec.ts` | test not written |
| `WEB-02` | R1 | P1 | `AC-WEB-02.4` | `T-WEB-02.4` | `apps/web/src/lib/__tests__/csrf.test.ts` | test not written |
| `WEB-02` | R1 | P1 | `AC-WEB-02.5` | `T-WEB-02.5` | `apps/web/e2e/multi-tab-logout.spec.ts` | test not written |
| `WEB-06` | R1 | P1 | `AC-WEB-06.1` | `T-WEB-06.1` | `apps/web/.../error-boundary.test.tsx` | test not written |
| `WEB-06` | R1 | P1 | `AC-WEB-06.2` | `T-WEB-06.2` | `apps/web/src/lib/__tests__/error-copy.test.ts` | test not written |
| `WEB-06` | R1 | P1 | `AC-WEB-06.3` | `T-WEB-06.3` | `apps/web/e2e/error-request-id.spec.ts` | test not written |
| `WEB-06` | R1 | P1 | `AC-WEB-06.4` | `T-WEB-06.4` | `apps/web/src/lib/__tests__/sentry-redaction.test.ts` | test not written |
| `WEB-06` | R1 | P1 | `AC-WEB-06.5` | `T-WEB-06.5` | `apps/web/e2e/offline.spec.ts` | test not written |
| `MOB-03` | R1 | P2 | `AC-MOB-03.1` | `T-MOB-03.1` | `apps/mobile/test/features/**/*_states_test.dart` | test not written |
| `MOB-03` | R1 | P2 | `AC-MOB-03.2` | `T-MOB-03.2` | `apps/mobile/test/match_explain_test.dart` | test not written |
| `MOB-03` | R1 | P2 | `AC-MOB-03.3` | `T-MOB-03.3` | `apps/mobile/test/pack_gate_test.dart` | test not written |
| `MOB-03` | R1 | P2 | `AC-MOB-03.4` | `T-MOB-03.4` | `apps/mobile/integration_test/background_upload_test.dart` | test not written |
| `MOB-03` | R1 | P2 | `AC-MOB-03.5` | `T-MOB-03.5` | `apps/mobile/test/apply_sheet_test.dart` | test not written |
| `MOB-03` | R1 | P2 | `AC-MOB-03.6` | `T-MOB-03.6` | `apps/mobile/test/deep_links_test.dart` | test not written |
| `MOB-03` | R1 | P2 | `AC-MOB-03.7` | `T-MOB-03.7` | `apps/mobile/test/tracker_card_test.dart` | test not written |
| `MOB-04` | R1 | P2 | `AC-MOB-04.1` | `T-MOB-04.1` | `apps/mobile/test/manifest_test.dart` | test not written |
| `MOB-04` | R1 | P2 | `AC-MOB-04.2` | `T-MOB-04.2` | `apps/mobile/test/manifest_test.dart` | test not written |
| `MOB-04` | R1 | P2 | `AC-MOB-04.3` | `T-MOB-04.3` | `apps/mobile/integration_test/permission_timing_test.dart` | test not written |
| `MOB-04` | R1 | P2 | `AC-MOB-04.4` | `T-MOB-04.4` | `apps/mobile/test/notification_denied_test.dart` | test not written |
| `MOB-04` | R1 | P2 | `AC-MOB-04.5` | `T-MOB-04.5` | `.github/workflows/mobile-ci.yml` | test not written |
| `PROF-01` | R1 | P2 | `AC-PROF-01.1` | `T-PROF-01.1` | `tests/integration/test_profile_empty.py` | test not written |
| `PROF-01` | R1 | P2 | `AC-PROF-01.2` | `T-PROF-01.2` | `tests/integration/test_profile_versioning.py` | test not written |
| `PROF-01` | R1 | P2 | `AC-PROF-01.3` | `T-PROF-01.3` | `tests/unit/test_experience_months.py` | test not written |
| `PROF-01` | R1 | P2 | `AC-PROF-01.4` | `T-PROF-01.4` | `tests/unit/test_seniority_table.py` | test not written |
| `PROF-01` | R1 | P2 | `AC-PROF-01.5` | `T-PROF-01.5` | `tests/integration/test_profile_strict.py` | test not written |
| `PROF-01` | R1 | P2 | `AC-PROF-01.6` | `T-PROF-01.6` | `tests/integration/test_pack_target_staleness.py` | test not written |
| `PROF-01` | R1 | P2 | `AC-PROF-01.7` | `T-PROF-01.7` | `tests/integration/test_profile_concurrency.py` | test not written |
| `PROF-02` | R1 | P2 | `AC-PROF-02.1` | `T-PROF-02.1` | `tests/integration/test_preference_caps.py` | test not written |
| `PROF-02` | R1 | P2 | `AC-PROF-02.2` | `T-PROF-02.2` | `tests/integration/test_unmappable_title.py` | test not written |
| `PROF-02` | R1 | P2 | `AC-PROF-02.3` | `T-PROF-02.3` | `tests/integration/test_rescore_debounce.py` | test not written |
| `PROF-02` | R1 | P2 | `AC-PROF-02.4` | `T-PROF-02.4` | `tests/unit/test_exclude_keywords.py` | test not written |
| `PROF-02` | R1 | P2 | `AC-PROF-02.5` | `T-PROF-02.5` | `tests/unit/test_salary_currency.py` | test not written |
| `PROF-02` | R1 | P2 | `AC-PROF-02.6` | `T-PROF-02.6` | `tests/integration/test_preference_defaults.py` | test not written |
| `PROF-03` | R1 | P2 | `AC-PROF-03.1` | `T-PROF-03.1` | `tests/spec/test_provenance_coverage.py` | test not written |
| `PROF-03` | R1 | P2 | `AC-PROF-03.2` | `T-PROF-03.2` | `tests/unit/test_provenance_rules.py` | test not written |
| `PROF-03` | R1 | P2 | `AC-PROF-03.3` | `T-PROF-03.3` | `tests/unit/test_confidence_not_consent.py` | test not written |
| `PROF-03` | R1 | P2 | `AC-PROF-03.4` | `T-PROF-03.4` | `tests/integration/test_reextraction_safety.py` | test not written |
| `PROF-03` | R1 | P2 | `AC-PROF-03.5` | `T-PROF-03.5` | `tests/integration/test_pack_prompt_excludes_unconfirmed.py` | test not written |
| `PROF-03` | R1 | P2 | `AC-PROF-03.6` | `T-PROF-03.6` | `apps/web/.../profile-field.test.tsx`, `apps/mobile/test/profile_field_test.dart` | test not written |
| `PROF-03` | R1 | P2 | `AC-PROF-03.7` | `T-PROF-03.7` | `tests/unit/test_evidence_spans.py` | test not written |
| `PROF-06` | R1 | P2 | `AC-PROF-06.1` | `T-PROF-06.1` | `tests/unit/test_canonicalize_fixtures.py` | test not written |
| `PROF-06` | R1 | P2 | `AC-PROF-06.2` | `T-PROF-06.2` | `tests/unit/test_canonicalize_purity.py` | test not written |
| `PROF-06` | R1 | P2 | `AC-PROF-06.3` | `T-PROF-06.3` | `tests/integration/test_unmapped_skills.py` | test not written |
| `PROF-06` | R1 | P2 | `AC-PROF-06.4` | `T-PROF-06.4` | `tests/unit/test_fuzzy_skill_boundaries.py` | test not written |
| `PROF-06` | R1 | P2 | `AC-PROF-06.5` | `T-PROF-06.5` | `tests/spec/test_no_raw_skill_comparison.py` | test not written |
| `PROF-06` | R1 | P2 | `AC-PROF-06.6` | `T-PROF-06.6` | `tests/unit/test_skill_seed_integrity.py` | test not written |
| `RES-01` | R1 | P2 | `AC-RES-01.1` | `T-RES-01.1` | `tests/integration/test_upload_validation.py` | test not written |
| `RES-01` | R1 | P2 | `AC-RES-01.2` | `T-RES-01.2` | `tests/integration/test_upload_validation.py` | test not written |
| `RES-01` | R1 | P2 | `AC-RES-01.3` | `T-RES-01.3` | `tests/integration/test_upload_validation.py` | test not written |
| `RES-01` | R1 | P2 | `AC-RES-01.4` | `T-RES-01.4` | `tests/integration/test_email_verification.py` | test not written |
| `RES-01` | R1 | P2 | `AC-RES-01.5` | `T-RES-01.5` | `tests/integration/test_upload_idempotency.py` | test not written |
| `RES-01` | R1 | P2 | `AC-RES-01.6` | `T-RES-01.6` | `tests/integration/test_resume_replacement.py` | test not written |
| `RES-01` | R1 | P2 | `AC-RES-01.7` | `T-RES-01.7` | `tests/integration/test_rate_limits.py` | test not written |
| `RES-02a` | R1 | P2 | `AC-RES-02.1` | `T-RES-02.1` | `tests/unit/test_text_extraction.py` | test not written |
| `RES-02a` | R1 | P2 | `AC-RES-02.2` | `T-RES-02.2` | `tests/unit/test_text_extraction.py` | test not written |
| `RES-02a` | R1 | P2 | `AC-RES-02.3` | `T-RES-02.3` | `tests/unit/test_text_extraction.py` | test not written |
| `RES-02a` | R1 | P2 | `AC-RES-02.4` | `T-RES-02.4` | `tests/unit/test_text_extraction.py` | test not written |
| `RES-02a` | R1 | P2 | `AC-RES-02.5` | `T-RES-02.5` | `tests/unit/test_pdf_sanitization.py` | test not written |
| `RES-02a` | R1 | P2 | `AC-RES-02.6` | `T-RES-02.6` | `tests/unit/test_text_guardrails.py` | test not written |
| `RES-02a` | R1 | P2 | `AC-RES-02.7` | `T-RES-02.7` | `tests/integration/test_malformed_pdf.py` | test not written |
| `RES-02a` | R1 | P2 | `AC-RES-02.8` | `T-RES-02.8` | `tests/integration/test_ocr_fallback.py` | test not written |
| `RES-03` | R1 | P2 | `AC-RES-03.1` | `T-RES-03.1` | `tests/ai/test_structured_repair.py` | test not written |
| `RES-03` | R1 | P2 | `AC-RES-03.2` | `T-RES-03.2` | `tests/unit/test_evidence_spans.py` | test not written |
| `RES-03` | R1 | P2 | `AC-RES-03.3` | `T-RES-03.3` | `tests/ai/test_golden_fake.py`, `tests/ai/test_extraction_precision.py` | test not written |
| `RES-03` | R1 | P2 | `AC-RES-03.4` | `T-RES-03.4` | `tests/ai/test_golden_fake.py`, `tests/ai/test_extraction_precision.py` | test not written |
| `RES-03` | R1 | P2 | `AC-RES-03.5` | `T-RES-03.5` | `tests/ai/test_extraction_precision.py` | test not written |
| `RES-03` | R1 | P2 | `AC-RES-03.6` | `T-RES-03.6` | `tests/ai/test_injection_corpus.py` | test not written |
| `RES-03` | R1 | P2 | `AC-RES-03.7` | `T-RES-03.7` | `tests/unit/test_extraction_chunking.py` | test not written |
| `RES-03` | R1 | P2 | `AC-RES-03.8` | `T-RES-03.8` | `tests/spec/test_collection_ownership.py` | test not written |
| `RES-05` | R1 | P2 | `AC-RES-05.1` | `T-RES-05.1` | `tests/unit/test_llm_request.py` | test present |
| `RES-05` | R1 | P2 | `AC-RES-05.2` | `T-RES-05.2` | `tests/integration/test_no_file_to_provider.py` | test not written |
| `RES-05` | R1 | P2 | `AC-RES-05.3` | `T-RES-05.3` | `tests/integration/test_no_file_to_provider.py` | test not written |
| `RES-05` | R1 | P2 | `AC-RES-05.4` | `T-RES-05.4` | `tests/integration/test_presigned_urls.py` | test not written |
| `RES-05` | R1 | P2 | `AC-RES-05.5` | `T-RES-05.5` | `tests/unit/test_content_disposition.py` | test not written |
| `RES-06` | R1 | P2 | `AC-RES-06.1` | `T-RES-06.1` | `tests/integration/test_resume_stages.py` | test not written |
| `RES-06` | R1 | P2 | `AC-RES-06.2` | `T-RES-06.2` | `tests/integration/test_worker_restart.py` | test not written |
| `RES-06` | R1 | P2 | `AC-RES-06.3` | `T-RES-06.3` | `tests/integration/test_stage_ordering.py` | test not written |
| `RES-06` | R1 | P2 | `AC-RES-06.4` | `T-RES-06.4` | `tests/integration/test_resume_failures.py` | test not written |
| `RES-06` | R1 | P2 | `AC-RES-06.5` | `T-RES-06.5` | `tests/ai/test_degradation.py` | test not written |
| `RES-06` | R1 | P2 | `AC-RES-06.6` | `T-RES-06.6` | `tests/integration/test_resume_latency.py` | test not written |
| `RES-06` | R1 | P2 | `AC-RES-06.7` | `T-RES-06.7` | `tests/integration/test_poll_fallback.py` | test not written |
| `SEC-03` | R1 | P2 | `AC-SEC-03.1` | `T-SEC-03.1` | `tests/integration/test_ai_data_boundary.py` | test not written |
| `SEC-03` | R1 | P2 | `AC-SEC-03.2` | `T-SEC-03.2` | `tests/spec/test_consent_data_parity.py` | test not written |
| `SEC-03` | R1 | P2 | `AC-SEC-03.3` | `T-SEC-03.3` | `tests/spec/test_compliance_docs.py` | test not written |
| `SEC-03` | R1 | P2 | `AC-SEC-03.4` | `T-SEC-03.4` | `tests/integration/test_no_pii_in_prompts.py` | test not written |
| `SEC-03` | R1 | P2 | `AC-SEC-03.5` | `T-SEC-03.5` | `tests/integration/test_sensitive_questions.py` | test not written |
| `WEB-03` | R1 | P2 | `AC-WEB-03.1` | `T-WEB-03.1` | `apps/web/src/features/**/__tests__/*.states.test.tsx` | test not written |
| `WEB-03` | R1 | P2 | `AC-WEB-03.2` | `T-WEB-03.2` | `apps/web/e2e/onboarding-resume.spec.ts` | test not written |
| `WEB-03` | R1 | P2 | `AC-WEB-03.3` | `T-WEB-03.3` | `apps/web/.../match-explain.test.tsx` | test not written |
| `WEB-03` | R1 | P2 | `AC-WEB-03.4` | `T-WEB-03.4` | `apps/web/.../threshold.test.tsx` | test not written |
| `WEB-03` | R1 | P2 | `AC-WEB-03.5` | `T-WEB-03.5` | `apps/web/.../optimistic.test.tsx` | test not written |
| `WEB-03` | R1 | P2 | `AC-WEB-03.6` | `T-WEB-03.6` | `apps/web/.../apply-panel.test.tsx` | test not written |
| `WEB-03` | R1 | P2 | `AC-WEB-03.7` | `T-WEB-03.7` | `apps/web/e2e/account-deletion.spec.ts` | test not written |
| `WEB-03` | R1 | P2 | `AC-WEB-03.8` | `T-WEB-03.8` | `apps/web/e2e/sse-fallback.spec.ts` | test not written |
| `WEB-04` | R1 | P2 | `AC-WEB-04.1` | `T-WEB-04.1` | `apps/web/.../ai-label.test.tsx` | test not written |
| `WEB-04` | R1 | P2 | `AC-WEB-04.2` | `T-WEB-04.2` | `apps/web/scripts/check-danger-sites.mjs` | test not written |
| `WEB-04` | R1 | P2 | `AC-WEB-04.3` | `T-WEB-04.3` | `apps/web/.../job-description.test.tsx` | test not written |
| `WEB-04` | R1 | P2 | `AC-WEB-04.4` | `T-WEB-04.4` | `apps/web/.../ai-content.test.tsx` | test not written |
| `WEB-04` | R1 | P2 | `AC-WEB-04.5` | `T-WEB-04.5` | `apps/web/e2e/csp.spec.ts` | test not written |
| `ADMIN-01` | R1 | P3 | `AC-ADMIN-01.1` | `T-ADMIN-01.1` | `tests/integration/test_admin_connectors.py` | test not written |
| `ADMIN-01` | R1 | P3 | `AC-ADMIN-01.2` | `T-ADMIN-01.2` | `tests/integration/test_connector_toggle.py` | test not written |
| `ADMIN-01` | R1 | P3 | `AC-ADMIN-01.3` | `T-ADMIN-01.3` | `tests/integration/test_admin_run_now.py` | test not written |
| `ADMIN-01` | R1 | P3 | `AC-ADMIN-01.4` | `T-ADMIN-01.4` | `tests/integration/test_circuit_reset.py` | test not written |
| `ADMIN-01` | R1 | P3 | `AC-ADMIN-01.5` | `T-ADMIN-01.5` | `tests/unit/test_provider_error_logging.py` | test not written |
| `ADMIN-01` | R1 | P3 | `AC-ADMIN-01.6` | `T-ADMIN-01.6` | `tests/integration/test_raw_payload_link.py` | test not written |
| `ADMIN-01` | R1 | P3 | `AC-ADMIN-01.7` | `T-ADMIN-01.7` | `tests/integration/test_board_slug_lifecycle.py` | test not written |
| `ADMIN-01` | R1 | P3 | `AC-ADMIN-01.8` | `T-ADMIN-01.8` | `apps/web/.../connector-status.test.tsx` | test not written |
| `ADMIN-01` | R1 | P3 | `AC-ADMIN-01.9` | `T-ADMIN-01.9` | `tests/integration/test_admin_no_fetch.py` | test not written |
| `CONN-01` | R1 | P3 | `AC-CONN-01.1` | `T-CONN-01.1` | `tests/connectors/test_registry_contract.py` | test not written |
| `CONN-01` | R1 | P3 | `AC-CONN-01.2` | `T-CONN-01.2` | `tests/connectors/test_normalize_fixtures.py` | test not written |
| `CONN-01` | R1 | P3 | `AC-CONN-01.3` | `T-CONN-01.3` | `tests/spec/test_normalize_purity.py` | test not written |
| `CONN-01` | R1 | P3 | `AC-CONN-01.4` | `T-CONN-01.4` | `tests/unit/test_jobdraft_validation.py` | test not written |
| `CONN-01` | R1 | P3 | `AC-CONN-01.5` | `T-CONN-01.5` | `tests/spec/test_connector_injection.py` | test not written |
| `CONN-01` | R1 | P3 | `AC-CONN-01.6` | `T-CONN-01.6` | `tests/connectors/test_healthchecks.py` | test not written |
| `CONN-01` | R1 | P3 | `AC-CONN-01.7` | `T-CONN-01.7` | `tests/connectors/test_normalize_fixtures.py` | test not written |
| `CONN-02` | R1 | P3 | `AC-CONN-02.1` | `T-CONN-02.1` | `tests/spec/test_layer_leaks.py` | test not written |
| `CONN-02` | R1 | P3 | `AC-CONN-02.2` | `T-CONN-02.2` | `tests/integration/test_no_connectors_enabled.py` | test not written |
| `CONN-02` | R1 | P3 | `AC-CONN-02.3` | `T-CONN-02.3` | `tests/spec/test_connector_addition_drill.py` | test not written |
| `CONN-02` | R1 | P3 | `AC-CONN-02.4` | `T-CONN-02.4` | `tests/spec/test_no_scraping_deps.py` | test not written |
| `CONN-02` | R1 | P3 | `AC-CONN-02.5` | `T-CONN-02.5` | `tests/spec/test_excluded_sources_doc.py` | test not written |
| `CONN-02` | R1 | P3 | `AC-CONN-02.6` | `T-CONN-02.6` | `tests/connectors/test_excluded_host_guard.py` | test not written |
| `CONN-02` | R1 | P3 | `AC-CONN-02.7` | `T-CONN-02.7` | `tests/spec/test_connector_smoke_target.py` | test not written |
| `CONN-02` | R1 | P3 | `AC-CONN-02.8` | `T-CONN-02.8` | `tests/spec/test_connector_addition_drill.py` | test not written |
| `CONN-02` | R1 | P3 | `AC-CONN-02.9` | `T-CONN-02.9` | `tests/spec/test_adr_present.py` | test not written |
| `CONN-03` | R1 | P3 | `AC-CONN-03.1` | `T-CONN-03.1` | `tests/integration/test_connector_rate_limit.py` | test not written |
| `CONN-03` | R1 | P3 | `AC-CONN-03.2` | `T-CONN-03.2` | `tests/connectors/test_retry_policy.py` | test not written |
| `CONN-03` | R1 | P3 | `AC-CONN-03.3` | `T-CONN-03.3` | `tests/integration/test_circuit_breaker.py` | test not written |
| `CONN-03` | R1 | P3 | `AC-CONN-03.4` | `T-CONN-03.4` | `tests/integration/test_connector_isolation.py` | test not written |
| `CONN-03` | R1 | P3 | `AC-CONN-03.5` | `T-CONN-03.5` | `tests/integration/test_connector_toggle.py` | test not written |
| `CONN-03` | R1 | P3 | `AC-CONN-03.6` | `T-CONN-03.6` | `tests/connectors/test_user_agent.py` | test not written |
| `CONN-04` | R1 | P3 | `AC-CONN-04.1` | `T-CONN-04.1` | `tests/connectors/test_compliance_records.py` | test not written |
| `CONN-04` | R1 | P3 | `AC-CONN-04.2` | `T-CONN-04.2` | `tests/connectors/test_compliance_records.py` | test not written |
| `CONN-04` | R1 | P3 | `AC-CONN-04.3` | `T-CONN-04.3` | `tests/connectors/test_compliance_records.py` | test not written |
| `CONN-04` | R1 | P3 | `AC-CONN-04.4` | `T-CONN-04.4` | `apps/web/.../job-card.test.tsx`, `apps/mobile/test/job_card_test.dart` | test not written |
| `CONN-04` | R1 | P3 | `AC-CONN-04.5` | `T-CONN-04.5` | `tests/integration/test_source_ttl.py` | test not written |
| `CONN-05` | R1 | P3 | `AC-CONN-05.1` | `T-CONN-05.1` | `tests/integration/test_ttl_indexes.py` | test not written |
| `CONN-06a` | R1 | P3 | `AC-CONN-06.1` | `T-CONN-06.1` | `tests/connectors/test_registry_contract.py` | test not written |
| `CONN-06a` | R1 | P3 | `AC-CONN-06.2` | `T-CONN-06.2` | `tests/connectors/test_normalize_fixtures.py` | test not written |
| `CONN-06a` | R1 | P3 | `AC-CONN-06.3` | `T-CONN-06.3` | `tests/connectors/test_normalize_fixtures.py` | test not written |
| `CONN-06a` | R1 | P3 | `AC-CONN-06.4` | `T-CONN-06.4` | `tests/integration/test_board_slug_lifecycle.py` | test not written |
| `CONN-06a` | R1 | P3 | `AC-CONN-06.5` | `T-CONN-06.5` | `tests/spec/test_no_live_source_calls.py` | test not written |
| `CONN-06a` | R1 | P3 | `AC-CONN-06.6` | `T-CONN-06.6` | `tests/connectors/test_rss_ssrf.py` | test not written |
| `CONN-07` | R1 | P3 | `AC-CONN-07.1` | `T-CONN-07.1` | `apps/web/.../job-card.test.tsx`, `apps/mobile/test/job_card_test.dart`, `tests/integration/test_attribution_persistence.py` | test not written |
| `CONN-07` | R1 | P3 | `AC-CONN-07.2` | `T-CONN-07.2` | `apps/web/.../job-card.test.tsx`, `apps/mobile/test/job_card_test.dart`, `tests/integration/test_attribution_persistence.py` | test not written |
| `JOB-01` | R1 | P3 | `AC-JOB-01.1` | `T-JOB-01.1` | `tests/spec/test_job_field_classes.py` | test not written |
| `JOB-01` | R1 | P3 | `AC-JOB-01.2` | `T-JOB-01.2` | `tests/unit/test_html_sanitizer.py` | test not written |
| `JOB-01` | R1 | P3 | `AC-JOB-01.3` | `T-JOB-01.3` | `tests/unit/test_quality_flags.py` | test not written |
| `JOB-01` | R1 | P3 | `AC-JOB-01.4` | `T-JOB-01.4` | `tests/integration/test_job_upsert.py` | test not written |
| `JOB-01` | R1 | P3 | `AC-JOB-01.5` | `T-JOB-01.5` | `tests/integration/test_job_upsert.py` | test not written |
| `JOB-01` | R1 | P3 | `AC-JOB-01.6` | `T-JOB-01.6` | `tests/integration/test_description_truncation.py` | test not written |
| `JOB-02` | R1 | P3 | `AC-JOB-02.1` | `T-JOB-02.1` | `tests/integration/test_query_fanout.py` | test not written |
| `JOB-02` | R1 | P3 | `AC-JOB-02.2` | `T-JOB-02.2` | `tests/integration/test_cron_locks.py` | test not written |
| `JOB-02` | R1 | P3 | `AC-JOB-02.3` | `T-JOB-02.3` | `tests/integration/test_cold_start_seed.py` | test not written |
| `JOB-02` | R1 | P3 | `AC-JOB-02.4` | `T-JOB-02.4` | `tests/integration/test_run_time_budget.py` | test not written |
| `JOB-02` | R1 | P3 | `AC-JOB-02.5` | `T-JOB-02.5` | `tests/integration/test_fanout_recording.py` | test not written |
| `JOB-02` | R1 | P3 | `AC-JOB-02.6` | `T-JOB-02.6` | `tests/integration/test_unfiltered_connector.py` | test not written |
| `JOB-03` | R1 | P3 | `AC-JOB-03.1` | `T-JOB-03.1` | `tests/unit/test_dedup_keys.py`, `tests/integration/test_dedup_exact.py` | test not written |
| `JOB-03` | R1 | P3 | `AC-JOB-03.2` | `T-JOB-03.2` | `tests/unit/test_dedup_keys.py`, `tests/integration/test_dedup_exact.py` | test not written |
| `JOB-03` | R1 | P3 | `AC-JOB-03.3` | `T-JOB-03.3` | `tests/unit/test_dedup_keys.py`, `tests/integration/test_dedup_exact.py` | test not written |
| `JOB-03` | R1 | P3 | `AC-JOB-03.4` | `T-JOB-03.4` | `tests/unit/test_dedup_fuzzy_boundaries.py` | test not written |
| `JOB-03` | R1 | P3 | `AC-JOB-03.5` | `T-JOB-03.5` | `tests/unit/test_merge_precedence.py` | test not written |
| `JOB-03` | R1 | P3 | `AC-JOB-03.6` | `T-JOB-03.6` | `tests/integration/test_dedup_idempotence.py` | test not written |
| `JOB-03` | R1 | P3 | `AC-JOB-03.7` | `T-JOB-03.7` | `tests/integration/test_late_merge.py` | test not written |
| `JOB-03` | R1 | P3 | `AC-JOB-03.8` | `T-JOB-03.8` | `tests/integration/test_index_usage.py` | test not written |
| `JOB-03` | R1 | P3 | `AC-JOB-03.9` | `T-JOB-03.9` | `tests/integration/test_dedup_corpus.py` | test not written |
| `JOB-04` | R1 | P3 | `AC-JOB-04.1` | `T-JOB-04.1` | `tests/unit/test_title_normalization.py` | test not written |
| `JOB-04` | R1 | P3 | `AC-JOB-04.2` | `T-JOB-04.2` | `tests/unit/test_title_normalization.py` | test not written |
| `JOB-04` | R1 | P3 | `AC-JOB-04.3` | `T-JOB-04.3` | `tests/unit/test_location_normalization.py` | test not written |
| `JOB-04` | R1 | P3 | `AC-JOB-04.4` | `T-JOB-04.4` | `tests/unit/test_location_normalization.py` | test not written |
| `JOB-04` | R1 | P3 | `AC-JOB-04.5` | `T-JOB-04.5` | `tests/unit/test_salary_parsing.py` | test not written |
| `JOB-04` | R1 | P3 | `AC-JOB-04.6` | `T-JOB-04.6` | `tests/unit/test_date_normalization.py` | test not written |
| `JOB-04` | R1 | P3 | `AC-JOB-04.7` | `T-JOB-04.7` | `tests/unit/test_date_normalization.py` | test not written |
| `JOB-04` | R1 | P3 | `AC-JOB-04.8` | `T-JOB-04.8` | `tests/spec/test_normalize_purity.py` | test not written |
| `JOB-05` | R1 | P3 | `AC-JOB-05.1` | `T-JOB-05.1` | `tests/unit/test_skill_dictionary_match.py` | test not written |
| `JOB-05` | R1 | P3 | `AC-JOB-05.2` | `T-JOB-05.2` | `tests/unit/test_requirement_sectioning.py` | test not written |
| `JOB-05` | R1 | P3 | `AC-JOB-05.3` | `T-JOB-05.3` | `tests/unit/test_enrichment_gate.py` | test not written |
| `JOB-05` | R1 | P3 | `AC-JOB-05.4` | `T-JOB-05.4` | `tests/unit/test_enrichment_no_override.py` | test not written |
| `JOB-05` | R1 | P3 | `AC-JOB-05.5` | `T-JOB-05.5` | `tests/ai/test_response_cache.py` | test not written |
| `JOB-05` | R1 | P3 | `AC-JOB-05.6` | `T-JOB-05.6` | `tests/integration/test_enrichment_degraded.py` | test not written |
| `JOB-05` | R1 | P3 | `AC-JOB-05.7` | `T-JOB-05.7` | `tests/unit/test_experience_parsing.py` | test not written |
| `JOB-06` | R1 | P3 | `AC-JOB-06.1` | `T-JOB-06.1` | `tests/integration/test_text_search_weights.py` | test not written |
| `JOB-06` | R1 | P3 | `AC-JOB-06.2` | `T-JOB-06.2` | `tests/integration/test_search_filters.py` | test not written |
| `JOB-06` | R1 | P3 | `AC-JOB-06.3` | `T-JOB-06.3` | `tests/integration/test_search_latency.py` | test not written |
| `JOB-06` | R1 | P3 | `AC-JOB-06.4` | `T-JOB-06.4` | `tests/integration/test_hidden_exclusion.py` | test not written |
| `JOB-06` | R1 | P3 | `AC-JOB-06.5` | `T-JOB-06.5` | `tests/integration/test_hide_idempotence.py` | test not written |
| `JOB-06` | R1 | P3 | `AC-JOB-06.6` | `T-JOB-06.6` | `tests/integration/test_hidden_exclusion.py` | test not written |
| `JOB-06` | R1 | P3 | `AC-JOB-06.7` | `T-JOB-06.7` | `tests/integration/test_expired_visibility.py` | test not written |
| `JOB-08` | R1 | P3 | `AC-JOB-08.1` | `T-JOB-08.1` | `tests/integration/test_staleness.py` | test not written |
| `JOB-08` | R1 | P3 | `AC-JOB-08.2` | `T-JOB-08.2` | `tests/integration/test_staleness.py` | test not written |
| `JOB-08` | R1 | P3 | `AC-JOB-08.3` | `T-JOB-08.3` | `tests/integration/test_expiry_safety.py` | test not written |
| `JOB-08` | R1 | P3 | `AC-JOB-08.4` | `T-JOB-08.4` | `tests/integration/test_expired_visibility.py` | test not written |
| `JOB-08` | R1 | P3 | `AC-JOB-08.5` | `T-JOB-08.5` | `tests/integration/test_job_revival.py` | test not written |
| `JOB-08` | R1 | P3 | `AC-JOB-08.6` | `T-JOB-08.6` | `tests/unit/test_apply_deadline.py` | test not written |
| `JOB-08` | R1 | P3 | `AC-JOB-08.7` | `T-JOB-08.7` | `tests/integration/test_job_purge.py` | test not written |
| `JOB-09` | R1 | P3 | `AC-JOB-09.1` | `T-JOB-09.1` | `tests/integration/test_hidden_exclusion.py`, `tests/unit/test_hide_reasons.py` | test not written |
| `JOB-09` | R1 | P3 | `AC-JOB-09.2` | `T-JOB-09.2` | `tests/integration/test_hidden_exclusion.py`, `tests/unit/test_hide_reasons.py` | test not written |
| `JOB-09` | R1 | P3 | `AC-JOB-09.3` | `T-JOB-09.3` | `tests/integration/test_hidden_exclusion.py`, `tests/unit/test_hide_reasons.py` | test not written |
| `SEC-05` | R1 | P3 | `AC-SEC-05.1` | `T-SEC-05.1` | `tests/connectors/test_compliance_records.py` | test not written |
| `SEC-05` | R1 | P3 | `AC-SEC-05.2` | `T-SEC-05.2` | `tests/spec/test_excluded_sources_doc.py` | test not written |
| `SEC-05` | R1 | P3 | `AC-SEC-05.3` | `T-SEC-05.3` | `tests/integration/test_connector_removal.py` | test not written |
| `SEC-05` | R1 | P3 | `AC-SEC-05.4` | `T-SEC-05.4` | `tests/spec/test_no_scraping_deps.py` | test not written |
| `SEC-05` | R1 | P3 | `AC-SEC-05.5` | `T-SEC-05.5` | `tests/integration/test_source_ttl.py` | test not written |
| `ADMIN-02` | R1 | P4 | `AC-ADMIN-02.1` | `T-ADMIN-02.1` | `tests/integration/test_admin_ai_dashboard.py` | test not written |
| `ADMIN-02` | R1 | P4 | `AC-ADMIN-02.2` | `T-ADMIN-02.2` | `tests/integration/test_admin_ai_dashboard.py` | test not written |
| `ADMIN-02` | R1 | P4 | `AC-ADMIN-02.3` | `T-ADMIN-02.3` | `tests/integration/test_budget_trip_e2e.py` | test not written |
| `ADMIN-02` | R1 | P4 | `AC-ADMIN-02.4` | `T-ADMIN-02.4` | `tests/integration/test_golden_spend_separation.py` | test not written |
| `ADMIN-02` | R1 | P4 | `AC-ADMIN-02.5` | `T-ADMIN-02.5` | `tests/ai/test_unpriced_model.py` | test not written |
| `ADMIN-02` | R1 | P4 | `AC-ADMIN-02.6` | `T-ADMIN-02.6` | `tests/integration/test_usage_rollup.py` | test not written |
| `ADMIN-02` | R1 | P4 | `AC-ADMIN-02.7` | `T-ADMIN-02.7` | `apps/web/.../ai-usage.test.tsx` | test not written |
| `ADMIN-03` | R1 | P4 | `AC-ADMIN-03.1` | `T-ADMIN-03.1` | `tests/integration/test_admin_flags.py` | test not written |
| `ADMIN-03` | R1 | P4 | `AC-ADMIN-03.2` | `T-ADMIN-03.2` | `tests/integration/test_feature_flags.py` | test present |
| `ADMIN-03` | R1 | P4 | `AC-ADMIN-03.3` | `T-ADMIN-03.3` | `tests/integration/test_unknown_flag.py` | test not written |
| `ADMIN-03` | R1 | P4 | `AC-ADMIN-03.4` | `T-ADMIN-03.4` | `tests/integration/test_admin_audit.py` | test not written |
| `ADMIN-03` | R1 | P4 | `AC-ADMIN-03.5` | `T-ADMIN-03.5` | `tests/integration/test_ingestion_kill_switch.py` | test not written |
| `ADMIN-03` | R1 | P4 | `AC-ADMIN-03.6` | `T-ADMIN-03.6` | `tests/integration/test_signup_gate.py` | test not written |
| `MATCH-01` | R1 | P4 | `AC-MATCH-01.1` | `T-MATCH-01.1` | `tests/unit/test_scoring_fixtures.py` | test not written |
| `MATCH-01` | R1 | P4 | `AC-MATCH-01.2` | `T-MATCH-01.2` | `tests/unit/test_weights_sum.py` | test not written |
| `MATCH-01` | R1 | P4 | `AC-MATCH-01.3` | `T-MATCH-01.3` | `tests/unit/test_scoring_properties.py` | test not written |
| `MATCH-01` | R1 | P4 | `AC-MATCH-01.4` | `T-MATCH-01.4` | `tests/unit/test_skills_fallback.py` | test not written |
| `MATCH-01` | R1 | P4 | `AC-MATCH-01.5` | `T-MATCH-01.5` | `tests/unit/test_penalties.py` | test not written |
| `MATCH-01` | R1 | P4 | `AC-MATCH-01.6` | `T-MATCH-01.6` | `tests/unit/test_penalties.py` | test not written |
| `MATCH-01` | R1 | P4 | `AC-MATCH-01.7` | `T-MATCH-01.7` | `tests/unit/test_experience_component.py` | test not written |
| `MATCH-01` | R1 | P4 | `AC-MATCH-01.8` | `T-MATCH-01.8` | `tests/unit/test_embedding_not_weighted.py` | test not written |
| `MATCH-01` | R1 | P4 | `AC-MATCH-01.9` | `T-MATCH-01.9` | `tests/unit/test_scoring_properties.py` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.1` | `T-MATCH-02.1` | `tests/spec/test_explain_completeness.py` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.2` | `T-MATCH-02.2` | `apps/web/.../match-explain.test.tsx`, `apps/mobile/test/match_explain_test.dart` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.3` | `T-MATCH-02.3` | `tests/spec/test_verdict_enums.py` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.4` | `T-MATCH-02.4` | `apps/web/.../skills-basis.test.tsx` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.5` | `T-MATCH-02.5` | `tests/unit/test_explain_size.py` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.6` | `T-MATCH-02.6` | `apps/web/.../rationale-off.test.tsx` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.7` | `T-MATCH-02.7` | `tests/ai/test_rationale_no_new_numbers.py` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.8` | `T-MATCH-02.8` | `tests/unit/test_red_flag_merge.py` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.9` | `T-MATCH-02.9` | `tests/integration/test_rationale_selection.py` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.10` | `T-MATCH-02.10` | `tests/integration/test_rationale_selection.py` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.11` | `T-MATCH-02.11` | `tests/integration/test_rationale_independence.py` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.12` | `T-MATCH-02.12` | `tests/integration/test_rationale_flag_off.py` | test not written |
| `MATCH-02a` | R1 | P4 | `AC-MATCH-02.13` | `T-MATCH-02.13` | `apps/web/.../ai-label.test.tsx`, `apps/mobile/test/ai_label_test.dart` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.1` | `T-MATCH-02.1` | `tests/spec/test_explain_completeness.py` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.2` | `T-MATCH-02.2` | `apps/web/.../match-explain.test.tsx`, `apps/mobile/test/match_explain_test.dart` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.3` | `T-MATCH-02.3` | `tests/spec/test_verdict_enums.py` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.4` | `T-MATCH-02.4` | `apps/web/.../skills-basis.test.tsx` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.5` | `T-MATCH-02.5` | `tests/unit/test_explain_size.py` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.6` | `T-MATCH-02.6` | `apps/web/.../rationale-off.test.tsx` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.7` | `T-MATCH-02.7` | `tests/ai/test_rationale_no_new_numbers.py` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.8` | `T-MATCH-02.8` | `tests/unit/test_red_flag_merge.py` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.9` | `T-MATCH-02.9` | `tests/integration/test_rationale_selection.py` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.10` | `T-MATCH-02.10` | `tests/integration/test_rationale_selection.py` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.11` | `T-MATCH-02.11` | `tests/integration/test_rationale_independence.py` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.12` | `T-MATCH-02.12` | `tests/integration/test_rationale_flag_off.py` | test not written |
| `MATCH-02b` | R1 | P4 | `AC-MATCH-02.13` | `T-MATCH-02.13` | `apps/web/.../ai-label.test.tsx`, `apps/mobile/test/ai_label_test.dart` | test not written |
| `MATCH-03` | R1 | P4 | `AC-MATCH-03.1` | `T-MATCH-03.1` | `tests/unit/test_scoring_determinism.py` | test not written |
| `MATCH-03` | R1 | P4 | `AC-MATCH-03.2` | `T-MATCH-03.2` | `tests/spec/test_scoring_purity.py` | test not written |
| `MATCH-03` | R1 | P4 | `AC-MATCH-03.3` | `T-MATCH-03.3` | `tests/integration/test_score_provenance.py` | test not written |
| `MATCH-03` | R1 | P4 | `AC-MATCH-03.4` | `T-MATCH-03.4` | `tests/unit/test_scorer_input_type.py` | test not written |
| `MATCH-03` | R1 | P4 | `AC-MATCH-03.5` | `T-MATCH-03.5` | `tests/unit/test_freshness_component.py` | test not written |
| `MATCH-03` | R1 | P4 | `AC-MATCH-03.6` | `T-MATCH-03.6` | `tests/unit/test_weights_loading.py` | test not written |
| `MATCH-04` | R1 | P4 | `AC-MATCH-04.1` | `T-MATCH-04.1` | `tests/unit/test_embedding_similarity.py`, `tests/unit/test_skills_fallback.py` | test not written |
| `MATCH-04` | R1 | P4 | `AC-MATCH-04.2` | `T-MATCH-04.2` | `tests/unit/test_embedding_similarity.py`, `tests/unit/test_skills_fallback.py` | test not written |
| `MATCH-05` | R1 | P4 | `AC-MATCH-05.1` | `T-MATCH-05.1` | `tests/integration/test_candidate_selection.py` | test not written |
| `MATCH-05` | R1 | P4 | `AC-MATCH-05.2` | `T-MATCH-05.2` | `tests/integration/test_rescore_debounce.py` | test not written |
| `MATCH-05` | R1 | P4 | `AC-MATCH-05.3` | `T-MATCH-05.3` | `tests/spec/test_no_full_scan_scoring.py` | test not written |
| `MATCH-05` | R1 | P4 | `AC-MATCH-05.4` | `T-MATCH-05.4` | `tests/integration/test_score_upsert_concurrency.py` | test not written |
| `MATCH-05` | R1 | P4 | `AC-MATCH-05.5` | `T-MATCH-05.5` | `tests/integration/test_inactive_user_scoring.py` | test not written |
| `MATCH-05` | R1 | P4 | `AC-MATCH-05.6` | `T-MATCH-05.6` | `tests/integration/test_threshold_read_time.py` | test not written |
| `MATCH-05` | R1 | P4 | `AC-MATCH-05.7` | `T-MATCH-05.7` | `tests/integration/test_feed_latency.py` | test not written |
| `MATCH-05` | R1 | P4 | `AC-MATCH-05.8` | `T-MATCH-05.8` | `tests/unit/test_embedding_guard.py` | test not written |
| `MATCH-05` | R1 | P4 | `AC-MATCH-05.9` | `T-MATCH-05.9` | `tests/integration/test_hidden_exclusion.py` | test not written |
| `MATCH-07` | R1 | P4 | `AC-MATCH-07.1` | `T-MATCH-07.1` | `tests/integration/test_threshold_read_time.py`, `tests/unit/test_threshold_bounds.py` | test not written |
| `MATCH-07` | R1 | P4 | `AC-MATCH-07.2` | `T-MATCH-07.2` | `tests/integration/test_threshold_read_time.py`, `tests/unit/test_threshold_bounds.py` | test not written |
| `MATCH-09` | R1 | P4 | `AC-MATCH-09.1` | `T-MATCH-09.1` | `tests/integration/test_feed_sufficiency.py` | test not written |
| `MATCH-09` | R1 | P4 | `AC-MATCH-09.2` | `T-MATCH-09.2` | `tests/integration/test_feed_counts.py` | test not written |
| `MATCH-09` | R1 | P4 | `AC-MATCH-09.3` | `T-MATCH-09.3` | `tests/integration/test_scoring_coverage.py` | test not written |
| `MATCH-09` | R1 | P4 | `AC-MATCH-09.4` | `T-MATCH-09.4` | `tests/integration/test_feed_states.py` | test not written |
| `MATCH-09` | R1 | P4 | `AC-MATCH-09.5` | `T-MATCH-09.5` | `apps/web/.../feed-states.test.tsx`, `apps/mobile/test/feed_states_test.dart` | test not written |
| `MATCH-09` | R1 | P4 | `AC-MATCH-09.6` | `T-MATCH-09.6` | `tests/integration/test_widen_block.py` | test not written |
| `MATCH-09` | R1 | P4 | `AC-MATCH-09.7` | `T-MATCH-09.7` | `tests/spec/test_no_auto_relax.py` | test not written |
| `MATCH-09` | R1 | P4 | `AC-MATCH-09.8` | `T-MATCH-09.8` | `tests/integration/test_threshold_floor.py` | test not written |
| `MATCH-09` | R1 | P4 | `AC-MATCH-09.9` | `T-MATCH-09.9` | `tests/integration/test_absence_reason.py` | test not written |
| `MATCH-09` | R1 | P4 | `AC-MATCH-09.10` | `T-MATCH-09.10` | `tests/spec/test_reference_fixtures.py` | test not written |
| `WEB-05` | R1 | P4 | `AC-WEB-05.1` | `T-WEB-05.1` | `apps/web/scripts/check-bundle-size.mjs` | test not written |
| `WEB-05` | R1 | P4 | `AC-WEB-05.2` | `T-WEB-05.2` | `.github/workflows/web-ci.yml` | test not written |
| `WEB-05` | R1 | P4 | `AC-WEB-05.3` | `T-WEB-05.3` | `apps/web/e2e/waterfall.spec.ts` | test not written |
| `WEB-05` | R1 | P4 | `AC-WEB-05.4` | `T-WEB-05.4` | `apps/web/.../logo-fallback.test.tsx` | test not written |
| `WEB-05` | R1 | P4 | `AC-WEB-05.5` | `T-WEB-05.5` | `apps/web/e2e/virtualization.spec.ts` | test not written |
| `APPLY-01` | R1 | P5 | `AC-APPLY-01.1` | `T-APPLY-01.1` | `tests/unit/test_question_taxonomy.py` | test not written |
| `APPLY-01` | R1 | P5 | `AC-APPLY-01.2` | `T-APPLY-01.2` | `tests/unit/test_question_matching.py` | test not written |
| `APPLY-01` | R1 | P5 | `AC-APPLY-01.3` | `T-APPLY-01.3` | `tests/integration/test_sensitive_questions.py` | test not written |
| `APPLY-01` | R1 | P5 | `AC-APPLY-01.4` | `T-APPLY-01.4` | `tests/integration/test_pack_prompt_excludes_unconfirmed.py` | test not written |
| `APPLY-01` | R1 | P5 | `AC-APPLY-01.5` | `T-APPLY-01.5` | `tests/unit/test_answer_types.py` | test not written |
| `APPLY-01` | R1 | P5 | `AC-APPLY-01.6` | `T-APPLY-01.6` | `tests/integration/test_answer_bank_limits.py` | test not written |
| `APPLY-01` | R1 | P5 | `AC-APPLY-01.7` | `T-APPLY-01.7` | `tests/unit/test_match_diagnostics.py` | test not written |
| `APPLY-02` | R1 | P5 | `AC-APPLY-02.1` | `T-APPLY-02.1` | `tests/integration/test_pack_prompt_excludes_unconfirmed.py` | test not written |
| `APPLY-02` | R1 | P5 | `AC-APPLY-02.2` | `T-APPLY-02.2` | `tests/unit/test_claim_paths.py` | test not written |
| `APPLY-02` | R1 | P5 | `AC-APPLY-02.3` | `T-APPLY-02.3` | `tests/ai/test_gap_honesty.py` | test not written |
| `APPLY-02` | R1 | P5 | `AC-APPLY-02.4` | `T-APPLY-02.4` | `tests/ai/test_tone_claim_invariance.py` | test not written |
| `APPLY-02` | R1 | P5 | `AC-APPLY-02.5` | `T-APPLY-02.5` | `tests/unit/test_pack_lengths.py` | test not written |
| `APPLY-02` | R1 | P5 | `AC-APPLY-02.6` | `T-APPLY-02.6` | `tests/unit/test_answer_coverage.py` | test not written |
| `APPLY-02` | R1 | P5 | `AC-APPLY-02.7` | `T-APPLY-02.7` | `tests/integration/test_idempotency.py` | test not written |
| `APPLY-02` | R1 | P5 | `AC-APPLY-02.8` | `T-APPLY-02.8` | `tests/ai/test_degradation.py` | test not written |
| `APPLY-02` | R1 | P5 | `AC-APPLY-02.9` | `T-APPLY-02.9` | `tests/ai/test_injection_corpus.py` | test not written |
| `APPLY-03` | R1 | P5 | `AC-APPLY-03.1` | `T-APPLY-03.1` | `tests/integration/test_pack_editing.py` | test not written |
| `APPLY-03` | R1 | P5 | `AC-APPLY-03.2` | `T-APPLY-03.2` | `tests/integration/test_pack_approval_gates.py` | test not written |
| `APPLY-03` | R1 | P5 | `AC-APPLY-03.3` | `T-APPLY-03.3` | `tests/integration/test_pack_immutability.py` | test not written |
| `APPLY-03` | R1 | P5 | `AC-APPLY-03.4` | `T-APPLY-03.4` | `tests/integration/test_content_hash.py` | test not written |
| `APPLY-03` | R1 | P5 | `AC-APPLY-03.5` | `T-APPLY-03.5` | `tests/integration/test_apply_requires_approved.py` | test not written |
| `APPLY-03` | R1 | P5 | `AC-APPLY-03.6` | `T-APPLY-03.6` | `tests/integration/test_approval_idempotence.py` | test not written |
| `APPLY-03` | R1 | P5 | `AC-APPLY-03.7` | `T-APPLY-03.7` | `tests/integration/test_edit_refabrication_check.py` | test not written |
| `APPLY-04` | R1 | P5 | `AC-APPLY-04.1` | `T-APPLY-04.1` | `tests/unit/test_fabrication_recall.py` | test not written |
| `APPLY-04` | R1 | P5 | `AC-APPLY-04.2` | `T-APPLY-04.2` | `tests/unit/test_fabrication_precision.py` | test not written |
| `APPLY-04` | R1 | P5 | `AC-APPLY-04.3` | `T-APPLY-04.3` | `tests/unit/test_claim_confirmation.py` | test not written |
| `APPLY-04` | R1 | P5 | `AC-APPLY-04.4` | `T-APPLY-04.4` | `tests/integration/test_pack_approval_gates.py` | test not written |
| `APPLY-04` | R1 | P5 | `AC-APPLY-04.5` | `T-APPLY-04.5` | `tests/integration/test_fabrication_override.py` | test not written |
| `APPLY-04` | R1 | P5 | `AC-APPLY-04.6` | `T-APPLY-04.6` | `tests/unit/test_checker_no_ai.py` | test not written |
| `APPLY-04` | R1 | P5 | `AC-APPLY-04.7` | `T-APPLY-04.7` | `tests/integration/test_edit_refabrication_check.py` | test not written |
| `APPLY-04` | R1 | P5 | `AC-APPLY-04.8` | `T-APPLY-04.8` | `apps/web/.../fabrication-flag.test.tsx`, `apps/mobile/test/fabrication_flag_test.dart` | test not written |
| `APPLY-04` | R1 | P5 | `AC-APPLY-04.9` | `T-APPLY-04.9` | `tests/unit/test_checker_determinism.py` | test not written |
| `APPLY-05` | R1 | P5 | `AC-APPLY-05.1` | `T-APPLY-05.1` | `tests/spec/test_no_submission_capability.py` | test not written |
| `APPLY-05` | R1 | P5 | `AC-APPLY-05.2` | `T-APPLY-05.2` | `tests/spec/test_no_autoapply_flag.py`, `tests/spec/test_adr_present.py` | test not written |
| `APPLY-05` | R1 | P5 | `AC-APPLY-05.3` | `T-APPLY-05.3` | `apps/web/.../apply-panel.test.tsx` | test not written |
| `APPLY-05` | R1 | P5 | `AC-APPLY-05.4` | `T-APPLY-05.4` | `apps/mobile/test/apply_sheet_test.dart` | test not written |
| `APPLY-05` | R1 | P5 | `AC-APPLY-05.5` | `T-APPLY-05.5` | `tests/integration/test_applied_confirmation.py` | test not written |
| `APPLY-05` | R1 | P5 | `AC-APPLY-05.6` | `T-APPLY-05.6` | `tests/integration/test_confirmation_dismissal.py` | test not written |
| `APPLY-05` | R1 | P5 | `AC-APPLY-05.7` | `T-APPLY-05.7` | `tests/integration/test_merged_apply_sources.py` | test not written |
| `APPLY-05` | R1 | P5 | `AC-APPLY-05.8` | `T-APPLY-05.8` | `apps/web/e2e/apply.spec.ts`, `apps/mobile/integration_test/apply_test.dart` | test not written |
| `APPLY-07` | R1 | P5 | `AC-APPLY-07.1` | `T-APPLY-07.1` | `tests/integration/test_audit_coverage.py` | test not written |
| `APPLY-07` | R1 | P5 | `AC-APPLY-07.2` | `T-APPLY-07.2` | `tests/integration/test_audit_append_only.py` | test not written |
| `APPLY-07` | R1 | P5 | `AC-APPLY-07.3` | `T-APPLY-07.3` | `tests/integration/test_audit_no_content.py` | test not written |
| `APPLY-07` | R1 | P5 | `AC-APPLY-07.4` | `T-APPLY-07.4` | `tests/integration/test_request_id_propagation.py` | test not written |
| `APPLY-07` | R1 | P5 | `AC-APPLY-07.5` | `T-APPLY-07.5` | `tests/unit/test_ip_prefix.py` | test not written |
| `MOB-05` | R1 | P5 | `AC-MOB-05.1` | `T-MOB-05.1` | `apps/mobile/integration_test/local_notifications_test.dart` | test not written |
| `MOB-05` | R1 | P5 | `AC-MOB-05.2` | `T-MOB-05.2` | `apps/mobile/integration_test/local_notifications_test.dart` | test not written |
| `MOB-05` | R1 | P5 | `AC-MOB-05.3` | `T-MOB-05.3` | `apps/mobile/integration_test/push_routing_test.dart` | test not written |
| `MOB-05` | R1 | P5 | `AC-MOB-05.4` | `T-MOB-05.4` | `tests/integration/test_fcm_token_lifecycle.py` | test not written |
| `SEC-06` | R1 | P5 | `AC-SEC-06.1` | `T-SEC-06.1` | `tests/spec/test_no_submission_capability.py`, `tests/spec/test_no_autoapply_flag.py`, `tests/unit/test_fabrication_recall.py`, `tests/integration/test_pack_prompt_excludes_unconfirmed.py` | test not written |
| `SEC-06` | R1 | P5 | `AC-SEC-06.2` | `T-SEC-06.2` | `tests/spec/test_no_submission_capability.py`, `tests/spec/test_no_autoapply_flag.py`, `tests/unit/test_fabrication_recall.py`, `tests/integration/test_pack_prompt_excludes_unconfirmed.py` | test not written |
| `SEC-06` | R1 | P5 | `AC-SEC-06.3` | `T-SEC-06.3` | `tests/spec/test_no_submission_capability.py`, `tests/spec/test_no_autoapply_flag.py`, `tests/unit/test_fabrication_recall.py`, `tests/integration/test_pack_prompt_excludes_unconfirmed.py` | test not written |
| `SEC-06` | R1 | P5 | `AC-SEC-06.4` | `T-SEC-06.4` | `tests/spec/test_no_submission_capability.py`, `tests/spec/test_no_autoapply_flag.py`, `tests/unit/test_fabrication_recall.py`, `tests/integration/test_pack_prompt_excludes_unconfirmed.py` | test not written |
| `SEC-06` | R1 | P5 | `AC-SEC-06.5` | `T-SEC-06.5` | `tests/spec/test_ethics_doc.py` | test not written |
| `SEC-06` | R1 | P5 | `AC-SEC-06.6` | `T-SEC-06.6` | `tests/spec/test_store_listing_claims.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.1` | `T-TRACK-01.1` | `tests/integration/test_application_job_xor.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.2` | `T-TRACK-01.2` | `tests/integration/test_save_idempotence.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.3` | `T-TRACK-01.3` | `tests/integration/test_manual_entry.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.4` | `T-TRACK-01.4` | `tests/integration/test_manual_url_ssrf.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.5` | `T-TRACK-01.5` | `tests/integration/test_application_source.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.6` | `T-TRACK-01.6` | `tests/integration/test_expired_flag.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.7` | `T-TRACK-01.7` | `tests/integration/test_application_soft_delete.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.8` | `T-TRACK-01.8` | `tests/spec/test_no_scraping_deps.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.9` | `T-TRACK-01.9` | `tests/unit/test_state_machine.py`, `tests/integration/test_transitions.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.10` | `T-TRACK-01.10` | `tests/unit/test_state_machine.py`, `tests/integration/test_transitions.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.11` | `T-TRACK-01.11` | `tests/unit/test_state_machine.py`, `tests/integration/test_transitions.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.12` | `T-TRACK-01.12` | `tests/spec/test_no_direct_status_assignment.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.13` | `T-TRACK-01.13` | `tests/spec/test_system_transitions.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.14` | `T-TRACK-01.14` | `tests/integration/test_applied_at_stability.py` | test not written |
| `TRACK-01` | R1 | P5 | `AC-TRACK-01.15` | `T-TRACK-01.15` | `tests/integration/test_event_wiring.py` | test not written |
| `APPLY-09` | R1 | P6 | `AC-APPLY-09.1` | `T-APPLY-09.1` | `tests/integration/test_followup_draft.py` | test not written |
| `APPLY-09` | R1 | P6 | `AC-APPLY-09.2` | `T-APPLY-09.2` | `tests/integration/test_followup_draft.py` | test not written |
| `APPLY-09` | R1 | P6 | `AC-APPLY-09.3` | `T-APPLY-09.3` | `tests/integration/test_followup_draft.py` | test not written |
| `APPLY-09` | R1 | P6 | `AC-APPLY-09.4` | `T-APPLY-09.4` | `tests/integration/test_followup_draft.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.1` | `T-NOTIF-01.1` | `tests/integration/test_reminder_scheduling.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.2` | `T-NOTIF-01.2` | `tests/integration/test_followup_delay_setting.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.3` | `T-NOTIF-01.3` | `tests/unit/test_past_due_skip.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.4` | `T-NOTIF-01.4` | `tests/integration/test_reminder_cancellation.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.5` | `T-NOTIF-01.5` | `tests/unit/test_terminal_no_reminders.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.6` | `T-NOTIF-01.6` | `tests/integration/test_reminder_payload.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.7` | `T-NOTIF-01.7` | `tests/unit/test_time_utc.py` | test present |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.8` | `T-NOTIF-01.8` | `tests/unit/test_dst_scheduling.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.9` | `T-NOTIF-01.9` | `tests/integration/test_tz_change_reconcile.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.10` | `T-NOTIF-01.10` | `tests/integration/test_reconciliation.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.11` | `T-NOTIF-01.11` | `tests/integration/test_reconciliation.py` | test not written |
| `NOTIF-01` | R1 | P6 | `AC-NOTIF-01.12` | `T-NOTIF-01.12` | `tests/spec/test_handlers_only_enqueue.py` | test not written |
| `NOTIF-02a` | R1 | P6 | `AC-NOTIF-02.1` | `T-NOTIF-02.1` | `tests/unit/test_email_templates.py` | test not written |
| `NOTIF-02a` | R1 | P6 | `AC-NOTIF-02.2` | `T-NOTIF-02.2` | `tests/integration/test_email_content_rules.py` | test not written |
| `NOTIF-02a` | R1 | P6 | `AC-NOTIF-02.3` | `T-NOTIF-02.3` | `tests/integration/test_bounce_handling.py` | test not written |
| `NOTIF-02a` | R1 | P6 | `AC-NOTIF-02.4` | `T-NOTIF-02.4` | `tests/spec/test_deep_link_parity.py` | test not written |
| `NOTIF-02a` | R1 | P6 | `AC-NOTIF-02.5` | `T-NOTIF-02.5` | `tests/integration/test_inbox_sse.py` | test not written |
| `NOTIF-02a` | R1 | P6 | `AC-NOTIF-02.6` | `T-NOTIF-02.6` | `infra/scripts/check_email_dns.sh`, `tests/spec/test_dns_check_exists.py` | test not written |
| `NOTIF-02a` | R1 | P6 | `AC-NOTIF-02.7` | `T-NOTIF-02.7` | `tests/integration/test_fcm_token_lifecycle.py` | test not written |
| `NOTIF-05` | R1 | P6 | `AC-NOTIF-05.1` | `T-NOTIF-05.1` | `tests/integration/test_dispatch_concurrency.py` | test not written |
| `NOTIF-05` | R1 | P6 | `AC-NOTIF-05.2` | `T-NOTIF-05.2` | `tests/integration/test_worker_restart.py` | test not written |
| `NOTIF-05` | R1 | P6 | `AC-NOTIF-05.3` | `T-NOTIF-05.3` | `tests/integration/test_dedup_key_uniqueness.py` | test not written |
| `NOTIF-05` | R1 | P6 | `AC-NOTIF-05.4` | `T-NOTIF-05.4` | `tests/integration/test_interview_reschedule.py` | test not written |
| `NOTIF-05` | R1 | P6 | `AC-NOTIF-05.5` | `T-NOTIF-05.5` | `tests/integration/test_send_failure.py` | test not written |
| `NOTIF-05` | R1 | P6 | `AC-NOTIF-05.6` | `T-NOTIF-05.6` | `tests/integration/test_provider_timeout.py` | test not written |
| `NOTIF-05` | R1 | P6 | `AC-NOTIF-05.7` | `T-NOTIF-05.7` | `tests/integration/test_inapp_always.py` | test not written |
| `NOTIF-05` | R1 | P6 | `AC-NOTIF-05.8` | `T-NOTIF-05.8` | `tests/integration/test_dispatch_batching.py` | test not written |
| `TRACK-02a` | R1 | P6 | `AC-TRACK-02.1` | `T-TRACK-02.1` | `tests/integration/test_kanban_pagination.py` | test not written |
| `TRACK-02a` | R1 | P6 | `AC-TRACK-02.2` | `T-TRACK-02.2` | `tests/unit/test_needs_attention.py` | test not written |
| `TRACK-02a` | R1 | P6 | `AC-TRACK-02.3` | `T-TRACK-02.3` | `tests/integration/test_application_filters.py` | test not written |
| `TRACK-02a` | R1 | P6 | `AC-TRACK-02.4` | `T-TRACK-02.4` | `tests/contract/test_card_projection.py` | test not written |
| `TRACK-02a` | R1 | P6 | `AC-TRACK-02.5` | `T-TRACK-02.5` | `apps/web/.../kanban.test.tsx`, `apps/mobile/test/tracker_card_test.dart` | test not written |
| `TRACK-02a` | R1 | P6 | `AC-TRACK-02.6` | `T-TRACK-02.6` | `tests/integration/test_tracker_latency.py` | test not written |
| `TRACK-02a` | R1 | P6 | `AC-TRACK-02.7` | `T-TRACK-02.7` | `apps/web/.../empty-states.test.tsx` | test not written |
| `TRACK-03` | R1 | P6 | `AC-TRACK-03.1` | `T-TRACK-03.1` | `tests/unit/test_markdown_renderer.py`, `apps/web/.../notes.test.tsx`, `apps/mobile/test/notes_test.dart` | test not written |
| `TRACK-03` | R1 | P6 | `AC-TRACK-03.2` | `T-TRACK-03.2` | `tests/integration/test_detail_caps.py` | test not written |
| `TRACK-03` | R1 | P6 | `AC-TRACK-03.3` | `T-TRACK-03.3` | `tests/integration/test_no_contacts_to_provider.py` | test not written |
| `TRACK-03` | R1 | P6 | `AC-TRACK-03.4` | `T-TRACK-03.4` | `tests/integration/test_application_documents.py` | test not written |
| `TRACK-03` | R1 | P6 | `AC-TRACK-03.5` | `T-TRACK-03.5` | `tests/integration/test_interview_reminders.py` | test not written |
| `TRACK-03` | R1 | P6 | `AC-TRACK-03.6` | `T-TRACK-03.6` | `tests/unit/test_interview_rounds.py` | test not written |
| `TRACK-03` | R1 | P6 | `AC-TRACK-03.7` | `T-TRACK-03.7` | `tests/integration/test_salary_log_append_only.py` | test not written |
| `TRACK-03` | R1 | P6 | `AC-TRACK-03.8` | `T-TRACK-03.8` | `tests/unit/test_money.py` | test present |
| `TRACK-03` | R1 | P6 | `AC-TRACK-03.9` | `T-TRACK-03.9` | `tests/integration/test_last_activity.py` | test not written |
| `TRACK-04` | R1 | P6 | `AC-TRACK-04.1` | `T-TRACK-04.1` | `tests/integration/test_timeline_journey.py` | test not written |
| `TRACK-04` | R1 | P6 | `AC-TRACK-04.2` | `T-TRACK-04.2` | `tests/integration/test_timeline_backing.py` | test not written |
| `TRACK-04` | R1 | P6 | `AC-TRACK-04.3` | `T-TRACK-04.3` | `tests/unit/test_timeline_ordering.py` | test not written |
| `TRACK-04` | R1 | P6 | `AC-TRACK-04.4` | `T-TRACK-04.4` | `tests/integration/test_timeline_tombstones.py` | test not written |
| `TRACK-04` | R1 | P6 | `AC-TRACK-04.5` | `T-TRACK-04.5` | `tests/spec/test_collection_ownership.py` | test not written |
| `TRACK-05` | R1 | P6 | `AC-TRACK-05.1` | `T-TRACK-05.1` | `tests/integration/test_manual_entry.py`, `tests/integration/test_manual_pack_gate.py`, `tests/integration/test_manual_reminders.py` | test not written |
| `TRACK-05` | R1 | P6 | `AC-TRACK-05.2` | `T-TRACK-05.2` | `tests/integration/test_manual_entry.py`, `tests/integration/test_manual_pack_gate.py`, `tests/integration/test_manual_reminders.py` | test not written |
| `TRACK-05` | R1 | P6 | `AC-TRACK-05.3` | `T-TRACK-05.3` | `tests/integration/test_manual_entry.py`, `tests/integration/test_manual_pack_gate.py`, `tests/integration/test_manual_reminders.py` | test not written |
| `MOB-06` | R1 | P7 | `AC-MOB-06.1` | `T-MOB-06.1` | `apps/mobile/integration_test/perf_test.dart` | test not written |
| `MOB-06` | R1 | P7 | `AC-MOB-06.2` | `T-MOB-06.2` | `apps/mobile/integration_test/perf_test.dart` | test not written |
| `MOB-06` | R1 | P7 | `AC-MOB-06.3` | `T-MOB-06.3` | `.github/workflows/mobile-ci.yml` | test not written |
| `MOB-06` | R1 | P7 | `AC-MOB-06.4` | `T-MOB-06.4` | `apps/mobile/test/golden/*_test.dart` | test not written |
| `MOB-06` | R1 | P7 | `AC-MOB-06.5` | `T-MOB-06.5` | `apps/mobile/integration_test/a11y_test.dart` | test not written |
| `MOB-08` | R1 | P7 | `AC-MOB-08.1` | `T-MOB-08.1` | `.github/workflows/mobile-release.yml` | test not written |
| `MOB-08` | R1 | P7 | `AC-MOB-08.2` | `T-MOB-08.2` | `.github/workflows/mobile-release.yml` | test not written |
| `MOB-08` | R1 | P7 | `AC-MOB-08.3` | `T-MOB-08.3` | `tests/spec/test_store_listing_claims.py` | test not written |
| `MOB-08` | R1 | P7 | `AC-MOB-08.4` | `T-MOB-08.4` | `tests/spec/test_data_safety_parity.py` | test not written |
| `MOB-08` | R1 | P7 | `AC-MOB-08.5` | `T-MOB-08.5` | `apps/mobile/integration_test/exit_sentence_test.dart` | test not written |
| `MOB-08` | R1 | P7 | `AC-MOB-08.6` | `T-MOB-08.6` | `.github/workflows/mobile-ci.yml` | test not written |
| `OPS-08` | R1 | P7 | `AC-OPS-08.1` | `T-OPS-08.1` | `tests/spec/test_cost_doc.py` | test not written |
| `OPS-08` | R1 | P7 | `AC-OPS-08.2` | `T-OPS-08.2` | `tests/integration/test_signup_gate.py` | test not written |
| `OPS-08` | R1 | P7 | `AC-OPS-08.3` | `T-OPS-08.3` | `tests/spec/test_freetier_alerts.py` | test not written |
| `OPS-08` | R1 | P7 | `AC-OPS-08.4` | `T-OPS-08.4` | `tests/spec/test_env_parity.py` | test not written |
| `WEB-08` | R1 | P7 | `AC-WEB-08.1` | `T-WEB-08.1` | `apps/web/e2e/exit-sentence.spec.ts` | test not written |
| `WEB-08` | R1 | P7 | `AC-WEB-08.2` | `T-WEB-08.2` | `apps/web/e2e/fixtures/no-external.ts` | test not written |
| `WEB-08` | R1 | P7 | `AC-WEB-08.3` | `T-WEB-08.3` | `apps/web/e2e/cross-tenant.spec.ts` | test not written |
| `WEB-08` | R1 | P7 | `AC-WEB-08.4` | `T-WEB-08.4` | `.github/workflows/web-ci.yml` | test not written |
| `WEB-08` | R1 | P7 | `AC-WEB-08.5` | `T-WEB-08.5` | `apps/web/scripts/check-no-sleep.mjs` | test not written |
| `ADMIN-04` | R2 | S2 | `AC-ADMIN-04.1` | `T-ADMIN-04.1` | `tests/integration/test_admin_taxonomy.py` | test not written |
| `ADMIN-04` | R2 | S2 | `AC-ADMIN-04.2` | `T-ADMIN-04.2` | `tests/integration/test_admin_taxonomy.py` | test not written |
| `ADMIN-04` | R2 | S2 | `AC-ADMIN-04.3` | `T-ADMIN-04.3` | `tests/integration/test_admin_taxonomy.py` | test not written |
| `ADMIN-04` | R2 | S2 | `AC-ADMIN-04.4` | `T-ADMIN-04.4` | `tests/integration/test_admin_taxonomy.py` | test not written |
| `ADMIN-04` | R2 | S2 | `AC-ADMIN-04.5` | `T-ADMIN-04.5` | `tests/integration/test_admin_taxonomy.py` | test not written |
| `ADMIN-05` | R2 | S2 | `AC-ADMIN-05.1` | `T-ADMIN-05.1` | `tests/integration/test_flagged_queue.py` | test not written |
| `ADMIN-05` | R2 | S2 | `AC-ADMIN-05.2` | `T-ADMIN-05.2` | `tests/integration/test_flagged_queue.py` | test not written |
| `ADMIN-05` | R2 | S2 | `AC-ADMIN-05.3` | `T-ADMIN-05.3` | `tests/integration/test_flagged_queue.py` | test not written |
| `ADMIN-05` | R2 | S2 | `AC-ADMIN-05.4` | `T-ADMIN-05.4` | `tests/integration/test_flagged_queue.py` | test not written |
| `ADMIN-05` | R2 | S2 | `AC-ADMIN-05.5` | `T-ADMIN-05.5` | `tests/integration/test_flagged_queue.py` | test not written |
| `CONN-06b` | R2 | S2 | `AC-CONN-06.1` | `T-CONN-06.1` | `tests/connectors/test_registry_contract.py` | test not written |
| `CONN-06b` | R2 | S2 | `AC-CONN-06.2` | `T-CONN-06.2` | `tests/connectors/test_normalize_fixtures.py` | test not written |
| `CONN-06b` | R2 | S2 | `AC-CONN-06.3` | `T-CONN-06.3` | `tests/connectors/test_normalize_fixtures.py` | test not written |
| `CONN-06b` | R2 | S2 | `AC-CONN-06.4` | `T-CONN-06.4` | `tests/integration/test_board_slug_lifecycle.py` | test not written |
| `CONN-06b` | R2 | S2 | `AC-CONN-06.5` | `T-CONN-06.5` | `tests/spec/test_no_live_source_calls.py` | test not written |
| `CONN-06b` | R2 | S2 | `AC-CONN-06.6` | `T-CONN-06.6` | `tests/connectors/test_rss_ssrf.py` | test not written |
| `JOB-07` | R2 | S2 | `AC-JOB-07.1` | `T-JOB-07.1` | `tests/integration/test_saved_searches.py` | test not written |
| `JOB-07` | R2 | S2 | `AC-JOB-07.2` | `T-JOB-07.2` | `tests/integration/test_saved_searches.py` | test not written |
| `JOB-07` | R2 | S2 | `AC-JOB-07.3` | `T-JOB-07.3` | `tests/integration/test_saved_searches.py` | test not written |
| `JOB-10` | R2 | S2 | `AC-JOB-10.1` | `T-JOB-10.1` | `tests/integration/test_job_reporting.py` | test not written |
| `JOB-10` | R2 | S2 | `AC-JOB-10.2` | `T-JOB-10.2` | `tests/integration/test_job_reporting.py` | test not written |
| `JOB-10` | R2 | S2 | `AC-JOB-10.3` | `T-JOB-10.3` | `tests/integration/test_job_reporting.py` | test not written |
| `JOB-10` | R2 | S2 | `AC-JOB-10.4` | `T-JOB-10.4` | `tests/integration/test_job_reporting.py` | test not written |
| `AUTH-06` | R2 | S3 | `AC-AUTH-06.1` | `T-AUTH-06.1` | `tests/integration/test_sessions.py` | test not written |
| `AUTH-06` | R2 | S3 | `AC-AUTH-06.2` | `T-AUTH-06.2` | `tests/integration/test_sessions.py` | test not written |
| `AUTH-06` | R2 | S3 | `AC-AUTH-06.3` | `T-AUTH-06.3` | `tests/integration/test_sessions.py` | test not written |
| `AUTH-06` | R2 | S3 | `AC-AUTH-06.4` | `T-AUTH-06.4` | `tests/integration/test_sessions.py` | test not written |
| `AUTH-08` | R2 | S3 | `AC-AUTH-08.1` | `T-AUTH-08.1` | `tests/integration/test_data_export.py` | test not written |
| `AUTH-08` | R2 | S3 | `AC-AUTH-08.2` | `T-AUTH-08.2` | `tests/integration/test_data_export.py` | test not written |
| `AUTH-08` | R2 | S3 | `AC-AUTH-08.3` | `T-AUTH-08.3` | `tests/integration/test_data_export.py` | test not written |
| `AUTH-08` | R2 | S3 | `AC-AUTH-08.4` | `T-AUTH-08.4` | `tests/integration/test_data_export.py` | test not written |
| `AUTH-08` | R2 | S3 | `AC-AUTH-08.5` | `T-AUTH-08.5` | `tests/integration/test_data_export.py` | test not written |
| `MATCH-06` | R2 | S3 | `AC-MATCH-06.1` | `T-MATCH-06.1` | `tests/unit/test_weight_offsets.py`, `tests/integration/test_feedback_loop.py` | test not written |
| `MATCH-06` | R2 | S3 | `AC-MATCH-06.2` | `T-MATCH-06.2` | `tests/unit/test_weight_offsets.py`, `tests/integration/test_feedback_loop.py` | test not written |
| `MATCH-06` | R2 | S3 | `AC-MATCH-06.3` | `T-MATCH-06.3` | `tests/unit/test_weight_offsets.py`, `tests/integration/test_feedback_loop.py` | test not written |
| `MATCH-06` | R2 | S3 | `AC-MATCH-06.4` | `T-MATCH-06.4` | `tests/unit/test_weight_offsets.py`, `tests/integration/test_feedback_loop.py` | test not written |
| `MATCH-06` | R2 | S3 | `AC-MATCH-06.5` | `T-MATCH-06.5` | `tests/unit/test_weight_offsets.py`, `tests/integration/test_feedback_loop.py` | test not written |
| `PROF-05` | R2 | S3 | `AC-PROF-05.1` | `T-PROF-05.1` | `tests/unit/test_completeness.py`, `tests/integration/test_completeness_recompute.py` | test not written |
| `PROF-05` | R2 | S3 | `AC-PROF-05.2` | `T-PROF-05.2` | `tests/unit/test_completeness.py`, `tests/integration/test_completeness_recompute.py` | test not written |
| `PROF-05` | R2 | S3 | `AC-PROF-05.3` | `T-PROF-05.3` | `tests/unit/test_completeness.py`, `tests/integration/test_completeness_recompute.py` | test not written |
| `PROF-05` | R2 | S3 | `AC-PROF-05.4` | `T-PROF-05.4` | `tests/unit/test_completeness.py`, `tests/integration/test_completeness_recompute.py` | test not written |
| `PROF-07` | R2 | S3 | `AC-PROF-07.1` | `T-PROF-07.1` | `tests/integration/test_profile_audit.py` | test not written |
| `PROF-07` | R2 | S3 | `AC-PROF-07.2` | `T-PROF-07.2` | `tests/integration/test_profile_audit.py` | test not written |
| `PROF-07` | R2 | S3 | `AC-PROF-07.3` | `T-PROF-07.3` | `tests/integration/test_profile_audit.py` | test not written |
| `PROF-07` | R2 | S3 | `AC-PROF-07.4` | `T-PROF-07.4` | `tests/integration/test_profile_audit.py` | test not written |
| `RES-02b` | R2 | S3 | `AC-RES-02.1` | `T-RES-02.1` | `tests/unit/test_text_extraction.py` | test not written |
| `RES-02b` | R2 | S3 | `AC-RES-02.2` | `T-RES-02.2` | `tests/unit/test_text_extraction.py` | test not written |
| `RES-02b` | R2 | S3 | `AC-RES-02.3` | `T-RES-02.3` | `tests/unit/test_text_extraction.py` | test not written |
| `RES-02b` | R2 | S3 | `AC-RES-02.4` | `T-RES-02.4` | `tests/unit/test_text_extraction.py` | test not written |
| `RES-02b` | R2 | S3 | `AC-RES-02.5` | `T-RES-02.5` | `tests/unit/test_pdf_sanitization.py` | test not written |
| `RES-02b` | R2 | S3 | `AC-RES-02.6` | `T-RES-02.6` | `tests/unit/test_text_guardrails.py` | test not written |
| `RES-02b` | R2 | S3 | `AC-RES-02.7` | `T-RES-02.7` | `tests/integration/test_malformed_pdf.py` | test not written |
| `RES-02b` | R2 | S3 | `AC-RES-02.8` | `T-RES-02.8` | `tests/integration/test_ocr_fallback.py` | test not written |
| `RES-04` | R2 | S3 | `AC-RES-04.1` | `T-RES-04.1` | `tests/unit/test_quality_checks.py`, `tests/integration/test_quality_feedback.py` | test not written |
| `RES-04` | R2 | S3 | `AC-RES-04.2` | `T-RES-04.2` | `tests/unit/test_quality_checks.py`, `tests/integration/test_quality_feedback.py` | test not written |
| `RES-04` | R2 | S3 | `AC-RES-04.3` | `T-RES-04.3` | `tests/unit/test_quality_checks.py`, `tests/integration/test_quality_feedback.py` | test not written |
| `RES-04` | R2 | S3 | `AC-RES-04.4` | `T-RES-04.4` | `tests/unit/test_quality_checks.py`, `tests/integration/test_quality_feedback.py` | test not written |
| `RES-07` | R2 | S3 | `AC-RES-07.1` | `T-RES-07.1` | `tests/integration/test_reanalysis.py` | test not written |
| `RES-07` | R2 | S3 | `AC-RES-07.2` | `T-RES-07.2` | `tests/integration/test_reanalysis.py` | test not written |
| `RES-07` | R2 | S3 | `AC-RES-07.3` | `T-RES-07.3` | `tests/integration/test_reanalysis.py` | test not written |
| `RES-07` | R2 | S3 | `AC-RES-07.4` | `T-RES-07.4` | `tests/integration/test_reanalysis.py` | test not written |
| `MOB-07` | R2 | S4 | `AC-MOB-07.1` | `T-MOB-07.1` | `apps/mobile/integration_test/offline_test.dart` | test not written |
| `MOB-07` | R2 | S4 | `AC-MOB-07.2` | `T-MOB-07.2` | `apps/mobile/integration_test/offline_test.dart` | test not written |
| `MOB-07` | R2 | S4 | `AC-MOB-07.3` | `T-MOB-07.3` | `apps/mobile/integration_test/offline_test.dart` | test not written |
| `MOB-07` | R2 | S4 | `AC-MOB-07.4` | `T-MOB-07.4` | `apps/mobile/integration_test/offline_test.dart` | test not written |
| `NOTIF-02b` | R2 | S4 | `AC-NOTIF-02.1` | `T-NOTIF-02.1` | `tests/unit/test_email_templates.py` | test not written |
| `NOTIF-02b` | R2 | S4 | `AC-NOTIF-02.2` | `T-NOTIF-02.2` | `tests/integration/test_email_content_rules.py` | test not written |
| `NOTIF-02b` | R2 | S4 | `AC-NOTIF-02.3` | `T-NOTIF-02.3` | `tests/integration/test_bounce_handling.py` | test not written |
| `NOTIF-02b` | R2 | S4 | `AC-NOTIF-02.4` | `T-NOTIF-02.4` | `tests/spec/test_deep_link_parity.py` | test not written |
| `NOTIF-02b` | R2 | S4 | `AC-NOTIF-02.5` | `T-NOTIF-02.5` | `tests/integration/test_inbox_sse.py` | test not written |
| `NOTIF-02b` | R2 | S4 | `AC-NOTIF-02.6` | `T-NOTIF-02.6` | `infra/scripts/check_email_dns.sh`, `tests/spec/test_dns_check_exists.py` | test not written |
| `NOTIF-02b` | R2 | S4 | `AC-NOTIF-02.7` | `T-NOTIF-02.7` | `tests/integration/test_fcm_token_lifecycle.py` | test not written |
| `NOTIF-03` | R2 | S4 | `AC-NOTIF-03.1` | `T-NOTIF-03.1` | `tests/integration/test_quiet_hours.py`, `tests/integration/test_weekly_digest.py` | test not written |
| `NOTIF-03` | R2 | S4 | `AC-NOTIF-03.2` | `T-NOTIF-03.2` | `tests/integration/test_quiet_hours.py`, `tests/integration/test_weekly_digest.py` | test not written |
| `NOTIF-04` | R2 | S4 | `AC-NOTIF-04.1` | `T-NOTIF-04.1` | `tests/integration/test_quiet_hours.py`, `tests/integration/test_weekly_digest.py` | test not written |
| `NOTIF-04` | R2 | S4 | `AC-NOTIF-04.2` | `T-NOTIF-04.2` | `tests/integration/test_quiet_hours.py`, `tests/integration/test_weekly_digest.py` | test not written |
| `NOTIF-04` | R2 | S4 | `AC-NOTIF-04.3` | `T-NOTIF-04.3` | `tests/integration/test_quiet_hours.py`, `tests/integration/test_weekly_digest.py` | test not written |
| `NOTIF-04` | R2 | S4 | `AC-NOTIF-04.4` | `T-NOTIF-04.4` | `tests/integration/test_quiet_hours.py`, `tests/integration/test_weekly_digest.py` | test not written |
| `TRACK-02b` | R2 | S4 | `AC-TRACK-02.1` | `T-TRACK-02.1` | `tests/integration/test_kanban_pagination.py` | test not written |
| `TRACK-02b` | R2 | S4 | `AC-TRACK-02.2` | `T-TRACK-02.2` | `tests/unit/test_needs_attention.py` | test not written |
| `TRACK-02b` | R2 | S4 | `AC-TRACK-02.3` | `T-TRACK-02.3` | `tests/integration/test_application_filters.py` | test not written |
| `TRACK-02b` | R2 | S4 | `AC-TRACK-02.4` | `T-TRACK-02.4` | `tests/contract/test_card_projection.py` | test not written |
| `TRACK-02b` | R2 | S4 | `AC-TRACK-02.5` | `T-TRACK-02.5` | `apps/web/.../kanban.test.tsx`, `apps/mobile/test/tracker_card_test.dart` | test not written |
| `TRACK-02b` | R2 | S4 | `AC-TRACK-02.6` | `T-TRACK-02.6` | `tests/integration/test_tracker_latency.py` | test not written |
| `TRACK-02b` | R2 | S4 | `AC-TRACK-02.7` | `T-TRACK-02.7` | `apps/web/.../empty-states.test.tsx` | test not written |
| `TRACK-06` | R2 | S4 | `AC-TRACK-06.1` | `T-TRACK-06.1` | `tests/integration/test_ghosted_suggestion.py` | test not written |
| `TRACK-06` | R2 | S4 | `AC-TRACK-06.2` | `T-TRACK-06.2` | `tests/integration/test_ghosted_suggestion.py` | test not written |
| `TRACK-06` | R2 | S4 | `AC-TRACK-06.3` | `T-TRACK-06.3` | `tests/integration/test_ghosted_suggestion.py` | test not written |
| `TRACK-06` | R2 | S4 | `AC-TRACK-06.4` | `T-TRACK-06.4` | `tests/integration/test_ghosted_suggestion.py` | test not written |
| `TRACK-07` | R2 | S4 | `AC-TRACK-07.1` | `T-TRACK-07.1` | `tests/unit/test_stats.py`, `tests/integration/test_stats_endpoint.py` | test not written |
| `TRACK-07` | R2 | S4 | `AC-TRACK-07.2` | `T-TRACK-07.2` | `tests/unit/test_stats.py`, `tests/integration/test_stats_endpoint.py` | test not written |
| `TRACK-07` | R2 | S4 | `AC-TRACK-07.3` | `T-TRACK-07.3` | `tests/unit/test_stats.py`, `tests/integration/test_stats_endpoint.py` | test not written |
| `TRACK-07` | R2 | S4 | `AC-TRACK-07.4` | `T-TRACK-07.4` | `tests/unit/test_stats.py`, `tests/integration/test_stats_endpoint.py` | test not written |
| `TRACK-07` | R2 | S4 | `AC-TRACK-07.5` | `T-TRACK-07.5` | `tests/unit/test_stats.py`, `tests/integration/test_stats_endpoint.py` | test not written |
| `OPS-07` | R2 | S5 | `AC-OPS-07.1` | `T-OPS-07.1` | `tests/spec/test_runbooks_present.py` | test not written |
| `OPS-07` | R2 | S5 | `AC-OPS-07.2` | `T-OPS-07.2` | `tests/spec/test_runbooks_present.py` | test not written |
| `OPS-07` | R2 | S5 | `AC-OPS-07.3` | `T-OPS-07.3` | `tests/spec/test_runbooks_present.py` | test not written |
| `WEB-07` | R2 | S5 | `AC-WEB-07.1` | `T-WEB-07.1` | `apps/web/e2e/a11y.spec.ts` | test not written |
| `WEB-07` | R2 | S5 | `AC-WEB-07.2` | `T-WEB-07.2` | `apps/web/e2e/keyboard-journey.spec.ts` | test not written |
| `WEB-07` | R2 | S5 | `AC-WEB-07.3` | `T-WEB-07.3` | `apps/web/src/styles/__tests__/contrast.test.ts` | test not written |
| `WEB-07` | R2 | S5 | `AC-WEB-07.4` | `T-WEB-07.4` | `apps/web/.../non-color-indicators.test.tsx` | test not written |
| `WEB-07` | R2 | S5 | `AC-WEB-07.5` | `T-WEB-07.5` | `apps/web/.../live-region.test.tsx` | test not written |
| `WEB-07` | R2 | S5 | `AC-WEB-07.6` | `T-WEB-07.6` | `tests/spec/test_a11y_audit_doc.py` | test not written |
| `APPLY-06` | R3 | — | `AC-APPLY-06.1` | `T-APPLY-06.1` | `apps/extension/test/extension.test.ts` | test not written |
| `APPLY-06` | R3 | — | `AC-APPLY-06.2` | `T-APPLY-06.2` | `apps/extension/test/extension.test.ts` | test not written |
| `APPLY-06` | R3 | — | `AC-APPLY-06.3` | `T-APPLY-06.3` | `apps/extension/test/extension.test.ts` | test not written |
| `APPLY-06` | R3 | — | `AC-APPLY-06.4` | `T-APPLY-06.4` | `apps/extension/test/extension.test.ts` | test not written |
| `APPLY-08` | R3 | — | `AC-APPLY-08.1` | `T-APPLY-08.1` | `tests/integration/test_resume_export.py` | test not written |
| `APPLY-08` | R3 | — | `AC-APPLY-08.2` | `T-APPLY-08.2` | `tests/integration/test_resume_export.py` | test not written |
| `APPLY-08` | R3 | — | `AC-APPLY-08.3` | `T-APPLY-08.3` | `tests/integration/test_resume_export.py` | test not written |
| `MATCH-08` | R3 | — | `AC-MATCH-08.1` | `T-MATCH-08.1` | `tests/unit/test_gap_analysis.py` | test not written |
| `MATCH-08` | R3 | — | `AC-MATCH-08.2` | `T-MATCH-08.2` | `tests/unit/test_gap_analysis.py` | test not written |
| `NOTIF-02c` | R3 | — | — | — | — | no criteria |
| `PROF-04` | R3 | — | `AC-PROF-04.1` | `T-PROF-04.1` | `tests/spec/test_adr_present.py`, `tests/integration/test_multi_resume_migration.py` | test not written |
| `PROF-04` | R3 | — | `AC-PROF-04.2` | `T-PROF-04.2` | `tests/spec/test_adr_present.py`, `tests/integration/test_multi_resume_migration.py` | test not written |
