"""FastAPI app: direct-PostgreSQL source_post list/detail endpoints, gated
by OIDC login (backend.app.auth) and RBAC + ABAC (this module).

RBAC gate: the account's roles (account_role_assignment -> role_permission)
must include the 'post_read' permission at all -- a coarse yes/no on the
resource type.

ABAC gate, evaluated per row on top of the RBAC gate: a source_post is
visible if it is public, or if it is private and the requesting account is
affiliated with the post's owning corporate_entity_id. A W source-detail row
is raw-source-visible only to its author or post_admin; derived readers use a
separate eligibility boundary that excludes W. abac_policy's
condition_expression column is reserved for a future, richer per-policy
DSL (documented in migrations/0001_initial_schema.sql); Phase 1 implements
exactly this one fixed rule directly, since it is the only rule the
product currently needs.

The HTTP paths stay ``/api/posts`` (the product noun). The table they
read is ``source_post`` -- two-or-more-word table names, per AGENTS.md.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import asyncpg
import redis.asyncio as redis
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from lineageweave.adjudication_client import (
    ContextualOrchestratorAdjudicationClient,
    NullAdjudicationClient,
)
from lineageweave.commitment_extraction import (
    ContextualOrchestratorCommitmentExtractionClient,
    NullCommitmentExtractionClient,
)
from lineageweave.caldav_client import (
    CALDAV_UNAVAILABLE_NEXT_ACTION,
    build_caldav_client,
)
from lineageweave.entity_relationship_classification import (
    ContextualOrchestratorEntityRelationshipClient,
    NullEntityRelationshipClient,
)
from lineageweave.image_content import orchestrator_vision_client
from lineageweave.embedding_client import orchestrator_embedding_client
from lineageweave.llm_context import build_post_llm_metadata, use_llm_metadata
from lineageweave.corporate_hierarchy_inference import (
    ContextualOrchestratorHierarchyInferenceClient,
    NullCorporateHierarchyInferenceClient,
)
from lineageweave.keyman_extraction import (
    COUNTERPARTY,
    ContextualOrchestratorKeymanExtractionClient,
    NullKeymanExtractionClient,
)
from lineageweave.customer_hint_resolution import (
    ContextualOrchestratorCustomerHintResolutionClient,
    NullCustomerHintResolutionClient,
)
from lineageweave.organization_name_resolution import (
    ContextualOrchestratorOrganizationNameResolutionClient,
    NullOrganizationNameResolutionClient,
)
from lineageweave.post_chat import (
    ContextualOrchestratorPostChatClient,
    NullPostChatClient,
    cited_post_evidence,
    cited_post_summaries,
)
from lineageweave.post_content_normalization import normalize_post_body
from lineageweave.post_evaluation import (
    ContextualOrchestratorPostEvaluationClient,
    NullPostEvaluationClient,
    RUBRIC_VERSION,
)
from lineageweave.post_structure import ContextualOrchestratorPostStructureClient, NullPostStructureClient
from lineageweave.post_summary import ContextualOrchestratorPostSummaryClient, NullPostSummaryClient
from lineageweave.relation_verification import NullRelationVerificationClient, SearxngRelationVerificationClient
from lineageweave.semantic_hints import customer_hint_trust, format_semantic_hints
from lineageweave.source_lineage_hints import source_lineage_hints
from lineageweave.ontology import LW
from lineageweave.rankweave_client import build_rankweave_client

from backend.app.analysis_run_ingestion import (
    AnalysisRunCreateError,
    create_pending_analysis_run,
    fetch_visible_analysis_run,
    fetch_visible_analysis_runs,
)
from backend.app.analysis_run_outbox import publish_outbox_event
from backend.app.analysis_run_start import (
    AnalysisRunStartError,
    configured_tepp_client,
    deliver_queued_analysis_run,
    enqueue_pending_analysis_run,
)
from backend.app.analysis_run_worker import run_analysis_run_worker
from backend.app.post_content_queue import (
    ensure_post_content_job,
    fetch_post_summary_source,
    post_content_api_status,
    post_content_is_complete,
    post_content_summary_is_ready,
    post_body_has_images,
    publish_post_content_event,
)
from backend.app.post_content_worker import run_post_content_worker_supervised
from backend.app.source_post_revision import fetch_known_at_revision, parse_as_of_clock
from backend.app.activity_stream import (
    create_valkey_client,
    get_valkey,
    publish_activity_event,
    read_activity_events,
    ticket_created_summary,
    ticket_status_changed_summary,
)
from backend.app.affiliate_tree_ingestion import fetch_affiliate_forest, fetch_voc_evidence
from backend.app.auth import CurrentAccount, get_current_account
from backend.app.config import load_settings
from backend.app.customer_hint_ingestion import resolve_customer_hint
from backend.app.db import create_pool, get_pool
from backend.app.entity_relationship_ingestion import (
    fetch_post_counterparties,
    fetch_relationship_network,
    ingest_post_entity_relationships,
)
from backend.app.five_w1h_ingestion import load_five_w1h_slots
from backend.app.global_ask_history import (
    GlobalAskConversationNotFound,
    conversation_exists,
    fetch_conversation,
    list_conversations,
    persist_turn,
)
from backend.app.post_evaluation_ingestion import fetch_post_evaluation, ingest_post_evaluation
from backend.app.ranking_ingestion import load_visible_ranking_posts
from backend.app.report_ingestion import (
    GROUPING_KINDS,
    fetch_period_comparison,
    fetch_period_reports,
    iso_week_period,
    list_period_report_summaries,
    parse_period_code,
    rebuild_period_reports,
)
from backend.app.relation_verification_ingestion import verify_post_relations
from backend.app.issue_ticket_ingestion import (
    create_ticket,
    fetch_ticket_post_id,
    fetch_upcoming_commitments,
    list_tickets_for_post,
    update_ticket,
    upsert_commitment_ticket,
)
from backend.app.keyman_ingestion import ingest_post_keymen
from backend.app.knowledge_graph import (
    corporate_entity_exists,
    fetch_person_role_history,
    fetch_post_keymen,
    labels_for_codes,
    person_exists,
    persist_edges_for_post,
    post_knowledge_graph,
    related_for_entity,
    related_for_person,
    related_for_team,
    team_exists,
    visible_affiliation_post_ids,
    visible_mention_post_ids,
    visible_team_mention_post_ids,
)
from backend.app.lineage_ingestion import rebuild_lineage, visible_lineage_graph
from backend.app.post_chat_ingestion import (
    fetch_persisted_chat,
    fetch_persisted_chats,
    find_linked_post_ids,
    gather_chat_sources,
    gather_global_chat_sources,
    persist_post_chat,
)
from backend.app.post_summary_ingestion import (
    fetch_persisted_summary,
    persist_post_summary,
    require_summary_source_body,
)
from backend.app.post_eligibility import (
    SOURCE_POST_ELIGIBILITY_SQL,
    SOURCE_POST_READER_ELIGIBILITY_SQL,
    SOURCE_POST_VISIBILITY_SQL,
    WRITING_SOURCE_DETAIL_STATE_CODE,
    normalize_source_detail_state_code,
    source_post_state_visibility_sql,
)
from backend.app.demo_scope import (
    fetch_demo_corporate_entity_ids,
    has_real_source_context,
)
from lineageweave.http_client import HttpClientError

_POST_READ = "post_read"
_POST_ADMIN = "post_admin"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open one asyncpg pool and one Valkey client for the process, and
    close both on shutdown."""
    settings = load_settings()
    app.state.pool = await create_pool(settings.database_url)
    app.state.valkey = create_valkey_client(settings.valkey_url)
    app.state.analysis_run_worker = asyncio.create_task(
        run_analysis_run_worker(
            app.state.valkey,
            app.state.pool,
            tepp_client=configured_tepp_client(
                settings.tepp_transport_url,
                settings.tepp_api_key,
            ),
            adjudication_client=_adjudication_client(),
        )
    )
    app.state.post_content_worker = asyncio.create_task(
        run_post_content_worker_supervised(
            app.state.valkey,
            app.state.pool,
            vision_factory=_vision_client,
            embedding_factory=_embedding_client,
            structure_factory=_post_structure_client,
        )
    )
    try:
        yield
    finally:
        app.state.analysis_run_worker.cancel()
        app.state.post_content_worker.cancel()
        await asyncio.gather(
            app.state.analysis_run_worker,
            app.state.post_content_worker,
            return_exceptions=True,
        )
        await app.state.pool.close()
        await app.state.valkey.aclose()


app = FastAPI(title="LineageWeave API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=load_settings().frontend_origins,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization"],
)


def _require_post_read(account: CurrentAccount) -> None:
    """Raise 403 when the account has no ``post_read`` permission at all."""
    if not account.has_permission(_POST_READ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account lacks the post_read permission")


def _require_post_admin(account: CurrentAccount) -> None:
    """Raise 403 when the account has no ``post_admin`` permission at all."""
    if not account.has_permission(_POST_ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account lacks the post_admin permission")


def _keyman_extraction_client():
    """Live orchestrator client when configured; otherwise the unavailable null."""
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullKeymanExtractionClient()
    return ContextualOrchestratorKeymanExtractionClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key
    )


def _entity_relationship_client():
    """Live orchestrator client when configured; otherwise the unavailable null."""
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullEntityRelationshipClient()
    return ContextualOrchestratorEntityRelationshipClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key
    )


def _relation_verification_client():
    """Live Searxng client when configured; otherwise the unavailable null."""
    settings = load_settings()
    if not settings.searxng_base_url:
        return NullRelationVerificationClient()
    return SearxngRelationVerificationClient(base_url=settings.searxng_base_url)


def _organization_name_resolution_client():
    """Live orchestrator client when configured; otherwise the unavailable null."""
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullOrganizationNameResolutionClient()
    return ContextualOrchestratorOrganizationNameResolutionClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key
    )


def _customer_hint_resolution_client():
    """Live orchestrator client when configured; otherwise the unavailable null.

    A longer timeout than the other channels' default 30s: this prompt
    carries up to five posts' excerpts, not one short mention -- a real
    resolve call measured 137.6s live end-to-end (90s was not enough
    margin and made every real hint 503; 200s gives real headroom).
    """
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullCustomerHintResolutionClient()
    return ContextualOrchestratorCustomerHintResolutionClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key, timeout=200.0
    )


def _corporate_hierarchy_inference_client():
    """Live orchestrator client when configured; otherwise the unavailable null."""
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullCorporateHierarchyInferenceClient()
    return ContextualOrchestratorHierarchyInferenceClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key
    )


def _post_summary_client():
    """Live orchestrator client when configured; otherwise the unavailable null."""
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullPostSummaryClient()
    return ContextualOrchestratorPostSummaryClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key
    )


def _adjudication_client():
    """Live orchestrator client when configured; otherwise the unavailable null.

    reconstruct.py's DEFAULT_CHANNEL_WEIGHTS gives this channel the most
    weight (0.40) of the four -- it is the only one that reasons about
    content instead of approximating it (ADR 0064) -- but nothing ever
    passed a real client through lineage_edge_specs() to reconstruct(),
    so every lineage reconstruction had silently run on the weaker
    3-channel fallback since the feature was built.
    """
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullAdjudicationClient()
    return ContextualOrchestratorAdjudicationClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key
    )


def _post_structure_client():
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullPostStructureClient()
    return ContextualOrchestratorPostStructureClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key
    )


def _post_chat_client():
    """Live orchestrator client when configured; otherwise the unavailable null."""
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullPostChatClient()
    return ContextualOrchestratorPostChatClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key
    )


def _commitment_extraction_client():
    """Live orchestrator client when configured; otherwise the unavailable null."""
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullCommitmentExtractionClient()
    return ContextualOrchestratorCommitmentExtractionClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key
    )


def _vision_client():
    """Live vision client when configured; otherwise the unavailable null.

    Same contextual-orchestrator gateway as every other channel. The model is
    intentionally omitted so contextual-orchestrator selects the registered
    vision-capable provider agent; LineageWeave never selects ``VISION_MODEL``.
    """
    settings = load_settings()
    return orchestrator_vision_client(
        settings.orchestrator_base_url,
        settings.orchestrator_api_key,
    )


def _embedding_client():
    """Build the orchestrator embedding client, or an unavailable channel."""
    settings = load_settings()
    return orchestrator_embedding_client(
        settings.orchestrator_base_url,
        settings.orchestrator_api_key,
        settings.embedding_model,
    )


def _post_evaluation_client():
    """Live judge client when configured; otherwise the unavailable null."""
    settings = load_settings()
    if not (settings.orchestrator_base_url and settings.orchestrator_api_key):
        return NullPostEvaluationClient()
    return ContextualOrchestratorPostEvaluationClient(
        base_url=settings.orchestrator_base_url, api_key=settings.orchestrator_api_key
    )


def _rankweave_client():
    """In-process RankWeave unless RANKWEAVE_DISABLED=1 (ADR 0024)."""
    return build_rankweave_client(disabled=load_settings().rankweave_disabled)


def _can_see_post(account: CurrentAccount, post: asyncpg.Record) -> bool:
    """ABAC: W is author/admin-only; other rows use public/corp visibility."""
    try:
        state_code = normalize_source_detail_state_code(post["source_detail_state_code"])
    except KeyError:
        return False
    if state_code == WRITING_SOURCE_DETAIL_STATE_CODE:
        return account.has_permission(_POST_ADMIN) or str(
            post.get("author_account_id")
        ) == account.user_account_id
    if post["visibility_code"] == "public":
        return True
    return str(post["corporate_entity_id"]) in account.corporate_entity_ids


def _can_use_post_for_analysis(account: CurrentAccount, post: asyncpg.Record) -> bool:
    """Derived features consume only non-W authorized source posts."""
    return (
        normalize_source_detail_state_code(post.get("source_detail_state_code"))
        != WRITING_SOURCE_DETAIL_STATE_CODE
        and _can_see_post(account, post)
    )


def _is_synthetic_demo_member(member: dict[str, Any], demo_entity_ids: set[str]) -> bool:
    """Identify one pure seed row without hiding real rows sharing its entity."""
    return bool(demo_entity_ids) and member["corporate_entity_id"] in demo_entity_ids and not bool(
        member.get("has_real_source_context", False)
    )


def _serialize_post(post: asyncpg.Record, labels: dict[str, str] | None = None) -> dict[str, Any]:
    """Turn a ``source_post`` row into the public JSON shape."""
    resolved = labels or {}
    voc = post["voc_type_code"]
    visibility = post["visibility_code"]
    project_evidence = post.get("project_evidence") or []
    if isinstance(project_evidence, str):
        project_evidence = json.loads(project_evidence)
    return {
        "post_id": str(post["post_id"]),
        "post_title": post["post_title"],
        "voc_type_code": voc,
        "voc_type_label": resolved.get(voc, voc),
        "visibility_code": visibility,
        "visibility_label": resolved.get(visibility, visibility),
        "source_stage_code": post.get("source_stage_code"),
        "source_detail_state_code": normalize_source_detail_state_code(
            post.get("source_detail_state_code")
        ),
        "source_draft_code": post.get("source_draft_code"),
        "source_deleted_flag": post.get("source_deleted_flag"),
        "publication_state_code": _publication_state_code(post),
        "source_author_code": post.get("source_author_code"),
        "source_author_name": post.get("source_author_name"),
        "source_company_code": post.get("source_company_code"),
        "source_company_name": post.get("source_company_name"),
        "source_process_unit_code": post.get("source_process_unit_code"),
        "source_process_unit_name": post.get("source_process_unit_name"),
        "source_process_unit_catalog_name": post.get("source_process_unit_catalog_name"),
        "source_sales_pool_code": post.get("source_sales_pool_code"),
        "source_sales_pool_name": post.get("source_sales_pool_name"),
        "source_order_pool_code": post.get("source_order_pool_code"),
        "source_sales_order_code": post.get("source_sales_order_code"),
        "source_sales_order_item_number": post.get("source_sales_order_item_number"),
        "source_inspection_point_code": post.get("source_inspection_point_code"),
        "source_customer_code": post.get("source_customer_code"),
        "source_customer_name": post.get("source_customer_name"),
        "source_project_code": post.get("source_project_code"),
        "source_project_name": post.get("source_project_name"),
        "source_system_code": post.get("source_system_code"),
        "source_record_key": post.get("source_record_key"),
        "source_lineage_hints": source_lineage_hints(
            customer_code=post.get("source_customer_code"),
            order_pool_code=post.get("source_order_pool_code"),
            sales_order_code=post.get("source_sales_order_code"),
            sales_order_item_number=post.get("source_sales_order_item_number"),
            stage_code=post.get("source_stage_code"),
            detail_state_code=post.get("source_detail_state_code"),
            inspection_point_code=post.get("source_inspection_point_code"),
            deleted_flag=post.get("source_deleted_flag"),
        ),
        "post_body_excerpt": post.get("post_body_excerpt"),
        "post_body_truncated": post.get("post_body_truncated", False),
        "project_evidence": project_evidence,
        "created_at": post["created_at"].isoformat(),
    }


def _publication_state_code(post: asyncpg.Record) -> str:
    """Expose raw lifecycle evidence without guessing its source semantics."""
    if str(post.get("source_deleted_flag") or "").strip():
        return "source_deletion_marker"
    if str(post.get("source_draft_code") or "").strip():
        return "source_draft_marker"
    return "publication_state_unknown"


async def _load_project_evidence(
    conn: asyncpg.Connection,
    post_id: str,
    source_project_code: str | None,
    source_project_name: str | None,
) -> list[dict[str, Any]]:
    """Merge explicit source hints and stored semantic project candidates."""
    evidence: list[dict[str, Any]] = []
    source_code = source_project_code.strip() if source_project_code else ""
    source_name = source_project_name.strip() if source_project_name else ""
    if source_code or source_name:
        source_field = (
            "source_post.source_project_name"
            if source_name
            else "source_post.source_project_code"
        )
        evidence.append(
            {
                "project_key": source_code or source_name,
                "project_name": source_name or source_code,
                "evidence": source_field,
                "confidence": None,
                "ontology_iri": str(LW.Project),
                "ontology_label": "Project",
                "extraction_method": "source_field_hint",
                "resolution_status": "hint_only",
                "provenance": source_field,
            }
        )
    rows = await conn.fetch(
        """
        select project_key, project_name, evidence_text, mention_confidence,
               ontology_iri, extraction_method
          from post_project_mention
         where post_id = $1
         order by mention_confidence desc, project_name, project_key
        """,
        post_id,
    )
    evidence.extend(
        {
            "project_key": row["project_key"],
            "project_name": row["project_name"],
            "evidence": row["evidence_text"],
            "confidence": float(row["mention_confidence"]),
            "ontology_iri": row["ontology_iri"],
            "ontology_label": "Project",
            "extraction_method": row["extraction_method"],
            "resolution_status": "semantic_candidate",
            "provenance": "post_project_mention.evidence_text",
        }
        for row in rows
    )
    return evidence


async def _lookup_post_labels(conn: asyncpg.Connection, rows: list[asyncpg.Record]) -> dict[str, str]:
    """Resolve voc_type / visibility codes against common_lookup_value."""
    codes = [row["voc_type_code"] for row in rows] + [row["visibility_code"] for row in rows]
    return await labels_for_codes(conn, codes)


async def _post_filter_options(
    conn: asyncpg.Connection, account: CurrentAccount
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Return every authorized filter value, not only values on the current page."""
    state_visibility_sql = source_post_state_visibility_sql(
        "post", corporate_param=1, account_param=2, admin_param=3
    )
    visibility_sql = f"""
        select distinct post.visibility_code as code,
               coalesce(lookup.lookup_label, post.visibility_code) as label,
               coalesce(lookup.display_order, 2147483647) as display_order
          from source_post post
          left join common_lookup_value lookup
            on lookup.lookup_category = 'post_visibility'
           and lookup.lookup_code = post.visibility_code
         where {state_visibility_sql}
           and {SOURCE_POST_READER_ELIGIBILITY_SQL.format(alias='post')}
         order by display_order, code
    """
    type_sql = f"""
        select distinct post.voc_type_code as code,
               coalesce(lookup.lookup_label, post.voc_type_code) as label,
               coalesce(lookup.display_order, 2147483647) as display_order
          from source_post post
          left join common_lookup_value lookup
            on lookup.lookup_category = 'voc_type'
           and lookup.lookup_code = post.voc_type_code
         where {state_visibility_sql}
           and {SOURCE_POST_READER_ELIGIBILITY_SQL.format(alias='post')}
         order by display_order, code
    """
    detail_state_sql = f"""
        select distinct upper(btrim(post.source_detail_state_code)) as code,
               upper(btrim(post.source_detail_state_code)) as label
          from source_post post
         where {state_visibility_sql}
           and {SOURCE_POST_READER_ELIGIBILITY_SQL.format(alias='post')}
           and nullif(btrim(post.source_detail_state_code), '') is not null
         order by code
    """
    # Safe SQL: both query strings are closed lookup statements; entity ids remain asyncpg parameters.
    visibility_rows = await conn.fetch(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
        visibility_sql,
        list(account.corporate_entity_ids),
        account.user_account_id,
        account.has_permission(_POST_ADMIN),
    )
    # Safe SQL: both query strings are closed lookup statements; entity ids remain asyncpg parameters.
    type_rows = await conn.fetch(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
        type_sql,
        list(account.corporate_entity_ids),
        account.user_account_id,
        account.has_permission(_POST_ADMIN),
    )
    # Detail-state codes intentionally remain raw here; the UI owns the
    # product-language explanation and preserves unknown source codes.
    # Safe SQL: a closed lookup statement identical in shape to visibility_sql/type_sql above; entity ids remain asyncpg parameters.
    detail_state_rows = await conn.fetch(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
        detail_state_sql,
        list(account.corporate_entity_ids),
        account.user_account_id,
        account.has_permission(_POST_ADMIN),
    )
    return (
        [{"code": row["code"], "label": row["label"]} for row in type_rows],
        [{"code": row["code"], "label": row["label"]} for row in detail_state_rows],
        [{"code": row["code"], "label": row["label"]} for row in visibility_rows],
    )


_TENANT_SETTINGS_DEFAULTS: dict[str, str | int] = {
    "brandName": "LineageWeave",
    "systemName": "LineageWeave",
    "copyrightYear": 2026,
    "copyrightHolder": "LineageWeave",
}


def _tenant_settings_response(row: asyncpg.Record | None) -> dict[str, str | int]:
    """Return the stable shell identity contract from one tenant settings row."""
    if row is None:
        return dict(_TENANT_SETTINGS_DEFAULTS)
    return {
        "brandName": row["brand_name"],
        "systemName": row["system_name"],
        "copyrightYear": row["copyright_year"],
        "copyrightHolder": row["copyright_holder"],
    }


def _tenant_setting_text(payload: dict[str, Any], key: str, current: str) -> str:
    """Validate and trim a required tenant display string at the API boundary."""
    value = payload.get(key, current)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{key} must not be blank")
    return value.strip()


def _tenant_copyright_year(payload: dict[str, Any], current: int) -> int:
    """Validate the explicit copyright year instead of deriving it from the clock."""
    value = payload.get("copyrightYear", current)
    if isinstance(value, bool) or not isinstance(value, int) or not 1900 <= value <= 2100:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "copyrightYear must be an integer between 1900 and 2100",
        )
    return value


@app.get("/api/settings", response_model=dict)
async def read_tenant_settings(
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT brand_name, system_name, copyright_year, copyright_holder
              FROM tenant_settings
             WHERE tenant_settings_id = 1
            """
        )
    return _tenant_settings_response(row)

@app.patch("/api/settings", response_model=dict)
async def update_tenant_settings(
    payload: dict[str, Any],
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
):
    # Only admins can change settings
    _require_post_admin(account)
    async with pool.acquire() as conn:
        async with conn.transaction():
            current_row = await conn.fetchrow(
                """
                SELECT brand_name, system_name, copyright_year, copyright_holder
                  FROM tenant_settings
                 WHERE tenant_settings_id = 1
                 FOR UPDATE
                """
            )
            current = _tenant_settings_response(current_row)
            brand_name = _tenant_setting_text(payload, "brandName", str(current["brandName"]))
            system_name = _tenant_setting_text(payload, "systemName", str(current["systemName"]))
            copyright_year = _tenant_copyright_year(payload, int(current["copyrightYear"]))
            copyright_holder = _tenant_setting_text(
                payload, "copyrightHolder", str(current["copyrightHolder"])
            )
            await conn.execute(
                """
                INSERT INTO tenant_settings
                    (tenant_settings_id, brand_name, system_name, copyright_year, copyright_holder)
                VALUES (1, $1, $2, $3, $4)
                ON CONFLICT (tenant_settings_id) DO UPDATE SET
                    brand_name = EXCLUDED.brand_name,
                    system_name = EXCLUDED.system_name,
                    copyright_year = EXCLUDED.copyright_year,
                    copyright_holder = EXCLUDED.copyright_holder,
                    updated_at = now()
                """,
                brand_name,
                system_name,
                copyright_year,
                copyright_holder,
            )
    return {
        "brandName": brand_name,
        "systemName": system_name,
        "copyrightYear": copyright_year,
        "copyrightHolder": copyright_holder,
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe: the process is up. Does not touch Postgres."""
    return {"status": "ok"}


@app.get("/api/me")
async def read_me(
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return the provisioned account and the corps this token may walk.

    Multi-affiliation operators need those names to choose which entity
    ``POST /api/analysis-runs`` should cover.
    """
    entities: list[dict[str, str]] = []
    account_affiliations: list[dict[str, Any]] = []
    if account.corporate_entity_ids:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select affiliation.corporate_entity_id,
                       entity.corporate_entity_code,
                       entity.entity_name,
                       affiliation.process_unit_id,
                       process.process_unit_code,
                       process.process_unit_name
                  from account_affiliation affiliation
                  join corporate_entity entity
                    on entity.corporate_entity_id = affiliation.corporate_entity_id
                  left join process_unit process
                    on process.process_unit_id = affiliation.process_unit_id
                   and process.corporate_entity_id = affiliation.corporate_entity_id
                 where affiliation.user_account_id = $1
                   and affiliation.corporate_entity_id = any($2::uuid[])
                 order by entity.entity_name, process.process_unit_code nulls first
                """,
                account.user_account_id,
                list(account.corporate_entity_ids),
            )
        seen_entities: set[str] = set()
        for row in rows:
            entity_id = str(row["corporate_entity_id"])
            if entity_id not in seen_entities:
                entities.append(
                    {
                        "corporate_entity_id": entity_id,
                        "corporate_entity_code": row["corporate_entity_code"],
                        "entity_name": row["entity_name"],
                    }
                )
                seen_entities.add(entity_id)
            account_affiliations.append(
                {
                    "corporate_entity_id": entity_id,
                    "corporate_entity_code": row["corporate_entity_code"],
                    "entity_name": row["entity_name"],
                    "process_unit_id": str(row["process_unit_id"]) if row["process_unit_id"] else None,
                    "process_unit_code": row["process_unit_code"],
                    "process_unit_name": row["process_unit_name"],
                }
            )
    return {
        "user_account_id": account.user_account_id,
        "display_name": account.display_name,
        "preferred_locale": account.preferred_locale,
        "permission_codes": sorted(account.permission_codes),
        "corporate_entities": entities,
        "account_affiliations": account_affiliations,
    }


class LocalePreferenceRequest(BaseModel):
    preferred_locale: Literal["en", "ko", "zh", "ja", "vi"]


class CustomerHintResolveRequest(BaseModel):
    hint_code: str


@app.patch("/api/me/preferences")
async def update_me_preferences(
    preference: LocalePreferenceRequest,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, str]:
    """Persist member preferences without putting them in browser-only state."""
    async with pool.acquire() as conn:
        await conn.execute(
            "update user_account set preferred_locale = $1 where user_account_id = $2",
            preference.preferred_locale,
            account.user_account_id,
        )
    return {"preferred_locale": preference.preferred_locale}


_AFFILIATION_SCOPE_CODE_TO_FACET = {
    "scope_own_entity": "authorized_own",
    "scope_granted_entity": "authorized_granted",
    # scope_unclassified contributes no own/granted facet -- the entity is
    # still authorized, it is just not labeled either way (ADR 0125).
}


def _customer_master_scope_facets(
    row: asyncpg.Record, observed_hierarchy_ids: set[str]
) -> list[str]:
    """Repeatable, provenance-bearing facets for one Customer Master row."""
    facets = [
        _AFFILIATION_SCOPE_CODE_TO_FACET[code]
        for code in row["scope_codes"]
        if code in _AFFILIATION_SCOPE_CODE_TO_FACET
    ]
    if str(row["corporate_entity_id"]) in observed_hierarchy_ids:
        facets.append("observed_hierarchy")
    if row["is_observed_organization"]:
        facets.append("observed_organization")
    return facets


def _observed_hierarchy_ids(rows: list[asyncpg.Record]) -> set[str]:
    """Return authorized ancestors of entities observed in visible posts."""
    rows_by_id = {str(row["corporate_entity_id"]): row for row in rows}
    hierarchy_ids: set[str] = set()
    for row in rows:
        if not row["is_observed_organization"] or row["parent_entity_id"] is None:
            continue
        parent_id = row["parent_entity_id"]
        while parent_id is not None:
            parent_key = str(parent_id)
            if parent_key in hierarchy_ids:
                break
            hierarchy_ids.add(parent_key)
            parent = rows_by_id.get(parent_key)
            parent_id = parent["parent_entity_id"] if parent is not None else None
    return hierarchy_ids


@app.get("/api/customer-master")
async def read_customer_master(
    hint_code: str | None = Query(default=None, max_length=255),
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return the authorized customer catalog and its cataloged Keymen."""
    _require_post_read(account)
    requested_hint_code = (hint_code or "").strip() or None
    authorized_entity_ids = list(account.corporate_entity_ids)
    if not authorized_entity_ids:
        return {
            "corporate_entities": [],
            "keymen": [],
            "source_customer_hints": [],
            "source_author_hints": [],
            "relationship_network": [],
        }

    async with pool.acquire() as conn:
        # Safe SQL: the evidence query uses only closed schema fragments; authorized entity ids are bound.
        source_customer_rows = await conn.fetch(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
            f"""
            with scoped as (
                select post_id, post_title, created_at,
                       nullif(btrim(source_customer_code), '') as customer_code,
                       nullif(btrim(source_customer_name), '') as customer_name,
                       case when nullif(btrim(source_customer_code), '') is null
                            then nullif(btrim(source_customer_name), '')
                            else null end as customer_name_group
                  from source_post
                 where (nullif(btrim(source_customer_code), '') is not null
                        or nullif(btrim(source_customer_name), '') is not null)
                   and ($2::text is null
                        or nullif(btrim(source_customer_code), '') = $2::text)
                   and {SOURCE_POST_VISIBILITY_SQL.format(alias='source_post', authorized_entity_ids='$1')}
                    and {SOURCE_POST_ELIGIBILITY_SQL.format(alias='source_post')}
            ), ranked as (
                select scoped.*,
                       row_number() over (
                           partition by customer_code, customer_name_group
                           order by created_at desc, post_id desc
                       ) as related_rank
                  from scoped
            ), groups as (
                select customer_code, customer_name_group,
                       max(customer_name) as customer_name,
                       count(*) as post_count
                  from ranked
                 group by customer_code, customer_name_group
            ), top_groups as materialized (
                select *
                  from groups
                 order by post_count desc, customer_code, customer_name
                 limit 100
            ), related as (
                select ranked.customer_code, ranked.customer_name_group,
                       json_agg(
                           json_build_object(
                               'post_id', post.post_id::text,
                               'post_title', post.post_title
                           )
                           order by ranked.created_at desc, ranked.post_id desc
                       ) as related_posts
                  from ranked
                  join top_groups
                    on top_groups.customer_code is not distinct from ranked.customer_code
                   and top_groups.customer_name_group is not distinct from ranked.customer_name_group
                  join source_post post on post.post_id = ranked.post_id
                 where ranked.related_rank <= 20
                 group by ranked.customer_code, ranked.customer_name_group
            )
            select top_groups.customer_code, top_groups.customer_name, top_groups.post_count,
                   coalesce(related.related_posts, '[]'::json) as related_posts
              from top_groups
              left join related
                on related.customer_code is not distinct from top_groups.customer_code
               and related.customer_name_group is not distinct from top_groups.customer_name_group
             order by top_groups.post_count desc, top_groups.customer_code, top_groups.customer_name
            """,
            authorized_entity_ids,
            requested_hint_code,
        )
        # Safe SQL: the evidence query uses only closed schema fragments; authorized entity ids are bound.
        source_author_rows = await conn.fetch(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
            f"""
            with scoped as (
                select post.post_id, post.post_title, post.created_at,
                       btrim(post.source_author_code) as author_code,
                       case
                           when post.source_author_name is null
                             or btrim(post.source_author_name) = ''
                             or lower(btrim(post.source_author_name)) = lower(btrim(post.source_author_code))
                           then null
                           else btrim(post.source_author_name)
                       end as source_author_name,
                       post.author_account_id,
                       author.display_name as account_display_name
                  from source_post post
                  join user_account author on author.user_account_id = post.author_account_id
                 where post.source_author_code is not null
                   and btrim(post.source_author_code) <> ''
                   and (post.visibility_code = 'public' or post.corporate_entity_id = any($1::uuid[]))
                   and {SOURCE_POST_ELIGIBILITY_SQL.format(alias='post')}
            ), ranked as (
                select scoped.*,
                       row_number() over (
                           partition by author_code, author_account_id, account_display_name
                           order by created_at desc, post_id desc
                       ) as related_rank
                  from scoped
            ), groups as (
                select author_code, author_account_id, account_display_name,
                       max(source_author_name) as author_name,
                       count(*) as post_count
                  from ranked
                 group by author_code, author_account_id, account_display_name
            ), keyman_mentions as (
                select ranked.author_code, ranked.author_account_id,
                       ranked.account_display_name, ranked.post_id,
                       person.person_id, person.person_name,
                       person.person_side_code, person.last_known_job_title
                  from ranked
                  join post_summary_role role
                    on role.post_id = ranked.post_id
                   and role.actor_type_code = 'prov_person'
                  join cataloged_person person
                    on person.person_id = role.cataloged_person_id
                   and person.person_side_code = 'our_side'
                 where role.cataloged_person_id is not null
                union
                select ranked.author_code, ranked.author_account_id,
                       ranked.account_display_name, ranked.post_id,
                       person.person_id, person.person_name,
                       person.person_side_code, person.last_known_job_title
                  from ranked
                  join post_person_mention mention
                    on mention.post_id = ranked.post_id
                  join cataloged_person person
                    on person.person_id = mention.person_id
                   and person.person_side_code = 'our_side'
            ), keyman_authors as (
                select distinct author_code, author_account_id, account_display_name
                  from keyman_mentions
            ), top_groups as materialized (
                select groups.*
                  from groups
                  left join keyman_authors
                    on keyman_authors.author_code = groups.author_code
                   and keyman_authors.author_account_id = groups.author_account_id
                   and keyman_authors.account_display_name = groups.account_display_name
                 order by (keyman_authors.author_code is not null) desc,
                          groups.post_count desc, groups.author_code
                 limit 100
            ), keyman_groups as (
                select mentions.author_code, mentions.author_account_id,
                       mentions.account_display_name,
                       mentions.person_id, mentions.person_name,
                       mentions.person_side_code, mentions.last_known_job_title,
                       count(distinct mentions.post_id) as mention_count
                  from keyman_mentions mentions
                  join top_groups
                    on top_groups.author_code = mentions.author_code
                   and top_groups.author_account_id = mentions.author_account_id
                   and top_groups.account_display_name = mentions.account_display_name
                 group by mentions.author_code, mentions.author_account_id,
                          mentions.account_display_name, mentions.person_id,
                          mentions.person_name, mentions.person_side_code,
                          mentions.last_known_job_title
            ), keyman_related as (
                select author_code, author_account_id, account_display_name,
                       json_agg(
                           json_build_object(
                               'person_id', person_id::text,
                               'person_name', person_name,
                               'person_side_code', person_side_code,
                               'last_known_job_title', last_known_job_title,
                               'mention_count', mention_count,
                               'provenance',
                               'post_person_mention.person_id|post_summary_role.cataloged_person_id/source_post.author_account_id'
                           )
                           order by mention_count desc, person_name, person_id
                       ) as keyman_hints
                  from keyman_groups
                 group by author_code, author_account_id, account_display_name
            ), related as (
                select ranked.author_code, ranked.author_account_id, ranked.account_display_name,
                       json_agg(
                           json_build_object(
                               'post_id', post.post_id::text,
                               'post_title', post.post_title
                           )
                           order by ranked.created_at desc, ranked.post_id desc
                       ) as related_posts
                  from ranked
                  join top_groups
                    on top_groups.author_code = ranked.author_code
                   and top_groups.author_account_id = ranked.author_account_id
                   and top_groups.account_display_name = ranked.account_display_name
                  join source_post post on post.post_id = ranked.post_id
                 where ranked.related_rank <= 20
                 group by ranked.author_code, ranked.author_account_id, ranked.account_display_name
            )
            select top_groups.author_code, top_groups.author_name, top_groups.author_account_id,
                   top_groups.account_display_name, top_groups.post_count,
                   coalesce(keyman_related.keyman_hints, '[]'::json) as keyman_hints,
                   coalesce(related.related_posts, '[]'::json) as related_posts
              from top_groups
              left join keyman_related
                on keyman_related.author_code = top_groups.author_code
               and keyman_related.author_account_id = top_groups.author_account_id
               and keyman_related.account_display_name = top_groups.account_display_name
              left join related
                on related.author_code = top_groups.author_code
               and related.author_account_id = top_groups.author_account_id
               and related.account_display_name = top_groups.account_display_name
             order by top_groups.post_count desc, top_groups.author_code
            """,
            list(account.corporate_entity_ids),
        )
        has_source_context = bool(source_customer_rows or source_author_rows)
        if not has_source_context:
            has_source_context = await has_real_source_context(
                conn, list(account.corporate_entity_ids)
            )
        synthetic_only_entity_ids: set[str] = set()
        if has_source_context:
            synthetic_only_entity_ids = await fetch_demo_corporate_entity_ids(conn)
        # ADR 0125: an entity reaches Customer Master either through this
        # account's own account_affiliation grants (authorized_own /
        # authorized_granted, per its explicit affiliation_scope_code -- an
        # unclassified affiliation is still authorized, it just carries no
        # own/granted facet) or because it is actually mentioned in a post
        # this account may already see (observed_organization). Neither
        # path widens access: the observed branch reuses the exact same
        # public-or-own-corp/eligibility predicate every other query on
        # this endpoint already applies to source_post.
        # Safe SQL: the eligibility predicate is an immutable schema fragment; ids are bound.
        entity_rows = await conn.fetch(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
            f"""
            with own_affiliation as (
                select corporate_entity_id,
                       array_agg(distinct affiliation_scope_code)
                           filter (where affiliation_scope_code is not null) as scope_codes
                 from account_affiliation
                 where user_account_id = $2
                   and corporate_entity_id = any($1::uuid[])
                 group by corporate_entity_id
            ), observed as (
                select org_mention.corporate_entity_id
                  from post_organization_mention org_mention
                  join source_post post on post.post_id = org_mention.post_id
                 where (post.visibility_code = 'public' or post.corporate_entity_id = any($1::uuid[]))
                   and {SOURCE_POST_ELIGIBILITY_SQL.format(alias='post')}
                   and not (org_mention.corporate_entity_id = any($3::uuid[]))
                 group by org_mention.corporate_entity_id
                 order by count(distinct org_mention.post_id) desc,
                          org_mention.corporate_entity_id
                 limit 100
            )
            select entity.corporate_entity_id, entity.corporate_entity_code, entity.entity_name,
                   entity.entity_level_code, entity.parent_entity_id,
                   coalesce(own_affiliation.scope_codes, array[]::text[]) as scope_codes,
                   (observed.corporate_entity_id is not null) as is_observed_organization
              from corporate_entity entity
              left join own_affiliation on own_affiliation.corporate_entity_id = entity.corporate_entity_id
              left join observed on observed.corporate_entity_id = entity.corporate_entity_id
             where (own_affiliation.corporate_entity_id is not null
                    or observed.corporate_entity_id is not null)
               and not (entity.corporate_entity_id = any($3::uuid[]))
             order by entity.entity_name
            """,
            list(account.corporate_entity_ids),
            account.user_account_id,
            list(synthetic_only_entity_ids),
        )
        observed_hierarchy_ids = _observed_hierarchy_ids(entity_rows)
        entity_ids = [row["corporate_entity_id"] for row in entity_rows]
        source_author_affiliations = await _load_account_affiliation_hints(
            conn,
            [str(row["author_account_id"]) for row in source_author_rows],
            [str(entity_id) for entity_id in entity_ids],
        )
        keyman_rows = await conn.fetch(
            """
            select person.person_id, person.person_name, person.person_side_code,
                   person.last_known_job_title,
                   affiliation.affiliated_organization_name,
                   affiliation.affiliated_corporate_entity_id,
                   affiliation.role_title,
                   entity.entity_name
             from cataloged_person person
             join person_affiliation affiliation on affiliation.person_id = person.person_id
             left join corporate_entity entity
                on entity.corporate_entity_id = affiliation.affiliated_corporate_entity_id
             where affiliation.affiliated_corporate_entity_id = any($1::uuid[])
               and person.person_side_code = 'our_side'
             order by person.person_name, affiliation.affiliated_organization_name
            """,
            entity_ids,
        )
        side_labels = await labels_for_codes(conn, [row["person_side_code"] for row in keyman_rows])
        entity_level_labels = await labels_for_codes(conn, [row["entity_level_code"] for row in entity_rows])
        relationship_network = await fetch_relationship_network(conn, entity_ids)

    keymen_by_id: dict[str, dict[str, Any]] = {}
    for row in keyman_rows:
        person_id = str(row["person_id"])
        keyman = keymen_by_id.setdefault(
            person_id,
            {
                "person_id": person_id,
                "person_name": row["person_name"],
                "person_side_code": row["person_side_code"],
                "person_side_label": side_labels.get(row["person_side_code"], row["person_side_code"]),
                "last_known_job_title": row["last_known_job_title"],
                "affiliations": [],
            },
        )
        keyman["affiliations"].append(
            {
                "organization_name": row["affiliated_organization_name"],
                "corporate_entity_id": (
                    str(row["affiliated_corporate_entity_id"])
                    if row["affiliated_corporate_entity_id"] is not None
                    else None
                ),
                "entity_name": row["entity_name"],
                "role_title": row["role_title"],
            }
        )

    return {
        "corporate_entities": [
            {
                "corporate_entity_id": str(row["corporate_entity_id"]),
                "corporate_entity_code": row["corporate_entity_code"],
                "entity_name": row["entity_name"],
                "entity_level_code": row["entity_level_code"],
                "entity_level_label": entity_level_labels.get(
                    row["entity_level_code"], row["entity_level_code"]
                ),
                "parent_entity_id": (
                    str(row["parent_entity_id"]) if row["parent_entity_id"] is not None else None
                ),
                "scope_facets": _customer_master_scope_facets(row, observed_hierarchy_ids),
            }
            for row in entity_rows
        ],
        "keymen": list(keymen_by_id.values()),
        "source_customer_hints": [
            {
                "customer_code": row["customer_code"],
                "customer_name": row["customer_name"],
                "post_count": row["post_count"],
                "related_posts": (
                    json.loads(row["related_posts"])
                    if isinstance(row["related_posts"], str)
                    else row["related_posts"] or []
                ),
                "resolution_status": "hint_only",
                "hint_trust": customer_hint_trust(row["customer_name"], row["customer_code"]),
                "provenance": "source_post.source_customer_code/source_post.source_customer_name",
            }
            for row in source_customer_rows
        ],
        "source_author_hints": [
            {
                "author_code": row["author_code"],
                "author_name": row["author_name"],
                "author_account_id": str(row["author_account_id"]),
                "account_display_name": row["account_display_name"],
                "account_affiliations": source_author_affiliations.get(
                    str(row["author_account_id"]), []
                ),
                "post_count": row["post_count"],
                "keyman_hints": (
                    json.loads(row["keyman_hints"])
                    if isinstance(row["keyman_hints"], str)
                    else row["keyman_hints"] or []
                ),
                "related_posts": (
                    json.loads(row["related_posts"])
                    if isinstance(row["related_posts"], str)
                    else row["related_posts"] or []
                ),
                "resolution_status": (
                    "our_side_context_only"
                    if source_author_affiliations.get(str(row["author_account_id"]), [])
                    else "source_author_hint_only"
                ),
                "provenance": (
                    "source_post.author_account_id/user_account.display_name/"
                    "account_affiliation.corporate_entity_id/source_post.source_author_code/source_post.source_author_name"
                ),
            }
            for row in source_author_rows
        ],
        "relationship_network": relationship_network,
    }


@app.post("/api/customer-master/resolve-hint")
async def resolve_customer_master_hint(
    request: CustomerHintResolveRequest,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Resolve one observed customer-hint code to a real corporate_entity.

    Gated by post_admin, not post_read: this is a write action with a
    real LLM-call cost, same discipline as extract-keymen/verify-relations.
    Only an externally-corroborated proposed name ever creates or binds an
    entity (`backend.app.customer_hint_ingestion`) -- an unresolved or
    uncorroborated hint is returned as such, never guessed into the
    catalog.
    """
    _require_post_admin(account)
    async with pool.acquire() as conn:
        try:
            resolution = await resolve_customer_hint(
                conn,
                _customer_hint_resolution_client(),
                _relation_verification_client(),
                request.hint_code,
            )
        except (HttpClientError, OSError) as exc:
            # resolve_and_verify_organization_name's resolution/verification
            # calls raise on a failed request rather than silently returning
            # "unresolved" -- a failed call is not the same claim as "the
            # model looked and found nothing" (same discipline as
            # verify-relations' identical try/except).
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Hint resolution is unavailable: the orchestrator or search provider did not respond",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - provider boundary is fail-closed.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Hint resolution is unavailable: the orchestrator or search provider did not respond",
            ) from exc
    if resolution is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "this hint could not be resolved to a corroborated organization name",
        )
    return resolution


@app.get("/api/lineage")
async def read_lineage_graph(
    limit: int = Query(500, ge=1, le=2000),
    post_id: str | None = Query(None, min_length=1),
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """ABAC-filtered reconstruct graph bounded for browser rendering."""
    _require_post_read(account)
    async with pool.acquire() as conn:
        return await visible_lineage_graph(
            conn,
            lambda row: _can_use_post_for_analysis(account, row),
            limit=limit,
            focus_post_id=post_id,
        )


@app.post("/api/lineage/rebuild")
async def rebuild_lineage_graph(
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Run reconstruct over every source_post and persist post_lineage_edge.

    post_admin only: this is a corpus-wide write. Reads stay ABAC-gated.
    """
    _require_post_admin(account)
    async with pool.acquire() as conn:
        async with conn.transaction():
            edges = await rebuild_lineage(conn)
    return {"edge_count": len(edges)}


@app.get("/api/posts")
async def list_posts(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, max_length=200),
    voc_type: list[str] | None = Query(None, max_length=80),
    source_detail_state: list[str] | None = Query(None, max_length=80),
    visibility: str | None = Query(None, max_length=80),
    sort: Literal["newest", "oldest", "title"] = Query("newest"),
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """List authorized posts, with semantic evidence search when requested."""
    _require_post_read(account)
    search_term = search.strip() if search and search.strip() else None
    voc_type_codes = (
        [code.strip() for code in voc_type if code.strip()] if voc_type else None
    ) or None
    source_detail_state_codes = (
        [code.strip().upper() for code in source_detail_state if code.strip()]
        if source_detail_state
        else None
    ) or None
    async with pool.acquire() as conn:
        voc_type_options, source_detail_state_options, visibility_options = await _post_filter_options(
            conn, account
        )
        body_search_ids: list[str] = []
        if search_term:
            # Safe SQL: search SQL is a closed schema query; search_term is bound through $1.
            body_rows = await conn.fetch(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
                f"""
                select post_id
                  from source_post
                where {source_post_state_visibility_sql("source_post", corporate_param=4, account_param=2, admin_param=3)}
                  and {SOURCE_POST_READER_ELIGIBILITY_SQL.format(alias="source_post")}
                  and (lower(left(source_post_search_text(post_body), 16384))
                           like '%' || lower($1) || '%'
                    or to_tsvector('simple', source_post_search_text(post_body))
                           @@ plainto_tsquery('simple', $1))
                order by
                    case when lower(left(source_post_search_text(post_body), 16384))
                              like '%' || lower($1) || '%' then 0 else 1 end,
                    ts_rank(
                        to_tsvector('simple', source_post_search_text(post_body)),
                        plainto_tsquery('simple', $1)
                    ) desc,
                    post_id
                """,
                search_term,
                account.user_account_id,
                account.has_permission(_POST_ADMIN),
                list(account.corporate_entity_ids),
            )
            body_search_ids = [str(row["post_id"]) for row in body_rows]
        # Safe SQL: page SQL is a closed schema query; every request value is an asyncpg parameter.
        rows = await conn.fetch(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
            f"""
            with page as (
                select post.post_id, post.post_title, post.voc_type_code, post.visibility_code,
                       post.source_stage_code, post.source_detail_state_code,
                       post.source_draft_code, post.source_deleted_flag,
                       post.source_author_code, post.source_author_name,
                       post.source_company_code, post.source_company_name,
                       post.source_process_unit_code, post.source_process_unit_name,
                       post.source_sales_pool_code, post.source_sales_pool_name,
                       post.source_order_pool_code, post.source_sales_order_code,
                       post.source_sales_order_item_number, post.source_inspection_point_code,
                       post.source_customer_code, post.source_customer_name,
                       post.source_project_code, post.source_project_name,
                       post.source_system_code,
                       post.source_record_key,
                       post.corporate_entity_id, post.author_account_id, post.created_at,
                       case
                           when $1::text is null then 0
                           when lower(coalesce(post.post_title, '')) like '%' || lower($1) || '%' then 0
                           when post.post_id = any($6::uuid[]) then 1
                           else 2
                       end as search_priority,
                       count(*) over() as total_count
                  from source_post post
             where {source_post_state_visibility_sql("post", corporate_param=2, account_param=10, admin_param=11)}
               and {SOURCE_POST_READER_ELIGIBILITY_SQL.format(alias="post")}
               and (
                    $1::text is null
                    or post.post_title ilike '%' || $1 || '%'
                    or post.thread_group_key ilike '%' || $1 || '%'
                    or post.secondary_grouping_key ilike '%' || $1 || '%'
                    or concat_ws(' ',
                        post.source_stage_code,
                        post.source_detail_state_code,
                        post.source_draft_code,
                        post.source_deleted_flag,
                        post.source_author_code,
                        post.source_author_name,
                        post.source_company_code,
                        post.source_company_name,
                        post.source_process_unit_code,
                        post.source_process_unit_name,
                        post.source_sales_pool_code,
                        post.source_sales_pool_name,
                        post.source_order_pool_code,
                        post.source_sales_order_code,
                        post.source_sales_order_item_number,
                        post.source_inspection_point_code,
                        post.source_customer_code,
                        post.source_customer_name,
                        post.source_project_code,
                        post.source_project_name,
                        post.source_system_code,
                        post.source_record_key
                    ) ilike '%' || $1 || '%'
                    or replace(post.post_id::text, '-', '') ilike '%' || lower($1) || '%'
                    or (
                        char_length($1) >= 3
                        and (
                            similarity(replace(post.post_id::text, '-', ''), lower($1)) >= 0.78
                            or similarity(lower(coalesce(post.source_record_key, '')), lower($1)) >= 0.78
                            or word_similarity(lower($1), lower(post.post_title)) >= 0.45
                            or word_similarity(lower($1), lower(post.secondary_grouping_key)) >= 0.45
                            or word_similarity(
                                lower($1),
                                lower(concat_ws(' ',
                                    post.source_stage_code,
                                    post.source_detail_state_code,
                                    post.source_draft_code,
                                    post.source_deleted_flag,
                                    post.source_author_code,
                                    post.source_author_name,
                                    post.source_company_code,
                                    post.source_company_name,
                                    post.source_process_unit_code,
                                    post.source_process_unit_name,
                                    post.source_sales_pool_code,
                                    post.source_sales_pool_name,
                                    post.source_order_pool_code,
                                    post.source_sales_order_code,
                                    post.source_sales_order_item_number,
                                    post.source_inspection_point_code,
                                    post.source_customer_code,
                                    post.source_customer_name,
                                    post.source_project_code,
                                    post.source_project_name
                                ))
                            ) >= 0.45
                        )
                    )
                    or post.post_id = any($6::uuid[])
                    or exists (
                        select 1 from post_project_mention project
                         where project.post_id = post.post_id
                           and (project.project_name ilike '%' || $1 || '%'
                                or project.evidence_text ilike '%' || $1 || '%'
                                or project.ontology_iri ilike '%' || $1 || '%'
                                or (char_length($1) >= 3 and word_similarity(lower($1), lower(project.project_name)) >= 0.45))
                    )
                    or exists (
                        select 1 from post_summary_role role
                         where role.post_id = post.post_id
                           and (role.actor_name ilike '%' || $1 || '%'
                                or role.responsibility_text ilike '%' || $1 || '%'
                                or coalesce(role.affiliated_organization_name, '') ilike '%' || $1 || '%'
                                or (char_length($1) >= 3 and word_similarity(lower($1), lower(role.actor_name)) >= 0.45))
                    )
                    or exists (
                        select 1
                          from post_person_mention mention
                          join cataloged_person person on person.person_id = mention.person_id
                         where mention.post_id = post.post_id
                           and (
                               person.person_name ilike '%' || $1 || '%'
                               or (char_length($1) >= 3 and word_similarity(lower($1), lower(person.person_name)) >= 0.45)
                           )
                    )
                    or exists (
                        select 1 from post_summary_result summary
                         where summary.post_id = post.post_id
                           and summary.korean_summary ilike '%' || $1 || '%'
                    )
                    or exists (
                        select 1 from post_summary_event event
                         where event.post_id = post.post_id
                           and (event.event_text ilike '%' || $1 || '%'
                                or coalesce(event.evidence_text, '') ilike '%' || $1 || '%')
                    )
                    or exists (
                        select 1 from post_summary_event_clue clue
                         where clue.post_id = post.post_id
                           and (clue.clue_text ilike '%' || $1 || '%'
                                or coalesce(clue.target_text, '') ilike '%' || $1 || '%'
                                or coalesce(clue.normalized_value_text, '') ilike '%' || $1 || '%'
                                or clue.evidence_text ilike '%' || $1 || '%')
                    )
                    or exists (
                        select 1 from post_summary_five_w1h evidence
                         where evidence.post_id = post.post_id
                           and (evidence.value_text ilike '%' || $1 || '%'
                                or evidence.evidence_text ilike '%' || $1 || '%')
                    )
                    or exists (
                        select 1 from post_summary_quantitative_observation observation
                         where observation.post_id = post.post_id
                           and (observation.label_text ilike '%' || $1 || '%'
                                or observation.raw_value_text ilike '%' || $1 || '%'
                                or observation.evidence_text ilike '%' || $1 || '%'
                                or observation.qualifier_text ilike '%' || $1 || '%'
                                or observation.measurement_type_code ilike '%' || $1 || '%'
                                or observation.unit_code ilike '%' || $1 || '%'
                                or observation.value_numeric::text ilike '%' || $1 || '%'
                                or observation.quantity_numeric::text ilike '%' || $1 || '%')
                    )
                    or exists (
                        select 1 from post_summary_source_fact fact
                         where fact.post_id = post.post_id
                           and (fact.label_text ilike '%' || $1 || '%'
                                or fact.value_text ilike '%' || $1 || '%'
                                or coalesce(fact.normalized_value_text, '') ilike '%' || $1 || '%'
                                or fact.evidence_text ilike '%' || $1 || '%'
                                or fact.normalized_date::text ilike '%' || $1 || '%')
                    )
                    or exists (
                        select 1 from post_summary_semantic_relationship relation
                         where relation.post_id = post.post_id
                           and (relation.subject_name ilike '%' || $1 || '%'
                                or relation.predicate_code ilike '%' || $1 || '%'
                                or relation.object_name ilike '%' || $1 || '%'
                                or relation.evidence_text ilike '%' || $1 || '%')
                    )
                    or exists (
                        select 1 from corporate_entity customer
                         where customer.corporate_entity_id = post.corporate_entity_id
                           and (customer.entity_name ilike '%' || $1 || '%'
                                or customer.corporate_entity_code ilike '%' || $1 || '%')
                    )
                    or exists (
                        select 1 from process_unit process
                         where process.process_unit_id = post.process_unit_id
                           and (process.process_unit_name ilike '%' || $1 || '%'
                                or process.process_unit_code ilike '%' || $1 || '%')
                    )
                    or exists (
                        select 1 from user_account author
                         where author.user_account_id = post.author_account_id
                           and (author.display_name ilike '%' || $1 || '%'
                                or author.email_address ilike '%' || $1 || '%')
                    )
                    or exists (
                        select 1
                          from account_affiliation affiliation
                          join corporate_entity affiliated
                            on affiliated.corporate_entity_id = affiliation.corporate_entity_id
                         where affiliation.user_account_id = post.author_account_id
                           and (affiliated.entity_name ilike '%' || $1 || '%'
                                or affiliated.corporate_entity_code ilike '%' || $1 || '%')
                    )
               )
               and ($3::text[] is null or post.voc_type_code = any($3::text[]))
               and ($4::text[] is null or coalesce(upper(btrim(post.source_detail_state_code)), '') = any($4::text[]))
               and ($5::text is null or post.visibility_code = $5)
                 order by
                    search_priority asc,
                    case
                        when $1::text is not null and post.post_id = any($6::uuid[])
                        then array_position($6::uuid[], post.post_id)
                    end asc,
                    case when $9::text = 'title' then lower(coalesce(post.post_title, '')) end asc,
                    case when $9::text = 'oldest' then post.created_at end asc,
                    case when $9::text in ('newest', 'title') then post.created_at end desc,
                    post.post_id desc
                   offset $7
                   limit $8
            )
            select page.*,
                   case
                       when $1::text is not null
                            and strpos(lower(source_post_search_text(post.post_body)), lower($1)) > 0
                       then btrim(substring(
                           source_post_search_text(post.post_body)
                           from greatest(
                               1,
                               strpos(lower(source_post_search_text(post.post_body)), lower($1)) - 140
                           ) for 420
                       ))
                       else btrim(left(source_post_search_text(post.post_body), 420))
                   end as post_body_excerpt,
                   char_length(coalesce(post.post_body, '')) > 420 as post_body_truncated,
                   coalesce(projects.project_evidence, '[]'::json) as project_evidence
              from page
              join source_post post on post.post_id = page.post_id
              left join lateral (
                  select json_agg(
                             json_build_object(
                                 'project_key', project.project_key,
                                 'project_name', project.project_name,
                                 'evidence', project.evidence_text,
                                 'confidence', project.mention_confidence,
                                 'ontology_iri', project.ontology_iri,
                                 'ontology_label', 'Project',
                                 'extraction_method', project.extraction_method,
                                 'resolution_status', 'semantic_candidate',
                                 'provenance', 'post_project_mention.evidence_text'
                             )
                             order by project.mention_confidence desc, project.project_name, project.project_key
                         ) as project_evidence
                    from (
                        select project_key, project_name, evidence_text, mention_confidence,
                               ontology_iri, extraction_method
                          from post_project_mention
                         where post_id = page.post_id
                         order by mention_confidence desc, project_name, project_key
                         limit 5
                    ) project
              ) projects on true
             order by
                case when $1::text is not null then page.search_priority end asc,
                case
                    when $1::text is not null and page.search_priority = 1
                    then array_position($6::uuid[], page.post_id)
                end asc,
                case when $9::text = 'title' then lower(coalesce(page.post_title, '')) end asc,
                case when $9::text = 'oldest' then page.created_at end asc,
                case when $9::text in ('newest', 'title') then page.created_at end desc,
                page.post_id desc
            """,
            search_term,
            list(account.corporate_entity_ids),
            voc_type_codes,
            source_detail_state_codes,
            visibility.strip() if visibility and visibility.strip() else None,
            body_search_ids,
            offset,
            limit,
            sort,
            account.user_account_id,
            account.has_permission(_POST_ADMIN),
        )
        visible = [row for row in rows if _can_see_post(account, row)]
        labels = await _lookup_post_labels(conn, visible)
    total_count = int(rows[0]["total_count"]) if rows else 0
    return {
        "posts": [_serialize_post(row, labels) for row in visible],
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "voc_type_options": voc_type_options,
        "source_detail_state_options": source_detail_state_options,
        "visibility_options": visibility_options,
    }


@app.get("/api/posts/{post_id}")
async def read_post(
    post_id: str,
    as_of: str | None = None,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return one source_post, or 404 / 403 if it is missing or out of scope.

    ``as_of`` adds ``known_at`` when a ``source_post_revision`` covers that
    clock (ADR 0025). The live ``post_body`` stays the live row. A missing
    cover is omitted -- never a fabricated cutoff sentence. Next action:
    pass the analysis-run cutoff, then compare ``known_at`` with the live
    body before treating the live text as reconstructed evidence.
    """
    _require_post_read(account)
    as_of_clock = None
    if as_of is not None:
        try:
            as_of_clock = parse_as_of_clock(as_of)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "as_of must be an ISO-8601 timestamp. Use the run cutoff, "
                "then compare the known body with the live body.",
            ) from exc
    async with pool.acquire() as conn:
        # Safe SQL: the eligibility predicate is an immutable schema fragment; post id is bound.
        row = await conn.fetchrow(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
            "select post_id, post_title, post_body, voc_type_code, visibility_code, "
            "source_stage_code, source_detail_state_code, source_draft_code, source_deleted_flag, "
                "source_author_code, source_author_name, source_company_code, source_company_name, "
                "source_process_unit_code, source_process_unit_name, "
                "source_process_unit.process_unit_name as source_process_unit_catalog_name, "
                "source_sales_pool_code, source_sales_pool_name, "
                "source_order_pool_code, source_sales_order_code, "
                "source_sales_order_item_number, source_inspection_point_code, "
                "source_customer_code, source_customer_name, source_project_code, source_project_name, "
                "source_system_code, source_record_key, author_account_id, "
                "source_post.corporate_entity_id, source_post.created_at "
            "from source_post "
            "left join process_unit source_process_unit "
            "on source_process_unit.process_unit_id = source_post.process_unit_id "
            "and source_process_unit.corporate_entity_id = source_post.corporate_entity_id "
            f"where source_post.post_id = $1 and {SOURCE_POST_READER_ELIGIBILITY_SQL.format(alias='source_post')}",
            post_id,
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "post not found")
        if not _can_see_post(account, row):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not authorized to view this post")
        labels = await _lookup_post_labels(conn, [row])
        project_evidence = await _load_project_evidence(
            conn, post_id, row["source_project_code"], row["source_project_name"]
        )
        known_at = None
        if as_of_clock is not None:
            known_at = await fetch_known_at_revision(conn, post_id, as_of_clock)
    payload = {
        **_serialize_post(row, labels),
        "post_body": row["post_body"],
        "project_evidence": project_evidence,
    }
    if known_at is not None:
        payload["known_at"] = known_at
    return payload


@app.get("/api/posts/{post_id}/content")
async def read_post_content(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """Return persisted content evidence; never derive or invent reader-facing copy."""
    await _load_visible_post(post_id, account, pool)
    queue_event: tuple[str, str] | None = None
    summary_waiting_for_images = False
    async with pool.acquire() as conn:
        unit_rows = await conn.fetch(
            """
            select unit.unit_index, unit.unit_kind_code, unit.unit_label, unit.unit_text,
                   coalesce(structure.indent_level, 0) as indent_level,
                   structure.decision_source_code, structure.structure_confidence,
                   structure.evidence_text
              from post_content_unit unit
              left join post_content_unit_structure structure
                on structure.post_content_unit_id = unit.post_content_unit_id
             where unit.post_id = $1
             order by unit.unit_index
            """,
            post_id,
        )
        content_status = post_content_api_status(
            None,
            content_present=bool(unit_rows),
        )
        body_row = await conn.fetchrow(
            "select post_body from source_post where post_id = $1", post_id
        )
        raw_body = None if body_row is None else body_row["post_body"]
        if isinstance(raw_body, str) and raw_body.strip():
            content_present = bool(unit_rows)
            content_complete = await post_content_is_complete(
                conn,
                post_id,
                embedding_model_code=load_settings().embedding_model,
                require_structure=bool(
                    load_settings().orchestrator_base_url
                    and load_settings().orchestrator_api_key
                ),
            )
            async with conn.transaction():
                job = await ensure_post_content_job(
                    conn,
                    post_id,
                    raw_body,
                    content_complete=content_complete,
                )
            content_status = post_content_api_status(
                job.status_code,
                content_present=content_present,
            )
            if job.should_publish:
                queue_event = (job.post_id, job.source_body_sha256)
        rows = await conn.fetch(
            """
            select image.post_content_image_id, unit.unit_index, image.mime_type, image.description_status_code,
                   image.extracted_text, image.image_caption,
                   coalesce(
                       array_agg(tag.tag_text order by tag.tag_text)
                           filter (where tag.tag_text is not null),
                       '{}'::text[]
                   ) as tags
              from post_content_unit unit
              join post_content_image image
                on image.post_content_unit_id = unit.post_content_unit_id
              left join post_content_image_tag tag
                on tag.post_content_image_id = image.post_content_image_id
             where unit.post_id = $1
             group by image.post_content_image_id, unit.unit_index, image.mime_type, image.description_status_code,
                      image.extracted_text, image.image_caption
             order by unit.unit_index
            """,
            post_id,
        )
        region_rows = await conn.fetch(
            """
            select image.post_content_image_id, region.region_index,
                   region.x_ratio, region.y_ratio, region.width_ratio, region.height_ratio,
                   region.description_status_code, region.extracted_text, region.image_caption,
                   coalesce(
                       array_agg(tag.tag_text order by tag.tag_text)
                           filter (where tag.tag_text is not null),
                       '{}'::text[]
                   ) as tags
              from post_content_image image
              join post_content_image_region region
                on region.post_content_image_id = image.post_content_image_id
              left join post_content_image_region_tag tag
                on tag.post_content_image_region_id = region.post_content_image_region_id
             where image.post_content_image_id = any($1::uuid[])
             group by image.post_content_image_id, region.region_index,
                      region.x_ratio, region.y_ratio, region.width_ratio, region.height_ratio,
                      region.description_status_code, region.extracted_text, region.image_caption
             order by image.post_content_image_id, region.region_index
            """,
            [row["post_content_image_id"] for row in rows],
        ) if rows else []
    if queue_event is not None:
        await publish_post_content_event(
            valkey,
            post_id=queue_event[0],
            source_body_digest=queue_event[1],
        )
    regions_by_image: dict[str, list[dict[str, Any]]] = {}
    for row in region_rows:
        regions_by_image.setdefault(str(row["post_content_image_id"]), []).append(
            {
                "region_index": row["region_index"],
                "x_ratio": row["x_ratio"],
                "y_ratio": row["y_ratio"],
                "width_ratio": row["width_ratio"],
                "height_ratio": row["height_ratio"],
                "status_code": row["description_status_code"],
                "extracted_text": row["extracted_text"],
                "caption": row["image_caption"],
                "tags": list(row["tags"] or []),
            }
        )
    return {
        "status": content_status,
        "units": [
            {
                "unit_index": row["unit_index"],
                "unit_kind_code": row["unit_kind_code"],
                "unit_label": row["unit_label"],
                "unit_text": row["unit_text"],
                "indent_level": row["indent_level"],
                "indent_source_code": row["decision_source_code"] or "unresolved",
                "indent_confidence": float(row["structure_confidence"] or 0),
                "indent_evidence": row["evidence_text"] or "",
            }
            for row in unit_rows
        ],
        "images": [
            {
                "unit_index": row["unit_index"],
                "mime_type": row["mime_type"],
                "status_code": row["description_status_code"],
                "extracted_text": row["extracted_text"],
                "caption": row["image_caption"],
                "tags": list(row["tags"] or []),
                "regions": regions_by_image.get(str(row["post_content_image_id"]), []),
            }
            for row in rows
        ]
    }


async def _load_visible_post(
    post_id: str,
    account: CurrentAccount,
    pool: asyncpg.Pool,
    *,
    allow_writing: bool = False,
) -> asyncpg.Record:
    """Load one post the account may see, or raise 404 / 403.

    Analysis callers keep the default W-state rejection. Non-analysis actions
    such as an author's bookmark may explicitly read an authorized W row.
    """
    _require_post_read(account)
    async with pool.acquire() as conn:
        # Safe SQL: the eligibility predicate is an immutable schema fragment; post id is bound.
        row = await conn.fetchrow(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
            """
            select source_post.post_id, source_post.post_title, source_post.voc_type_code,
                   source_post.visibility_code, source_post.corporate_entity_id,
                   source_post.source_detail_state_code,
                   source_post.created_at, source_post.author_account_id,
                   source_post.source_process_unit_code, source_post.source_author_code,
                   source_post.source_company_code, source_post.source_customer_code,
                   source_post.source_project_code, source_post.source_sales_pool_code,
                   customer.corporate_entity_code
              from source_post
              left join corporate_entity customer
                on customer.corporate_entity_id = source_post.corporate_entity_id
             where source_post.post_id = $1
               and """
            f"{SOURCE_POST_READER_ELIGIBILITY_SQL.format(alias='source_post')}",
            post_id,
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "post not found")
    if not _can_see_post(account, row):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not authorized to view this post")
    if (
        not allow_writing
        and normalize_source_detail_state_code(row.get("source_detail_state_code"))
        == WRITING_SOURCE_DETAIL_STATE_CODE
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Writing-in-progress posts are not analysis targets.",
        )
    return row


async def _load_post_semantic_hints(conn: asyncpg.Connection, post_id: str) -> str:
    """Render author, business-unit, sales-pool, and customer hints without treating them as proof."""
    rows = await conn.fetch(
        """
        select author.user_account_id as author_account_id,
               author.display_name as author_name,
               post.source_author_code,
               post.source_author_name,
               post.source_company_code,
               post.source_company_name,
               source_company.entity_name as source_company_catalog_name,
               post.source_process_unit_code,
               post.source_process_unit_name,
               source_process_unit.process_unit_name as source_process_unit_catalog_name,
               post.source_sales_pool_code,
               post.source_sales_pool_name,
               post.source_order_pool_code,
               post.source_sales_order_code,
               post.source_sales_order_item_number,
               post.source_inspection_point_code,
               post.source_stage_code,
               post.source_detail_state_code,
               post.source_deleted_flag,
               post.source_customer_code,
               post.source_customer_name,
               source_customer.entity_name as source_customer_catalog_name,
               post.source_project_code,
               post.source_project_name,
               post.secondary_grouping_key as project_field,
               customer.entity_name as customer_name,
               affiliated.entity_name as author_affiliation_name
          from source_post post
          join user_account author on author.user_account_id = post.author_account_id
          left join corporate_entity customer on customer.corporate_entity_id = post.corporate_entity_id
          left join corporate_entity source_company
            on source_company.corporate_entity_code = nullif(btrim(post.source_company_code), '')
          left join process_unit source_process_unit
            on source_process_unit.process_unit_code = nullif(btrim(post.source_process_unit_code), '')
          left join corporate_entity source_customer
            on source_customer.corporate_entity_code = nullif(btrim(post.source_customer_code), '')
          left join account_affiliation account_aff
            on account_aff.user_account_id = post.author_account_id
          left join corporate_entity affiliated
            on affiliated.corporate_entity_id = account_aff.corporate_entity_id
         where post.post_id = $1
        """,
        post_id,
    )
    if not rows:
        return "no structured hints available"
    first = rows[0]
    source_context_present = any(
        first[field] is not None
        for field in (
            "source_author_code",
            "source_author_name",
            "source_company_code",
            "source_company_name",
            "source_process_unit_code",
            "source_process_unit_name",
            "source_sales_pool_code",
            "source_sales_pool_name",
            "source_order_pool_code",
            "source_sales_order_code",
            "source_sales_order_item_number",
            "source_inspection_point_code",
            "source_customer_code",
            "source_customer_name",
            "source_project_code",
            "source_project_name",
        )
    )
    source_author_name = first["source_author_name"]
    if source_author_name and source_author_name == first["source_author_code"]:
        source_author_name = None
    return format_semantic_hints(
        author_name=source_author_name or first["author_name"],
        author_account_id=str(first["author_account_id"]),
        author_account_name=first["author_name"],
        author_affiliations=(
            str(row["author_affiliation_name"])
            for row in rows
            if row["author_affiliation_name"]
        ),
        order_pool_code=first["source_sales_pool_code"],
        order_pool_name=first["source_sales_pool_name"],
        project_field=first["project_field"],
        customer_name=first["customer_name"],
        source_author_code=first["source_author_code"],
        source_author_name=source_author_name,
        source_company_code=first["source_company_code"],
        source_company_name=first["source_company_name"],
        source_company_catalog_name=first["source_company_catalog_name"],
        source_business_unit_code=first["source_process_unit_code"],
        source_process_unit_name=first["source_process_unit_name"],
        source_process_unit_catalog_name=first["source_process_unit_catalog_name"],
        source_sales_pool_code=first["source_sales_pool_code"],
        source_sales_pool_name=first["source_sales_pool_name"],
        source_order_pool_code=first["source_order_pool_code"],
        source_sales_order_code=first["source_sales_order_code"],
        source_sales_order_item_number=first["source_sales_order_item_number"],
        source_inspection_point_code=first["source_inspection_point_code"],
        source_stage_code=first["source_stage_code"],
        source_detail_state_code=first["source_detail_state_code"],
        source_deleted_flag=first["source_deleted_flag"],
        source_customer_code=first["source_customer_code"],
        source_customer_name=first["source_customer_name"],
        source_customer_catalog_name=first["source_customer_catalog_name"],
        source_project_code=first["source_project_code"],
        source_project_name=first["source_project_name"],
        source_context_present=source_context_present,
    )


async def _load_account_affiliation_hints(
    conn: asyncpg.Connection,
    account_ids: list[str],
    corporate_entity_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Load authorized account affiliations as non-binding Keyman context."""
    if not account_ids or not corporate_entity_ids:
        return {}
    rows = await conn.fetch(
        """
        select affiliation.user_account_id,
               entity.corporate_entity_id,
               entity.entity_name,
               process.process_unit_code,
               process.process_unit_name
          from account_affiliation affiliation
          join corporate_entity entity
            on entity.corporate_entity_id = affiliation.corporate_entity_id
          left join process_unit process
            on process.process_unit_id = affiliation.process_unit_id
         where affiliation.user_account_id = any($1::uuid[])
           and affiliation.corporate_entity_id = any($2::uuid[])
         order by entity.entity_name, process.process_unit_code
        """,
        account_ids,
        corporate_entity_ids,
    )
    affiliations: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        account_id = str(row["user_account_id"])
        affiliations.setdefault(account_id, []).append(
            {
                "corporate_entity_id": str(row["corporate_entity_id"]),
                "entity_name": row["entity_name"],
                "process_unit_code": row["process_unit_code"],
                "process_unit_name": row["process_unit_name"],
            }
        )
    return affiliations


async def _load_source_author_context(
    conn: asyncpg.Connection,
    post_id: str,
    corporate_entity_ids: list[str],
) -> dict[str, Any] | None:
    """Return source-author/account context without binding a cataloged person."""
    row = await conn.fetchrow(
        """
        select post.author_account_id,
               author.display_name as account_display_name,
               nullif(btrim(post.source_author_code), '') as source_author_code,
               nullif(btrim(post.source_author_name), '') as source_author_name
          from source_post post
          join user_account author on author.user_account_id = post.author_account_id
         where post.post_id = $1
        """,
        post_id,
    )
    if row is None:
        return None
    account_id = str(row["author_account_id"])
    affiliations = (
        await _load_account_affiliation_hints(conn, [account_id], corporate_entity_ids)
    ).get(account_id, [])
    source_author_name = row["source_author_name"]
    if source_author_name and source_author_name.casefold() == str(row["source_author_code"] or '').casefold():
        source_author_name = None
    return {
        "author_account_id": account_id,
        "account_display_name": row["account_display_name"],
        "source_author_code": row["source_author_code"],
        "source_author_name": source_author_name,
        "account_affiliations": affiliations,
        "resolution_status": (
            "our_side_context_only" if affiliations else "source_author_hint_only"
        ),
        "provenance": (
            "source_post.author_account_id/user_account.display_name/"
            "account_affiliation.corporate_entity_id/source_post.source_author_code/source_post.source_author_name"
        ),
    }


@app.get("/api/posts/{post_id}/keymen")
async def read_post_keymen(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """People mentioned on one visible post, with their N:N affiliations."""
    post = await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        keymen = await fetch_post_keymen(conn, post_id)
        source_author_context = await _load_source_author_context(
            conn, post_id, list(account.corporate_entity_ids)
        )
    return {
        "post_id": str(post["post_id"]),
        "keymen": keymen,
        "source_author_context": source_author_context,
    }


@app.get("/api/keymen/{person_id}/related")
async def read_related_keymen(
    person_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """RWR-ranked related nodes from one person, hiding unseen posts."""
    _require_post_read(account)
    async with pool.acquire() as conn:
        if not await person_exists(conn, person_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "person not found")
        visible_post_ids = await visible_mention_post_ids(conn, person_id, lambda row: _can_use_post_for_analysis(account, row))
        if not visible_post_ids:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not authorized to view this person")
        person = await conn.fetchrow(
            "select person_id, person_name, person_side_code from cataloged_person where person_id = $1",
            person_id,
        )
        related = await related_for_person(conn, person_id, visible_post_ids)
        role_history = await fetch_person_role_history(conn, person_id, visible_post_ids)
    return {
        "person_id": str(person["person_id"]),
        "person_name": person["person_name"],
        "person_side_code": person["person_side_code"],
        "related": related,
        "role_history": role_history,
    }


@app.get("/api/corporate-entities/{entity_id}/related")
async def read_related_corporate_entity(
    entity_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """RWR-ranked related nodes from one corporate entity, hiding unseen posts."""
    _require_post_read(account)
    async with pool.acquire() as conn:
        if not await corporate_entity_exists(conn, entity_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "corporate entity not found")
        visible_post_ids = await visible_affiliation_post_ids(
            conn, entity_id, lambda row: _can_use_post_for_analysis(account, row)
        )
        if not visible_post_ids:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not authorized to view this entity")
        entity = await conn.fetchrow(
            "select corporate_entity_id, entity_name from corporate_entity "
            "where corporate_entity_id = $1",
            entity_id,
        )
        related = await related_for_entity(conn, entity_id, visible_post_ids)
    return {
        "corporate_entity_id": str(entity["corporate_entity_id"]),
        "entity_name": entity["entity_name"],
        "related": related,
    }


@app.get("/api/teams/{team_id}/related")
async def read_related_team(
    team_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """RWR-ranked related nodes from one cataloged team, hiding unseen posts."""
    _require_post_read(account)
    async with pool.acquire() as conn:
        if not await team_exists(conn, team_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "team not found")
        visible_post_ids = await visible_team_mention_post_ids(
            conn, team_id, lambda row: _can_use_post_for_analysis(account, row)
        )
        if not visible_post_ids:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not authorized to view this team")
        team = await conn.fetchrow(
            "select team_id, team_name from cataloged_team where team_id = $1",
            team_id,
        )
        related = await related_for_team(conn, team_id, visible_post_ids)
    return {
        "team_id": str(team["team_id"]),
        "team_name": team["team_name"],
        "related": related,
    }


@app.get("/api/posts/{post_id}/counterparties")
async def read_post_counterparties(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Classified counterparty orgs for one visible post.

    A name that resolves to a cataloged ``corporate_entity`` carries
    that id so the popup can start the same related walk as an
    affiliate-tree org click. Unresolved names stay ``null``.
    """
    post = await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        counterparties = await fetch_post_counterparties(conn, post_id)
    return {
        "post_id": str(post["post_id"]),
        "counterparties": counterparties,
    }


@app.get("/api/posts/{post_id}/affiliate-tree")
async def read_post_affiliate_tree(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Ancestor forest of every organization this post's Keymen touch.

    Resolved affiliations walk ``corporate_entity.parent_entity_id``.
    Unresolved names stay as their own roots -- a missing hierarchy
    match is not a guessed parent.
    """
    post = await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        trees = await fetch_affiliate_forest(conn, post_id)
    return {"post_id": str(post["post_id"]), "trees": trees}


@app.get("/api/posts/{post_id}/voc-evidence")
async def read_post_voc_evidence(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """VOC type label plus extractive excerpts that name classified orgs."""
    post = await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        return await fetch_voc_evidence(conn, post_id, post["voc_type_code"])


@app.post("/api/posts/{post_id}/verify-relations")
async def verify_post_entity_relationships(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """Checks this post's `verify_pending` counterparty relationships
    (entity_relationship_classification's LLM output) against external
    web search (relation_verification.py) and persists the outcome, so a
    hallucinated organization/relationship doesn't sit indistinguishable
    from a corroborated one -- see ADR 0005. Gated by post_admin, not
    post_read: a real external-search-call write action, same discipline
    as extract-keymen.
    """
    _require_post_admin(account)
    post = await _load_visible_post(post_id, account, pool)
    client = _relation_verification_client()
    if not client.available:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Relation verification is unavailable: set SEARXNG_BASE_URL",
        )
    async with pool.acquire() as conn:
        try:
            verified = await verify_post_relations(
                conn,
                client,
                post_id,
                visible_corporate_entity_ids=account.corporate_entity_ids,
            )
        except (HttpClientError, OSError) as exc:
            # verify_post_relations() deliberately raises on a failed search
            # (a failed search is not "searched and found nothing" -- see
            # its docstring); this is the one caller, so it is the right
            # place to turn that into a clean 503 instead of a raw 500.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Relation verification is unavailable: the search provider did not respond",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - provider boundary is fail-closed.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Relation verification is unavailable: the search provider did not respond",
            ) from exc
    await publish_activity_event(
        valkey,
        post_id,
        "relations_verified",
        account.user_account_id,
        f"Relations verified: {len(verified)} counterparty relationship(s) checked",
    )
    return {
        "post_id": str(post["post_id"]),
        "verified": [
            {
                "counterparty_entity_name": row.counterparty_entity_name,
                "verification_status_code": row.verification_status_code,
                "verification_evidence_url": row.verification_evidence_url,
                "verification_evidence_post_id": row.verification_evidence_post_id,
            }
            for row in verified
        ],
    }


@app.post("/api/posts/{post_id}/extract-keymen")
async def extract_post_keymen(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """Runs Keyman extraction over a post's own title+body and persists the
    result (cataloged_person / person_affiliation / post_person_mention /
    knowledge_graph_edge), then classifies each affiliated organization's
    relationship to the post author's org (post_counterparty_entity).
    Gated by post_admin, not post_read: this is a write action with a
    real LLM-call cost, not a read.
    """
    _require_post_admin(account)
    post = await _load_visible_post(post_id, account, pool)
    post_metadata = build_post_llm_metadata(post_id, post)
    with use_llm_metadata(post_metadata):
        keyman_client = _keyman_extraction_client()
        if not keyman_client.available:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Keymen extraction is unavailable: set ORCHESTRATOR_BASE_URL / ORCHESTRATOR_API_KEY",
            )
        relationship_client = _entity_relationship_client()
        async with pool.acquire() as conn:
            body_row = await conn.fetchrow("select post_body from source_post where post_id = $1", post_id)
            raw_body = "" if body_row is None else body_row["post_body"]
            # HTML/base64-image content must never reach an LLM prompt raw --
            # tags dilute the model's attention and a base64 payload sent as
            # literal text either blows the token budget or is silently
            # ignored (see lineageweave/post_content_normalization.py).
            context_hints = await _load_post_semantic_hints(conn, post_id)
            try:
                post_body = (
                    await asyncio.to_thread(normalize_post_body, raw_body, _vision_client())
                ).text
                mentions = await ingest_post_keymen(
                    conn,
                    keyman_client,
                    post_id,
                    post["post_title"],
                    post_body,
                    resolution_client=_organization_name_resolution_client(),
                    verification_client=_relation_verification_client(),
                    hierarchy_inference_client=_corporate_hierarchy_inference_client(),
                    context_hints=context_hints,
                    persist_graph=False,
                )
            except (HttpClientError, KeyError, OSError, TypeError, ValueError, RuntimeError) as exc:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Keymen extraction is unavailable: contextual-orchestrator or corroboration provider returned no complete evidence object",
                ) from exc
            except Exception as exc:  # noqa: BLE001 - provider boundary is fail-closed.
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Keymen extraction is unavailable: contextual-orchestrator or corroboration provider returned no complete evidence object",
                ) from exc
            # Live bug (2026-08-19): an organization affiliated ONLY with an
            # our_side person (our own factory, our own affiliate) got fed
            # into the counterparty-relationship classifier the same as any
            # external org -- forced to pick from six codes that all assume
            # an external counterparty, it had no correct answer and landed
            # on the closest wrong one (typically "Partner"). Only classify
            # organizations a counterparty-side mention actually names.
            organization_names = sorted(
                {
                    name
                    for mention in mentions
                    if mention.person_side_code == COUNTERPARTY
                    for name in mention.affiliated_organization_names
                }
            )
            try:
                relationships = await ingest_post_entity_relationships(
                    conn, relationship_client, post_id, post["post_title"], post_body, organization_names
                )
            except (HttpClientError, KeyError, OSError, TypeError, ValueError, RuntimeError) as exc:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Keymen extraction is unavailable: contextual-orchestrator or corroboration provider returned no complete evidence object",
                ) from exc
            except Exception as exc:  # noqa: BLE001 - provider boundary is fail-closed.
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Keymen extraction is unavailable: contextual-orchestrator or corroboration provider returned no complete evidence object",
                ) from exc
            async with conn.transaction():
                await persist_edges_for_post(conn, post_id)
    await publish_activity_event(
        valkey,
        post_id,
        "keymen_extracted",
        account.user_account_id,
        f"Keymen extracted: {len(mentions)} mention(s) found",
    )
    return {
        "post_id": str(post["post_id"]),
        "extracted_count": len(mentions),
        "mentions": [
            {
                "person_name": mention.person_name,
                "person_side_code": mention.person_side_code,
                "affiliated_organization_names": list(mention.affiliated_organization_names),
                "job_title": mention.job_title,
            }
            for mention in mentions
        ],
        "counterparties": [
            {
                "organization_name": relationship.organization_name,
                "relationship_type_code": relationship.relationship_type_code,
            }
            for relationship in relationships
        ],
    }


@app.get("/api/posts/{post_id}/lineage")
async def read_post_lineage(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """The Event Lineage panel's data: this post's directly (thread-)linked
    posts and its indirectly (shared-Keyman/organization) linked posts,
    kept as two distinguishable lists -- not merged into one, since they
    are different claims about *why* two posts are related. ABAC-filtered
    per candidate the same way every other endpoint here is.
    """
    await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        linked = await find_linked_post_ids(conn, post_id)
        candidate_ids = linked.direct | linked.indirect
        rows = {}
        if candidate_ids:
            # Safe SQL: the eligibility predicate is an immutable schema fragment; candidate ids are bound.
            fetched = await conn.fetch(  # nosemgrep: python.lang.security.audit.sqli.asyncpg-sqli.asyncpg-sqli
                "select post_id, post_title, visibility_code, corporate_entity_id, "
                "author_account_id, source_detail_state_code, "
                "btrim(left(source_post_search_text(post_body), 420)) as post_body_excerpt, "
                "char_length(coalesce(post_body, '')) > 420 as post_body_truncated "
                f"from source_post where post_id = any($1::uuid[]) and {SOURCE_POST_ELIGIBILITY_SQL.format(alias='source_post')}",
                list(candidate_ids),
            )
            rows = {str(row["post_id"]): row for row in fetched}

    def _visible_summaries(ids: frozenset[str]) -> list[dict[str, Any]]:
        return [
            {
                "post_id": post_id_,
                "post_title": rows[post_id_]["post_title"],
                "post_body_excerpt": rows[post_id_].get("post_body_excerpt"),
                "post_body_truncated": rows[post_id_].get("post_body_truncated", False),
            }
            for post_id_ in ids
            if post_id_ in rows and _can_use_post_for_analysis(account, rows[post_id_])
        ]

    return {
        "post_id": post_id,
        "direct": _visible_summaries(linked.direct),
        "indirect": _visible_summaries(linked.indirect),
    }


@app.get("/api/posts/{post_id}/knowledge-graph")
async def read_post_knowledge_graph(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return the authorized post-scoped KG projection for visualization."""
    await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        return await post_knowledge_graph(conn, post_id)


@app.get("/api/posts/{post_id}/evaluation")
async def read_post_evaluation(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Persisted IRT responses for this post (ADR 0003 slice 2)."""
    await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        rows = await fetch_post_evaluation(conn, post_id)
    return {
        "post_id": post_id,
        "rubric_version": RUBRIC_VERSION,
        "responses": [
            {
                "criterion_code": row.criterion_code,
                "criterion_label": row.criterion_label,
                "response_category": row.response_category,
                "rubric_version": row.rubric_version,
            }
            for row in rows
        ],
    }


@app.post("/api/posts/{post_id}/evaluate")
async def evaluate_post(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """LLM-as-a-Judge a post through fast-mlsirm and persist the IRT row.

    Gated by post_admin: a real LLM-call write, same discipline as
    extract-keymen. Null channel is 503, never a fabricated score.
    """
    _require_post_admin(account)
    post = await _load_visible_post(post_id, account, pool)
    post_metadata = build_post_llm_metadata(post_id, post)
    with use_llm_metadata(post_metadata):
        client = _post_evaluation_client()
        if not client.available:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Post evaluation is unavailable: set ORCHESTRATOR_BASE_URL / ORCHESTRATOR_API_KEY",
            )
        async with pool.acquire() as conn:
            body_row = await conn.fetchrow("select post_body from source_post where post_id = $1", post_id)
        try:
            normalized_body = (
                await asyncio.to_thread(
                    normalize_post_body,
                    "" if body_row is None else body_row["post_body"],
                    _vision_client(),
                )
            ).text
            async with pool.acquire() as conn:
                rows = await ingest_post_evaluation(
                    conn, client, post_id, post["post_title"], normalized_body
                )
        except (HttpClientError, KeyError, OSError, TypeError, ValueError, RuntimeError) as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Post evaluation is unavailable: contextual-orchestrator returned no complete evidence object",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - provider boundary is fail-closed.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Post evaluation is unavailable: contextual-orchestrator returned no complete evidence object",
            ) from exc
    await publish_activity_event(
        valkey,
        post_id,
        "post_evaluated",
        account.user_account_id,
        f"Post evaluated: {len(rows)} rubric criterion response(s)",
    )
    return {
        "post_id": str(post["post_id"]),
        "rubric_version": RUBRIC_VERSION,
        "responses": [
            {
                "criterion_code": row.criterion_code,
                "criterion_label": row.criterion_label,
                "response_category": row.response_category,
                "rubric_version": row.rubric_version,
            }
            for row in rows
        ],
    }


@app.get("/api/reports/compare/{period_code}")
async def compare_period_groupings(
    period_code: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """PU / corp / thread scores for one period on the shared metric."""
    _require_post_read(account)
    try:
        parse_period_code(period_code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    async with pool.acquire() as conn:
        rows = await fetch_period_comparison(conn, period_code)
        demo_entity_ids: set[str] = set()
        if rows and await has_real_source_context(conn, list(account.corporate_entity_ids)):
            demo_entity_ids = await fetch_demo_corporate_entity_ids(conn)
    visible: list[dict[str, Any]] = []
    for row in rows:
        members = [
            member
            for member in row["members"]
            if _can_use_post_for_analysis(account, member)
            and not _is_synthetic_demo_member(member, demo_entity_ids)
        ]
        if not members:
            continue
        visible.append({**row, "members": [], "post_count": len(members)})
    return {"period_code": period_code, "groupings": visible}


@app.get("/api/reports/{grouping_kind}")
async def list_period_reports(
    grouping_kind: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Available calibrated periods for one grouping kind (FIPC trend)."""
    _require_post_read(account)
    if grouping_kind not in GROUPING_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown grouping_kind")
    async with pool.acquire() as conn:
        summaries = await list_period_report_summaries(conn, grouping_kind)
        demo_entity_ids: set[str] = set()
        if summaries and await has_real_source_context(conn, list(account.corporate_entity_ids)):
            demo_entity_ids = await fetch_demo_corporate_entity_ids(conn)
    visible: list[dict[str, Any]] = []
    for summary in summaries:
        members = [
            member
            for member in summary["members"]
            if _can_use_post_for_analysis(account, member)
            and not _is_synthetic_demo_member(member, demo_entity_ids)
        ]
        if not members:
            continue
        visible.append({**summary, "members": [], "post_count": len(members)})
    return {"grouping_kind": grouping_kind, "periods": visible}


@app.get("/api/reports/{grouping_kind}/{period_code}")
async def read_period_reports(
    grouping_kind: str,
    period_code: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Calibrated IRT scores for one grouping kind and calendar period."""
    _require_post_read(account)
    if grouping_kind not in GROUPING_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown grouping_kind")
    try:
        parse_period_code(period_code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    async with pool.acquire() as conn:
        reports = await fetch_period_reports(conn, grouping_kind, period_code)
        demo_entity_ids: set[str] = set()
        if reports and await has_real_source_context(conn, list(account.corporate_entity_ids)):
            demo_entity_ids = await fetch_demo_corporate_entity_ids(conn)
    visible: list[dict[str, Any]] = []
    for report in reports:
        members = [
            member
            for member in report["members"]
            if _can_use_post_for_analysis(account, member)
            and not _is_synthetic_demo_member(member, demo_entity_ids)
        ]
        if not members:
            continue
        leftover_pairs = [
            pair
            for pair in report.get("leftover_pairs", [])
            if _can_use_post_for_analysis(account, pair)
            and not _is_synthetic_demo_member(pair, demo_entity_ids)
        ]
        members = [
            {
                key: value
                for key, value in member.items()
                if key
                not in {
                    "visibility_code",
                    "corporate_entity_id",
                    "author_account_id",
                    "source_detail_state_code",
                    "has_real_source_context",
                }
            }
            for member in members
        ]
        leftover_pairs = [
            {
                key: value
                for key, value in pair.items()
                if key
                not in {
                    "visibility_code",
                    "corporate_entity_id",
                    "author_account_id",
                    "source_detail_state_code",
                    "has_real_source_context",
                }
            }
            for pair in leftover_pairs
        ]
        visible.append(
            {**report, "members": members, "leftover_pairs": leftover_pairs, "post_count": len(members)}
        )
    return {"grouping_kind": grouping_kind, "period_code": period_code, "reports": visible}


@app.post("/api/reports/{grouping_kind}/{period_code}/rebuild")
async def rebuild_period_report_endpoint(
    grouping_kind: str,
    period_code: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Refit or FIPC-score every group in the period. post_admin only."""
    _require_post_admin(account)
    if grouping_kind not in GROUPING_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown grouping_kind")
    try:
        parse_period_code(period_code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    async with pool.acquire() as conn:
        async with conn.transaction():
            reports = await rebuild_period_reports(conn, grouping_kind, period_code)
    return {
        "grouping_kind": grouping_kind,
        "period_code": period_code,
        "group_count": len(reports),
        "default_period": iso_week_period(),
    }


@app.get("/api/posts/{post_id}/summary")
async def read_post_summary(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """A Korean summary, key events, and R&R for the popup.

    Returns a persisted row when one exists so a seeded demo stack is
    not empty without a live LLM. Otherwise derives through the
    orchestrator and stores the result. Missing both is 503 -- never a
    fabricated summary.
    """
    post = await _load_visible_post(post_id, account, pool)
    post_metadata = build_post_llm_metadata(post_id, post)
    queue_event: tuple[str, str] | None = None
    summary_waiting_for_images = False
    async with pool.acquire() as conn:
        body_row = await conn.fetchrow(
            "select post_body from source_post where post_id = $1", post_id
        )
        try:
            raw_body = require_summary_source_body(
                None if body_row is None else body_row["post_body"]
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        stored = await fetch_persisted_summary(conn, post_id)
        if stored is not None:
            return stored
        stale = await fetch_persisted_summary(conn, post_id, allow_stale=True)
        image_body = post_body_has_images(raw_body)
        if image_body:
            content_complete = await post_content_is_complete(
                conn,
                post_id,
                embedding_model_code=load_settings().embedding_model,
                require_structure=bool(
                    load_settings().orchestrator_base_url
                    and load_settings().orchestrator_api_key
                ),
            )
            async with conn.transaction():
                job = await ensure_post_content_job(
                    conn,
                    post_id,
                    raw_body,
                    content_complete=content_complete,
                )
            if job.should_publish:
                queue_event = (job.post_id, job.source_body_sha256)
            summary_waiting_for_images = not await post_content_summary_is_ready(conn, post_id)
            if summary_waiting_for_images and queue_event is not None:
                await publish_post_content_event(
                    valkey,
                    post_id=queue_event[0],
                    source_body_digest=queue_event[1],
                )
                queue_event = None
            if summary_waiting_for_images:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Post summary is unavailable: image evidence is still being processed",
                )
        with use_llm_metadata(post_metadata):
            client = _post_summary_client()
            if not client.available:
                if stale is not None and not image_body:
                    return stale
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Post summary is unavailable: set ORCHESTRATOR_BASE_URL / ORCHESTRATOR_API_KEY",
                )
            context_hints = await _load_post_semantic_hints(conn, post_id)
            summarize_with_hints = getattr(client, "summarize_with_hints", None)
            try:
                if image_body:
                    normalized_body = await fetch_post_summary_source(conn, post_id)
                    if not normalized_body:
                        raise ValueError("persisted post content is not available")
                else:
                    normalized_body = (
                        await asyncio.to_thread(normalize_post_body, raw_body)
                    ).text
                if callable(summarize_with_hints):
                    summary = await asyncio.to_thread(
                        summarize_with_hints, post["post_title"], normalized_body, context_hints
                    )
                else:
                    summary = await asyncio.to_thread(client.summarize, post["post_title"], normalized_body)
            except (HttpClientError, KeyError, OSError, TypeError, ValueError) as exc:
                if stale is not None and not image_body:
                    return stale
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Post summary is unavailable: contextual-orchestrator returned no complete evidence object",
                ) from exc
            except Exception as exc:  # noqa: BLE001 - provider boundary is fail-closed.
                if stale is not None and not image_body:
                    return stale
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Post summary is unavailable: contextual-orchestrator returned no complete evidence object",
                ) from exc
            try:
                payload = await persist_post_summary(
                    conn,
                    post_id,
                    summary,
                    post_body=normalized_body,
                    resolution_client=_organization_name_resolution_client(),
                    hierarchy_inference_client=_corporate_hierarchy_inference_client(),
                    verification_client=_relation_verification_client(),
                )
            except Exception as exc:  # noqa: BLE001 - provider boundary is fail-closed.
                if stale is not None and not image_body:
                    return stale
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Post summary is unavailable: contextual-orchestrator or corroboration provider returned no complete evidence object",
                ) from exc
        if not image_body:
            content_complete = await post_content_is_complete(
                conn,
                post_id,
                embedding_model_code=load_settings().embedding_model,
                require_structure=bool(
                    load_settings().orchestrator_base_url
                    and load_settings().orchestrator_api_key
                ),
            )
            async with conn.transaction():
                job = await ensure_post_content_job(
                    conn,
                    post_id,
                    raw_body,
                    content_complete=content_complete,
                )
            if job.should_publish:
                queue_event = (job.post_id, job.source_body_sha256)
    if queue_event is not None:
        await publish_post_content_event(
            valkey,
            post_id=queue_event[0],
            source_body_digest=queue_event[1],
        )
    return payload


@app.get("/api/posts/{post_id}/five-w1h")
async def read_post_five_w1h(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return an evidence-only 5W1H projection for an authorized post."""
    await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        return await load_five_w1h_slots(
            conn,
            post_id,
            lambda row: _can_use_post_for_analysis(account, row),
        )


class ChatRequest(BaseModel):
    """JSON body for ``POST /api/posts/{post_id}/chat``."""

    question: str


class GlobalAskRequest(BaseModel):
    """JSON body for the reader's source-grounded Global Ask Agent."""

    question: str
    conversation_id: UUID | None = None


@app.get("/api/posts/{post_id}/chat")
async def read_post_chat(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Stored Ask exchanges for this post.

    Seeded fixture answers (and any later live persist) so the popup is
    not an empty Ask box when the orchestrator is off. Missing rows are
    an empty list, not a fabricated transcript.
    """
    await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        exchanges = await fetch_persisted_chats(conn, post_id)
    return {"post_id": post_id, "exchanges": exchanges}


@app.post("/api/posts/{post_id}/chat")
async def chat_about_post(
    post_id: str,
    request: ChatRequest,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """In-popup chat: answers `request.question` using this post's own
    content plus its Event-Lineage-linked posts (direct and Knowledge-
    Graph-indirect) as context, and returns which source post(s) the
    answer drew from -- the sliding evidence panel's citation data.

    A persisted (seeded or previously live) row is returned first so
    Ask works on the demo stack without an orchestrator. Live
    reason-and-cite still runs only when no stored match exists and
    the orchestrator is configured -- never a fabricated reply.
    """
    question = request.question.strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "question is required")
    post = await _load_visible_post(post_id, account, pool)
    post_metadata = build_post_llm_metadata(post_id, post)
    async with pool.acquire() as conn:
        stored = await fetch_persisted_chat(conn, post_id, question)
        if stored is not None:
            source_ids = [post_id]
            source_ids.extend(cid for cid in stored["cited_post_ids"] if cid != post_id)
            return {
                "post_id": post_id,
                "answer_text": stored["answer_text"],
                "cited_post_ids": stored["cited_post_ids"],
                "cited_posts": stored["cited_posts"],
                "source_post_ids": source_ids,
            }
        with use_llm_metadata(post_metadata):
            client = _post_chat_client()
            if not client.available:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Post chat is unavailable: set ORCHESTRATOR_BASE_URL / ORCHESTRATOR_API_KEY",
                )
            sources = await gather_chat_sources(
                conn, post_id, lambda row: _can_use_post_for_analysis(account, row), vision_client=_vision_client()
            )
    try:
        with use_llm_metadata(post_metadata):
            answer = await asyncio.to_thread(client.answer, question, sources)
    except (HttpClientError, KeyError, OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Post chat is unavailable: contextual-orchestrator returned no complete evidence object",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - provider boundary is fail-closed.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Post chat is unavailable: contextual-orchestrator returned no complete evidence object",
        ) from exc
    cited_ids = list(answer.cited_post_ids)
    async with pool.acquire() as conn:
        await persist_post_chat(conn, post_id, question, answer.answer_text, cited_ids)
    await publish_activity_event(
        valkey,
        post_id,
        "chat_answered",
        account.user_account_id,
        f"Chat answered: {question}",
    )
    return {
        "post_id": post_id,
        "answer_text": answer.answer_text,
        "cited_post_ids": cited_ids,
        "cited_posts": cited_post_summaries(sources, cited_ids),
        "source_post_ids": [source.post_id for source in sources],
    }


@app.get("/api/ask/conversations")
async def read_ask_conversations(
    limit: int = Query(50, ge=1, le=50),
    before_updated_at: datetime | None = Query(None),
    before_conversation_id: UUID | None = Query(None),
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return only the authenticated account's Global Ask conversations."""
    _require_post_read(account)
    async with pool.acquire() as conn:
        if (before_updated_at is None) != (before_conversation_id is None):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "before_updated_at and before_conversation_id must be provided together",
            )
        return await list_conversations(
            conn,
            account.user_account_id,
            limit=limit,
            before_updated_at=before_updated_at,
            before_conversation_id=before_conversation_id,
        )


@app.get("/api/ask/conversations/{conversation_id}")
async def read_ask_conversation(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=50),
    before_turn: int | None = Query(None, ge=1),
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return one owned transcript with currently authorized evidence."""
    _require_post_read(account)
    async with pool.acquire() as conn:
        conversation = await fetch_conversation(
            conn,
            account.user_account_id,
            conversation_id,
            lambda row: _can_use_post_for_analysis(account, row),
            turn_limit=limit,
            before_turn_ordinal=before_turn,
        )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return conversation


@app.post("/api/ask")
async def ask_agent(
    request: GlobalAskRequest,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Answer a reader question from authorized post and graph evidence."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "question is required")
    _require_post_read(account)
    async with pool.acquire() as conn:
        if request.conversation_id is not None and not await conversation_exists(
            conn, account.user_account_id, request.conversation_id
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    client = _post_chat_client()
    if not client.available:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Ask Agent is unavailable: set ORCHESTRATOR_BASE_URL / ORCHESTRATOR_API_KEY",
        )
    async with pool.acquire() as conn:
        sources = await gather_global_chat_sources(
            conn,
            lambda row: _can_use_post_for_analysis(account, row),
            account.corporate_entity_ids,
            question=question,
        )
    if not sources:
        response: dict[str, Any] = {
            "answer_text": "",
            "cited_post_ids": [],
            "cited_posts": [],
            "source_post_ids": [],
            "cited_post_evidence": [],
            "next_action": "No authorized source posts are available for this question.",
        }
    else:
        try:
            answer = await asyncio.to_thread(client.answer, question, sources)
        except (HttpClientError, KeyError, OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Ask Agent is unavailable: contextual-orchestrator returned no complete evidence object",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - provider boundary is fail-closed.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Ask Agent is unavailable: contextual-orchestrator returned no complete evidence object",
            ) from exc
        cited_ids = list(answer.cited_post_ids)
        response = {
            "answer_text": answer.answer_text,
            "cited_post_ids": cited_ids,
            "cited_posts": cited_post_summaries(sources, cited_ids),
            "cited_post_evidence": cited_post_evidence(sources, cited_ids),
            "source_post_ids": [source.post_id for source in sources],
        }
    async with pool.acquire() as conn:
        try:
            persisted_conversation_id = await persist_turn(
                conn,
                account.user_account_id,
                request.conversation_id,
                question,
                response["answer_text"],
                response.get("next_action"),
                response["source_post_ids"],
                response["cited_post_ids"],
                response["cited_post_evidence"],
            )
        except GlobalAskConversationNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found") from exc
    response["conversation_id"] = str(persisted_conversation_id)
    return response


class PostBookmarkRequest(BaseModel):
    bookmarked: bool


@app.get("/api/posts/{post_id}/bookmark")
async def read_post_bookmark(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    await _load_visible_post(post_id, account, pool, allow_writing=True)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "select 1 from post_bookmark where user_account_id = $1 and post_id = $2",
            account.user_account_id,
            post_id,
        )
    return {"post_id": post_id, "bookmarked": row is not None}


@app.post("/api/posts/{post_id}/bookmark")
async def write_post_bookmark(
    post_id: str,
    request: PostBookmarkRequest,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    await _load_visible_post(post_id, account, pool, allow_writing=True)
    async with pool.acquire() as conn:
        if request.bookmarked:
            await conn.execute(
                """
                insert into post_bookmark (user_account_id, post_id)
                values ($1, $2)
                on conflict (user_account_id, post_id) do nothing
                """,
                account.user_account_id,
                post_id,
            )
        else:
            await conn.execute(
                "delete from post_bookmark where user_account_id = $1 and post_id = $2",
                account.user_account_id,
                post_id,
            )
    return {"post_id": post_id, "bookmarked": request.bookmarked}


@app.get("/api/posts/{post_id}/tickets")
async def read_post_tickets(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """List issue tickets on one visible post. Read-only, so post_read
    is enough -- same gate as every other post-scoped GET here.
    """
    await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        tickets = await list_tickets_for_post(conn, post_id)
    return {"post_id": post_id, "tickets": tickets}


class CreateTicketRequest(BaseModel):
    """JSON body for ``POST /api/posts/{post_id}/tickets``."""

    ticket_title: str
    ticket_status_code: str
    assigned_account_id: str | None = None
    # Manual calendar/to-do date, e.g. YYYY-MM-DD. Set automatically instead
    # by POST /api/posts/{post_id}/derive-commitment when the LLM should
    # decide it.
    due_date: str | None = None


@app.post("/api/posts/{post_id}/tickets", status_code=status.HTTP_201_CREATED)
async def create_post_ticket(
    post_id: str,
    request: CreateTicketRequest,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """Create an issue ticket on a visible post. post_admin-gated: opening
    a ticket is a write action, same discipline as extract-keymen.
    """
    _require_post_admin(account)
    await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        try:
            ticket = await create_ticket(
                conn,
                post_id,
                request.ticket_title,
                request.ticket_status_code,
                request.assigned_account_id,
                due_date=request.due_date,
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"ticket_status_code {request.ticket_status_code!r} is not a valid ticket_status lookup code",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"due_date {request.due_date!r} is not a valid YYYY-MM-DD date",
            ) from exc
    await publish_activity_event(
        valkey,
        post_id,
        "ticket_created",
        account.user_account_id,
        ticket_created_summary(request.ticket_title),
    )
    return ticket


class UpdateTicketRequest(BaseModel):
    """JSON body for ``PATCH /api/tickets/{issue_ticket_id}``.

    ``assigned_account_id`` left unset means "don't touch it";
    ``clear_assignment=True`` explicitly unassigns. Both are distinct,
    expressible outcomes a partial-update endpoint needs.
    """

    ticket_status_code: str | None = None
    assigned_account_id: str | None = None
    clear_assignment: bool = False


@app.patch("/api/tickets/{issue_ticket_id}")
async def patch_ticket(
    issue_ticket_id: str,
    request: UpdateTicketRequest,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """Update a ticket's status and/or assignee. post_admin-gated. The
    ABAC check runs against the ticket's OWNING post, resolved first --
    a ticket has no visibility_code of its own, it inherits its post's.
    """
    _require_post_admin(account)
    async with pool.acquire() as conn:
        post_id = await fetch_ticket_post_id(conn, issue_ticket_id)
        if post_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "ticket not found")
    await _load_visible_post(post_id, account, pool)
    async with pool.acquire() as conn:
        try:
            ticket = await update_ticket(
                conn,
                issue_ticket_id,
                request.ticket_status_code,
                request.assigned_account_id,
                request.clear_assignment,
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"ticket_status_code {request.ticket_status_code!r} is not a valid ticket_status lookup code",
            ) from exc
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ticket not found")
    if request.ticket_status_code is not None:
        await publish_activity_event(
            valkey,
            post_id,
            "ticket_status_changed",
            account.user_account_id,
            ticket_status_changed_summary(
                ticket.get("ticket_status_label") or request.ticket_status_code
            ),
        )
    return ticket


@app.get("/api/posts/{post_id}/activity")
async def read_post_activity(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """The post's activity feed, read straight off its Valkey stream
    (``XREVRANGE``) -- newest first. Read-only, so post_read is enough.
    """
    await _load_visible_post(post_id, account, pool)
    events = await read_activity_events(valkey, post_id)
    return {"post_id": post_id, "events": events}


@app.post("/api/posts/{post_id}/derive-commitment")
async def derive_post_commitment(
    post_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """LLM-derive a customer commitment (if any) from a post's own text,
    and -- when found -- register it as an issue_ticket with a due_date,
    which is what makes it show up on GET /api/calendar. post_admin-gated:
    a real LLM-call write action, same discipline as extract-keymen.
    `has_commitment: false` is a normal 200 response, not an error --
    most posts genuinely have no commitment in them.
    """
    _require_post_admin(account)
    post = await _load_visible_post(post_id, account, pool)
    post_metadata = build_post_llm_metadata(post_id, post)
    with use_llm_metadata(post_metadata):
        client = _commitment_extraction_client()
        if not client.available:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Commitment derivation is unavailable: set ORCHESTRATOR_BASE_URL / ORCHESTRATOR_API_KEY",
            )
        async with pool.acquire() as conn:
            body_row = await conn.fetchrow("select post_body from source_post where post_id = $1", post_id)
        try:
            normalized_body = (
                await asyncio.to_thread(normalize_post_body, body_row["post_body"], _vision_client())
            ).text
            # TimeML/TempEval document creation time, not wall-clock now: "by next
            # Friday" in a January post must resolve to that January, not to the
            # Friday after the operator clicked Derive.
            reference_date = post["created_at"].date().isoformat()
            commitment = client.extract(post["post_title"], normalized_body, reference_date)
        except (HttpClientError, KeyError, OSError, TypeError, ValueError, RuntimeError) as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Commitment derivation is unavailable: contextual-orchestrator returned no complete evidence object",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - provider boundary is fail-closed.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Commitment derivation is unavailable: contextual-orchestrator returned no complete evidence object",
            ) from exc
    if not commitment.has_commitment:
        return {"post_id": str(post["post_id"]), "has_commitment": False, "ticket": None}
    async with pool.acquire() as conn:
        try:
            ticket = await upsert_commitment_ticket(
                conn,
                post_id,
                commitment.commitment_summary,
                commitment.due_date,
                commitment.commitment_summary,
            )
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"due_date {commitment.due_date!r} is not a valid YYYY-MM-DD date",
            ) from exc
    await publish_activity_event(
        valkey,
        post_id,
        "commitment_derived",
        account.user_account_id,
        f"Commitment derived: {commitment.commitment_summary}",
    )
    return {"post_id": str(post["post_id"]), "has_commitment": True, "ticket": ticket}


@app.get("/api/analysis-runs")
async def list_analysis_runs(
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Authorized analysis-run list: aggregates and labels only.

    Hidden scopes 404 at the item path and never appear here. The
    payload has no source SQL, DSN, raw record, or provider body.
    """
    _require_post_read(account)
    async with pool.acquire() as conn:
        runs = await fetch_visible_analysis_runs(
            conn,
            account.user_account_id,
            list(account.corporate_entity_ids),
        )
    return {"analysis_runs": runs}


class CreateAnalysisRunRequest(BaseModel):
    """JSON body for ``POST /api/analysis-runs``.

    Omitting ``corporate_entity_id`` uses the account's sole affiliation.
    Only ``analysis_run_lineage`` is accepted. Reconstruction and TEPP
    execution stay later slices; this write records Pending lineage only.
    """

    run_kind_code: str = "analysis_run_lineage"
    scope_kind_code: str = "analysis_scope_corporate_entity"
    corporate_entity_id: str | None = None
    knowledge_cutoff: datetime | None = None
    idempotency_key: str


@app.post("/api/analysis-runs", status_code=status.HTTP_201_CREATED)
async def create_analysis_run(
    request: CreateAnalysisRunRequest,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Record a Pending lineage run on an authorized cutoff capture.

    post_read is enough: the caller requests a run of a corp they
    already walk. TEPP and period-report kinds are 422 so this path
    cannot invent a measurement. Hidden scopes 404. A matching
    idempotent retry returns the same run.
    """
    _require_post_read(account)
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                created = await create_pending_analysis_run(
                    conn,
                    account_id=account.user_account_id,
                    affiliated_entity_ids=list(account.corporate_entity_ids),
                    run_kind_code=request.run_kind_code,
                    scope_kind_code=request.scope_kind_code,
                    corporate_entity_id=request.corporate_entity_id,
                    knowledge_cutoff=request.knowledge_cutoff,
                    idempotency_key=request.idempotency_key,
                )
            except AnalysisRunCreateError as exc:
                raise HTTPException(exc.status_code, exc.detail) from exc
    return created


@app.post("/api/analysis-runs/{analysis_run_id}/start")
async def start_analysis_run(
    analysis_run_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
    valkey: redis.Redis = Depends(get_valkey),
) -> dict[str, Any]:
    """Enqueue start work, then deliver ThreadWeave or TEPP.

    post_read is enough. Hidden runs 404. Period-report is 422 so this
    path cannot invent a calibrated score. TEPP goes through
    ``tepp_client`` and stays Failed when the transport is missing or
    the envelope is not persistable. A Succeeded lineage retry returns
    the stored tree. A Running restart with an undelivered outbox
    finishes that work. A Running restart without pending work is 409.
    The outbox commits before reconstruct/TEPP so a crash leaves a
    durable work item (ADR 0023).
    """
    _require_post_read(account)
    settings = load_settings()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                queued = await enqueue_pending_analysis_run(
                    conn,
                    analysis_run_id=analysis_run_id,
                    account_id=account.user_account_id,
                    affiliated_entity_ids=list(account.corporate_entity_ids),
                )
            except AnalysisRunStartError as exc:
                raise HTTPException(exc.status_code, exc.detail) from exc
    if queued.get("status_code") == "analysis_status_succeeded":
        return queued
    request_digest = queued.pop("outbox_request_sha256", None)
    stream_id = None
    if request_digest:
        stream_id = await publish_outbox_event(
            valkey,
            analysis_run_id=analysis_run_id,
            work_kind_code=str(queued.get("run_kind_code") or ""),
            request_sha256=request_digest,
        )
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                started = await deliver_queued_analysis_run(
                    conn,
                    analysis_run_id=analysis_run_id,
                    account_id=account.user_account_id,
                    affiliated_entity_ids=list(account.corporate_entity_ids),
                    tepp_client=configured_tepp_client(
                        settings.tepp_transport_url,
                        settings.tepp_api_key,
                    ),
                    adjudication_client=_adjudication_client(),
                    valkey_stream_entry_id=stream_id,
                )
            except AnalysisRunStartError as exc:
                raise HTTPException(exc.status_code, exc.detail) from exc
    return started


@app.get("/api/analysis-runs/{analysis_run_id}")
async def read_analysis_run(
    analysis_run_id: str,
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """One authorized analysis-run projection, or 404 when hidden.

    Detail adds the labeled status history. Hidden runs never leak events.
    """
    _require_post_read(account)
    try:
        UUID(analysis_run_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "analysis run not found") from None
    async with pool.acquire() as conn:
        run = await fetch_visible_analysis_run(
            conn,
            analysis_run_id,
            account.user_account_id,
            list(account.corporate_entity_ids),
        )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "analysis run not found")
    return run


@app.get("/api/calendar")
async def read_calendar(
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return independent CalDAV events alongside authorized commitments.

    An unavailable optional CalDAV source never hides the internal to-do
    projection and never creates a synthetic event.
    """
    _require_post_read(account)
    caldav = build_caldav_client(load_settings().caldav_base_url)
    events = []
    caldav_available = caldav.available
    caldav_next_action = None
    if caldav.available:
        try:
            events = [asdict(event) for event in caldav.list_events()]
        except (HttpClientError, OSError, ValueError):
            caldav_available = False
            caldav_next_action = CALDAV_UNAVAILABLE_NEXT_ACTION
    else:
        caldav_next_action = CALDAV_UNAVAILABLE_NEXT_ACTION
    async with pool.acquire() as conn:
        commitments = await fetch_upcoming_commitments(conn)
        demo_entity_ids: set[str] = set()
        if commitments and await has_real_source_context(conn, list(account.corporate_entity_ids)):
            demo_entity_ids = await fetch_demo_corporate_entity_ids(conn)
    visible = [c for c in commitments if _can_use_post_for_analysis(account, c)]
    # Once real evidence is visible, the synthetic Demo Corp commitments
    # (ADR 0001 / ADR 0042) stop appearing beside it.
    if demo_entity_ids:
        visible = [
            c for c in visible if not _is_synthetic_demo_member(c, demo_entity_ids)
        ]
    for c in visible:
        for key in (
            "visibility_code",
            "corporate_entity_id",
            "author_account_id",
            "source_detail_state_code",
            "has_real_source_context",
        ):
            c.pop(key, None)
    return {
        "events": events,
        "commitments": visible,
        "calendar_sources": {
            "caldav_available": caldav_available,
            "caldav_next_action": caldav_next_action,
        },
    }


@app.get("/api/rankings")
async def read_rankings(
    account: CurrentAccount = Depends(get_current_account),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """RankWeave fusion of ABAC-visible posts (ADR 0024).

    Hidden posts are omitted from every channel. Never invents a fused
    score or a theta. Fail-closed when RankWeave is disabled or the
    library is missing.
    """
    _require_post_read(account)
    async with pool.acquire() as conn:
        posts = await load_visible_ranking_posts(
            conn, lambda row: _can_use_post_for_analysis(account, row)
        )
    return _rankweave_client().as_api_payload(
        posts, can_see_post=lambda _row: True
    )
