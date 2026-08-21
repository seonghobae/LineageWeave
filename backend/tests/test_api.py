"""Real-integration test for the FastAPI backend: a genuine access token
from a live Keycloak, verified against Keycloak's live JWKS, against a
throwaway PostgreSQL database migrated with the actual schema file --
proving the OIDC + RBAC + ABAC path actually enforces what it claims to,
not just that the code type-checks.

Skipped unless both a local PostgreSQL server and a local Keycloak
(`docker compose up`, matching this repo's default ports) are reachable.

HTTP to Keycloak goes through ``lineageweave.http_client``.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import jwt
import psycopg2
import pytest
import redis

from lineageweave.http_client import HttpClientError, get_json, post_form
from lineageweave.knowledge_graph import knowledge_graph_edges_for_post
from lineageweave.post_summary import POST_SUMMARY_CONTRACT_VERSION

_POSTGRES_ADMIN_DSN = os.environ.get(
    "LINEAGEWEAVE_TEST_POSTGRES_ADMIN_DSN", "postgresql://lineageweave:lineageweave_dev_only@localhost:15432/lineageweave"
)
_KEYCLOAK_BASE_URL = os.environ.get("LINEAGEWEAVE_TEST_KEYCLOAK_BASE_URL", "http://localhost:18080")
_VALKEY_URL = os.environ.get("LINEAGEWEAVE_TEST_VALKEY_URL", "redis://localhost:16379/0")
_REALM = "lineageweave-demo"
_MIGRATION_PATH = Path(__file__).resolve().parents[2] / "migrations" / "0001_initial_schema.sql"
_REGISTRY_MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "0018_analysis_run_registry.sql"
_RETENTION_MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "0020_analysis_run_retention_purge.sql"
_RECONSTRUCTION_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0021_analysis_run_reconstruction.sql"
)
_SNAPSHOT_MEMBER_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0022_analysis_source_snapshot_member.sql"
)
_OUTBOX_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0023_analysis_run_outbox.sql"
)
_REVISION_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0024_source_post_revision.sql"
)
_POST_CONTENT_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0026_post_content_artifacts.sql"
)
_TEPP_RESULT_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0027_analysis_run_tepp_result.sql"
)
_INTERNAL_RELATION_EVIDENCE_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0028_internal_relation_evidence.sql"
)
_PROJECT_GROUPING_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0030_report_project_grouping.sql"
)
_SEMANTIC_PROJECT_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0031_semantic_project_mentions.sql"
)
_SEMANTIC_SEARCH_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0032_semantic_search_trigram.sql"
)
_SOURCE_STATE_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0033_source_state_provenance.sql"
)
_SOURCE_CONTEXT_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0034_source_context_provenance.sql"
)
_NORMALIZED_BODY_SEARCH_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0036_normalized_body_search.sql"
)
_SOURCE_RECORD_IDENTITY_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0037_source_record_identity.sql"
)
_SOURCE_NAMED_HINTS_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0038_source_named_hints.sql"
)
_SOURCE_ORG_NAMED_HINTS_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0039_source_org_named_hints.sql"
)
_SOURCE_COMMERCIAL_CONTEXT_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0130_source_commercial_context.sql"
)
_MEMBER_LOCALE_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0044_member_locale_preference.sql"
)
_IMAGE_REGION_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0045_post_content_image_regions.sql"
)
_POST_CONTENT_STRUCTURE_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0046_post_content_structure_evidence.sql"
)
_IMAGE_REGION_EMBEDDING_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0047_post_content_image_region_embeddings.sql"
)
_SUMMARY_FIVE_W1H_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0048_post_summary_five_w1h.sql"
)
_POST_CONTENT_QUEUE_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0050_post_content_ingestion_queue.sql"
)
_MAJOR_EVENT_ACTION_MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0100_major_event_action.sql"
)
_PROJECT_BOUND_ACTION_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0101_project_bound_major_event_action.sql"
)
_PROJECT_BOUND_EVENT_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0102_project_bound_summary_event.sql"
)
_TENANT_SETTINGS_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0103_tenant_settings.sql"
)
_IDENTIFIER_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0104_two_word_database_identifiers.sql"
)
_TENANT_IDENTITY_METADATA_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0132_tenant_identity_metadata.sql"
)
_AFFILIATION_SCOPE_FACET_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0106_account_affiliation_scope_facet.sql"
)
_QUANTITATIVE_OBSERVATION_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0108_post_summary_quantitative_observation.sql"
)
_SOURCE_FACT_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0109_post_summary_source_fact.sql"
)
_SOFTWARE_AGENT_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0110_role_responsibility_software_agent.sql"
)
_SEMANTIC_RELATIONSHIP_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0111_post_summary_semantic_relationship.sql"
)
_EVENT_CLUE_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0112_event_clue_semantic_projection.sql"
)
_BROAD_FACT_TYPES_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0113_broad_source_fact_types.sql"
)
_SEMANTIC_RELATIONSHIP_PREDICATES_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0114_semantic_relationship_standard_predicates.sql"
)


def _postgres_available() -> bool:
    """True when a Postgres at the admin DSN accepts a connection."""
    try:
        psycopg2.connect(_POSTGRES_ADMIN_DSN, connect_timeout=2).close()
        return True
    except psycopg2.OperationalError:
        return False


def _keycloak_available() -> bool:
    """True when the Keycloak realm's OIDC discovery document is reachable."""
    try:
        get_json(
            f"{_KEYCLOAK_BASE_URL}/realms/{_REALM}/.well-known/openid-configuration",
            timeout=2,
        )
        return True
    except (HttpClientError, OSError, ValueError):
        return False


def _valkey_available() -> bool:
    """True when the Valkey instance at ``_VALKEY_URL`` responds to PING."""
    try:
        client = redis.from_url(_VALKEY_URL, socket_connect_timeout=2)
        try:
            return client.ping()
        finally:
            client.close()
    except redis.RedisError:
        return False


pytestmark = pytest.mark.skipif(
    not (_postgres_available() and _keycloak_available() and _valkey_available()),
    reason="requires a reachable local PostgreSQL, Keycloak, and Valkey -- run `make up` first",
)


def _fetch_demo_analyst_token() -> str:
    """Request a real resource-owner token for the synthetic demo.analyst user."""
    token_response = post_form(
        f"{_KEYCLOAK_BASE_URL}/realms/{_REALM}/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": "lineageweave-frontend",
            "username": "demo.analyst",
            "password": "lineageweave-demo-only",
        },
        timeout=10,
    )
    return token_response["access_token"]


@pytest.fixture(scope="module")
def demo_analyst_token() -> str:
    return _fetch_demo_analyst_token()


@pytest.fixture
def seeded_db(demo_analyst_token):
    """A throwaway, freshly migrated database seeded with a user_account
    keyed to the real Keycloak demo.analyst subject, plus three source_post
    rows covering the three visibility outcomes the API must distinguish:
    public (visible to anyone), same-corp private (visible), and
    other-corp private (must NOT be visible).
    """
    subject = jwt.decode(demo_analyst_token, options={"verify_signature": False})["sub"]

    db_name = f"lineageweave_api_test_{uuid.uuid4().hex[:12]}"
    admin_conn = psycopg2.connect(_POSTGRES_ADMIN_DSN)
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(f'create database "{db_name}"')

    db_dsn = _POSTGRES_ADMIN_DSN.rsplit("/", 1)[0] + f"/{db_name}"
    conn = psycopg2.connect(db_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_PATH.read_text())
            cur.execute(_REGISTRY_MIGRATION.read_text())
            cur.execute(_RETENTION_MIGRATION.read_text())
            cur.execute(_RECONSTRUCTION_MIGRATION.read_text())
            cur.execute(_SNAPSHOT_MEMBER_MIGRATION.read_text())
            cur.execute(_OUTBOX_MIGRATION.read_text())
            cur.execute(_REVISION_MIGRATION.read_text())
            cur.execute(_POST_CONTENT_MIGRATION.read_text())
            cur.execute(_TEPP_RESULT_MIGRATION.read_text())
            cur.execute(_INTERNAL_RELATION_EVIDENCE_MIGRATION.read_text())
            cur.execute(_PROJECT_GROUPING_MIGRATION.read_text())
            cur.execute(_SEMANTIC_PROJECT_MIGRATION.read_text())
            cur.execute(_SEMANTIC_SEARCH_MIGRATION.read_text())
            cur.execute(_SOURCE_STATE_MIGRATION.read_text())
            cur.execute(_SOURCE_CONTEXT_MIGRATION.read_text())
            cur.execute(_NORMALIZED_BODY_SEARCH_MIGRATION.read_text())
            cur.execute(_SOURCE_RECORD_IDENTITY_MIGRATION.read_text())
            cur.execute(_SOURCE_NAMED_HINTS_MIGRATION.read_text())
            cur.execute(_SOURCE_ORG_NAMED_HINTS_MIGRATION.read_text())
            cur.execute(_SOURCE_COMMERCIAL_CONTEXT_MIGRATION.read_text())
            cur.execute(
                (Path(__file__).resolve().parents[2] / "migrations" / "0040_post_summary_contract.sql")
                .read_text()
            )
            cur.execute(_MEMBER_LOCALE_MIGRATION.read_text())
            cur.execute(_IMAGE_REGION_MIGRATION.read_text())
            cur.execute(_POST_CONTENT_STRUCTURE_MIGRATION.read_text())
            cur.execute(_IMAGE_REGION_EMBEDDING_MIGRATION.read_text())
            cur.execute(_SUMMARY_FIVE_W1H_MIGRATION.read_text())
            cur.execute(_POST_CONTENT_QUEUE_MIGRATION.read_text())
            cur.execute(_MAJOR_EVENT_ACTION_MIGRATION.read_text())
            cur.execute(_PROJECT_BOUND_ACTION_MIGRATION.read_text())
            cur.execute(_PROJECT_BOUND_EVENT_MIGRATION.read_text())
            cur.execute(_TENANT_SETTINGS_MIGRATION.read_text())
            cur.execute(_IDENTIFIER_MIGRATION.read_text())
            cur.execute(_TENANT_IDENTITY_METADATA_MIGRATION.read_text())
            cur.execute(_AFFILIATION_SCOPE_FACET_MIGRATION.read_text())
            cur.execute(_EVENT_CLUE_MIGRATION.read_text())
            cur.execute(_BROAD_FACT_TYPES_MIGRATION.read_text())
            cur.execute(_QUANTITATIVE_OBSERVATION_MIGRATION.read_text())
            cur.execute(_SOURCE_FACT_MIGRATION.read_text())
            cur.execute(_SOFTWARE_AGENT_MIGRATION.read_text())
            cur.execute(_SEMANTIC_RELATIONSHIP_MIGRATION.read_text())
            cur.execute(_SEMANTIC_RELATIONSHIP_PREDICATES_MIGRATION.read_text())
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) values "
                "('corporate_entity_level', 'group', 'Group'), "
                "('corporate_entity_level', 'company', 'Company'), "
                "('corporate_entity_level', 'plant', 'Plant'), "
                "('post_visibility', 'public', 'Public'), "
                "('post_visibility', 'private', 'Private'), "
                "('voc_type', 'voc', 'Voice of Customer'), "
                "('permission', 'post_read', 'Read posts'), "
                "('person_side', 'our_side', 'Our side'), "
                "('person_side', 'counterparty', 'Counterparty'), "
                "('node_type', 'node_person', 'Person'), "
                "('node_type', 'node_corporate_entity', 'Corporate entity'), "
                "('node_type', 'node_post', 'Post'), "
                "('node_type', 'node_team', 'Team'), "
                "('edge_type', 'edge_mention', 'Mentioned in'), "
                "('edge_type', 'edge_affiliation', 'Affiliated with'), "
                "('edge_type', 'edge_co_mention', 'Co-mentioned'), "
                "('edge_type', 'edge_mention_team', 'Team mentioned in'), "
                "('edge_type', 'edge_team_affiliation', 'Team affiliated with'), "
                "('edge_type', 'edge_mention_organization', 'Organization mentioned in'), "
                "('entity_relationship_type', 'rel_voc', 'Voice of Customer'), "
                "('entity_relationship_type', 'rel_vom', 'Voice of Market'), "
                "('entity_relationship_type', 'rel_vop', 'Voice of Partner'), "
                "('entity_relationship_type', 'rel_vocc', 'Voice of Customer''s Customer'), "
                "('entity_relationship_type', 'rel_voco', 'Voice of Competitor'), "
                "('entity_relationship_type', 'rel_vos', 'Voice of Supplier'), "
                "('ticket_status', 'open', 'Open'), "
                "('ticket_status', 'in_progress', 'In progress'), "
                "('ticket_status', 'closed', 'Closed'), "
                "('relation_verification_status', 'verify_pending', 'Not yet checked'), "
                "('relation_verification_status', 'verify_corroborated', 'Corroborated by external search'), "
                "('relation_verification_status', 'verify_uncorroborated', 'No corroborating evidence found'), "
                "('evaluation_criterion', 'general_sentiment_positive', 'Constructive stance'), "
                "('evaluation_criterion', 'general_sentiment_negative', 'Negative stance'), "
                "('evaluation_criterion', 'sales_lead_specificity', 'Sales-lead specificity'), "
                "('prov_agent_type', 'prov_person', 'Person'), "
                "('prov_agent_type', 'prov_organization', 'Organization'), "
                "('prov_agent_type', 'prov_team', 'Team')"
            )
            cur.execute(
                "insert into corporate_entity (corporate_entity_code, entity_name, entity_level_code) "
                "values ('TEST-GROUP', 'Test Group', 'group') returning corporate_entity_id"
            )
            own_group_id = cur.fetchone()[0]
            cur.execute(
                "insert into corporate_entity (parent_entity_id, corporate_entity_code, entity_name, entity_level_code) "
                "values (%s, 'TEST-CORP', 'Test Corp', 'company') returning corporate_entity_id",
                (own_group_id,),
            )
            own_corp_id = cur.fetchone()[0]
            cur.execute(
                "insert into corporate_entity (corporate_entity_code, entity_name, entity_level_code) "
                "values ('OTHER-CORP', 'Other Corp', 'group') returning corporate_entity_id"
            )
            other_corp_id = cur.fetchone()[0]
            cur.execute(
                "insert into corporate_entity (corporate_entity_code, entity_name, entity_level_code) "
                "values ('GRANTED-CORP', 'Granted Corp', 'company') returning corporate_entity_id"
            )
            granted_corp_id = cur.fetchone()[0]
            cur.execute(
                "insert into corporate_entity (corporate_entity_code, entity_name, entity_level_code) "
                "values ('HIDDEN-CORP', 'Hidden Corp', 'company') returning corporate_entity_id"
            )
            hidden_corp_id = cur.fetchone()[0]

            cur.execute(
                "insert into user_account (external_subject_id, display_name, email_address) "
                "values (%s, 'Test Analyst', 'test.analyst@example.test') returning user_account_id",
                (subject,),
            )
            account_id = cur.fetchone()[0]
            cur.execute(
                "insert into account_affiliation "
                "(user_account_id, corporate_entity_id, affiliation_scope_code) "
                "values (%s, %s, 'scope_own_entity'), (%s, %s, 'scope_granted_entity')",
                (account_id, own_corp_id, account_id, granted_corp_id),
            )
            cur.execute(
                "insert into access_role (role_code, role_name) values ('viewer', 'Viewer') returning access_role_id"
            )
            role_id = cur.fetchone()[0]
            cur.execute(
                "insert into role_permission (access_role_id, permission_code) values (%s, 'post_read')",
                (role_id,),
            )

            def _seed_analysis_run(
                digest: str,
                idempotency_key: str,
                requester_id,
                scope_kind: str,
                corp_id=None,
            ) -> str:
                cur.execute(
                    """
                    insert into analysis_source_snapshot
                        (snapshot_sha256, source_contract_version,
                         maximum_available_time, captured_at)
                    values (%s, 'source-contract-v1',
                            '2026-01-12T00:00:00Z', '2026-01-12T00:05:00Z')
                    returning analysis_source_snapshot_id
                    """,
                    (digest,),
                )
                snapshot_id = cur.fetchone()[0]
                cur.execute(
                    """
                    insert into analysis_source_count
                        (analysis_source_snapshot_id, count_type_code, count_value)
                    values (%s, 'analysis_count_document', 3)
                    """,
                    (snapshot_id,),
                )
                cur.execute(
                    """
                    insert into analysis_run
                        (analysis_source_snapshot_id, run_kind_code, idempotency_key,
                         requested_by_account_id, knowledge_cutoff,
                         configuration_schema_version, configuration_sha256,
                         code_revision_sha, requested_at)
                    values (%s, 'analysis_run_lineage', %s, %s,
                            '2026-01-12T12:00:00Z', 'lineage-run-v1', %s, %s,
                            '2026-01-12T12:30:00Z')
                    returning analysis_run_id
                    """,
                    (snapshot_id, idempotency_key, requester_id, "b" * 64, "c" * 40),
                )
                run_id = str(cur.fetchone()[0])
                if scope_kind == "analysis_scope_corporate_entity":
                    cur.execute(
                        """
                        insert into analysis_run_scope
                            (analysis_run_id, scope_kind_code, corporate_entity_id)
                        values (%s, %s, %s)
                        """,
                        (run_id, scope_kind, corp_id),
                    )
                else:
                    cur.execute(
                        """
                        insert into analysis_run_scope
                            (analysis_run_id, scope_kind_code)
                        values (%s, %s)
                        """,
                        (run_id, scope_kind),
                    )
                for ordinal, status, occurred in (
                    (1, "analysis_status_pending", "2026-01-12T12:31:00Z"),
                    (2, "analysis_status_running", "2026-01-12T12:32:00Z"),
                    (3, "analysis_status_succeeded", "2026-01-12T12:33:00Z"),
                ):
                    cur.execute(
                        """
                        insert into analysis_run_status_event
                            (analysis_run_id, status_ordinal, status_code, occurred_at)
                        values (%s, %s, %s, %s)
                        """,
                        (run_id, ordinal, status, occurred),
                    )
                return run_id

            cur.execute(
                "insert into user_account (external_subject_id, display_name, email_address) "
                "values (%s, 'Other Analyst', 'other.analyst@example.test') returning user_account_id",
                (f"other-{uuid.uuid4()}",),
            )
            other_account_id = cur.fetchone()[0]
            visible_run_id = _seed_analysis_run(
                "a" * 64,
                "visible-own-corp",
                account_id,
                "analysis_scope_corporate_entity",
                own_corp_id,
            )
            hidden_run_id = _seed_analysis_run(
                "d" * 64,
                "hidden-other-corp",
                other_account_id,
                "analysis_scope_corporate_entity",
                other_corp_id,
            )
            hidden_all_visible_id = _seed_analysis_run(
                "e" * 64,
                "hidden-all-visible",
                other_account_id,
                "analysis_scope_all_visible",
            )
            cur.execute(
                "insert into account_role_assignment (user_account_id, access_role_id) values (%s, %s)",
                (account_id, role_id),
            )

            def _insert_post(
                title: str,
                corporate_entity_id,
                visibility_code: str,
                body: str = "body",
                created_at: str = "2026-01-10T12:00:00Z",
                updated_at: str | None = None,
            ) -> str:
                written_at = updated_at if updated_at is not None else created_at
                cur.execute(
                    "insert into source_post (author_account_id, corporate_entity_id, post_title, post_body, voc_type_code, visibility_code, created_at, updated_at) "
                    "values (%s, %s, %s, %s, 'voc', %s, %s, %s) returning post_id",
                    (
                        account_id,
                        corporate_entity_id,
                        title,
                        body,
                        visibility_code,
                        created_at,
                        written_at,
                    ),
                )
                return str(cur.fetchone()[0])

            public_post_id = _insert_post("Public post", other_corp_id, "public")
            own_private_post_id = _insert_post(
                "Own-corp private post",
                own_corp_id,
                "private",
                "Ada West at Test Corp followed up with Priya Nair at Northridge Grid about the delayed shipment. "
                "The weather in Gwangju was irrelevant.",
            )
            other_private_post_id = _insert_post("Other-corp private post", other_corp_id, "private")
            late_own_private_post_id = _insert_post(
                "Late own-corp private post",
                own_corp_id,
                "private",
                "A follow-up written after the January 2026 run cutoff.",
                created_at="2026-01-20T12:00:00Z",
            )
            edited_own_post_id = _insert_post(
                "Edited own-corp private post",
                own_corp_id,
                "private",
                "A January post before the rewrite.",
                created_at="2026-01-10T12:00:00Z",
                updated_at="2026-01-10T12:00:00Z",
            )
            cur.execute(
                "update source_post set post_body = %s, updated_at = %s where post_id = %s",
                (
                    "A January post rewritten after the run cutoff.",
                    "2026-01-13T09:00:00Z",
                    edited_own_post_id,
                ),
            )

            cur.execute(
                "insert into cataloged_person (person_name, person_side_code) values "
                "('Ada West', 'our_side') returning person_id"
            )
            our_person_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into cataloged_person (person_name, person_side_code) values "
                "('Priya Nair', 'counterparty') returning person_id"
            )
            counterpart_person_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into cataloged_person (person_name, person_side_code) values "
                "('Other Corp Only', 'counterparty') returning person_id"
            )
            hidden_person_id = str(cur.fetchone()[0])

            cur.execute(
                "insert into person_affiliation (person_id, affiliated_organization_name, affiliated_corporate_entity_id) "
                "values (%s, 'Test Corp', %s)",
                (our_person_id, own_corp_id),
            )
            cur.execute(
                "insert into person_affiliation (person_id, affiliated_organization_name) "
                "values (%s, 'Northridge Grid'), (%s, 'Northridge Holdings')",
                (counterpart_person_id, counterpart_person_id),
            )
            cur.execute(
                "insert into person_affiliation "
                "(person_id, affiliated_organization_name, affiliated_corporate_entity_id) "
                "values (%s, 'Other Corp Only', %s)",
                (hidden_person_id, other_corp_id),
            )

            cur.execute(
                "insert into post_person_mention (post_id, person_id) values "
                "(%s, %s), (%s, %s), (%s, %s), (%s, %s)",
                (
                    own_private_post_id,
                    our_person_id,
                    own_private_post_id,
                    counterpart_person_id,
                    public_post_id,
                    our_person_id,
                    other_private_post_id,
                    hidden_person_id,
                ),
            )

            from lineageweave.knowledge_graph import knowledge_graph_edges_for_post

            seen_edges: set[tuple[str, str, str, str, str]] = set()
            for post_id, person_ids, affiliations in (
                (own_private_post_id, [our_person_id, counterpart_person_id], [(our_person_id, str(own_corp_id))]),
                (public_post_id, [our_person_id], [(our_person_id, str(own_corp_id))]),
                (other_private_post_id, [hidden_person_id], []),
            ):
                for edge in knowledge_graph_edges_for_post(post_id, person_ids, affiliations):
                    key = (
                        edge.source_node_type_code,
                        edge.source_node_id,
                        edge.target_node_type_code,
                        edge.target_node_id,
                        edge.edge_type_code,
                    )
                    if key in seen_edges:
                        continue
                    seen_edges.add(key)
                    cur.execute(
                        "insert into knowledge_graph_edge ("
                        "source_node_type_code, source_node_id, target_node_type_code, "
                        "target_node_id, edge_type_code, edge_weight"
                        ") values (%s, %s, %s, %s, %s, %s)",
                        (
                            edge.source_node_type_code,
                            edge.source_node_id,
                            edge.target_node_type_code,
                            edge.target_node_id,
                            edge.edge_type_code,
                            edge.edge_weight,
                        ),
                    )
        conn.commit()

        yield {
            "dsn": db_dsn,
            "public_post_id": public_post_id,
            "own_group_id": str(own_group_id),
            "own_corp_id": str(own_corp_id),
            "other_corp_id": str(other_corp_id),
            "granted_corp_id": str(granted_corp_id),
            "hidden_corp_id": str(hidden_corp_id),
            "own_private_post_id": own_private_post_id,
            "late_own_private_post_id": late_own_private_post_id,
            "edited_own_post_id": edited_own_post_id,
            "other_private_post_id": other_private_post_id,
            "our_person_id": our_person_id,
            "counterpart_person_id": counterpart_person_id,
            "hidden_person_id": hidden_person_id,
            "visible_run_id": visible_run_id,
            "hidden_run_id": hidden_run_id,
            "hidden_all_visible_id": hidden_all_visible_id,
        }
    finally:
        conn.close()
        with admin_conn.cursor() as cur:
            cur.execute(f'drop database "{db_name}"')
        admin_conn.close()


@pytest.fixture
def client(seeded_db):
    os.environ["DATABASE_URL"] = seeded_db["dsn"]
    os.environ["KEYCLOAK_BASE_URL"] = _KEYCLOAK_BASE_URL
    os.environ["KEYCLOAK_ISSUER"] = f"{_KEYCLOAK_BASE_URL}/realms/{_REALM}"

    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_analysis_runs_are_labeled_aggregates_and_hide_other_scopes(
    client, demo_analyst_token, seeded_db
) -> None:
    """Demo analyst sees the Test Corp run, never the Other Corp or outsider run."""
    listed = client.get("/api/analysis-runs", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert listed.status_code == 200
    runs = listed.json()["analysis_runs"]
    ids = {run["analysis_run_id"] for run in runs}
    assert seeded_db["visible_run_id"] in ids
    assert seeded_db["hidden_run_id"] not in ids
    assert seeded_db["hidden_all_visible_id"] not in ids
    visible = next(run for run in runs if run["analysis_run_id"] == seeded_db["visible_run_id"])
    assert visible["run_kind_label"] == "Lineage reconstruction"
    assert visible["status_label"] == "Succeeded"
    assert visible["scope_kind_label"] == "Corporate entity"
    assert visible["scope_entity_name"] == "Test Corp"
    assert visible["source_counts"] == [
        {
            "count_type_code": "analysis_count_document",
            "count_type_label": "Documents",
            "count_value": 3,
        }
    ]
    dumped = str(visible)
    assert "postgresql://" not in dumped
    assert "select " not in dumped.lower()
    assert "status_history" not in visible

    detail = client.get(
        f"/api/analysis-runs/{seeded_db['visible_run_id']}",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["configuration_schema_version"] == "lineage-run-v1"
    assert "snapshot_sha256" not in body
    history = body["status_history"]
    assert [event["status_label"] for event in history] == [
        "Pending",
        "Running",
        "Succeeded",
    ]
    assert [event["occurred_at"][:16] for event in history] == [
        "2026-01-12T12:31",
        "2026-01-12T12:32",
        "2026-01-12T12:33",
    ]
    assert all("failure_code" not in event for event in history)
    titles = {post["post_title"] for post in body["visible_posts"]}
    assert "Own-corp private post" in titles
    assert "Edited own-corp private post" in titles
    assert "Late own-corp private post" not in titles
    assert "Other-corp private post" not in titles
    posts_by_title = {post["post_title"]: post for post in body["visible_posts"]}
    assert posts_by_title["Own-corp private post"]["live_after_cutoff"] is False
    assert posts_by_title["Edited own-corp private post"]["live_after_cutoff"] is True
    assert posts_by_title["Edited own-corp private post"]["updated_at"].startswith("2026-01-13")
    assert "post_body" not in posts_by_title["Edited own-corp private post"]
    assert "postgresql://" not in str(body)
    assert "visible_posts" not in visible

    hidden = client.get(
        f"/api/analysis-runs/{seeded_db['hidden_run_id']}",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert hidden.status_code == 404

    unauthenticated = client.get("/api/analysis-runs")
    assert unauthenticated.status_code == 401


def test_create_analysis_run_records_pending_without_inventing_a_score(
    client, demo_analyst_token, seeded_db
) -> None:
    """POST /api/analysis-runs writes Pending on the authorized cutoff bag."""
    created = client.post(
        "/api/analysis-runs",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
        json={
            "run_kind_code": "analysis_run_lineage",
            "corporate_entity_id": seeded_db["own_corp_id"],
            "idempotency_key": "run-create-2026-w02",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["run_kind_label"] == "Lineage reconstruction"
    assert body["status_label"] == "Pending"
    assert body["status_history"][0]["status_label"] == "Pending"
    assert all(event["status_label"] != "Succeeded" for event in body["status_history"])
    titles = {post["post_title"] for post in body["visible_posts"]}
    assert "Own-corp private post" in titles
    assert "Other-corp private post" not in titles
    assert "theta" not in str(body).lower()
    assert "postgresql://" not in str(body)

    replay = client.post(
        "/api/analysis-runs",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
        json={
            "run_kind_code": "analysis_run_lineage",
            "corporate_entity_id": seeded_db["own_corp_id"],
            "idempotency_key": "run-create-2026-w02",
        },
    )
    assert replay.status_code == 201
    assert replay.json()["analysis_run_id"] == body["analysis_run_id"]

    tepp = client.post(
        "/api/analysis-runs",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
        json={
            "run_kind_code": "analysis_run_tepp",
            "corporate_entity_id": seeded_db["own_corp_id"],
            "idempotency_key": "run-create-tepp",
        },
    )
    assert tepp.status_code == 422
    assert "invent a measurement" in tepp.json()["detail"]
    assert "theta" not in tepp.json()["detail"].lower()

    report = client.post(
        "/api/analysis-runs",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
        json={
            "run_kind_code": "analysis_run_report",
            "corporate_entity_id": seeded_db["own_corp_id"],
            "idempotency_key": "run-create-report",
        },
    )
    assert report.status_code == 422
    assert "Reports panel" in report.json()["detail"]

    conflict = client.post(
        "/api/analysis-runs",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
        json={
            "run_kind_code": "analysis_run_lineage",
            "corporate_entity_id": seeded_db["own_corp_id"],
            "knowledge_cutoff": "2026-01-01T00:00:00Z",
            "idempotency_key": "run-create-2026-w02",
        },
    )
    assert conflict.status_code == 409

    hidden = client.post(
        "/api/analysis-runs",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
        json={
            "run_kind_code": "analysis_run_lineage",
            "corporate_entity_id": seeded_db["other_corp_id"],
            "idempotency_key": "run-create-hidden-corp",
        },
    )
    assert hidden.status_code == 404

    unauthenticated = client.post(
        "/api/analysis-runs",
        json={"idempotency_key": "run-create-unauthenticated"},
    )
    assert unauthenticated.status_code == 401


def test_start_analysis_run_recovers_the_a100_fork(
    client, demo_analyst_token, seeded_db
) -> None:
    """Starting a Pending lineage run persists the designed fixture tree."""
    from scripts.seed_demo_data import insert_fixture_source_posts

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('voc_type', 'vom', 'Voice of Market') "
                "on conflict (lookup_code) do nothing"
            )
            cur.execute(
                "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                "select corporate_entity_id, 'TEST-PU-START', 'Start reconstruction' "
                "from source_post where post_id = %s returning process_unit_id",
                (seeded_db["own_private_post_id"],),
            )
            process_unit_id = cur.fetchone()[0]
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            insert_fixture_source_posts(cur, author_id, corp_id, process_unit_id)
    finally:
        admin_conn.close()

    created = client.post(
        "/api/analysis-runs",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
        json={
            "run_kind_code": "analysis_run_lineage",
            "corporate_entity_id": seeded_db["own_corp_id"],
            "knowledge_cutoff": "2026-02-15T00:00:00Z",
            "idempotency_key": "run-start-2026-w07",
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["analysis_run_id"]
    assert created.json()["status_label"] == "Pending"

    started = client.post(
        f"/api/analysis-runs/{run_id}/start",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status_label"] == "Succeeded"
    assert all(event["status_label"] != "Failed" for event in body["status_history"])
    assert body["reconstruction_result_sha256"]
    children = {
        edge["child_post_title"]
        for edge in body["reconstructed_edges"]
        if edge["parent_post_title"] == "Pricing renegotiation follow-up"
    }
    assert "Pricing renegotiation: revised quote sent" in children
    assert "Delivery schedule question raised" in children
    assert "theta" not in str(body).lower()
    assert "outbox_request_sha256" not in body

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                select outbox.work_kind_code, delivery.delivery_status_code
                from analysis_run_outbox outbox
                join analysis_run_outbox_delivery delivery
                  on delivery.analysis_run_id = outbox.analysis_run_id
                where outbox.analysis_run_id = %s
                order by delivery.delivery_ordinal desc
                limit 1
                """,
                (run_id,),
            )
            outbox_row = cur.fetchone()
            assert outbox_row == ("analysis_run_lineage", "analysis_outbox_delivered")
    finally:
        admin_conn.close()
    valkey = redis.from_url(_VALKEY_URL, decode_responses=True)
    try:
        entries = valkey.xrevrange("analysis-run-outbox", count=50)
        assert any(
            fields.get("analysis_run_id") == run_id
            and fields.get("work_kind_code") == "analysis_run_lineage"
            and "theta" not in str(fields).casefold()
            for _entry_id, fields in entries
        )
    finally:
        valkey.close()

    replay = client.post(
        f"/api/analysis-runs/{run_id}/start",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert replay.status_code == 200
    assert replay.json()["reconstruction_result_sha256"] == body["reconstruction_result_sha256"]

    tepp_create = client.post(
        "/api/analysis-runs",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
        json={
            "run_kind_code": "analysis_run_tepp",
            "corporate_entity_id": seeded_db["own_corp_id"],
            "knowledge_cutoff": "2026-02-15T00:00:00Z",
            "idempotency_key": "run-start-tepp-2026-w07",
        },
    )
    assert tepp_create.status_code == 422
    assert "invent a measurement" in tepp_create.json()["detail"]

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select requested_by_account_id from analysis_run where analysis_run_id = %s",
                (run_id,),
            )
            requester_id = cur.fetchone()[0]
            cur.execute(
                """
                insert into analysis_source_snapshot
                    (snapshot_sha256, source_contract_version,
                     maximum_available_time, captured_at)
                values (%s, 'source-contract-v1',
                        '2026-02-15T00:00:00Z', '2026-02-15T00:05:00Z')
                returning analysis_source_snapshot_id
                """,
                ("f" * 64,),
            )
            tepp_snapshot_id = cur.fetchone()[0]
            cur.execute(
                """
                insert into analysis_run
                    (analysis_source_snapshot_id, run_kind_code, idempotency_key,
                     requested_by_account_id, knowledge_cutoff,
                     configuration_schema_version, configuration_sha256,
                     code_revision_sha, requested_at)
                values (%s, 'analysis_run_tepp', 'run-start-tepp-seeded',
                        %s, '2026-02-15T00:00:00Z', 'tepp-run-v1', %s, %s,
                        '2026-02-15T12:30:00Z')
                returning analysis_run_id
                """,
                (tepp_snapshot_id, requester_id, "a" * 64, "b" * 40),
            )
            tepp_run_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into analysis_run_scope
                    (analysis_run_id, scope_kind_code, corporate_entity_id)
                values (%s, 'analysis_scope_corporate_entity', %s)
                """,
                (tepp_run_id, seeded_db["own_corp_id"]),
            )
            cur.execute(
                """
                insert into analysis_run_status_event
                    (analysis_run_id, status_ordinal, status_code, occurred_at)
                values (%s, 1, 'analysis_status_pending', '2026-02-15T12:31:00Z')
                """,
                (tepp_run_id,),
            )
    finally:
        admin_conn.close()

    measured = client.post(
        f"/api/analysis-runs/{tepp_run_id}/start",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert measured.status_code == 200, measured.text
    tepp_body = measured.json()
    assert tepp_body["status_label"] == "Failed"
    assert tepp_body["failure_code"] == "tepp_not_available"
    assert any(
        event.get("failure_code") == "tepp_not_available"
        for event in tepp_body["status_history"]
    )
    assert "theta" not in str(tepp_body).lower()

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                insert into analysis_source_snapshot
                    (snapshot_sha256, source_contract_version,
                     maximum_available_time, captured_at)
                values (%s, 'source-contract-v1',
                        '2026-01-12T00:00:00Z', '2026-01-12T00:05:00Z')
                returning analysis_source_snapshot_id
                """,
                ("9" * 64,),
            )
            report_snapshot_id = cur.fetchone()[0]
            cur.execute(
                "select requested_by_account_id from analysis_run where analysis_run_id = %s",
                (run_id,),
            )
            requester_id = cur.fetchone()[0]
            cur.execute(
                """
                insert into analysis_run
                    (analysis_source_snapshot_id, run_kind_code, idempotency_key,
                     requested_by_account_id, knowledge_cutoff,
                     configuration_schema_version, configuration_sha256,
                     code_revision_sha, requested_at)
                values (%s, 'analysis_run_report', 'run-start-report',
                        %s, '2026-01-12T12:00:00Z', 'lineage-run-v1', %s, %s,
                        '2026-01-12T12:30:00Z')
                returning analysis_run_id
                """,
                (report_snapshot_id, requester_id, "8" * 64, "7" * 40),
            )
            report_run_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into analysis_run_scope
                    (analysis_run_id, scope_kind_code, corporate_entity_id)
                values (%s, 'analysis_scope_corporate_entity', %s)
                """,
                (report_run_id, seeded_db["own_corp_id"]),
            )
            cur.execute(
                """
                insert into analysis_run_status_event
                    (analysis_run_id, status_ordinal, status_code, occurred_at)
                values (%s, 1, 'analysis_status_pending', '2026-01-12T12:31:00Z')
                """,
                (report_run_id,),
            )
            cur.execute(
                """
                insert into analysis_source_snapshot
                    (snapshot_sha256, source_contract_version,
                     maximum_available_time, captured_at)
                values (%s, 'source-contract-v1',
                        '2026-01-12T00:00:00Z', '2026-01-12T00:05:00Z')
                returning analysis_source_snapshot_id
                """,
                ("6" * 64,),
            )
            running_snapshot_id = cur.fetchone()[0]
            cur.execute(
                """
                insert into analysis_run
                    (analysis_source_snapshot_id, run_kind_code, idempotency_key,
                     requested_by_account_id, knowledge_cutoff,
                     configuration_schema_version, configuration_sha256,
                     code_revision_sha, requested_at)
                values (%s, 'analysis_run_lineage', 'run-start-running',
                        %s, '2026-01-12T12:00:00Z', 'lineage-run-v1', %s, %s,
                        '2026-01-12T12:30:00Z')
                returning analysis_run_id
                """,
                (running_snapshot_id, requester_id, "5" * 64, "4" * 40),
            )
            running_run_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into analysis_run_scope
                    (analysis_run_id, scope_kind_code, corporate_entity_id)
                values (%s, 'analysis_scope_corporate_entity', %s)
                """,
                (running_run_id, seeded_db["own_corp_id"]),
            )
            for ordinal, status, occurred in (
                (1, "analysis_status_pending", "2026-01-12T12:31:00Z"),
                (2, "analysis_status_running", "2026-01-12T12:32:00Z"),
            ):
                cur.execute(
                    """
                    insert into analysis_run_status_event
                        (analysis_run_id, status_ordinal, status_code, occurred_at)
                    values (%s, %s, %s, %s)
                    """,
                    (running_run_id, ordinal, status, occurred),
                )
    finally:
        admin_conn.close()

    report_refused = client.post(
        f"/api/analysis-runs/{report_run_id}/start",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert report_refused.status_code == 422
    assert "invent a measurement" in report_refused.json()["detail"]

    running = client.post(
        f"/api/analysis-runs/{running_run_id}/start",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert running.status_code == 409

    hidden = client.post(
        f"/api/analysis-runs/{seeded_db['hidden_run_id']}/start",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert hidden.status_code == 404

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                insert into analysis_source_snapshot
                    (snapshot_sha256, source_contract_version,
                     maximum_available_time, captured_at)
                values (%s, 'source-contract-v1',
                        '2026-01-12T00:00:00Z', '2026-01-12T00:05:00Z')
                returning analysis_source_snapshot_id
                """,
                ("3" * 64,),
            )
            crash_snapshot_id = cur.fetchone()[0]
            cur.execute(
                """
                insert into analysis_run
                    (analysis_source_snapshot_id, run_kind_code, idempotency_key,
                     requested_by_account_id, knowledge_cutoff,
                     configuration_schema_version, configuration_sha256,
                     code_revision_sha, requested_at)
                values (%s, 'analysis_run_lineage', 'run-start-outbox-resume',
                        %s, '2026-02-15T00:00:00Z', 'lineage-run-v1', %s, %s,
                        '2026-02-15T12:30:00Z')
                returning analysis_run_id
                """,
                (crash_snapshot_id, requester_id, "2" * 64, "1" * 40),
            )
            crash_run_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into analysis_run_scope
                    (analysis_run_id, scope_kind_code, corporate_entity_id)
                values (%s, 'analysis_scope_corporate_entity', %s)
                """,
                (crash_run_id, seeded_db["own_corp_id"]),
            )
            for ordinal, status, occurred in (
                (1, "analysis_status_pending", "2026-02-15T12:31:00Z"),
                (2, "analysis_status_running", "2026-02-15T12:32:00Z"),
            ):
                cur.execute(
                    """
                    insert into analysis_run_status_event
                        (analysis_run_id, status_ordinal, status_code, occurred_at)
                    values (%s, %s, %s, %s)
                    """,
                    (crash_run_id, ordinal, status, occurred),
                )
            cur.execute(
                """
                insert into analysis_run_outbox
                    (analysis_run_id, work_kind_code, request_sha256, enqueued_at)
                values (%s, 'analysis_run_lineage', %s, '2026-02-15T12:32:00Z')
                """,
                (crash_run_id, "a" * 64),
            )
    finally:
        admin_conn.close()

    resumed = client.post(
        f"/api/analysis-runs/{crash_run_id}/start",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert resumed.status_code == 200, resumed.text
    resumed_body = resumed.json()
    assert resumed_body["status_label"] == "Succeeded"
    assert "theta" not in str(resumed_body).lower()
    children = {
        edge["child_post_title"]
        for edge in resumed_body["reconstructed_edges"]
        if edge["parent_post_title"] == "Pricing renegotiation follow-up"
    }
    assert "Pricing renegotiation: revised quote sent" in children


def test_me_reflects_the_authenticated_account(client, demo_analyst_token, seeded_db) -> None:
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select user_account_id from account_affiliation where corporate_entity_id = %s",
                (seeded_db["own_corp_id"],),
            )
            account_id = cur.fetchone()[0]
            cur.execute(
                "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                "values (%s, 'TEST-PU', 'Test PU') returning process_unit_id",
                (seeded_db["own_corp_id"],),
            )
            process_unit_id = cur.fetchone()[0]
            cur.execute(
                "update account_affiliation set process_unit_id = %s "
                "where user_account_id = %s and corporate_entity_id = %s",
                (process_unit_id, account_id, seeded_db["own_corp_id"]),
            )
        admin_conn.commit()
    finally:
        admin_conn.close()

    response = client.get("/api/me", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Test Analyst"
    assert "post_read" in body["permission_codes"]
    assert any(
        entity["entity_name"] == "Test Corp" for entity in body["corporate_entities"]
    )
    assert {
        row["corporate_entity_code"] for row in body["account_affiliations"]
    } == {"TEST-CORP", "GRANTED-CORP"}
    affiliation = next(
        row
        for row in body["account_affiliations"]
        if row["corporate_entity_id"] == seeded_db["own_corp_id"]
    )
    assert affiliation == {
        "corporate_entity_id": seeded_db["own_corp_id"],
        "corporate_entity_code": "TEST-CORP",
        "entity_name": "Test Corp",
        "process_unit_id": affiliation["process_unit_id"],
        "process_unit_code": "TEST-PU",
        "process_unit_name": "Test PU",
    }


def test_healthz_is_a_public_liveness_probe(client) -> None:
    """Regression test: a dangling ``@app.get("/healthz")`` decorator once
    attached to ``read_tenant_settings`` instead of the liveness probe,
    requiring auth on ``/healthz`` and leaving the real ``healthz()``
    handler undecorated. Docker's own healthcheck (docker-compose.yml)
    calls this route unauthenticated, so any auth requirement here breaks
    container health and cascades into the whole compose dependency graph.
    """
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_get_requires_auth_and_returns_brand_name(client, demo_analyst_token) -> None:
    unauthenticated = client.get("/api/settings")
    assert unauthenticated.status_code == 401

    response = client.get("/api/settings", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 200
    assert response.json() == {
        "brandName": "LineageWeave",
        "systemName": "LineageWeave",
        "copyrightYear": 2026,
        "copyrightHolder": "LineageWeave",
    }


def test_settings_patch_requires_post_admin(client, demo_analyst_token, seeded_db) -> None:
    denied = client.patch(
        "/api/settings",
        json={"brandName": "Should not apply"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert denied.status_code == 403

    _grant_post_admin(seeded_db["dsn"])
    allowed = client.patch(
        "/api/settings",
        json={
            "brandName": "LineageWeave Demo",
            "systemName": "LineageWeave Intelligence",
            "copyrightYear": 2025,
            "copyrightHolder": "LineageWeave Demo",
        },
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert allowed.status_code == 200
    assert allowed.json() == {
        "brandName": "LineageWeave Demo",
        "systemName": "LineageWeave Intelligence",
        "copyrightYear": 2025,
        "copyrightHolder": "LineageWeave Demo",
    }

    with psycopg2.connect(seeded_db["dsn"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "update tenant_settings set updated_at = '2000-01-01T00:00:00Z' where tenant_settings_id = 1"
            )

    legacy = client.patch(
        "/api/settings",
        json={"brandName": "Legacy Client Brand"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert legacy.status_code == 200
    assert legacy.json() == {
        "brandName": "Legacy Client Brand",
        "systemName": "LineageWeave Intelligence",
        "copyrightYear": 2025,
        "copyrightHolder": "LineageWeave Demo",
    }

    with psycopg2.connect(seeded_db["dsn"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("select updated_at from tenant_settings where tenant_settings_id = 1")
            assert cursor.fetchone()[0].year > 2000

    confirm = client.get("/api/settings", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert confirm.json() == legacy.json()


def test_settings_patch_rejects_blank_identity_and_invalid_copyright_year(
    client, demo_analyst_token, seeded_db
) -> None:
    _grant_post_admin(seeded_db["dsn"])
    headers = {"Authorization": f"Bearer {demo_analyst_token}"}

    blank_system_name = client.patch(
        "/api/settings", json={"systemName": "   "}, headers=headers
    )
    assert blank_system_name.status_code == 422

    invalid_year = client.patch(
        "/api/settings", json={"copyrightYear": 1899}, headers=headers
    )
    assert invalid_year.status_code == 422


def test_customer_master_returns_authorized_catalog_contract(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    subject = jwt.decode(demo_analyst_token, options={"verify_signature": False})["sub"]
    from backend.app import main as main_module

    relationship_entity_ids: list[str] = []
    original_relationship_network = main_module.fetch_relationship_network

    async def capture_relationship_entity_ids(conn, corporate_entity_ids):
        relationship_entity_ids.extend(corporate_entity_ids)
        return await original_relationship_network(conn, corporate_entity_ids)

    monkeypatch.setattr(main_module, "fetch_relationship_network", capture_relationship_entity_ids)
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "update source_post set source_customer_code = %s, source_author_code = %s, source_author_name = %s where post_id = %s",
                ("TEST-CUSTOMER-001", "TEST-AUTHOR-001", "Test Author", seeded_db["public_post_id"]),
            )
            # SOURCE_POST_ELIGIBILITY_SQL treats a post with no source_*
            # context as ineligible once any other post has real context
            # (the demo-vs-real-data lifecycle rule). source_project_code
            # isn't read by the customer/author hint queries, so setting
            # it keeps this post eligible for relationship_network
            # without adding a second source_customer_hints/
            # source_author_hints row to the exact-list assertions below.
            cur.execute(
                "update source_post set source_project_code = %s where post_id = %s",
                ("TEST-PROJECT-001", seeded_db["own_private_post_id"]),
            )
            cur.execute(
                "insert into post_summary_result (post_id, korean_summary, summary_contract_version) "
                "values (%s, %s, %s)",
                (seeded_db["public_post_id"], "stored summary", POST_SUMMARY_CONTRACT_VERSION),
            )
            cur.execute(
                "insert into post_summary_role "
                "(post_id, actor_name, responsibility_text, actor_type_code, affiliated_organization_name, cataloged_person_id) "
                "values (%s, %s, %s, %s, %s, %s)",
                (
                    seeded_db["public_post_id"],
                    "Ada West",
                    "account lead",
                    "prov_person",
                    "Test Corp",
                    seeded_db["our_person_id"],
                ),
            )
            cur.execute(
                "insert into corporate_entity "
                "(parent_entity_id, corporate_entity_code, entity_name, entity_level_code) "
                "values (%s, 'DEMO-GRANTED-CHILD', 'Demo Granted Child', 'company') "
                "returning corporate_entity_id",
                (seeded_db["granted_corp_id"],),
            )
            demo_child_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into account_affiliation "
                "(user_account_id, corporate_entity_id, affiliation_scope_code) "
                "select user_account_id, %s, 'scope_granted_entity' "
                "from user_account where external_subject_id = %s",
                (demo_child_id, subject),
            )
            cur.execute(
                "insert into post_organization_mention (post_id, corporate_entity_id) "
                "values (%s, %s), (%s, %s), (%s, %s), (%s, %s)",
                (
                    seeded_db["public_post_id"],
                    seeded_db["other_corp_id"],
                    seeded_db["other_private_post_id"],
                    seeded_db["hidden_corp_id"],
                    seeded_db["public_post_id"],
                    seeded_db["own_corp_id"],
                    seeded_db["public_post_id"],
                    demo_child_id,
                ),
            )
            cur.execute(
                "insert into post_counterparty_entity "
                "(post_id, counterparty_entity_name, relationship_type_code, verification_status_code) "
                "values (%s, 'Private Other Corp', 'rel_voc', 'verify_pending')",
                (seeded_db["other_private_post_id"],),
            )
            cur.execute(
                "insert into account_affiliation "
                "(user_account_id, corporate_entity_id, affiliation_scope_code) "
                "select user_account_id, %s, 'scope_granted_entity' "
                "from user_account where external_subject_id = %s",
                (seeded_db["own_group_id"], subject),
            )
            # A real counterparty can hold more than one role over its
            # lifetime -- one post classifies "Northridge Grid" as a
            # customer, a different visible post classifies the same
            # name as a competitor. relationship_network must surface
            # both, not just the most recent/frequent one.
            cur.execute(
                "insert into post_counterparty_entity "
                "(post_id, counterparty_entity_name, relationship_type_code, verification_status_code) "
                "values (%s, 'Northridge Grid', 'rel_voc', 'verify_pending'), "
                "       (%s, 'Northridge Grid', 'rel_voco', 'verify_pending'), "
                "       (%s, 'Solo Role Corp', 'rel_vos', 'verify_pending')",
                (
                    seeded_db["public_post_id"],
                    seeded_db["own_private_post_id"],
                    seeded_db["public_post_id"],
                ),
            )
            # Once imported source context exists, this affiliated child is
            # synthetic-only and must be removed consistently from the tree,
            # stale observed hierarchy facets, Keymen, and account hints.
            cur.execute(
                "insert into cataloged_person (person_name, person_side_code) "
                "values ('Demo Grant Only', 'our_side') returning person_id",
            )
            demo_person_id = cur.fetchone()[0]
            cur.execute(
                "insert into person_affiliation "
                "(person_id, affiliated_organization_name, affiliated_corporate_entity_id) "
                "values (%s, 'Demo Granted Child', %s)",
                (demo_person_id, demo_child_id),
            )
        admin_conn.commit()
    finally:
        admin_conn.close()
    response = client.get(
        "/api/customer-master",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "corporate_entities", "keymen", "source_customer_hints", "source_author_hints",
        "relationship_network",
    }
    entity = next(item for item in body["corporate_entities"] if item["entity_name"] == "Test Corp")
    assert {
        "corporate_entity_id", "corporate_entity_code", "entity_name",
        "entity_level_code", "entity_level_label", "parent_entity_id",
    } <= set(entity)
    # Live UI finding (2026-08-19): the corporate entity list rendered
    # the raw entity_level_code ("company") instead of a human label --
    # confirm this is a real common_lookup_value label, not the code echoed back.
    assert entity["entity_level_code"] == "company"
    assert entity["entity_level_label"] not in ("", "company")
    assert entity["scope_facets"] == ["authorized_own", "observed_organization"]
    parent = next(item for item in body["corporate_entities"] if item["entity_name"] == "Test Group")
    assert parent["scope_facets"] == ["authorized_granted", "observed_hierarchy"]
    granted = next(item for item in body["corporate_entities"] if item["entity_name"] == "Granted Corp")
    assert granted["scope_facets"] == ["authorized_granted"]
    assert not any(item["entity_name"] == "Demo Granted Child" for item in body["corporate_entities"])
    observed = next(item for item in body["corporate_entities"] if item["entity_name"] == "Other Corp")
    assert observed["scope_facets"] == ["observed_organization"]
    assert not any(item["entity_name"] == "Hidden Corp" for item in body["corporate_entities"])
    assert isinstance(body["keymen"], list)
    assert not any(item["person_name"] == "Other Corp Only" for item in body["keymen"])
    assert not any(item["person_name"] == "Demo Grant Only" for item in body["keymen"])
    ada_west = next(item for item in body["keymen"] if item["person_name"] == "Ada West")
    assert ada_west["person_side_code"] == "our_side"
    # Live UI finding (2026-08-19): the Customer Master Keymen list falls
    # back to person_side_label, not the raw code, whenever
    # last_known_job_title is null -- confirm the label is actually a
    # human label from common_lookup_value, not the bare code repeated.
    assert ada_west["person_side_label"] not in ("", "our_side")

    network = {row["counterparty_entity_name"]: row for row in body["relationship_network"]}
    assert demo_child_id not in relationship_entity_ids
    assert "Private Other Corp" not in network
    northridge = network["Northridge Grid"]
    assert northridge["multi_role"] is True
    assert {rel["relationship_type_code"] for rel in northridge["relationships"]} == {"rel_voc", "rel_voco"}
    for rel in northridge["relationships"]:
        assert rel["post_count"] == 1
        assert rel["relationship_label"] not in ("", rel["relationship_type_code"])
    solo = network["Solo Role Corp"]
    assert solo["multi_role"] is False
    assert [rel["relationship_type_code"] for rel in solo["relationships"]] == ["rel_vos"]
    # Neither counterparty name matches a cataloged corporate_entity in
    # this fixture -- resolution stays null rather than guessing.
    assert northridge["corporate_entity_id"] is None
    assert solo["corporate_entity_id"] is None
    assert body["source_customer_hints"] == [
        {
            "customer_code": "TEST-CUSTOMER-001",
            "customer_name": None,
            "post_count": 1,
            "related_posts": [{
                "post_id": seeded_db["public_post_id"],
                "post_title": "Public post",
            }],
            "resolution_status": "hint_only",
            "hint_trust": "normal",
            "provenance": "source_post.source_customer_code/source_post.source_customer_name",
        }
    ]
    filtered_response = client.get(
        "/api/customer-master?hint_code=TEST-CUSTOMER-001",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert filtered_response.status_code == 200
    assert filtered_response.json()["source_customer_hints"] == body["source_customer_hints"]
    missing_response = client.get(
        "/api/customer-master?hint_code=NOT-OBSERVED",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert missing_response.status_code == 200
    assert missing_response.json()["source_customer_hints"] == []
    author_hint = body["source_author_hints"]
    assert len(author_hint) == 1
    assert author_hint[0]["author_code"] == "TEST-AUTHOR-001"
    assert author_hint[0]["author_name"] == "Test Author"
    assert author_hint[0]["author_account_id"]
    assert author_hint[0]["account_display_name"] == "Test Analyst"
    assert author_hint[0]["keyman_hints"] == [
        {
            "person_id": seeded_db["our_person_id"],
            "person_name": "Ada West",
            "person_side_code": "our_side",
            "last_known_job_title": None,
            "mention_count": 1,
                "provenance": "post_person_mention.person_id|post_summary_role.cataloged_person_id/source_post.author_account_id",
        }
    ]
    assert author_hint[0]["related_posts"] == [
        {
            "post_id": seeded_db["public_post_id"],
            "post_title": "Public post",
        }
    ]
    assert author_hint[0]["resolution_status"] == "our_side_context_only"
    assert any(
        affiliation["entity_name"] == "Test Corp"
        for affiliation in author_hint[0]["account_affiliations"]
    )
    assert any(
        affiliation["entity_name"] == "Granted Corp"
        for affiliation in author_hint[0]["account_affiliations"]
    )
    assert not any(
        affiliation["entity_name"] == "Demo Granted Child"
        for affiliation in author_hint[0]["account_affiliations"]
    )
    assert "account_affiliation.corporate_entity_id" in author_hint[0]["provenance"]


def test_customer_master_scope_facets_reflect_authorization_and_observed_evidence(
    client, demo_analyst_token, seeded_db
) -> None:
    """ADR 0125: an entity's scope_facets must reflect exactly how it was
    admitted -- an account's own affiliation, a granted affiliation, an
    organization actually mentioned in a post the account may see -- and
    private evidence must never add a node the account cannot otherwise see.
    """
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "update account_affiliation set affiliation_scope_code = 'scope_own_entity' "
                "where corporate_entity_id = %s",
                (seeded_db["own_corp_id"],),
            )
            cur.execute(
                "insert into corporate_entity (corporate_entity_code, entity_name, entity_level_code) "
                "values ('CASE-GRANTED-CORP', 'Case Granted Corp', 'company') returning corporate_entity_id"
            )
            granted_corp_id = cur.fetchone()[0]
            cur.execute(
                "select user_account_id from account_affiliation where corporate_entity_id = %s",
                (seeded_db["own_corp_id"],),
            )
            account_id = cur.fetchone()[0]
            cur.execute(
                "insert into account_affiliation "
                "(user_account_id, corporate_entity_id, affiliation_scope_code) "
                "values (%s, %s, 'scope_granted_entity')",
                (account_id, granted_corp_id),
            )
            # Deliberately no scope_code override -- proves the column's
            # own default lands new/unaudited affiliations on the honest
            # "unclassified" state rather than a guessed own/granted label.
            cur.execute(
                "insert into corporate_entity (corporate_entity_code, entity_name, entity_level_code) "
                "values ('UNCLASSIFIED-CORP', 'Case Unclassified Corp', 'company') returning corporate_entity_id"
            )
            unclassified_corp_id = cur.fetchone()[0]
            cur.execute(
                "insert into account_affiliation (user_account_id, corporate_entity_id) values (%s, %s)",
                (account_id, unclassified_corp_id),
            )
            # Observed via a post the account may see -- never affiliated,
            # so it can only reach the response through evidence.
            cur.execute(
                "insert into corporate_entity (corporate_entity_code, entity_name, entity_level_code) "
                "values ('OBSERVED-CORP', 'Case Observed Corp', 'company') returning corporate_entity_id"
            )
            observed_corp_id = cur.fetchone()[0]
            # Enter the real-source branch used by production to hide
            # demo-only entities once imported source context exists.
            cur.execute(
                "update source_post set source_customer_code = %s where post_id = %s",
                ("CASE-CUSTOMER-001", seeded_db["own_private_post_id"]),
            )
            cur.execute(
                "insert into post_organization_mention (post_id, corporate_entity_id) values (%s, %s)",
                (seeded_db["own_private_post_id"], observed_corp_id),
            )
            cur.execute(
                "insert into post_organization_mention (post_id, corporate_entity_id) values (%s, %s)",
                (seeded_db["public_post_id"], observed_corp_id),
            )
            cur.execute(
                "insert into corporate_entity (corporate_entity_code, entity_name, entity_level_code) "
                "values ('DEMO-CAP-CORP', 'Demo Cap Corp', 'company') returning corporate_entity_id"
            )
            demo_cap_corp_id = cur.fetchone()[0]
            for post_id in (
                seeded_db["public_post_id"],
                seeded_db["own_private_post_id"],
                seeded_db["late_own_private_post_id"],
                seeded_db["edited_own_post_id"],
            ):
                cur.execute(
                    "insert into post_organization_mention (post_id, corporate_entity_id) values (%s, %s)",
                    (post_id, demo_cap_corp_id),
                )
            for index in range(101):
                cur.execute(
                    "insert into corporate_entity "
                    "(corporate_entity_code, entity_name, entity_level_code) "
                    "values (%s, %s, 'company') returning corporate_entity_id",
                    (f"OBSERVED-FILLER-{index:03}", f"Observed Filler {index:03}"),
                )
                filler_corp_id = cur.fetchone()[0]
                cur.execute(
                    "insert into post_organization_mention (post_id, corporate_entity_id) "
                    "values (%s, %s)",
                    (seeded_db["own_private_post_id"], filler_corp_id),
                )
            # Observed only via a private post from another corp -- must
            # never surface, no matter how "real" the mention is.
            cur.execute(
                "insert into corporate_entity (corporate_entity_code, entity_name, entity_level_code) "
                "values ('HIDDEN-OBSERVED-CORP', 'Case Hidden Observed Corp', 'company') "
                "returning corporate_entity_id"
            )
            hidden_observed_corp_id = cur.fetchone()[0]
            cur.execute(
                "insert into post_organization_mention (post_id, corporate_entity_id) values (%s, %s)",
                (seeded_db["other_private_post_id"], hidden_observed_corp_id),
            )
        admin_conn.commit()
    finally:
        admin_conn.close()

    response = client.get(
        "/api/customer-master",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    entities = response.json()["corporate_entities"]
    facets_by_name = {row["entity_name"]: set(row["scope_facets"]) for row in entities}

    assert facets_by_name["Test Corp"] == {"authorized_own"}
    assert facets_by_name["Case Granted Corp"] == {"authorized_granted"}
    assert facets_by_name["Case Unclassified Corp"] == set()
    assert facets_by_name["Case Observed Corp"] == {"observed_organization"}
    assert "Demo Cap Corp" not in facets_by_name
    assert "Case Hidden Observed Corp" not in facets_by_name
    observed_entities = [
        row for row in entities if "observed_organization" in row["scope_facets"]
    ]
    assert len(observed_entities) == 100


def test_resolve_customer_hint_creates_and_links_a_corroborated_entity(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """A Customer Master hint (an opaque source_customer_code with no name)
    must resolve to a real corporate_entity only once external search
    corroborates the proposed name -- deterministic fake resolution/
    verification clients (not a real LLM or Searxng call) so this is
    CI-stable; the point under test is the resolve-then-persist wiring.
    """
    from lineageweave.relation_verification import STATUS_CORROBORATED, RelationVerificationResult

    _grant_post_admin(seeded_db["dsn"])
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            # corporate_entity_id is NOT NULL: a bulk-imported real record
            # defaults to whatever entity its author account is affiliated
            # with, never to a null "unresolved" sentinel. own_private_post_id
            # already sits at that exact default (its author's own
            # account_affiliation row) -- the case this endpoint reclaims.
            cur.execute(
                "update source_post set source_customer_code = %s where post_id = %s",
                ("HINT-CODE-001", seeded_db["own_private_post_id"]),
            )

        class _FakeResolutionClient:
            available = True

            def resolve(self, hint_code: str, context_text: str) -> str | None:
                assert hint_code == "HINT-CODE-001"
                return "Northridge Grid"

        class _FakeVerificationClient:
            available = True

            def verify(self, organization_name: str, relationship_label: str) -> RelationVerificationResult:
                assert organization_name == "Northridge Grid"
                return RelationVerificationResult(
                    status_code=STATUS_CORROBORATED, evidence_url="https://example.org/northridge"
                )

        monkeypatch.setattr(
            "backend.app.main._customer_hint_resolution_client", lambda: _FakeResolutionClient()
        )
        monkeypatch.setattr(
            "backend.app.main._relation_verification_client", lambda: _FakeVerificationClient()
        )

        response = client.post(
            "/api/customer-master/resolve-hint",
            json={"hint_code": "HINT-CODE-001"},
            headers={"Authorization": f"Bearer {demo_analyst_token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["entity_name"] == "Northridge Grid"
        assert body["linked_post_count"] == 1

        with admin_conn.cursor() as cur:
            cur.execute(
                "select entity_name, corporate_entity_code from corporate_entity where corporate_entity_id = %s",
                (body["corporate_entity_id"],),
            )
            entity_row = cur.fetchone()
            assert entity_row == ("Northridge Grid", "HINT-HINT-CODE-001")
            cur.execute(
                "select corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            assert str(cur.fetchone()[0]) == body["corporate_entity_id"]
    finally:
        admin_conn.close()


def test_resolve_customer_hint_requires_post_admin(client, demo_analyst_token, seeded_db) -> None:
    response = client.post(
        "/api/customer-master/resolve-hint",
        json={"hint_code": "HINT-CODE-001"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_post_list_includes_public_and_own_corp_but_excludes_other_corp(client, demo_analyst_token, seeded_db) -> None:
    response = client.get("/api/posts", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 200
    payload = response.json()
    titles = {post["post_title"] for post in payload["posts"]}
    assert titles == {
        "Public post",
        "Own-corp private post",
        "Late own-corp private post",
        "Edited own-corp private post",
    }
    public = next(post for post in payload["posts"] if post["post_title"] == "Public post")
    assert public["voc_type_label"] == "Voice of Customer"
    assert public["visibility_label"] == "Public"
    assert {option["code"] for option in payload["voc_type_options"]} == {"voc"}
    assert payload["source_detail_state_options"] == []
    assert {option["code"] for option in payload["visibility_options"]} == {"public", "private"}
    assert next(option for option in payload["visibility_options"] if option["code"] == "public")["label"] == "Public"


def test_post_list_filters_and_lists_source_detail_state_codes(
    client, demo_analyst_token, seeded_db
) -> None:
    conn = psycopg2.connect(seeded_db["dsn"])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select user_account_id from user_account "
                "where email_address = 'other.analyst@example.test'"
            )
            other_account_id = cur.fetchone()[0]
            cur.execute(
                """
                update source_post
                   set source_detail_state_code = case post_title
                       when 'Public post' then ' W '
                       when 'Own-corp private post' then ' D '
                       when 'Late own-corp private post' then ' A '
                       when 'Edited own-corp private post' then ' W '
                       else source_detail_state_code
                   end
                 where post_title in (
                    'Public post', 'Own-corp private post',
                    'Late own-corp private post', 'Edited own-corp private post'
                 )
                """
            )
            cur.execute(
                "update source_post set author_account_id = %s where post_title = %s",
                (other_account_id, "Edited own-corp private post"),
            )
            cur.execute(
                "update source_post set corporate_entity_id = %s, visibility_code = 'private' "
                "where post_title = %s",
                (seeded_db["other_corp_id"], "Public post"),
            )
        conn.commit()
    finally:
        conn.close()

    headers = {"Authorization": f"Bearer {demo_analyst_token}"}
    listed = client.get("/api/posts", headers=headers)
    assert listed.status_code == 200, listed.text
    assert {
        option["code"] for option in listed.json()["source_detail_state_options"]
    } == {"A", "D", "W"}
    assert {post["post_title"] for post in listed.json()["posts"]} == {
        "Public post",
        "Own-corp private post",
        "Late own-corp private post",
    }

    blank_filter = client.get("/api/posts?source_detail_state=", headers=headers)
    assert blank_filter.status_code == 200, blank_filter.text
    assert {post["post_title"] for post in blank_filter.json()["posts"]} == {
        "Public post",
        "Own-corp private post",
        "Late own-corp private post",
    }

    blank_voc_filter = client.get("/api/posts?voc_type=", headers=headers)
    assert blank_voc_filter.status_code == 200, blank_voc_filter.text
    assert {post["post_title"] for post in blank_voc_filter.json()["posts"]} == {
        "Public post",
        "Own-corp private post",
        "Late own-corp private post",
    }

    filtered = client.get("/api/posts?source_detail_state=D", headers=headers)
    assert filtered.status_code == 200, filtered.text
    assert [post["post_title"] for post in filtered.json()["posts"]] == [
        "Own-corp private post"
    ]

    writing = client.get("/api/posts?source_detail_state=W", headers=headers)
    assert writing.status_code == 200, writing.text
    assert {post["post_title"] for post in writing.json()["posts"]} == {"Public post"}

    authored_detail = client.get(
        f"/api/posts/{seeded_db['public_post_id']}", headers=headers
    )
    assert authored_detail.status_code == 200, authored_detail.text
    summary = client.get(
        f"/api/posts/{seeded_db['public_post_id']}/summary", headers=headers
    )
    assert summary.status_code == 422
    assert "not analysis targets" in summary.json()["detail"]
    for derived_path in (
        "content",
        "five-w1h",
        "keymen",
        "counterparties",
        "lineage",
        "knowledge-graph",
        "evaluation",
        "chat",
    ):
        derived = client.get(
            f"/api/posts/{seeded_db['public_post_id']}/{derived_path}", headers=headers
        )
        assert derived.status_code == 422, (derived_path, derived.text)

    hidden_detail = client.get(
        f"/api/posts/{seeded_db['edited_own_post_id']}", headers=headers
    )
    assert hidden_detail.status_code == 403

    _grant_post_admin(seeded_db["dsn"])
    admin_list = client.get("/api/posts?source_detail_state=W", headers=headers)
    assert admin_list.status_code == 200, admin_list.text
    assert {post["post_title"] for post in admin_list.json()["posts"]} == {
        "Public post",
        "Edited own-corp private post",
    }


def test_post_list_supports_bounded_offset_pages(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        "/api/posts?limit=1&offset=1",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["posts"]) == 1
    assert response.json()["total_count"] == 4

    title_sorted = client.get(
        "/api/posts?limit=1&offset=0&sort=title",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert title_sorted.status_code == 200, title_sorted.text
    assert title_sorted.json()["posts"][0]["post_title"] == "Edited own-corp private post"

    invalid_sort = client.get(
        "/api/posts?sort=unsupported",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert invalid_sort.status_code == 422


def test_post_detail_uses_lookup_labels_not_raw_codes(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['public_post_id']}",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["voc_type_code"] == "voc"
    assert body["voc_type_label"] == "Voice of Customer"
    assert body["visibility_code"] == "public"
    assert body["visibility_label"] == "Public"


def test_post_detail_exposes_explicit_and_semantic_project_evidence(
    client, demo_analyst_token, seeded_db
) -> None:
    conn = psycopg2.connect(seeded_db["dsn"])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "update source_post set source_project_code = %s where post_id = %s",
                ("SOURCE-PROJECT-001", seeded_db["public_post_id"]),
            )
            cur.execute(
                """
                insert into post_project_mention
                    (post_id, project_key, project_name, evidence_text, mention_confidence,
                     ontology_iri, extraction_method)
                values (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    seeded_db["public_post_id"],
                    "semantic-project",
                    "Semantic project",
                    "project was described in the body",
                    0.82,
                    "https://contextualwisdomlab.github.io/lineageweave/ontology#Project",
                    "contextual_orchestrator_semantic",
                ),
            )
        conn.commit()
    finally:
        conn.close()
    response = client.get(
        f"/api/posts/{seeded_db['public_post_id']}",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    evidence = response.json()["project_evidence"]
    source = next(row for row in evidence if row["extraction_method"] == "source_field_hint")
    semantic = next(row for row in evidence if row["extraction_method"] == "contextual_orchestrator_semantic")
    assert source["resolution_status"] == "hint_only"
    assert source["confidence"] is None
    assert semantic["resolution_status"] == "semantic_candidate"
    assert semantic["ontology_label"] == "Project"

    listed = client.get(
        "/api/posts?search=semantic-project",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert listed.status_code == 200, listed.text
    listed_post = next(
        post for post in listed.json()["posts"] if post["post_id"] == seeded_db["public_post_id"]
    )
    assert listed_post["project_evidence"][0]["project_name"] == "Semantic project"
    assert listed_post["project_evidence"][0]["provenance"] == "post_project_mention.evidence_text"


def test_post_detail_as_of_returns_the_cutoff_known_body(
    client, demo_analyst_token, seeded_db
) -> None:
    """Opened marked titles compare two real sentences, not two clocks."""
    headers = {"Authorization": f"Bearer {demo_analyst_token}"}
    live = client.get(f"/api/posts/{seeded_db['edited_own_post_id']}", headers=headers)
    assert live.status_code == 200
    assert live.json()["post_body"] == "A January post rewritten after the run cutoff."
    assert "known_at" not in live.json()

    known = client.get(
        f"/api/posts/{seeded_db['edited_own_post_id']}",
        params={"as_of": "2026-01-12T12:00:00Z"},
        headers=headers,
    )
    assert known.status_code == 200
    body = known.json()
    assert body["post_body"] == "A January post rewritten after the run cutoff."
    assert body["known_at"]["post_body"] == "A January post before the rewrite."
    assert body["known_at"]["written_at"].startswith("2026-01-10")
    assert "postgresql://" not in str(body)

    missing = client.get(
        f"/api/posts/{seeded_db['edited_own_post_id']}",
        params={"as_of": "2026-01-01T00:00:00Z"},
        headers=headers,
    )
    assert missing.status_code == 200
    assert "known_at" not in missing.json()

    invalid = client.get(
        f"/api/posts/{seeded_db['edited_own_post_id']}",
        params={"as_of": "not-a-clock"},
        headers=headers,
    )
    assert invalid.status_code == 422


def test_persisted_summary_is_returned_without_an_llm(client, demo_analyst_token, seeded_db) -> None:
    """GET /api/posts/{id}/summary must serve a stored row even when the
    orchestrator is off -- otherwise a seeded demo popup stays empty.
    """
    os.environ.pop("ORCHESTRATOR_BASE_URL", None)
    os.environ.pop("ORCHESTRATOR_API_KEY", None)
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into post_summary_result "
                "(post_id, korean_summary, summary_contract_version) values (%s, %s, %s)",
                (
                    seeded_db["public_post_id"],
                    "저장된 한국어 요약입니다.",
                    POST_SUMMARY_CONTRACT_VERSION,
                ),
            )
            cur.execute(
                "insert into post_summary_event (post_id, event_ordinal, event_text) "
                "values (%s, 0, '저장된 이벤트')",
                (seeded_db["public_post_id"],),
            )
            cur.execute(
                "insert into post_summary_role "
                "(post_id, actor_name, responsibility_text, actor_type_code, affiliated_organization_name) "
                "values (%s, 'Ada West', '후속 연락', 'prov_person', 'Demo Corp')",
                (seeded_db["public_post_id"],),
            )
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/posts/{seeded_db['public_post_id']}/summary",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["korean_summary"] == "저장된 한국어 요약입니다."
    assert body["key_events"] == ["저장된 이벤트"]
    assert len(body["roles_and_responsibilities"]) == 1
    role = body["roles_and_responsibilities"][0]
    assert role["actor_name"] == "Ada West"
    assert role["responsibility"] == "후속 연락"
    assert role["actor_type_code"] == "prov_person"
    assert role["affiliated_organization_name"] == "Demo Corp"
    assert role["ontology_label"] == "Role actor (person)"


def test_stale_summary_is_returned_labeled_when_orchestrator_is_unavailable(
    client, demo_analyst_token, seeded_db
) -> None:
    """A legacy saved summary preserves reader continuity with an explicit label."""
    os.environ.pop("ORCHESTRATOR_BASE_URL", None)
    os.environ.pop("ORCHESTRATOR_API_KEY", None)
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into post_summary_result "
                "(post_id, korean_summary, summary_contract_version) values (%s, %s, %s)",
                (
                    seeded_db["public_post_id"],
                    "보관된 이전 계약 요약입니다.",
                    POST_SUMMARY_CONTRACT_VERSION - 1,
                ),
            )
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/posts/{seeded_db['public_post_id']}/summary",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary_status"] == "stale"
    assert body["summary_contract_version"] == POST_SUMMARY_CONTRACT_VERSION - 1
    assert body["korean_summary"] == "보관된 이전 계약 요약입니다."


def test_seed_demo_summary_surfaces_on_get_summary(client, demo_analyst_token, seeded_db) -> None:
    """The same helper `make seed` calls must produce a row GET summary
    returns -- even with the orchestrator unset.
    """
    os.environ.pop("ORCHESTRATOR_BASE_URL", None)
    os.environ.pop("ORCHESTRATOR_API_KEY", None)
    from scripts.seed_demo_data import _seed_demo_public_summary

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            _seed_demo_public_summary(cur, seeded_db["public_post_id"])
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/posts/{seeded_db['public_post_id']}/summary",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "에이다" in body["korean_summary"]
    assert body["key_events"]
    roles = {role["actor_name"]: role for role in body["roles_and_responsibilities"]}
    assert roles["Ada West"]["actor_type_code"] == "prov_person"
    assert roles["당사"]["actor_type_code"] == "prov_organization"
    assert roles["당사"]["ontology_label"] == "Role actor (organization)"


def test_seed_fixture_summaries_surface_on_get_summary(client, demo_analyst_token, seeded_db) -> None:
    """The A-100 fork and calendar commitment `make seed` writes must
    answer GET /api/posts/{id}/summary without a live orchestrator.
    """
    from scripts.seed_demo_data import (
        _seed_demo_calendar_commitment,
        _seed_fixture_summaries,
        insert_fixture_source_posts,
    )

    os.environ.pop("ORCHESTRATOR_BASE_URL", None)
    os.environ.pop("ORCHESTRATOR_API_KEY", None)
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('voc_type', 'vom', 'Voice of Market') "
                "on conflict (lookup_code) do nothing"
            )
            cur.execute(
                "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                "select corporate_entity_id, 'TEST-PU-SUMMARY', 'Summary thread' "
                "from source_post where post_id = %s returning process_unit_id",
                (seeded_db["own_private_post_id"],),
            )
            process_unit_id = cur.fetchone()[0]
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            insert_fixture_source_posts(cur, author_id, corp_id, process_unit_id)
            _seed_demo_calendar_commitment(cur, author_id, corp_id, process_unit_id)
            _seed_fixture_summaries(cur)
            cur.execute(
                "select post_id from source_post where post_title = %s",
                ("Pricing renegotiation follow-up",),
            )
            fork_id = str(cur.fetchone()[0])
            cur.execute(
                "select post_id from source_post where post_title = %s",
                ("Follow-up on the Riverbend order confirmation",),
            )
            calendar_id = str(cur.fetchone()[0])
    finally:
        admin_conn.close()

    fork = client.get(
        f"/api/posts/{fork_id}/summary",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert fork.status_code == 200, fork.text
    assert "재협상" in fork.json()["korean_summary"]
    assert fork.json()["key_events"]
    fork_roles = {role["actor_name"] for role in fork.json()["roles_and_responsibilities"]}
    assert fork_roles == {"Ada West", "Priya Nair"}

    calendar = client.get(
        f"/api/posts/{calendar_id}/summary",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert calendar.status_code == 200, calendar.text
    assert "리버벤드" in calendar.json()["korean_summary"]
    assert calendar.json()["roles_and_responsibilities"] == []

    missing = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/summary",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert missing.status_code == 503


def test_persisted_chat_is_returned_without_an_llm(client, demo_analyst_token, seeded_db) -> None:
    """POST /api/posts/{id}/chat must serve a stored row even when the
    orchestrator is off -- otherwise a seeded demo Ask stays empty.
    """
    os.environ.pop("ORCHESTRATOR_BASE_URL", None)
    os.environ.pop("ORCHESTRATOR_API_KEY", None)
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into post_chat_result (post_id, question_norm, question_text, answer_text) "
                "values (%s, 'what happened between these events', "
                "'What happened between these events?', 'Stored follow-up after the site visit.')",
                (seeded_db["public_post_id"],),
            )
            cur.execute(
                "insert into post_chat_citation "
                "(post_id, question_norm, citation_ordinal, cited_post_id) "
                "values (%s, 'what happened between these events', 0, %s)",
                (seeded_db["public_post_id"], seeded_db["public_post_id"]),
            )
    finally:
        admin_conn.close()

    asked = client.post(
        f"/api/posts/{seeded_db['public_post_id']}/chat",
        json={"question": "What happened?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert asked.status_code == 200, asked.text
    body = asked.json()
    assert body["answer_text"] == "Stored follow-up after the site visit."
    assert body["cited_post_ids"] == [seeded_db["public_post_id"]]
    assert body["cited_posts"] == [
        {"post_id": seeded_db["public_post_id"], "post_title": "Public post"}
    ]

    history = client.get(
        f"/api/posts/{seeded_db['public_post_id']}/chat",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert history.status_code == 200, history.text
    assert history.json()["exchanges"][0]["answer_text"] == "Stored follow-up after the site visit."


def test_seed_demo_chat_surfaces_on_get_and_post_chat(client, demo_analyst_token, seeded_db) -> None:
    """The same helper `make seed` calls must produce a row GET/POST chat
    return -- even with the orchestrator unset.
    """
    os.environ.pop("ORCHESTRATOR_BASE_URL", None)
    os.environ.pop("ORCHESTRATOR_API_KEY", None)
    from scripts.seed_demo_data import _seed_demo_public_chat

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "update source_post set post_title = 'Demo public post' where post_id = %s",
                (seeded_db["public_post_id"],),
            )
            _seed_demo_public_chat(cur, seeded_db["public_post_id"])
    finally:
        admin_conn.close()

    history = client.get(
        f"/api/posts/{seeded_db['public_post_id']}/chat",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert history.status_code == 200, history.text
    questions = [row["question_text"] for row in history.json()["exchanges"]]
    assert questions == [
        "What happened between these events?",
        "Who is involved?",
        "What is the next commitment?",
    ]
    assert "Northridge Grid" in history.json()["exchanges"][0]["answer_text"]
    assert "Ada West" in history.json()["exchanges"][1]["answer_text"]
    assert "Priya Nair" in history.json()["exchanges"][1]["answer_text"]
    assert "Send Northridge Grid the revised quote" in history.json()["exchanges"][2]["answer_text"]
    assert "2026-01-12" in history.json()["exchanges"][2]["answer_text"]

    asked = client.post(
        f"/api/posts/{seeded_db['public_post_id']}/chat",
        json={"question": "What happened between these events?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert asked.status_code == 200, asked.text
    assert "Northridge Grid" in asked.json()["answer_text"]

    involved = client.post(
        f"/api/posts/{seeded_db['public_post_id']}/chat",
        json={"question": "Who's involved?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert involved.status_code == 200, involved.text
    assert "Ada West" in involved.json()["answer_text"]
    assert "Priya Nair" in involved.json()["answer_text"]

    commitment = client.post(
        f"/api/posts/{seeded_db['public_post_id']}/chat",
        json={"question": "What's the next commitment?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert commitment.status_code == 200, commitment.text
    assert "Send Northridge Grid the revised quote" in commitment.json()["answer_text"]
    assert "2026-01-12" in commitment.json()["answer_text"]


def test_seed_fixture_chats_surface_on_post_chat(client, demo_analyst_token, seeded_db) -> None:
    """The A-100 fork and calendar commitment `make seed` writes must
    answer POST /api/posts/{id}/chat without a live orchestrator.
    """
    from scripts.seed_demo_data import (
        _seed_demo_calendar_commitment,
        _seed_fixture_chats,
        insert_fixture_source_posts,
    )

    os.environ.pop("ORCHESTRATOR_BASE_URL", None)
    os.environ.pop("ORCHESTRATOR_API_KEY", None)
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('voc_type', 'vom', 'Voice of Market') "
                "on conflict (lookup_code) do nothing"
            )
            cur.execute(
                "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                "select corporate_entity_id, 'TEST-PU-CHAT', 'Chat thread' "
                "from source_post where post_id = %s returning process_unit_id",
                (seeded_db["own_private_post_id"],),
            )
            process_unit_id = cur.fetchone()[0]
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            insert_fixture_source_posts(cur, author_id, corp_id, process_unit_id)
            _seed_demo_calendar_commitment(cur, author_id, corp_id, process_unit_id)
            _seed_fixture_chats(cur)
            cur.execute(
                "select post_id from source_post where post_title = %s",
                ("Pricing renegotiation follow-up",),
            )
            fork_id = str(cur.fetchone()[0])
            cur.execute(
                "select post_id from source_post where post_title = %s",
                ("Follow-up on the Riverbend order confirmation",),
            )
            calendar_id = str(cur.fetchone()[0])
    finally:
        admin_conn.close()

    fork = client.post(
        f"/api/posts/{fork_id}/chat",
        json={"question": "What happened between these events?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert fork.status_code == 200, fork.text
    assert "pricing renegotiation" in fork.json()["answer_text"].lower()
    assert fork.json()["cited_posts"]

    fork_involved = client.post(
        f"/api/posts/{fork_id}/chat",
        json={"question": "Who is involved?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert fork_involved.status_code == 200, fork_involved.text
    assert "Ada West" in fork_involved.json()["answer_text"]
    assert "Priya Nair" in fork_involved.json()["answer_text"]

    fork_history = client.get(
        f"/api/posts/{fork_id}/chat",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert fork_history.status_code == 200, fork_history.text
    assert [row["question_text"] for row in fork_history.json()["exchanges"]] == [
        "What happened between these events?",
        "Who is involved?",
        "What is the next commitment?",
    ]

    fork_commitment = client.post(
        f"/api/posts/{fork_id}/chat",
        json={"question": "What is the next commitment?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert fork_commitment.status_code == 200, fork_commitment.text
    assert "Send Northridge Grid the revised quote" in fork_commitment.json()["answer_text"]
    assert "2026-01-12" in fork_commitment.json()["answer_text"]

    calendar = client.post(
        f"/api/posts/{calendar_id}/chat",
        json={"question": "What happened?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert calendar.status_code == 200, calendar.text
    assert "Riverbend" in calendar.json()["answer_text"]

    calendar_involved = client.post(
        f"/api/posts/{calendar_id}/chat",
        json={"question": "Who is involved?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert calendar_involved.status_code == 200, calendar_involved.text
    assert "does not name a Keyman" in calendar_involved.json()["answer_text"]

    calendar_commitment = client.post(
        f"/api/posts/{calendar_id}/chat",
        json={"question": "What is the next commitment?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert calendar_commitment.status_code == 200, calendar_commitment.text
    assert "Send Riverbend the revised delivery schedule" in calendar_commitment.json()["answer_text"]
    assert "2026-01-09" in calendar_commitment.json()["answer_text"]

    missing = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/chat",
        json={"question": "What happened between these events?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert missing.status_code == 503

    unknown = client.post(
        f"/api/posts/{fork_id}/chat",
        json={"question": "What is the weather in Gwangju?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert unknown.status_code == 503


def test_own_corp_private_post_detail_is_readable(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}", headers={"Authorization": f"Bearer {demo_analyst_token}"}
    )
    assert response.status_code == 200
    assert "Test Corp" in response.json()["post_body"]


def test_other_corp_private_post_detail_is_forbidden(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['other_private_post_id']}", headers={"Authorization": f"Bearer {demo_analyst_token}"}
    )
    assert response.status_code == 403


def test_nonexistent_post_is_not_found(client, demo_analyst_token) -> None:
    response = client.get(
        f"/api/posts/{uuid.uuid4()}", headers={"Authorization": f"Bearer {demo_analyst_token}"}
    )
    assert response.status_code == 404


def test_missing_token_is_unauthorized(client) -> None:
    response = client.get("/api/posts")
    assert response.status_code in (401, 403)


def test_forged_token_is_rejected(client) -> None:
    forged = jwt.encode({"sub": "not-a-real-subject", "iss": f"{_KEYCLOAK_BASE_URL}/realms/{_REALM}"}, key="wrong-key", algorithm="HS256")
    response = client.get("/api/posts", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_own_corp_post_keymen_are_readable(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    names = {person["person_name"]: person for person in response.json()["keymen"]}
    assert set(names) == {"Ada West", "Priya Nair"}
    assert names["Ada West"]["person_side_code"] == "our_side"
    assert names["Ada West"]["person_side_label"] == "Our side"
    assert names["Priya Nair"]["person_side_code"] == "counterparty"
    assert names["Priya Nair"]["person_side_label"] == "Counterparty"
    assert {aff["organization_name"] for aff in names["Priya Nair"]["affiliations"]} == {
        "Northridge Grid",
        "Northridge Holdings",
    }
    context = response.json()["source_author_context"]
    assert context["account_display_name"] == "Test Analyst"
    assert context["resolution_status"] == "our_side_context_only"
    assert any(affiliation["entity_name"] == "Test Corp" for affiliation in context["account_affiliations"])


def test_other_corp_private_post_keymen_are_forbidden(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['other_private_post_id']}/keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_affiliate_tree_walks_ancestors_and_keeps_unresolved_orgs(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/affiliate-tree",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    trees = response.json()["trees"]
    names = [node["entity_name"] for node in trees]
    assert names[0] == "Test Group"
    assert trees[0]["entity_id"] == seeded_db["own_group_id"]
    assert trees[0]["resolved"] is True
    assert trees[0]["entity_level_label"] == "Group"
    children = trees[0]["children"]
    assert [child["entity_name"] for child in children] == ["Test Corp"]
    assert children[0]["entity_id"] == seeded_db["own_corp_id"]
    assert children[0]["entity_level_label"] == "Company"
    assert {person["person_name"] for person in children[0]["people"]} == {"Ada West"}
    assert children[0]["people"][0]["person_side_label"] == "Our side"
    unresolved = [node for node in trees if node["resolved"] is False]
    assert {node["entity_name"] for node in unresolved} == {"Northridge Grid", "Northridge Holdings"}
    assert all(person["person_name"] == "Priya Nair" for node in unresolved for person in node["people"])


def test_other_corp_private_affiliate_tree_is_forbidden(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['other_private_post_id']}/affiliate-tree",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_voc_evidence_quotes_the_sentence_that_names_the_org(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/voc-evidence",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["voc_type_code"] == "voc"
    assert body["voc_type_label"] == "Voice of Customer"
    assert body["excerpts"] == [
        "Ada West at Test Corp followed up with Priya Nair at Northridge Grid about the delayed shipment."
    ]
    assert "weather" not in " ".join(body["excerpts"]).lower()
    assert body["counterparties"] == []


def test_voc_evidence_includes_verification_status(client, demo_analyst_token, seeded_db) -> None:
    """GET /voc-evidence must carry the counterparty verification badge
    fields -- the VOC panel is not a second unverified claim list.
    """
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into post_counterparty_entity "
                "(post_id, counterparty_entity_name, relationship_type_code, "
                " verification_status_code, verification_evidence_url) "
                "values (%s, 'Northridge Grid', 'rel_voc', 'verify_pending', null)",
                (seeded_db["own_private_post_id"],),
            )
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/voc-evidence",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["counterparties"]
    assert len(rows) == 1
    assert rows[0]["counterparty_entity_name"] == "Northridge Grid"
    assert rows[0]["verification_status_code"] == "verify_pending"
    assert rows[0]["verification_evidence_url"] is None


def test_other_corp_private_voc_evidence_is_forbidden(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['other_private_post_id']}/voc-evidence",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_related_keymen_use_rwr_and_hide_invisible_posts(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/keymen/{seeded_db['our_person_id']}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["person_name"] == "Ada West"
    related_ids = {node["node_id"] for node in body["related"]}
    assert seeded_db["counterpart_person_id"] in related_ids
    assert seeded_db["own_private_post_id"] in related_ids
    assert seeded_db["hidden_person_id"] not in related_ids
    assert seeded_db["other_private_post_id"] not in related_ids
    assert all(node["relevance"] > 0 for node in body["related"])
    by_id = {node["node_id"]: node for node in body["related"]}
    counterpart = by_id[seeded_db["counterpart_person_id"]]
    assert counterpart["ontology_label"] == "Person"
    assert counterpart["ontology_iri"].endswith("#Person")
    assert counterpart["person_side_code"] == "counterparty"
    assert counterpart["person_side_label"] == "Counterparty"
    own_post = by_id[seeded_db["own_private_post_id"]]
    assert own_post["ontology_label"] == "Post"


def test_related_keymen_includes_chronological_role_history(client, demo_analyst_token, seeded_db) -> None:
    """Feature request (2026-08-19): clicking a Keyman should show which
    company they were affiliated with and how their responsibility
    changed over time, not just the RWR-related node list.
    """
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    try:
        with admin_conn.cursor() as cur:
            # Two visible posts, given a known chronological order, each
            # classifying a different role/organization for the same
            # cataloged person -- simulating a real job change.
            cur.execute(
                "update source_post set created_at = %s where post_id = %s",
                ("2026-01-01T00:00:00+00:00", seeded_db["own_private_post_id"]),
            )
            cur.execute(
                "update source_post set created_at = %s where post_id = %s",
                ("2026-06-01T00:00:00+00:00", seeded_db["public_post_id"]),
            )
            for post_id, summary in (
                (seeded_db["own_private_post_id"], "early summary"),
                (seeded_db["public_post_id"], "later summary"),
            ):
                cur.execute(
                    "insert into post_summary_result (post_id, korean_summary, summary_contract_version) "
                    "values (%s, %s, %s)",
                    (post_id, summary, POST_SUMMARY_CONTRACT_VERSION),
                )
            cur.execute(
                "insert into post_summary_role "
                "(post_id, actor_name, responsibility_text, actor_type_code, affiliated_organization_name, cataloged_person_id) "
                "values (%s, %s, %s, %s, %s, %s)",
                (
                    seeded_db["own_private_post_id"],
                    "Ada West",
                    "junior account rep",
                    "prov_person",
                    "Northwind Labs",
                    seeded_db["our_person_id"],
                ),
            )
            cur.execute(
                "insert into post_summary_role "
                "(post_id, actor_name, responsibility_text, actor_type_code, affiliated_organization_name, cataloged_person_id) "
                "values (%s, %s, %s, %s, %s, %s)",
                (
                    seeded_db["public_post_id"],
                    "Ada West",
                    "account lead",
                    "prov_person",
                    "Test Corp",
                    seeded_db["our_person_id"],
                ),
            )
        admin_conn.commit()
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/keymen/{seeded_db['our_person_id']}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    history = body["role_history"]
    assert [row["post_id"] for row in history] == [
        seeded_db["own_private_post_id"],
        seeded_db["public_post_id"],
    ]
    assert history[0]["responsibility"] == "junior account rep"
    assert history[0]["affiliated_organization_name"] == "Northwind Labs"
    assert history[1]["responsibility"] == "account lead"
    assert history[1]["affiliated_organization_name"] == "Test Corp"
    assert history[0]["created_at"] < history[1]["created_at"]


def test_related_keymen_role_history_is_empty_without_any_role_classification(
    client, demo_analyst_token, seeded_db
) -> None:
    """No post_summary_role rows for this person -- an empty history is
    the correct, non-fabricated answer, not an error.
    """
    response = client.get(
        f"/api/keymen/{seeded_db['our_person_id']}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    assert response.json()["role_history"] == []


def test_related_corporate_entity_uses_rwr_and_hides_invisible_posts(
    client, demo_analyst_token, seeded_db
) -> None:
    """GET /api/corporate-entities/{id}/related must walk from the org
    the same way Keyman related walks from a person.
    """
    response = client.get(
        f"/api/corporate-entities/{seeded_db['own_corp_id']}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entity_name"] == "Test Corp"
    related_ids = {node["node_id"] for node in body["related"]}
    assert seeded_db["our_person_id"] in related_ids
    our_person = next(node for node in body["related"] if node["node_id"] == seeded_db["our_person_id"])
    assert our_person["person_side_code"] == "our_side"
    assert our_person["person_side_label"] == "Our side"
    assert seeded_db["other_private_post_id"] not in related_ids
    assert seeded_db["hidden_person_id"] not in related_ids


def test_corporate_entity_with_no_visible_affiliation_is_forbidden(
    client, demo_analyst_token, seeded_db
) -> None:
    """Other Corp exists but no visible person is affiliated with it."""
    response = client.get(
        f"/api/corporate-entities/{seeded_db['other_corp_id']}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_unknown_corporate_entity_related_is_not_found(
    client, demo_analyst_token, seeded_db
) -> None:
    response = client.get(
        f"/api/corporate-entities/{uuid.uuid4()}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 404


def test_team_only_on_other_corp_private_post_is_forbidden(
    client, demo_analyst_token, seeded_db
) -> None:
    """A team mentioned only on another corp's private post must 403."""

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into cataloged_team (team_name, affiliated_organization_name) "
                "values ('비공개 설계팀', 'Other Corp') returning team_id"
            )
            team_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into post_team_mention (post_id, team_id) values (%s, %s)",
                (seeded_db["other_private_post_id"], team_id),
            )
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/teams/{team_id}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_unknown_team_related_is_not_found(client, demo_analyst_token) -> None:
    """An unknown team UUID must 404, matching person and entity related."""

    response = client.get(
        f"/api/teams/{uuid.uuid4()}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 404


def test_keyman_only_on_other_corp_private_post_is_forbidden(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/keymen/{seeded_db['hidden_person_id']}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_extract_keymen_requires_post_admin(client, demo_analyst_token, seeded_db) -> None:
    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/extract-keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_extract_keymen_and_verify_relations_publish_activity_events(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """Live gap (2026-08-19): extract-keymen and verify-relations are real,
    consequential write actions (an LLM call, an external-search call) but
    never published anything to the post's activity feed -- only ticket
    mutations did. An operator reviewing a post's history had no way to
    see that Keymen extraction or relation verification ever ran on it.
    """
    from lineageweave.keyman_extraction import OUR_SIDE, PersonMention
    from lineageweave.relation_verification import STATUS_UNCORROBORATED, RelationVerificationResult

    _grant_post_admin(seeded_db["dsn"])

    class _FakeKeymanClient:
        available = True

        def extract(self, post_title: str, post_body: str) -> list[PersonMention]:
            return [PersonMention(person_name="Kim Cheolsu", person_side_code=OUR_SIDE)]

    class _FakeRelationshipClient:
        available = True

        def classify(self, post_title: str, post_body: str, organization_names: list[str]):
            return []

    class _FakeVerificationClient:
        available = True

        def verify(self, organization_name: str, relationship_label: str) -> RelationVerificationResult:
            return RelationVerificationResult(status_code=STATUS_UNCORROBORATED, evidence_url=None)

    monkeypatch.setattr("backend.app.main._keyman_extraction_client", lambda: _FakeKeymanClient())
    monkeypatch.setattr("backend.app.main._entity_relationship_client", lambda: _FakeRelationshipClient())
    monkeypatch.setattr("backend.app.main._relation_verification_client", lambda: _FakeVerificationClient())

    post_id = seeded_db["own_private_post_id"]
    extract_response = client.post(
        f"/api/posts/{post_id}/extract-keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert extract_response.status_code == 200, extract_response.text

    verify_response = client.post(
        f"/api/posts/{post_id}/verify-relations",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert verify_response.status_code == 200, verify_response.text

    activity_response = client.get(
        f"/api/posts/{post_id}/activity",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    events = activity_response.json()["events"]
    event_types = [event["event_type"] for event in events]
    # XREVRANGE returns newest first: verify-relations ran second.
    assert event_types == ["relations_verified", "keymen_extracted"]
    assert "1 mention" in events[1]["summary"]


_ORCHESTRATOR_BASE_URL = os.environ.get("LINEAGEWEAVE_TEST_ORCHESTRATOR_BASE_URL")
_ORCHESTRATOR_API_KEY = os.environ.get("LINEAGEWEAVE_TEST_ORCHESTRATOR_API_KEY")


def test_extract_keymen_never_classifies_an_org_named_only_by_our_side_mentions(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """Live bug (2026-08-19): an organization affiliated ONLY with an
    our_side person (our own factory, our own affiliate) got fed into the
    counterparty-relationship classifier the same as any external org --
    forced to pick from six codes that all assume an external
    counterparty, it had no correct answer and landed on the closest
    wrong one (observed live as "Partner"). Only a counterparty-side
    mention's affiliated organizations may reach that classifier.
    """
    from lineageweave.keyman_extraction import COUNTERPARTY, OUR_SIDE, PersonMention

    _grant_post_admin(seeded_db["dsn"])

    class _FakeKeymanClient:
        available = True

        def extract(self, post_title: str, post_body: str) -> list[PersonMention]:
            return [
                PersonMention(
                    person_name="Kim Cheolsu",
                    person_side_code=OUR_SIDE,
                    affiliated_organization_names=("Our Own Factory",),
                ),
                PersonMention(
                    person_name="Lee Younghee",
                    person_side_code=COUNTERPARTY,
                    affiliated_organization_names=("Acme Corp",),
                ),
            ]

    classified_names: list[str] = []

    class _FakeRelationshipClient:
        available = True

        def classify(self, post_title: str, post_body: str, organization_names: list[str]):
            classified_names.extend(organization_names)
            return []

    monkeypatch.setattr("backend.app.main._keyman_extraction_client", lambda: _FakeKeymanClient())
    monkeypatch.setattr("backend.app.main._entity_relationship_client", lambda: _FakeRelationshipClient())

    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/extract-keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    assert classified_names == ["Acme Corp"]


def test_extract_keymen_does_not_merge_same_name_people_with_conflicting_titles(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """Two different real people can share a name -- extracting a second
    post that names the same person_name+side but a genuinely different
    stated job_title must NOT reuse the first post's cataloged_person row.
    A deterministic fake client (not a real orchestrator call) so this
    is CI-stable: the point under test is `_upsert_person`'s own SQL
    logic, not LLM extraction quality.
    """
    from lineageweave.keyman_extraction import COUNTERPARTY, PersonMention

    _grant_post_admin(seeded_db["dsn"])

    class _FakeClient:
        available = True

        def __init__(self, job_title: str) -> None:
            self._job_title = job_title

        def extract(self, post_title: str, post_body: str) -> list[PersonMention]:
            return [PersonMention(person_name="Kim Cheolsu", person_side_code=COUNTERPARTY, job_title=self._job_title)]

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            post_ids = []
            for title in ("Sales follow-up", "Purchasing follow-up"):
                cur.execute(
                    "insert into source_post (author_account_id, corporate_entity_id, post_title, post_body, voc_type_code, visibility_code) "
                    "select author_account_id, corporate_entity_id, %s, %s, 'voc', 'public' "
                    "from source_post where post_id = %s "
                    "returning post_id",
                    (title, "placeholder body", seeded_db["own_private_post_id"]),
                )
                post_ids.append(str(cur.fetchone()[0]))
    finally:
        admin_conn.close()

    monkeypatch.setattr("backend.app.main._entity_relationship_client", lambda: _FakeClient("unused"))

    monkeypatch.setattr("backend.app.main._keyman_extraction_client", lambda: _FakeClient("Sales Manager"))
    response_a = client.post(
        f"/api/posts/{post_ids[0]}/extract-keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response_a.status_code == 200, response_a.text

    monkeypatch.setattr("backend.app.main._keyman_extraction_client", lambda: _FakeClient("Purchasing Lead"))
    response_b = client.post(
        f"/api/posts/{post_ids[1]}/extract-keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response_b.status_code == 200, response_b.text

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select count(distinct person_id) from cataloged_person where person_name = 'Kim Cheolsu'"
            )
            distinct_people = cur.fetchone()[0]
    finally:
        admin_conn.close()

    assert distinct_people == 2, "conflicting stated job titles for the same name must not be merged into one person"


def test_extract_keymen_resolves_and_caches_an_abbreviated_organization_name(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """ADR 0008: an affiliated organization named by abbreviation
    ("AGP") must be resolved to its canonical name
    ("Aurora Grid Power") and cross-verified before that name is trusted --
    deterministic fake resolution/verification clients (not a real LLM
    or Searxng call) so this is CI-stable; the point under test is the
    resolve-then-persist wiring, not model/search quality.
    """
    from lineageweave.keyman_extraction import COUNTERPARTY, PersonMention
    from lineageweave.relation_verification import STATUS_CORROBORATED, RelationVerificationResult

    _grant_post_admin(seeded_db["dsn"])

    class _FakeKeymanClient:
        available = True

        def extract(self, post_title: str, post_body: str) -> list[PersonMention]:
            return [
                PersonMention(
                    person_name="Kim Cheolsu",
                    person_side_code=COUNTERPARTY,
                    affiliated_organization_names=("AGP",),
                )
            ]

    class _FakeRelationshipClient:
        available = True

        def classify(self, post_title: str, post_body: str, organization_names: list[str]):
            return []

    class _FakeResolutionClient:
        available = True

        def resolve(self, raw_name: str, context_text: str) -> str | None:
            assert raw_name == "AGP"
            return "Aurora Grid Power"

    class _FakeVerificationClient:
        available = True

        def verify(self, organization_name: str, relationship_label: str) -> RelationVerificationResult:
            assert organization_name == "Aurora Grid Power"
            assert relationship_label == "AGP"
            return RelationVerificationResult(
                status_code=STATUS_CORROBORATED, evidence_url="https://example.org/khnp"
            )

    monkeypatch.setattr("backend.app.main._keyman_extraction_client", lambda: _FakeKeymanClient())
    monkeypatch.setattr("backend.app.main._entity_relationship_client", lambda: _FakeRelationshipClient())
    monkeypatch.setattr(
        "backend.app.main._organization_name_resolution_client", lambda: _FakeResolutionClient()
    )
    monkeypatch.setattr("backend.app.main._relation_verification_client", lambda: _FakeVerificationClient())

    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/extract-keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select resolved_organization_name, verification_status_code, verification_evidence_url "
                "from organization_name_resolution where raw_organization_name = 'AGP'"
            )
            cached = cur.fetchone()
            cur.execute(
                "select pa.affiliated_organization_name from person_affiliation pa "
                "join cataloged_person cp on cp.person_id = pa.person_id "
                "where cp.person_name = 'Kim Cheolsu'"
            )
            affiliation_name = cur.fetchone()[0]
    finally:
        admin_conn.close()

    assert cached == ("Aurora Grid Power", STATUS_CORROBORATED, "https://example.org/khnp")
    assert affiliation_name == "Aurora Grid Power", "a corroborated resolution must be the stored affiliation name"


def test_same_team_named_in_two_posts_resolves_to_one_cataloged_team(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """ADR 0009: extraction runs per-post, but "설계팀" (design team) at
    the same company named in two different posts must resolve to the
    same cataloged_team row -- otherwise every extraction is an island
    and can never become a cross-post Knowledge Graph clue. A
    deterministic fake summary client (not a real LLM call) so this is
    CI-stable; the point under test is the upsert-then-dedupe wiring.
    """
    from lineageweave.post_summary import ACTOR_TYPE_TEAM, PostSummary, RoleResponsibility

    class _FakeSummaryClient:
        available = True

        def summarize(self, post_title: str, post_body: str) -> PostSummary:
            return PostSummary(
                korean_summary="설계팀이 도면을 검토했다.",
                roles_and_responsibilities=(
                    RoleResponsibility(
                        actor_name="설계팀",
                        responsibility="도면 검토",
                        actor_type_code=ACTOR_TYPE_TEAM,
                        affiliated_organization_name="Demo Corp",
                    ),
                ),
            )

    monkeypatch.setattr("backend.app.main._post_summary_client", lambda: _FakeSummaryClient())

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            post_ids = []
            for title in ("설계 검토 회의 1", "설계 검토 회의 2"):
                cur.execute(
                    "insert into source_post (author_account_id, corporate_entity_id, post_title, post_body, voc_type_code, visibility_code) "
                    "select author_account_id, corporate_entity_id, %s, %s, 'voc', 'public' "
                    "from source_post where post_id = %s returning post_id",
                    (title, "placeholder body", seeded_db["own_private_post_id"]),
                )
                post_ids.append(str(cur.fetchone()[0]))
    finally:
        admin_conn.close()

    headers = {"Authorization": f"Bearer {demo_analyst_token}"}
    for post_id in post_ids:
        response = client.get(f"/api/posts/{post_id}/summary", headers=headers)
        assert response.status_code == 200, response.text

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute("select count(*), count(distinct team_id) from cataloged_team where team_name = '설계팀'")
            team_row_count, distinct_team_count = cur.fetchone()
            cur.execute(
                "select count(distinct pt.post_id) from post_team_mention pt "
                "join cataloged_team ct on ct.team_id = pt.team_id "
                "where ct.team_name = '설계팀'"
            )
            mentioning_post_count = cur.fetchone()[0]
            cur.execute(
                "select count(*) from knowledge_graph_edge "
                "where source_node_type_code = 'node_team' and edge_type_code = 'edge_mention_team'"
            )
            team_mention_edge_count = cur.fetchone()[0]
    finally:
        admin_conn.close()

    assert (team_row_count, distinct_team_count) == (1, 1), "the same team+org pair must dedupe to one row"
    assert mentioning_post_count == 2, "both posts must link to the single cataloged team"
    assert team_mention_edge_count == 2, "each post's mention must become a real KG edge"

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    try:
        with admin_conn.cursor() as cur:
            cur.execute("select team_id from cataloged_team where team_name = '설계팀'")
            team_id = str(cur.fetchone()[0])
    finally:
        admin_conn.close()

    related = client.get(
        f"/api/teams/{team_id}/related",
        headers=headers,
    )
    assert related.status_code == 200, related.text
    related_ids = {node["node_id"] for node in related.json()["related"]}
    assert set(post_ids) <= related_ids
    summaries = [
        client.get(f"/api/posts/{post_id}/summary", headers=headers).json()
        for post_id in post_ids
    ]
    for body in summaries:
        role = body["roles_and_responsibilities"][0]
        assert role["catalog_node_id"] == team_id
        assert role["catalog_node_type_code"] == "node_team"


def test_organization_mention_only_posts_appear_in_entity_related(
    client, demo_analyst_token, seeded_db
) -> None:
    """An org mentioned with no affiliated person must still start a related walk."""

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into source_post (author_account_id, corporate_entity_id, post_title, post_body, voc_type_code, visibility_code) "
                "select author_account_id, corporate_entity_id, %s, %s, 'voc', 'public' "
                "from source_post where post_id = %s returning post_id",
                ("Org-only mention", "Test Corp was named without a person.", seeded_db["own_private_post_id"]),
            )
            org_only_post_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into post_organization_mention (post_id, corporate_entity_id) values (%s, %s)",
                (org_only_post_id, seeded_db["own_corp_id"]),
            )
            for edge in knowledge_graph_edges_for_post(
                org_only_post_id,
                [],
                organization_corporate_entity_ids=[seeded_db["own_corp_id"]],
            ):
                cur.execute(
                    "insert into knowledge_graph_edge ("
                    "source_node_type_code, source_node_id, target_node_type_code, "
                    "target_node_id, edge_type_code, edge_weight"
                    ") values (%s, %s, %s, %s, %s, %s) "
                    "on conflict do nothing",
                    (
                        edge.source_node_type_code,
                        edge.source_node_id,
                        edge.target_node_type_code,
                        edge.target_node_id,
                        edge.edge_type_code,
                        edge.edge_weight,
                    ),
                )
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/corporate-entities/{seeded_db['own_corp_id']}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    related_ids = {node["node_id"] for node in response.json()["related"]}
    assert org_only_post_id in related_ids


def test_private_other_corp_organization_mention_does_not_leak(
    client, demo_analyst_token, seeded_db
) -> None:
    """The org-mention UNION must still apply ABAC per post."""

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into post_organization_mention (post_id, corporate_entity_id) "
                "values (%s, %s) on conflict do nothing",
                (seeded_db["other_private_post_id"], seeded_db["own_corp_id"]),
            )
            cur.execute(
                "insert into post_organization_mention (post_id, corporate_entity_id) "
                "values (%s, %s) on conflict do nothing",
                (seeded_db["other_private_post_id"], seeded_db["other_corp_id"]),
            )
            for entity_id in (seeded_db["own_corp_id"], seeded_db["other_corp_id"]):
                for edge in knowledge_graph_edges_for_post(
                    seeded_db["other_private_post_id"],
                    [],
                    organization_corporate_entity_ids=[entity_id],
                ):
                    cur.execute(
                        "insert into knowledge_graph_edge ("
                        "source_node_type_code, source_node_id, target_node_type_code, "
                        "target_node_id, edge_type_code, edge_weight"
                        ") values (%s, %s, %s, %s, %s, %s) "
                        "on conflict do nothing",
                        (
                            edge.source_node_type_code,
                            edge.source_node_id,
                            edge.target_node_type_code,
                            edge.target_node_id,
                            edge.edge_type_code,
                            edge.edge_weight,
                        ),
                    )
    finally:
        admin_conn.close()

    headers = {"Authorization": f"Bearer {demo_analyst_token}"}
    own = client.get(
        f"/api/corporate-entities/{seeded_db['own_corp_id']}/related",
        headers=headers,
    )
    assert own.status_code == 200, own.text
    own_ids = {node["node_id"] for node in own.json()["related"]}
    assert seeded_db["other_private_post_id"] not in own_ids

    hidden = client.get(
        f"/api/corporate-entities/{seeded_db['other_corp_id']}/related",
        headers=headers,
    )
    assert hidden.status_code == 403


def test_thread_group_run_list_honors_knowledge_cutoff(
    client, demo_analyst_token, seeded_db
) -> None:
    """A later public post must not surface a previously hidden thread-group run."""

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into source_post (author_account_id, corporate_entity_id, post_title, post_body, voc_type_code, visibility_code, thread_group_key, created_at) "
                "select author_account_id, corporate_entity_id, %s, %s, 'voc', 'public', %s, %s "
                "from source_post where post_id = %s",
                (
                    "Late thread-group post",
                    "Written after the January cutoff.",
                    "late-thread-group",
                    "2026-01-20T12:00:00Z",
                    seeded_db["own_private_post_id"],
                ),
            )
            cur.execute(
                """
                insert into analysis_source_snapshot
                    (snapshot_sha256, source_contract_version,
                     maximum_available_time, captured_at)
                values (%s, 'source-contract-v1',
                        '2026-01-12T00:00:00Z', '2026-01-12T00:05:00Z')
                returning analysis_source_snapshot_id
                """,
                ("f" * 64,),
            )
            snapshot_id = cur.fetchone()[0]
            cur.execute(
                """
                insert into analysis_run
                    (analysis_source_snapshot_id, run_kind_code, idempotency_key,
                     requested_by_account_id, knowledge_cutoff,
                     configuration_schema_version, configuration_sha256,
                     code_revision_sha, requested_at)
                values (%s, 'analysis_run_lineage', %s,
                        (select user_account_id from user_account
                          where email_address = 'other.analyst@example.test'),
                        '2026-01-12T12:00:00Z', 'lineage-run-v1', %s, %s,
                        '2026-01-12T12:30:00Z')
                returning analysis_run_id
                """,
                (snapshot_id, "hidden-late-thread", "b" * 64, "c" * 40),
            )
            run_id = str(cur.fetchone()[0])
            cur.execute(
                """
                insert into analysis_run_scope
                    (analysis_run_id, scope_kind_code, scope_key)
                values (%s, 'analysis_scope_thread_group', 'late-thread-group')
                """,
                (run_id,),
            )
            for ordinal, status, occurred in (
                (1, "analysis_status_pending", "2026-01-12T12:31:00Z"),
                (2, "analysis_status_running", "2026-01-12T12:32:00Z"),
                (3, "analysis_status_succeeded", "2026-01-12T12:33:00Z"),
            ):
                cur.execute(
                    """
                    insert into analysis_run_status_event
                        (analysis_run_id, status_ordinal, status_code, occurred_at)
                    values (%s, %s, %s, %s)
                    """,
                    (run_id, ordinal, status, occurred),
                )
    finally:
        admin_conn.close()

    listed = client.get(
        "/api/analysis-runs",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert listed.status_code == 200
    ids = {run["analysis_run_id"] for run in listed.json()["analysis_runs"]}
    assert run_id not in ids
    assert seeded_db["visible_run_id"] in ids


def test_first_mention_of_a_new_counterparty_creates_a_real_corporate_entity(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """ADR 0010: a person's affiliation to an organization with no
    existing corporate_entity candidate must not stay permanently
    unresolved -- an LLM-proposed, search-corroborated hierarchy
    placement creates a real new row, closing the "통합 고객사 계열
    tree AI" gap synthetic regression corpus data confirmed (0 of thousands of
    real affiliations ever resolved before this). Deterministic fake
    clients, CI-stable -- the point under test is the create-then-link
    wiring, not model/search quality.
    """
    from lineageweave.corporate_hierarchy_inference import HierarchyProposal
    from lineageweave.keyman_extraction import COUNTERPARTY, PersonMention
    from lineageweave.relation_verification import STATUS_CORROBORATED, RelationVerificationResult

    _grant_post_admin(seeded_db["dsn"])

    class _FakeKeymanClient:
        available = True

        def extract(self, post_title: str, post_body: str) -> list[PersonMention]:
            return [
                PersonMention(
                    person_name="Priya Sharma",
                    person_side_code=COUNTERPARTY,
                    affiliated_organization_names=("Northwind Turbines Gwangju Plant",),
                )
            ]

    class _FakeRelationshipClient:
        available = True

        def classify(self, post_title: str, post_body: str, organization_names: list[str]):
            return []

    class _FakeHierarchyInferenceClient:
        available = True

        def infer(self, organization_name: str, context_text: str) -> HierarchyProposal | None:
            if organization_name == "Northwind Turbines Gwangju Plant":
                return HierarchyProposal(level_code="plant", parent_name="Northwind Turbines")
            if organization_name == "Northwind Turbines":
                return HierarchyProposal(level_code="company", parent_name=None)
            return None

    class _FakeVerificationClient:
        available = True

        def verify(self, organization_name: str, relationship_label: str) -> RelationVerificationResult:
            return RelationVerificationResult(
                status_code=STATUS_CORROBORATED, evidence_url=f"https://example.org/{organization_name}"
            )

    monkeypatch.setattr("backend.app.main._keyman_extraction_client", lambda: _FakeKeymanClient())
    monkeypatch.setattr("backend.app.main._entity_relationship_client", lambda: _FakeRelationshipClient())
    monkeypatch.setattr(
        "backend.app.main._corporate_hierarchy_inference_client", lambda: _FakeHierarchyInferenceClient()
    )
    monkeypatch.setattr("backend.app.main._relation_verification_client", lambda: _FakeVerificationClient())

    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/extract-keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select corporate_entity_id, entity_level_code, parent_entity_id, corporate_entity_code "
                "from corporate_entity where entity_name = 'Northwind Turbines Gwangju Plant'"
            )
            plant_row = cur.fetchone()
            cur.execute(
                "select corporate_entity_id, entity_level_code "
                "from corporate_entity where entity_name = 'Northwind Turbines'"
            )
            company_row = cur.fetchone()
            cur.execute(
                "select pa.affiliated_corporate_entity_id from person_affiliation pa "
                "join cataloged_person cp on cp.person_id = pa.person_id "
                "where cp.person_name = 'Priya Sharma'"
            )
            affiliation_entity_id = cur.fetchone()[0]
    finally:
        admin_conn.close()

    assert plant_row is not None, "the plant-level entity must be created"
    plant_entity_id, plant_level_code, plant_parent_id, plant_code = plant_row
    assert plant_level_code == "plant"
    assert plant_code.startswith("AUTO-"), "an auto-created code must never collide with a real login corp code"
    assert company_row is not None, "the inferred parent company must also be created, not left dangling"
    company_entity_id, company_level_code = company_row
    assert company_level_code == "company"
    assert str(plant_parent_id) == str(company_entity_id), "the plant's parent must be the real created company"
    assert str(affiliation_entity_id) == str(plant_entity_id), "the affiliation must link to the real created plant"


@pytest.mark.skipif(
    not (_ORCHESTRATOR_BASE_URL and _ORCHESTRATOR_API_KEY),
    reason="set LINEAGEWEAVE_TEST_ORCHESTRATOR_BASE_URL and LINEAGEWEAVE_TEST_ORCHESTRATOR_API_KEY to run",
)
def test_extract_keymen_persists_a_real_llm_extraction(client, demo_analyst_token, seeded_db) -> None:
    """The full write path, end to end: a real LLM call through a live
    contextual-orchestrator, persisted to Postgres, then read back through
    the read endpoints -- not a mocked extraction client.
    """
    os.environ["ORCHESTRATOR_BASE_URL"] = _ORCHESTRATOR_BASE_URL
    os.environ["ORCHESTRATOR_API_KEY"] = _ORCHESTRATOR_API_KEY

    from lineageweave.fixtures import ambiguous_keyman_post

    title, body = ambiguous_keyman_post()

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('permission', 'post_admin', 'Administer posts') on conflict (lookup_code) do nothing"
            )
            cur.execute("select access_role_id from account_role_assignment limit 1")
            role_id = cur.fetchone()[0]
            cur.execute(
                "insert into role_permission (access_role_id, permission_code) values (%s, 'post_admin') "
                "on conflict do nothing",
                (role_id,),
            )
            cur.execute(
                "insert into source_post (author_account_id, corporate_entity_id, post_title, post_body, voc_type_code, visibility_code) "
                "select author_account_id, corporate_entity_id, %s, %s, 'voc', 'public' "
                "from source_post where post_id = %s "
                "returning post_id",
                (title, body, seeded_db["own_private_post_id"]),
            )
            new_post_id = str(cur.fetchone()[0])
    finally:
        admin_conn.close()

    response = client.post(
        f"/api/posts/{new_post_id}/extract-keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    body_json = response.json()
    assert body_json["extracted_count"] >= 2
    names = {mention["person_name"] for mention in body_json["mentions"]}
    assert any("Jordan" in name for name in names)
    assert any("Priya" in name for name in names)

    keymen_response = client.get(
        f"/api/posts/{new_post_id}/keymen", headers={"Authorization": f"Bearer {demo_analyst_token}"}
    )
    assert keymen_response.status_code == 200
    persisted_names = {person["person_name"] for person in keymen_response.json()["keymen"]}
    assert persisted_names == names

    # ambiguous_keyman_post's Priya Nair is affiliated with "Northridge
    # Grid" and "Northridge Holdings" -- extract-keymen should have fed
    # those into the entity-relationship classifier and persisted a real
    # classification for each, readable back via the counterparties endpoint.
    counterparty_names = {c["organization_name"] for c in body_json["counterparties"]}
    assert counterparty_names == {"Northridge Grid", "Northridge Holdings"}
    valid_codes = {"rel_voc", "rel_vom", "rel_vop", "rel_vocc", "rel_voco", "rel_vos"}
    assert all(c["relationship_type_code"] in valid_codes for c in body_json["counterparties"])

    counterparties_response = client.get(
        f"/api/posts/{new_post_id}/counterparties", headers={"Authorization": f"Bearer {demo_analyst_token}"}
    )
    assert counterparties_response.status_code == 200
    persisted_counterparty_names = {
        c["counterparty_entity_name"] for c in counterparties_response.json()["counterparties"]
    }
    assert persisted_counterparty_names == counterparty_names


_SEARXNG_BASE_URL = os.environ.get("LINEAGEWEAVE_TEST_SEARXNG_BASE_URL", "http://localhost:18888")


def _searxng_available() -> bool:
    """True when a Searxng instance at `_SEARXNG_BASE_URL` answers a JSON
    search. A generous timeout: a real search round-trips through several
    real upstream search engines, genuinely slower than a local health
    check.
    """
    try:
        get_json(f"{_SEARXNG_BASE_URL}/search?q=ping&format=json", timeout=10)
        return True
    except (HttpClientError, OSError, ValueError):
        return False


@pytest.mark.skipif(
    not _searxng_available(),
    reason="requires a reachable local Searxng -- run `docker compose up searxng` first",
)
def test_verify_relations_persists_real_search_outcomes(client, demo_analyst_token, seeded_db) -> None:
    """A real end-to-end proof of relation_verification.py's search-backed
    check: a real, well-known organization name gets `verify_corroborated`
    with a real evidence URL, and a deliberately fabricated organization
    name gets `verify_uncorroborated` with none -- not a mocked search
    client, a genuine Searxng round trip through
    POST /api/posts/{id}/verify-relations.
    """
    os.environ["SEARXNG_BASE_URL"] = _SEARXNG_BASE_URL

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('permission', 'post_admin', 'Administer posts') on conflict (lookup_code) do nothing"
            )
            cur.execute("select access_role_id from account_role_assignment limit 1")
            role_id = cur.fetchone()[0]
            cur.execute(
                "insert into role_permission (access_role_id, permission_code) values (%s, 'post_admin') "
                "on conflict do nothing",
                (role_id,),
            )
            cur.execute(
                "insert into post_counterparty_entity (post_id, counterparty_entity_name, relationship_type_code) "
                "values (%s, 'Wikipedia', 'rel_voc'), "
                "(%s, 'Zzqxvthorp Fictitious Nonexistent Org 8f3e1c', 'rel_voco')",
                (seeded_db["public_post_id"], seeded_db["public_post_id"]),
            )
    finally:
        admin_conn.close()

    response = client.post(
        f"/api/posts/{seeded_db['public_post_id']}/verify-relations",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    verified = {row["counterparty_entity_name"]: row for row in response.json()["verified"]}

    real_org = verified["Wikipedia"]
    if real_org["verification_status_code"] != "verify_corroborated":
        pytest.skip(
            "Searxng answered JSON but produced no non-search host/snippet "
            "for a known org -- upstream engines are empty or blocked"
        )
    assert real_org["verification_evidence_url"]

    fake_org = verified["Zzqxvthorp Fictitious Nonexistent Org 8f3e1c"]
    assert fake_org["verification_status_code"] == "verify_uncorroborated"
    assert fake_org["verification_evidence_url"] is None

    counterparties_response = client.get(
        f"/api/posts/{seeded_db['public_post_id']}/counterparties",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    persisted = {c["counterparty_entity_name"]: c for c in counterparties_response.json()["counterparties"]}
    assert persisted["Wikipedia"]["verification_status_code"] == "verify_corroborated"
    assert persisted["Zzqxvthorp Fictitious Nonexistent Org 8f3e1c"]["verification_status_code"] == "verify_uncorroborated"

    # Already-checked rows are left alone on a second call, not re-searched.
    second_response = client.post(
        f"/api/posts/{seeded_db['public_post_id']}/verify-relations",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert second_response.json()["verified"] == []


def test_seed_fixture_evaluations_surface_on_get_evaluation(
    client, demo_analyst_token, seeded_db
) -> None:
    """The same helper `make seed` calls must fill GET /evaluation for an
    A-100 fixture post -- otherwise the popup stays Not yet evaluated.
    """
    from lineageweave.fixtures import sample_records
    from scripts.seed_demo_data import _seed_fixture_evaluations

    fixture_title = sample_records()[1].label  # Pricing renegotiation follow-up
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            cur.execute(
                "insert into source_post "
                "(author_account_id, corporate_entity_id, post_title, post_body, "
                " voc_type_code, visibility_code) "
                "values (%s, %s, %s, %s, 'voc', 'public') returning post_id",
                (author_id, corp_id, fixture_title, fixture_title),
            )
            post_id = str(cur.fetchone()[0])
            _seed_fixture_evaluations(cur)
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/posts/{post_id}/evaluation",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["responses"]) == 3
    by_code = {row["criterion_code"]: row for row in body["responses"]}
    assert by_code["sales_lead_specificity"]["response_category"] == 3
    assert by_code["general_sentiment_positive"]["criterion_label"] == "Constructive stance"


def test_seed_fixture_keymen_and_voc_surface_on_get(client, demo_analyst_token, seeded_db) -> None:
    """The same helper `make seed` calls must fill Keyman, affiliate tree,
    and VOC evidence for an A-100 fixture post -- otherwise DAG
    click-through stays empty on those panels.
    """
    from scripts.seed_demo_data import _seed_fixture_keymen_and_voc

    fixture_title = "Pricing renegotiation follow-up"
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            cur.execute(
                "insert into source_post "
                "(author_account_id, corporate_entity_id, post_title, post_body, "
                " voc_type_code, visibility_code) "
                "values (%s, %s, %s, %s, 'voc', 'public') returning post_id",
                (author_id, corp_id, fixture_title, fixture_title),
            )
            post_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into source_post "
                "(author_account_id, corporate_entity_id, post_title, post_body, "
                " voc_type_code, visibility_code) "
                "values (%s, %s, %s, %s, 'voc', 'public') returning post_id",
                (
                    author_id,
                    corp_id,
                    "Technical specification review meeting",
                    "Technical specification review meeting",
                ),
            )
            beta_id = str(cur.fetchone()[0])
            _seed_fixture_keymen_and_voc(cur, corp_id)
    finally:
        admin_conn.close()

    headers = {"Authorization": f"Bearer {demo_analyst_token}"}
    keymen = client.get(f"/api/posts/{post_id}/keymen", headers=headers)
    assert keymen.status_code == 200, keymen.text
    names = {person["person_name"] for person in keymen.json()["keymen"]}
    assert names == {"Ada West", "Priya Nair"}

    tree = client.get(f"/api/posts/{post_id}/affiliate-tree", headers=headers)
    assert tree.status_code == 200, tree.text

    def _org_names(nodes):
        names: set[str] = set()
        for node in nodes:
            names.add(node["entity_name"])
            names.update(_org_names(node.get("children", [])))
        return names

    assert "Northridge Grid" in _org_names(tree.json()["trees"])

    voc = client.get(f"/api/posts/{post_id}/voc-evidence", headers=headers)
    assert voc.status_code == 200, voc.text
    body = voc.json()
    assert any("Northridge Grid" in excerpt for excerpt in body["excerpts"])
    counterparties = {row["counterparty_entity_name"] for row in body["counterparties"]}
    assert "Northridge Grid" in counterparties

    beta = client.get(f"/api/posts/{beta_id}/keymen", headers=headers)
    assert beta.status_code == 200, beta.text
    assert {person["person_name"] for person in beta.json()["keymen"]} == {"Jordan Hale"}
    beta_voc = client.get(f"/api/posts/{beta_id}/voc-evidence", headers=headers)
    assert beta_voc.status_code == 200, beta_voc.text
    assert any("Westfield Power" in excerpt for excerpt in beta_voc.json()["excerpts"])


def test_evaluation_is_empty_before_a_judge_run(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['public_post_id']}/evaluation",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["responses"] == []


def test_evaluate_publishes_an_activity_event(client, demo_analyst_token, seeded_db, monkeypatch) -> None:
    """Live gap (2026-08-19): evaluate is a real, consequential write
    action (an LLM-as-a-Judge call), same discipline as extract-keymen --
    it must publish to the post's activity feed too, not only those two.
    """
    from backend.app.post_evaluation_ingestion import PersistedEvaluation

    _grant_post_admin(seeded_db["dsn"])

    class _FakeEvaluationClient:
        available = True

    async def _fake_ingest_post_evaluation(conn, client, post_id, post_title, post_body):
        return [
            PersistedEvaluation(
                criterion_code="specificity",
                criterion_label="Specificity",
                response_category=2,
                rubric_version="v1",
            )
        ]

    monkeypatch.setattr("backend.app.main._post_evaluation_client", lambda: _FakeEvaluationClient())
    monkeypatch.setattr("backend.app.main.ingest_post_evaluation", _fake_ingest_post_evaluation)

    post_id = seeded_db["own_private_post_id"]
    response = client.post(
        f"/api/posts/{post_id}/evaluate",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text

    activity_response = client.get(
        f"/api/posts/{post_id}/activity",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    events = activity_response.json()["events"]
    assert events[0]["event_type"] == "post_evaluated"
    assert "1 rubric criterion response" in events[0]["summary"]


def test_live_chat_answer_publishes_an_activity_event(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """Live gap (2026-08-20): a live (non-cached) chat answer is a real,
    consequential LLM call, same discipline as extract-keymen/evaluate --
    it must publish to the post's activity feed too. A stored/seeded
    answer (no live call made) must not.
    """
    from lineageweave.post_chat import ChatAnswer

    _grant_post_admin(seeded_db["dsn"])

    class _FakeChatClient:
        available = True

        def answer(self, question: str, sources) -> ChatAnswer:
            return ChatAnswer(answer_text="a live answer", cited_post_ids=())

    monkeypatch.setattr("backend.app.main._post_chat_client", lambda: _FakeChatClient())

    post_id = seeded_db["own_private_post_id"]
    response = client.post(
        f"/api/posts/{post_id}/chat",
        json={"question": "What happened here that no seed already answers?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text

    activity_response = client.get(
        f"/api/posts/{post_id}/activity",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    events = activity_response.json()["events"]
    assert events[0]["event_type"] == "chat_answered"
    assert "What happened here that no seed already answers?" in events[0]["summary"]


def test_live_chat_provider_error_does_not_leak_raw_error(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """A provider exception becomes a stable 503 without its raw message."""
    class _FailingChatClient:
        available = True

        def answer(self, question: str, sources) -> object:
            raise Exception("raw-provider-secret")

    monkeypatch.setattr("backend.app.main._post_chat_client", lambda: _FailingChatClient())

    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/chat",
        json={"question": "What happened in this provider failure case?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )

    assert response.status_code == 503
    assert "raw-provider-secret" not in response.text


def test_global_ask_provider_error_does_not_leak_raw_error(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """The cross-post Ask boundary also returns a stable provider failure."""
    class _FailingAskClient:
        available = True

        def answer(self, question: str, sources) -> object:
            raise Exception("raw-global-provider-secret")

    monkeypatch.setattr("backend.app.main._post_chat_client", lambda: _FailingAskClient())

    response = client.post(
        "/api/ask",
        json={"question": "What happened in this global failure case?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )

    assert response.status_code == 503
    assert "raw-global-provider-secret" not in response.text


def test_keymen_provider_error_does_not_leak_raw_error(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """Keymen provider failures become a stable 503 at the API boundary."""
    _grant_post_admin(seeded_db["dsn"])

    class _FailingKeymanClient:
        available = True

        def extract(self, post_title: str, post_body: str) -> object:
            raise Exception("raw-keyman-provider-secret")

    monkeypatch.setattr("backend.app.main._keyman_extraction_client", lambda: _FailingKeymanClient())

    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/extract-keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )

    assert response.status_code == 503
    assert "raw-keyman-provider-secret" not in response.text


def test_evaluation_provider_error_does_not_leak_raw_error(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """Evaluation provider failures become a stable 503 at the API boundary."""
    _grant_post_admin(seeded_db["dsn"])

    class _FailingEvaluationClient:
        available = True

        def evaluate(self, post_title: str, post_body: str) -> object:
            raise Exception("raw-evaluation-provider-secret")

    monkeypatch.setattr(
        "backend.app.main._post_evaluation_client", lambda: _FailingEvaluationClient()
    )

    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/evaluate",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )

    assert response.status_code == 503
    assert "raw-evaluation-provider-secret" not in response.text


def test_commitment_provider_error_does_not_leak_raw_error(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """Commitment provider failures become a stable 503 at the API boundary."""
    _grant_post_admin(seeded_db["dsn"])

    class _FailingCommitmentClient:
        available = True

        def extract(self, post_title: str, post_body: str, reference_date: str) -> object:
            raise Exception("raw-commitment-provider-secret")

    monkeypatch.setattr(
        "backend.app.main._commitment_extraction_client", lambda: _FailingCommitmentClient()
    )

    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/derive-commitment",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )

    assert response.status_code == 503
    assert "raw-commitment-provider-secret" not in response.text


def test_summary_enrichment_provider_error_does_not_leak_raw_error(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """Summary enrichment failures stay a stable 503 at the API boundary."""
    from lineageweave.post_summary import PostSummary

    class _FakeSummaryClient:
        available = True

        def summarize(self, post_title: str, post_body: str) -> PostSummary:
            return PostSummary(korean_summary="합성 요약")

    async def _fail_persist(*args, **kwargs):
        raise Exception("raw-summary-provider-secret")

    monkeypatch.setattr("backend.app.main._post_summary_client", lambda: _FakeSummaryClient())
    monkeypatch.setattr("backend.app.main.persist_post_summary", _fail_persist)

    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/summary",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )

    assert response.status_code == 503
    assert "raw-summary-provider-secret" not in response.text


def test_evaluate_is_unavailable_without_orchestrator(client, demo_analyst_token, seeded_db) -> None:
    os.environ.pop("ORCHESTRATOR_BASE_URL", None)
    os.environ.pop("ORCHESTRATOR_API_KEY", None)
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('permission', 'post_admin', 'Administer posts') on conflict (lookup_code) do nothing"
            )
            cur.execute("select access_role_id from account_role_assignment limit 1")
            role_id = cur.fetchone()[0]
            cur.execute(
                "insert into role_permission (access_role_id, permission_code) values (%s, 'post_admin') "
                "on conflict do nothing",
                (role_id,),
            )
    finally:
        admin_conn.close()
    response = client.post(
        f"/api/posts/{seeded_db['public_post_id']}/evaluate",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 503


@pytest.mark.skipif(
    not (_ORCHESTRATOR_BASE_URL and _ORCHESTRATOR_API_KEY),
    reason="set LINEAGEWEAVE_TEST_ORCHESTRATOR_BASE_URL and LINEAGEWEAVE_TEST_ORCHESTRATOR_API_KEY to run",
)
def test_extract_keymen_normalizes_html_and_embedded_image_content(
    client, demo_analyst_token, seeded_db
) -> None:
    """A real end-to-end proof that HTML/base64-image post bodies are
    normalized (lineageweave.post_content_normalization) before the LLM
    ever sees them: the same real people from ambiguous_keyman_post()
    must still be found even though the post body is wrapped in HTML
    formatting and carries an embedded image, which a raw-body call
    would either choke the model's attention on (literal tags) or bloat
    the prompt with (raw base64) -- see backend/app/main.py's
    extract-keymen endpoint and ADR-referenced design in
    lineageweave/post_content_normalization.py.
    """
    os.environ["ORCHESTRATOR_BASE_URL"] = _ORCHESTRATOR_BASE_URL
    os.environ["ORCHESTRATOR_API_KEY"] = _ORCHESTRATOR_API_KEY

    from lineageweave.fixtures import ambiguous_keyman_post

    title, plain_body = ambiguous_keyman_post()
    # A 1x1 PNG data URI -- real base64 image bytes, not a fake string.
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    html_body = (
        f'<div style="color:red;font-weight:bold"><p>{plain_body}</p>'
        f'<img src="data:image/png;base64,{tiny_png_b64}"/></div>'
    )

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('permission', 'post_admin', 'Administer posts') on conflict (lookup_code) do nothing"
            )
            cur.execute("select access_role_id from account_role_assignment limit 1")
            role_id = cur.fetchone()[0]
            cur.execute(
                "insert into role_permission (access_role_id, permission_code) values (%s, 'post_admin') "
                "on conflict do nothing",
                (role_id,),
            )
            cur.execute(
                "insert into source_post (author_account_id, corporate_entity_id, post_title, post_body, voc_type_code, visibility_code) "
                "select author_account_id, corporate_entity_id, %s, %s, 'voc', 'public' "
                "from source_post where post_id = %s "
                "returning post_id",
                (title, html_body, seeded_db["own_private_post_id"]),
            )
            new_post_id = str(cur.fetchone()[0])
    finally:
        admin_conn.close()

    response = client.post(
        f"/api/posts/{new_post_id}/extract-keymen",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    names = {mention["person_name"] for mention in response.json()["mentions"]}
    # The real people are still findable through the HTML/image wrapping --
    # proof the LLM received clean text, not raw markup or base64 noise
    # drowning out the actual content.
    assert any("Jordan" in name for name in names)
    assert any("Priya" in name for name in names)


def test_counterparties_resolve_cataloged_org_ids(client, demo_analyst_token, seeded_db) -> None:
    """GET /counterparties must attach a cataloged entity id when the
    classified name resolves, and leave unresolved names null.
    """
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into post_counterparty_entity "
                "(post_id, counterparty_entity_name, relationship_type_code) "
                "values (%s, 'Test Corp', 'rel_voc'), (%s, 'Northridge Grid', 'rel_voc')",
                (seeded_db["own_private_post_id"], seeded_db["own_private_post_id"]),
            )
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/counterparties",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    by_name = {row["counterparty_entity_name"]: row for row in response.json()["counterparties"]}
    assert by_name["Test Corp"]["corporate_entity_id"] == seeded_db["own_corp_id"]
    assert by_name["Northridge Grid"]["corporate_entity_id"] is None


def test_counterparties_endpoint_is_empty_before_extraction(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/counterparties",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    assert response.json()["counterparties"] == []


def test_other_corp_private_post_counterparties_are_forbidden(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['other_private_post_id']}/counterparties",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_unknown_keyman_is_not_found(client, demo_analyst_token) -> None:
    response = client.get(
        f"/api/keymen/{uuid.uuid4()}/related",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 404


def test_post_lineage_surfaces_indirect_link_via_shared_keyman(client, demo_analyst_token, seeded_db) -> None:
    """No live orchestrator needed -- this is pure DB + graph-math, no LLM
    call. own_private_post_id and public_post_id share no post_lineage_edge
    but both mention our_person_id (Ada West); the other-corp private
    post (hidden_person_id, a DIFFERENT person, no shared Keyman with
    either) must not appear at all.
    """
    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/lineage",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["direct"] == []
    indirect_ids = {post["post_id"] for post in body["indirect"]}
    assert indirect_ids == {seeded_db["public_post_id"]}
    assert body["indirect"][0]["post_body_excerpt"]
    assert "post_body_truncated" in body["indirect"][0]


def test_other_corp_private_post_summary_is_forbidden(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['other_private_post_id']}/summary",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_other_corp_private_post_chat_is_forbidden(client, demo_analyst_token, seeded_db) -> None:
    headers = {"Authorization": f"Bearer {demo_analyst_token}"}
    posted = client.post(
        f"/api/posts/{seeded_db['other_private_post_id']}/chat",
        json={"question": "what happened"},
        headers=headers,
    )
    assert posted.status_code == 403
    listed = client.get(f"/api/posts/{seeded_db['other_private_post_id']}/chat", headers=headers)
    assert listed.status_code == 403


@pytest.mark.skipif(
    not (_ORCHESTRATOR_BASE_URL and _ORCHESTRATOR_API_KEY),
    reason="set LINEAGEWEAVE_TEST_ORCHESTRATOR_BASE_URL and LINEAGEWEAVE_TEST_ORCHESTRATOR_API_KEY to run",
)
def test_post_summary_returns_a_real_korean_summary(client, demo_analyst_token, seeded_db) -> None:
    os.environ["ORCHESTRATOR_BASE_URL"] = _ORCHESTRATOR_BASE_URL
    os.environ["ORCHESTRATOR_API_KEY"] = _ORCHESTRATOR_API_KEY

    from lineageweave.fixtures import ambiguous_keyman_post

    title, body = ambiguous_keyman_post()
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into source_post (author_account_id, corporate_entity_id, post_title, post_body, voc_type_code, visibility_code) "
                "select author_account_id, corporate_entity_id, %s, %s, 'voc', 'public' "
                "from source_post where post_id = %s returning post_id",
                (title, body, seeded_db["own_private_post_id"]),
            )
            new_post_id = str(cur.fetchone()[0])
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/posts/{new_post_id}/summary", headers={"Authorization": f"Bearer {demo_analyst_token}"}
    )
    assert response.status_code == 200, response.text
    body_json = response.json()
    assert any("가" <= ch <= "힣" for ch in body_json["korean_summary"])
    assert len(body_json["key_events"]) >= 1


@pytest.mark.skipif(
    not (_ORCHESTRATOR_BASE_URL and _ORCHESTRATOR_API_KEY),
    reason="set LINEAGEWEAVE_TEST_ORCHESTRATOR_BASE_URL and LINEAGEWEAVE_TEST_ORCHESTRATOR_API_KEY to run",
)
def test_post_chat_cites_a_post_linked_only_via_a_shared_keyman(client, demo_analyst_token, seeded_db) -> None:
    """The real end-to-end proof of Phase 4's Event Lineage chat: two
    posts with no direct lineage edge between them, linked only by a
    shared Keyman -- the retrieve step must pull the second post in via
    the Knowledge Graph, and the answer must cite it, because the
    question can only be answered by combining both.
    """
    os.environ["ORCHESTRATOR_BASE_URL"] = _ORCHESTRATOR_BASE_URL
    os.environ["ORCHESTRATOR_API_KEY"] = _ORCHESTRATOR_API_KEY

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_account_id, corporate_entity_id = cur.fetchone()

            def _insert_post(title, body):
                cur.execute(
                    "insert into source_post (author_account_id, corporate_entity_id, post_title, post_body, voc_type_code, visibility_code) "
                    "values (%s, %s, %s, %s, 'voc', 'public') returning post_id",
                    (author_account_id, corporate_entity_id, title, body),
                )
                return str(cur.fetchone()[0])

            post_a = _insert_post("Kickoff call", "We agreed to submit the transformer bid by March 3.")
            post_b = _insert_post("Bid follow-up", "The client requested a revised quote, sent March 12.")

            cur.execute(
                "insert into cataloged_person (person_name, person_side_code) values ('Shared Keyman', 'our_side') "
                "returning person_id"
            )
            shared_person_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into post_person_mention (post_id, person_id) values (%s, %s), (%s, %s)",
                (post_a, shared_person_id, post_b, shared_person_id),
            )

            from lineageweave.knowledge_graph import knowledge_graph_edges_for_post

            for post_id in (post_a, post_b):
                for edge in knowledge_graph_edges_for_post(post_id, [shared_person_id]):
                    cur.execute(
                        "insert into knowledge_graph_edge (source_node_type_code, source_node_id, "
                        "target_node_type_code, target_node_id, edge_type_code, edge_weight) "
                        "values (%s, %s, %s, %s, %s, %s)",
                        (
                            edge.source_node_type_code,
                            edge.source_node_id,
                            edge.target_node_type_code,
                            edge.target_node_id,
                            edge.edge_type_code,
                            edge.edge_weight,
                        ),
                    )
    finally:
        admin_conn.close()

    response = client.post(
        f"/api/posts/{post_a}/chat",
        json={"question": "What happened with the bid between the kickoff and now?"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    body_json = response.json()
    assert set(body_json["source_post_ids"]) == {post_a, post_b}
    assert post_b in body_json["cited_post_ids"]
    cited_by_id = {row["post_id"]: row["post_title"] for row in body_json["cited_posts"]}
    assert cited_by_id[post_b] == "Bid follow-up"
    cited_evidence = next(row for row in body_json["cited_post_evidence"] if row["post_id"] == post_b)
    assert any(
        fact["kind"] == "semantic_keyman" and "Shared Keyman" in fact["text"]
        for fact in cited_evidence["facts"]
    )
    assert all(
        "ontology_iri" not in fact["text"] and "contextual_orchestrator" not in fact["text"]
        for fact in cited_evidence["facts"]
    )


def test_rebuild_lineage_requires_post_admin(client, demo_analyst_token) -> None:
    response = client.post("/api/lineage/rebuild", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 403


def test_rebuild_lineage_recovers_the_a100_fork(client, demo_analyst_token, seeded_db) -> None:
    """Rebuild on the same A-100+B-200 rows seed writes (grouping keys +
    occurred_at), not a hand-picked A-100-only insert that hides mapping bugs.
    """
    from scripts.seed_demo_data import insert_fixture_source_posts

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('permission', 'post_admin', 'Administer posts'), "
                "('voc_type', 'vom', 'Voice of Market') "
                "on conflict (lookup_code) do nothing"
            )
            cur.execute("select access_role_id from account_role_assignment limit 1")
            role_id = cur.fetchone()[0]
            cur.execute(
                "insert into role_permission (access_role_id, permission_code) values (%s, 'post_admin') "
                "on conflict do nothing",
                (role_id,),
            )
            cur.execute(
                "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                "select corporate_entity_id, 'TEST-PU-LINEAGE', 'Lineage thread' "
                "from source_post where post_id = %s returning process_unit_id",
                (seeded_db["own_private_post_id"],),
            )
            process_unit_id = cur.fetchone()[0]
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            insert_fixture_source_posts(cur, author_id, corp_id, process_unit_id)
    finally:
        admin_conn.close()

    rebuild = client.post("/api/lineage/rebuild", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert rebuild.status_code == 200, rebuild.text
    assert rebuild.json()["edge_count"] >= 2

    graph = client.get("/api/lineage", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert graph.status_code == 200
    body = graph.json()
    nodes = {node["label"]: node for node in body["nodes"]}
    fork = nodes["Pricing renegotiation follow-up"]
    assert fork["is_branch_point"] is True
    assert fork["group"] == "A-100"
    children = {
        next(node["label"] for node in body["nodes"] if node["id"] == edge["target"])
        for edge in body["edges"]
        if edge["source"] == fork["id"]
    }
    assert "Pricing renegotiation: revised quote sent" in children
    assert "Delivery schedule question raised" in children
    assert nodes["Unrelated: annual account review"]["is_root"] is True
    assert nodes["Unrelated: annual account review"]["group"] == "A-100"
    assert nodes["Technical specification review meeting"]["group"] == "B-200"

    per_post = client.get(
        f"/api/posts/{fork['id']}/lineage",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert per_post.status_code == 200
    direct_titles = {post["post_title"] for post in per_post.json()["direct"]}
    assert "Pricing renegotiation: revised quote sent" in direct_titles
    assert "Delivery schedule question raised" in direct_titles


def test_lineage_graph_hides_other_corp_private_posts(client, demo_analyst_token, seeded_db) -> None:
    response = client.get("/api/lineage", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 200
    ids = {node["id"] for node in response.json()["nodes"]}
    assert seeded_db["public_post_id"] in ids
    assert seeded_db["own_private_post_id"] in ids
    assert seeded_db["other_private_post_id"] not in ids


def _grant_post_admin(dsn: str) -> None:
    """Same ad-hoc grant every post_admin-gated test in this file uses:
    the base fixture only seeds `post_read`.
    """
    admin_conn = psycopg2.connect(dsn)
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('permission', 'post_admin', 'Administer posts') on conflict (lookup_code) do nothing"
            )
            cur.execute("select access_role_id from account_role_assignment limit 1")
            role_id = cur.fetchone()[0]
            cur.execute(
                "insert into role_permission (access_role_id, permission_code) values (%s, 'post_admin') "
                "on conflict do nothing",
                (role_id,),
            )
    finally:
        admin_conn.close()


def test_tickets_list_is_empty_before_any_created(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    assert response.json()["tickets"] == []


def test_create_ticket_requires_post_admin(client, demo_analyst_token, seeded_db) -> None:
    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        json={"ticket_title": "Follow up on pricing", "ticket_status_code": "open"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_other_corp_private_post_tickets_are_forbidden(client, demo_analyst_token, seeded_db) -> None:
    list_response = client.get(
        f"/api/posts/{seeded_db['other_private_post_id']}/tickets",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert list_response.status_code == 403

    _grant_post_admin(seeded_db["dsn"])
    create_response = client.post(
        f"/api/posts/{seeded_db['other_private_post_id']}/tickets",
        json={"ticket_title": "Should not be creatable", "ticket_status_code": "open"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert create_response.status_code == 403


def test_create_ticket_with_invalid_status_code_is_422(client, demo_analyst_token, seeded_db) -> None:
    _grant_post_admin(seeded_db["dsn"])
    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        json={"ticket_title": "Bad status", "ticket_status_code": "not_a_real_status"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 422


def test_create_list_and_patch_ticket_end_to_end(client, demo_analyst_token, seeded_db) -> None:
    """The full CRUD path against a live Postgres: create a ticket on a
    visible post, confirm it's listed, PATCH its status and assignee, and
    confirm the change is reflected on the next GET.
    """
    _grant_post_admin(seeded_db["dsn"])

    create_response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        json={"ticket_title": "Confirm delivery window", "ticket_status_code": "open"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    created = create_response.json()
    assert created["ticket_status_code"] == "open"
    assert created["ticket_status_label"] == "Open"
    assert created["ticket_title"] == "Confirm delivery window"
    assert created["assigned_account_id"] is None
    ticket_id = created["issue_ticket_id"]

    list_response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert list_response.status_code == 200
    listed_ids = {ticket["issue_ticket_id"] for ticket in list_response.json()["tickets"]}
    assert ticket_id in listed_ids

    patch_response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"ticket_status_code": "closed"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["ticket_status_code"] == "closed"
    assert patch_response.json()["ticket_status_label"] == "Closed"

    reread_response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    reread_ticket = next(t for t in reread_response.json()["tickets"] if t["issue_ticket_id"] == ticket_id)
    assert reread_ticket["ticket_status_code"] == "closed"
    assert reread_ticket["ticket_status_label"] == "Closed"


def test_patch_ticket_requires_post_admin(client, demo_analyst_token, seeded_db) -> None:
    _grant_post_admin(seeded_db["dsn"])
    create_response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        json={"ticket_title": "Needs admin to edit", "ticket_status_code": "open"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    ticket_id = create_response.json()["issue_ticket_id"]

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute("select access_role_id from account_role_assignment limit 1")
            role_id = cur.fetchone()[0]
            cur.execute(
                "delete from role_permission where access_role_id = %s and permission_code = 'post_admin'",
                (role_id,),
            )
    finally:
        admin_conn.close()

    response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"ticket_status_code": "closed"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_patch_unknown_ticket_is_not_found(client, demo_analyst_token, seeded_db) -> None:
    _grant_post_admin(seeded_db["dsn"])
    response = client.patch(
        f"/api/tickets/{uuid.uuid4()}",
        json={"ticket_status_code": "closed"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 404


def test_patch_ticket_on_other_corp_private_post_is_forbidden(client, demo_analyst_token, seeded_db) -> None:
    """A ticket has no visibility_code of its own -- ABAC must resolve to
    the ticket's OWNING post before deciding, not skip the check because
    the ticket row itself has no corporate_entity_id.
    """
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into issue_ticket (post_id, ticket_status_code, ticket_title) "
                "values (%s, 'open', 'Ticket on a post this account cannot see') "
                "returning issue_ticket_id",
                (seeded_db["other_private_post_id"],),
            )
            ticket_id = str(cur.fetchone()[0])
    finally:
        admin_conn.close()

    _grant_post_admin(seeded_db["dsn"])
    response = client.patch(
        f"/api/tickets/{ticket_id}",
        json={"ticket_status_code": "closed"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_post_activity_is_empty_before_any_mutation(client, demo_analyst_token, seeded_db) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/activity",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200
    assert response.json()["events"] == []


def test_ticket_mutations_publish_real_events_to_the_activity_feed(
    client, demo_analyst_token, seeded_db
) -> None:
    """Proves Valkey is genuinely load-bearing: a ticket create/patch
    through the real HTTP API is independently observable afterward on
    ``GET /api/posts/{post_id}/activity``, which reads straight off the
    live Valkey stream (no DB involvement in the read path).
    """
    _grant_post_admin(seeded_db["dsn"])

    create_response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        json={"ticket_title": "Confirm freight terms", "ticket_status_code": "open"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    ticket_id = create_response.json()["issue_ticket_id"]

    client.patch(
        f"/api/tickets/{ticket_id}",
        json={"ticket_status_code": "in_progress"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )

    activity_response = client.get(
        f"/api/posts/{seeded_db['own_private_post_id']}/activity",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert activity_response.status_code == 200
    events = activity_response.json()["events"]
    assert len(events) == 2
    # XREVRANGE returns newest first: the status change comes before the
    # creation event.
    assert events[0]["event_type"] == "ticket_status_changed"
    assert events[0]["summary"] == "Ticket status changed to In progress"
    assert "in_progress" not in events[0]["summary"]
    assert events[1]["event_type"] == "ticket_created"
    assert "Confirm freight terms" in events[1]["summary"]


def test_post_activity_on_other_corp_private_post_is_forbidden(
    client, demo_analyst_token, seeded_db
) -> None:
    response = client.get(
        f"/api/posts/{seeded_db['other_private_post_id']}/activity",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_derive_commitment_requires_post_admin(client, demo_analyst_token, seeded_db) -> None:
    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/derive-commitment",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_calendar_is_empty_before_any_commitment(client, demo_analyst_token, seeded_db) -> None:
    response = client.get("/api/calendar", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 200
    assert response.json()["commitments"] == []


def test_calendar_hides_other_corp_private_commitments_and_sorts_by_due_date(
    client, demo_analyst_token, seeded_db
) -> None:
    """Two dated tickets inserted directly (own-corp private and
    other-corp private, in reverse due-date order); the calendar must
    show only the visible one, proving both the ABAC filter and the
    soonest-first ordering.
    """
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into issue_ticket (post_id, ticket_status_code, ticket_title, due_date, commitment_summary) "
                "values (%s, 'open', 'Visible commitment', '2026-03-01', 'Send the revised quote')",
                (seeded_db["own_private_post_id"],),
            )
            cur.execute(
                "insert into issue_ticket (post_id, ticket_status_code, ticket_title, due_date, commitment_summary) "
                "values (%s, 'open', 'Hidden commitment', '2026-01-01', 'Should never be visible')",
                (seeded_db["other_private_post_id"],),
            )
    finally:
        admin_conn.close()

    response = client.get("/api/calendar", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 200
    commitments = response.json()["commitments"]
    assert len(commitments) == 1
    assert commitments[0]["ticket_title"] == "Visible commitment"
    assert commitments[0]["due_date"] == "2026-03-01"
    assert commitments[0]["commitment_summary"] == "Send the revised quote"
    assert "visibility_code" not in commitments[0]
    assert "corporate_entity_id" not in commitments[0]
    assert "author_account_id" not in commitments[0]
    assert "source_detail_state_code" not in commitments[0]


def test_calendar_keeps_real_ticket_when_demo_code_is_shared(
    client, demo_analyst_token, seeded_db
) -> None:
    """A shared DEMO code must filter pure seed tickets row by row."""
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "update corporate_entity set corporate_entity_code = 'DEMO-SHARED' where corporate_entity_id = %s",
                (seeded_db["own_corp_id"],),
            )
            cur.execute(
                "update source_post set source_author_code = null, source_company_code = null, "
                "source_process_unit_code = null, source_sales_pool_code = null, "
                "source_customer_code = null, source_project_code = null where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            cur.execute(
                "update source_post set source_author_code = 'REAL-AUTHOR', source_company_code = 'REAL-COMPANY' "
                "where post_id = %s",
                (seeded_db["public_post_id"],),
            )
            cur.execute(
                "insert into issue_ticket (post_id, ticket_status_code, ticket_title, due_date, commitment_summary) "
                "values (%s, 'open', 'Synthetic commitment', '2026-01-01', 'seed')",
                (seeded_db["own_private_post_id"],),
            )
            cur.execute(
                "insert into issue_ticket (post_id, ticket_status_code, ticket_title, due_date, commitment_summary) "
                "values (%s, 'open', 'Real commitment', '2026-02-01', 'source-backed')",
                (seeded_db["public_post_id"],),
            )
    finally:
        admin_conn.close()

    response = client.get("/api/calendar", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 200
    titles = [commitment["ticket_title"] for commitment in response.json()["commitments"]]
    assert titles == ["Real commitment"]


def test_calendar_excludes_closed_tickets_and_includes_manual_due_dates(
    client, demo_analyst_token, seeded_db
) -> None:
    """A closed dated ticket is done work, not a calendar item; a
    still-open ticket created through the regular ticket API with a
    due_date must still appear -- the calendar is every dated open
    ticket, not only LLM-derived ones.
    """
    _grant_post_admin(seeded_db["dsn"])
    closed = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        json={
            "ticket_title": "Already done",
            "ticket_status_code": "open",
            "due_date": "2026-02-01",
        },
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert closed.status_code == 201, closed.text
    patch = client.patch(
        f"/api/tickets/{closed.json()['issue_ticket_id']}",
        json={"ticket_status_code": "closed"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert patch.status_code == 200
    opened = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        json={
            "ticket_title": "Still open",
            "ticket_status_code": "open",
            "due_date": "2026-04-01",
        },
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert opened.status_code == 201, opened.text

    response = client.get("/api/calendar", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 200
    titles = [c["ticket_title"] for c in response.json()["commitments"]]
    assert "Still open" in titles
    assert "Already done" not in titles


def test_create_ticket_with_malformed_due_date_is_422(client, demo_analyst_token, seeded_db) -> None:
    _grant_post_admin(seeded_db["dsn"])
    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/tickets",
        json={"ticket_title": "Bad date", "ticket_status_code": "open", "due_date": "next Friday"},
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 422


def test_derive_commitment_unavailable_without_orchestrator(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """Null client must 503, not invent a commitment."""
    from lineageweave.commitment_extraction import NullCommitmentExtractionClient

    _grant_post_admin(seeded_db["dsn"])
    monkeypatch.setattr(
        "backend.app.main._commitment_extraction_client",
        lambda: NullCommitmentExtractionClient(),
    )
    response = client.post(
        f"/api/posts/{seeded_db['own_private_post_id']}/derive-commitment",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 503


def test_derive_commitment_uses_post_created_at_and_does_not_duplicate(
    client, demo_analyst_token, seeded_db, monkeypatch
) -> None:
    """CI-stable persist path: a fake client still has to receive the
    post's document-creation date (not wall-clock now) and a second
    derive must refresh the same ticket instead of stacking another.
    """
    from lineageweave.commitment_extraction import CustomerCommitment

    _grant_post_admin(seeded_db["dsn"])

    class _FakeClient:
        available = True
        seen_reference_dates: list[str] = []

        def extract(self, post_title: str, post_body: str, reference_date: str) -> CustomerCommitment:
            self.seen_reference_dates.append(reference_date)
            return CustomerCommitment(
                has_commitment=True,
                commitment_summary="Send Riverbend the revised delivery schedule.",
                due_date="2026-01-09",
            )

    fake = _FakeClient()
    monkeypatch.setattr("backend.app.main._commitment_extraction_client", lambda: fake)

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into source_post "
                "(author_account_id, corporate_entity_id, post_title, post_body, "
                "voc_type_code, visibility_code, created_at) "
                "select author_account_id, corporate_entity_id, %s, %s, 'voc', 'public', %s "
                "from source_post where post_id = %s "
                "returning post_id",
                (
                    "Follow-up on the Riverbend order confirmation",
                    "We still owe Riverbend the revised delivery schedule by next Friday.",
                    "2026-01-05T00:00:00+00",
                    seeded_db["own_private_post_id"],
                ),
            )
            new_post_id = str(cur.fetchone()[0])
    finally:
        admin_conn.close()

    first = client.post(
        f"/api/posts/{new_post_id}/derive-commitment",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert first.status_code == 200, first.text
    first_ticket = first.json()["ticket"]
    assert first.json()["has_commitment"] is True
    assert first_ticket["due_date"] == "2026-01-09"
    assert fake.seen_reference_dates == ["2026-01-05"]

    fake.seen_reference_dates.clear()
    second = client.post(
        f"/api/posts/{new_post_id}/derive-commitment",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["ticket"]["issue_ticket_id"] == first_ticket["issue_ticket_id"]

    listed = client.get(
        f"/api/posts/{new_post_id}/tickets",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert len(listed.json()["tickets"]) == 1

    calendar = client.get("/api/calendar", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    ticket_ids = {c["issue_ticket_id"] for c in calendar.json()["commitments"]}
    assert first_ticket["issue_ticket_id"] in ticket_ids


@pytest.mark.skipif(
    not (_ORCHESTRATOR_BASE_URL and _ORCHESTRATOR_API_KEY),
    reason="set LINEAGEWEAVE_TEST_ORCHESTRATOR_BASE_URL and LINEAGEWEAVE_TEST_ORCHESTRATOR_API_KEY to run",
)
def test_derive_commitment_persists_a_real_llm_derivation(client, demo_analyst_token, seeded_db) -> None:
    """The full write path, end to end: a real LLM call through a live
    contextual-orchestrator resolves a relative deadline ("by next
    Friday") against a reference date, persists it as an issue_ticket,
    and the calendar surfaces it -- not a mocked extraction client.
    """
    os.environ["ORCHESTRATOR_BASE_URL"] = _ORCHESTRATOR_BASE_URL
    os.environ["ORCHESTRATOR_API_KEY"] = _ORCHESTRATOR_API_KEY

    from lineageweave.fixtures import ambiguous_commitment_post

    title, body = ambiguous_commitment_post()

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('permission', 'post_admin', 'Administer posts') on conflict (lookup_code) do nothing"
            )
            cur.execute("select access_role_id from account_role_assignment limit 1")
            role_id = cur.fetchone()[0]
            cur.execute(
                "insert into role_permission (access_role_id, permission_code) values (%s, 'post_admin') "
                "on conflict do nothing",
                (role_id,),
            )
            cur.execute(
                "insert into source_post (author_account_id, corporate_entity_id, post_title, post_body, voc_type_code, visibility_code) "
                "select author_account_id, corporate_entity_id, %s, %s, 'voc', 'public' "
                "from source_post where post_id = %s "
                "returning post_id",
                (title, body, seeded_db["own_private_post_id"]),
            )
            new_post_id = str(cur.fetchone()[0])
    finally:
        admin_conn.close()

    response = client.post(
        f"/api/posts/{new_post_id}/derive-commitment",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    body_json = response.json()
    assert body_json["has_commitment"] is True
    assert body_json["ticket"]["due_date"] is not None
    assert body_json["ticket"]["commitment_summary"]

    calendar_response = client.get("/api/calendar", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    ticket_ids = {c["issue_ticket_id"] for c in calendar_response.json()["commitments"]}
    assert body_json["ticket"]["issue_ticket_id"] in ticket_ids


def test_seed_calendar_commitment_surfaces_on_get_calendar(client, demo_analyst_token, seeded_db) -> None:
    """The same helper `make seed` calls must produce a row GET /api/calendar
    returns -- due 2026-01-09 against the Riverbend fixture created 2026-01-05.
    """
    from scripts.seed_demo_data import _seed_demo_calendar_commitment

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                "select corporate_entity_id, 'TEST-PU-CAL', 'Calendar seed unit' "
                "from source_post where post_id = %s returning process_unit_id",
                (seeded_db["own_private_post_id"],),
            )
            process_unit_id = cur.fetchone()[0]
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            _seed_demo_calendar_commitment(cur, author_id, corp_id, process_unit_id)
    finally:
        admin_conn.close()

    response = client.get("/api/calendar", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 200, response.text
    commitments = response.json()["commitments"]
    dues = {c["due_date"] for c in commitments}
    assert "2026-01-09" in dues
    riverbend = next(c for c in commitments if c["due_date"] == "2026-01-09")
    assert riverbend["ticket_status_label"] == "Open"
    titles = {c["post_title"] for c in commitments}
    from lineageweave.fixtures import ambiguous_commitment_post

    expected_title, _ = ambiguous_commitment_post()
    assert expected_title in titles


def test_seed_fixture_tickets_surface_on_get_calendar(client, demo_analyst_token, seeded_db) -> None:
    """The same helper `make seed` calls must put the A-100 pricing
    and B-200 revision tickets on GET /api/calendar -- otherwise home
    Calendar only shows Riverbend and a B-200 report-member click
    never matches a dated ticket.
    """
    from lineageweave.fixtures import sample_records
    from scripts.seed_demo_data import _seed_fixture_tickets

    fixture_title = sample_records()[1].label  # Pricing renegotiation follow-up
    beta_title = sample_records()[7].label  # Specification revision requested
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            for title in (fixture_title, beta_title):
                cur.execute(
                    "insert into source_post "
                    "(author_account_id, corporate_entity_id, post_title, post_body, "
                    " voc_type_code, visibility_code) "
                    "values (%s, %s, %s, %s, 'voc', 'public')",
                    (author_id, corp_id, title, title),
                )
            _seed_fixture_tickets(cur)
    finally:
        admin_conn.close()

    response = client.get("/api/calendar", headers={"Authorization": f"Bearer {demo_analyst_token}"})
    assert response.status_code == 200, response.text
    pricing = next(
        row
        for row in response.json()["commitments"]
        if row["ticket_title"] == "Send Northridge Grid the revised quote"
    )
    assert pricing["due_date"] == "2026-01-12"
    assert pricing["post_title"] == fixture_title
    assert pricing["ticket_status_label"] == "Open"
    beta = next(
        row
        for row in response.json()["commitments"]
        if row["ticket_title"] == "Send Westfield Power the revised specification"
    )
    assert beta["due_date"] == "2026-01-14"
    assert beta["post_title"] == beta_title
    assert beta["ticket_status_label"] == "Open"


def test_seed_fixture_tickets_surface_on_get_tickets(client, demo_analyst_token, seeded_db) -> None:
    """The same helper `make seed` calls must put a ticket on the A-100
    follow-up and B-200 revision posts -- otherwise a report-member
    click shows No tickets yet.
    """
    from lineageweave.fixtures import sample_records
    from scripts.seed_demo_data import _seed_fixture_tickets

    fixture_title = sample_records()[1].label  # Pricing renegotiation follow-up
    beta_title = sample_records()[7].label  # Specification revision requested
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            ids: dict[str, str] = {}
            for title in (fixture_title, beta_title):
                cur.execute(
                    "insert into source_post "
                    "(author_account_id, corporate_entity_id, post_title, post_body, "
                    " voc_type_code, visibility_code) "
                    "values (%s, %s, %s, %s, 'voc', 'public') returning post_id",
                    (author_id, corp_id, title, title),
                )
                ids[title] = str(cur.fetchone()[0])
            _seed_fixture_tickets(cur)
    finally:
        admin_conn.close()

    headers = {"Authorization": f"Bearer {demo_analyst_token}"}
    response = client.get(f"/api/posts/{ids[fixture_title]}/tickets", headers=headers)
    assert response.status_code == 200, response.text
    titles = {ticket["ticket_title"] for ticket in response.json()["tickets"]}
    assert "Send Northridge Grid the revised quote" in titles
    due = next(
        ticket["due_date"]
        for ticket in response.json()["tickets"]
        if ticket["ticket_title"] == "Send Northridge Grid the revised quote"
    )
    assert due == "2026-01-12"
    pricing = next(
        ticket
        for ticket in response.json()["tickets"]
        if ticket["ticket_title"] == "Send Northridge Grid the revised quote"
    )
    assert pricing["ticket_status_label"] == "Open"

    beta = client.get(f"/api/posts/{ids[beta_title]}/tickets", headers=headers)
    assert beta.status_code == 200, beta.text
    beta_titles = {ticket["ticket_title"] for ticket in beta.json()["tickets"]}
    assert "Send Westfield Power the revised specification" in beta_titles
    beta_due = next(
        ticket["due_date"]
        for ticket in beta.json()["tickets"]
        if ticket["ticket_title"] == "Send Westfield Power the revised specification"
    )
    assert beta_due == "2026-01-14"


def test_seed_fixture_tickets_surface_on_get_activity(client, demo_analyst_token, seeded_db) -> None:
    """The same helper `make seed` calls must XADD ticket_created so
    GET /api/posts/{id}/activity is not empty after a report-member click.
    """
    from lineageweave.fixtures import sample_records
    from scripts.seed_demo_data import _seed_fixture_ticket_activity, _seed_fixture_tickets

    fixture_title = sample_records()[1].label  # Pricing renegotiation follow-up
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            cur.execute(
                "insert into source_post "
                "(author_account_id, corporate_entity_id, post_title, post_body, "
                " voc_type_code, visibility_code) "
                "values (%s, %s, %s, %s, 'voc', 'public') returning post_id",
                (author_id, corp_id, fixture_title, fixture_title),
            )
            post_id = str(cur.fetchone()[0])
            _seed_fixture_tickets(cur)
            _seed_fixture_ticket_activity(cur, author_id, _VALKEY_URL)
            _seed_fixture_ticket_activity(cur, author_id, _VALKEY_URL)
    finally:
        admin_conn.close()

    response = client.get(
        f"/api/posts/{post_id}/activity",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    events = response.json()["events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "ticket_created"
    assert "Send Northridge Grid the revised quote" in events[0]["summary"]
    assert events[0]["actor_account_id"] == str(author_id)


def test_seed_period_report_surfaces_on_get_reports(client, demo_analyst_token, seeded_db) -> None:
    """The same helper `make seed` calls must produce a 2026-W02 report
    GET /api/reports returns -- high-band posts outrank low-band posts
    on the fitted EAP metric.
    """
    from scripts.seed_demo_data import _seed_demo_period_report

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                "select corporate_entity_id, 'TEST-PU-SEED-REPORT', 'Report seed unit' "
                "from source_post where post_id = %s returning process_unit_id",
                (seeded_db["own_private_post_id"],),
            )
            process_unit_id = cur.fetchone()[0]
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            _seed_demo_period_report(cur, author_id, corp_id, process_unit_id)
    finally:
        admin_conn.close()

    response = client.get(
        "/api/reports/process_unit/2026-W02",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    reports = response.json()["reports"]
    assert len(reports) >= 2
    high_report = next(
        report for report in reports if any(m["post_title"].startswith("High-band") for m in report["members"])
    )
    low_report = next(
        report for report in reports if any(m["post_title"].startswith("Low-band") for m in report["members"])
    )
    assert high_report["mean_theta"] > low_report["mean_theta"]
    assert high_report["link_method"] == "fipc"
    assert high_report["selected_model"] in {"grm", "gpcm"}
    assert high_report["delta_mean_theta"] is None
    leftover_kinds = {pair["pair_kind"] for pair in high_report.get("leftover_pairs", [])}
    assert leftover_kinds <= {"closest", "farthest"}
    assert all(pair["post_title"] for pair in high_report.get("leftover_pairs", []))
    assert all(pair["leftover_distance"] >= 0 for pair in high_report.get("leftover_pairs", []))

    week3 = client.get(
        "/api/reports/process_unit/2026-W03",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert week3.status_code == 200, week3.text
    linked = week3.json()["reports"]
    assert linked
    assert linked[0]["link_method"] == "fipc"
    assert linked[0]["anchor_period_code"] == "2026-W02"
    assert linked[0]["mean_theta"] > low_report["mean_theta"]

    index = client.get(
        "/api/reports/process_unit",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert index.status_code == 200, index.text
    periods = {row["period_code"] for row in index.json()["periods"]}
    assert {"2026-W02", "2026-W03"} <= periods

    compare = client.get(
        "/api/reports/compare/2026-W02",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert compare.status_code == 200, compare.text
    kinds = {row["grouping_kind"] for row in compare.json()["groupings"]}
    assert {"process_unit", "corporate_entity", "thread_group"} <= kinds
    threads = {
        row["grouping_label"]: row["mean_theta"]
        for row in compare.json()["groupings"]
        if row["grouping_kind"] == "thread_group"
    }
    assert threads["A-100"] > threads["B-200"]


def test_seed_period_report_includes_fixture_event_lineage_posts(
    client, demo_analyst_token, seeded_db
) -> None:
    """A-100/B-200 reconstruct posts with IRT cells must appear on the
    seeded W02 report and comparison strip -- otherwise click-through
    only opens dummy high/low band rows.
    """
    from scripts.seed_demo_data import (
        _seed_demo_calendar_commitment,
        _seed_demo_period_report,
        _seed_fixture_evaluations,
        _seed_fixture_tickets,
        insert_fixture_source_posts,
    )

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('voc_type', 'vom', 'Voice of Market') "
                "on conflict (lookup_code) do nothing"
            )
            cur.execute(
                "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                "select corporate_entity_id, 'TEST-PU-FIXTURE-REPORT', 'Fixture report unit' "
                "from source_post where post_id = %s returning process_unit_id",
                (seeded_db["own_private_post_id"],),
            )
            process_unit_id = cur.fetchone()[0]
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            insert_fixture_source_posts(cur, author_id, corp_id, process_unit_id)
            _seed_demo_calendar_commitment(cur, author_id, corp_id, process_unit_id)
            _seed_fixture_evaluations(cur)
            _seed_fixture_tickets(cur)
            _seed_demo_period_report(cur, author_id, corp_id, process_unit_id)
    finally:
        admin_conn.close()

    headers = {"Authorization": f"Bearer {demo_analyst_token}"}
    threads = client.get("/api/reports/thread_group/2026-W02", headers=headers)
    assert threads.status_code == 200, threads.text
    reports = threads.json()["reports"]
    a100 = next(report for report in reports if report["grouping_key"] == "A-100")
    b200 = next(report for report in reports if report["grouping_key"] == "B-200")
    a100_titles = {member["post_title"] for member in a100["members"]}
    b200_titles = {member["post_title"] for member in b200["members"]}
    assert "Pricing renegotiation follow-up" in a100_titles
    assert "Follow-up on the Riverbend order confirmation" in a100_titles
    assert "Specification revision requested" in b200_titles
    assert a100["mean_theta"] > b200["mean_theta"]
    follow_up = next(m for m in a100["members"] if m["post_title"] == "Pricing renegotiation follow-up")
    assert follow_up["ticket_due_date"] == "2026-01-12"
    assert follow_up["ticket_title"] == "Send Northridge Grid the revised quote"
    assert follow_up["ticket_status_label"] == "Open"
    revision = next(m for m in b200["members"] if m["post_title"] == "Specification revision requested")
    assert revision["ticket_due_date"] == "2026-01-14"
    assert revision["ticket_title"] == "Send Westfield Power the revised specification"
    assert revision["ticket_status_label"] == "Open"

    compare = client.get("/api/reports/compare/2026-W02", headers=headers)
    assert compare.status_code == 200, compare.text
    thread_counts = {
        row["grouping_label"]: row["post_count"]
        for row in compare.json()["groupings"]
        if row["grouping_kind"] == "thread_group"
    }
    assert thread_counts["A-100"] > 4
    assert thread_counts["B-200"] > 4


def test_seed_period_report_member_click_lands_on_decorated_fixture(
    client, demo_analyst_token, seeded_db
) -> None:
    """The first W02 report member must already have Event Lineage,
    Keyman, and evaluation -- otherwise the reader click opens a dummy
    high/low band row.
    """
    from lineageweave.fixtures import fixture_thread_cast, fixture_titles_in_iso_week
    from scripts.seed_demo_data import (
        _seed_demo_calendar_commitment,
        _seed_demo_period_report,
        _seed_fixture_evaluations,
        _seed_fixture_keymen_and_voc,
        _seed_reconstructed_lineage,
    )

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) "
                "values ('voc_type', 'vom', 'Voice of Market') "
                "on conflict (lookup_code) do nothing"
            )
            cur.execute(
                "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                "select corporate_entity_id, 'TEST-PU-MEMBER-CLICK', 'Member click unit' "
                "from source_post where post_id = %s returning process_unit_id",
                (seeded_db["own_private_post_id"],),
            )
            process_unit_id = cur.fetchone()[0]
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            _seed_reconstructed_lineage(cur, author_id, corp_id, process_unit_id)
            _seed_demo_calendar_commitment(cur, author_id, corp_id, process_unit_id)
            _seed_fixture_evaluations(cur)
            _seed_fixture_keymen_and_voc(cur, corp_id)
            _seed_demo_period_report(cur, author_id, corp_id, process_unit_id)
    finally:
        admin_conn.close()

    headers = {"Authorization": f"Bearer {demo_analyst_token}"}
    decorated = {
        title
        for title in fixture_titles_in_iso_week("2026-W02")
        if (cast := fixture_thread_cast(title)) is not None and cast.person_names
    }
    for grouping in ("thread_group", "process_unit"):
        response = client.get(f"/api/reports/{grouping}/2026-W02", headers=headers)
        assert response.status_code == 200, response.text
        for report in response.json()["reports"]:
            assert report["members"], report["grouping_key"]
            first = report["members"][0]
            assert first["post_title"] in decorated, first["post_title"]
            assert not first["post_title"].startswith(("High-band", "Low-band"))
            assert not {
                "visibility_code",
                "corporate_entity_id",
                "author_account_id",
                "source_detail_state_code",
                "has_real_source_context",
            } & first.keys()
            for pair in report.get("leftover_pairs", []):
                assert not {
                    "visibility_code",
                    "corporate_entity_id",
                    "author_account_id",
                    "source_detail_state_code",
                    "has_real_source_context",
                } & pair.keys()

    threads = client.get("/api/reports/thread_group/2026-W02", headers=headers)
    a100 = next(report for report in threads.json()["reports"] if report["grouping_key"] == "A-100")
    post_id = a100["members"][0]["post_id"]

    lineage = client.get(f"/api/posts/{post_id}/lineage", headers=headers)
    assert lineage.status_code == 200, lineage.text
    body = lineage.json()
    assert body["direct"] or body["indirect"]

    keymen = client.get(f"/api/posts/{post_id}/keymen", headers=headers)
    assert keymen.status_code == 200, keymen.text
    names = {person["person_name"] for person in keymen.json()["keymen"]}
    assert names == {"Ada West", "Priya Nair"}

    evaluation = client.get(f"/api/posts/{post_id}/evaluation", headers=headers)
    assert evaluation.status_code == 200, evaluation.text
    assert len(evaluation.json()["responses"]) == 3


def test_rebuild_reports_requires_post_admin(client, demo_analyst_token) -> None:
    response = client.post(
        "/api/reports/process_unit/2026-W02/rebuild",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 403


def test_reports_reject_unknown_period(client, demo_analyst_token) -> None:
    response = client.get(
        "/api/reports/process_unit/not-a-period",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 422


def test_period_report_high_posts_outrank_low_posts(client, demo_analyst_token, seeded_db) -> None:
    """Insert constructed high/low IRT rows, rebuild, and read GET /api/reports.

    The numbers must come from the fitted EAP metric: high-category posts
    outscore low-category posts in the same process unit and ISO week.
    """
    from datetime import datetime, timezone

    from lineageweave.post_evaluation import CRITERION_CODES, IRT_CATEGORY_COUNT

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) values "
                "('permission', 'post_admin', 'Administer posts'), "
                "('evaluation_criterion', 'general_sentiment_positive', 'Constructive stance'), "
                "('evaluation_criterion', 'general_sentiment_negative', 'Negative stance'), "
                "('evaluation_criterion', 'sales_lead_specificity', 'Sales-lead specificity') "
                "on conflict (lookup_code) do nothing"
            )
            cur.execute("select access_role_id from account_role_assignment limit 1")
            role_id = cur.fetchone()[0]
            cur.execute(
                "insert into role_permission (access_role_id, permission_code) values (%s, 'post_admin') "
                "on conflict do nothing",
                (role_id,),
            )
            cur.execute(
                "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                "select corporate_entity_id, 'TEST-PU-REPORT', 'Report unit' "
                "from source_post where post_id = %s returning process_unit_id",
                (seeded_db["own_private_post_id"],),
            )
            process_unit_id = cur.fetchone()[0]
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            created = datetime(2026, 1, 5, tzinfo=timezone.utc)
            post_ids = {"high": [], "low": []}
            for band, category in (("high", IRT_CATEGORY_COUNT - 1), ("low", 0)):
                for idx in range(4):
                    cur.execute(
                        "insert into source_post "
                        "(author_account_id, corporate_entity_id, process_unit_id, "
                        " post_title, post_body, voc_type_code, visibility_code, created_at) "
                        "values (%s, %s, %s, %s, 'body', 'voc', 'public', %s) returning post_id",
                        (author_id, corp_id, process_unit_id, f"{band} report post {idx}", created),
                    )
                    post_id = cur.fetchone()[0]
                    post_ids[band].append(str(post_id))
                    for code in CRITERION_CODES:
                        cur.execute(
                            "insert into post_evaluation_response "
                            "(post_id, criterion_code, rubric_version, response_category) "
                            "values (%s, %s, '2026-08-13', %s)",
                            (post_id, code, category),
                        )
    finally:
        admin_conn.close()

    rebuild = client.post(
        "/api/reports/process_unit/2026-W02/rebuild",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert rebuild.status_code == 200, rebuild.text
    assert rebuild.json()["group_count"] >= 1

    response = client.get(
        "/api/reports/process_unit/2026-W02",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    reports = response.json()["reports"]
    assert reports
    members = {member["post_title"]: member["theta_eap"] for member in reports[0]["members"]}
    high_mean = sum(theta for title, theta in members.items() if title.startswith("high")) / 4
    low_mean = sum(theta for title, theta in members.items() if title.startswith("low")) / 4
    assert high_mean > low_mean
    assert reports[0]["selected_model"] in {"grm", "gpcm"}
    assert reports[0]["post_count"] == 8
    assert reports[0]["link_method"] == "fipc"

    created_w03 = datetime(2026, 1, 12, tzinfo=timezone.utc)
    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "select author_account_id, corporate_entity_id, process_unit_id "
                "from source_post where post_title = 'high report post 0'"
            )
            author_id, corp_id, process_unit_id = cur.fetchone()
            for idx in range(6):
                cur.execute(
                    "insert into source_post "
                    "(author_account_id, corporate_entity_id, process_unit_id, "
                    " post_title, post_body, voc_type_code, visibility_code, created_at) "
                    "values (%s, %s, %s, %s, 'body', 'voc', 'public', %s) returning post_id",
                    (author_id, corp_id, process_unit_id, f"high week3 report post {idx}", created_w03),
                )
                post_id = cur.fetchone()[0]
                for code in CRITERION_CODES:
                    cur.execute(
                        "insert into post_evaluation_response "
                        "(post_id, criterion_code, rubric_version, response_category) "
                        "values (%s, %s, '2026-08-13', %s)",
                        (post_id, code, IRT_CATEGORY_COUNT - 1),
                    )
    finally:
        admin_conn.close()

    rebuild_w03 = client.post(
        "/api/reports/process_unit/2026-W03/rebuild",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert rebuild_w03.status_code == 200, rebuild_w03.text
    week3 = client.get(
        "/api/reports/process_unit/2026-W03",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert week3.status_code == 200, week3.text
    linked = week3.json()["reports"]
    assert linked
    assert linked[0]["link_method"] == "fipc"
    assert linked[0]["anchor_period_code"] == "2026-W02"
    assert linked[0]["mean_theta"] > reports[0]["mean_theta"]


def test_shared_metric_ranks_two_process_units(client, demo_analyst_token, seeded_db) -> None:
    """Two process units in one week must stay comparable on one bank.

    Independent per-unit refits would both recenter near 0. Rebuild
    scores them on the shared metric so the high unit outranks the low
    unit.
    """
    from datetime import datetime, timezone

    from lineageweave.post_evaluation import CRITERION_CODES, IRT_CATEGORY_COUNT

    admin_conn = psycopg2.connect(seeded_db["dsn"])
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(
                "insert into common_lookup_value (lookup_category, lookup_code, lookup_label) values "
                "('permission', 'post_admin', 'Administer posts') on conflict (lookup_code) do nothing"
            )
            cur.execute("select access_role_id from account_role_assignment limit 1")
            role_id = cur.fetchone()[0]
            cur.execute(
                "insert into role_permission (access_role_id, permission_code) values (%s, 'post_admin') "
                "on conflict do nothing",
                (role_id,),
            )
            cur.execute(
                "select author_account_id, corporate_entity_id from source_post where post_id = %s",
                (seeded_db["own_private_post_id"],),
            )
            author_id, corp_id = cur.fetchone()
            created = datetime(2026, 1, 5, tzinfo=timezone.utc)
            for band, category in (("high", IRT_CATEGORY_COUNT - 1), ("low", 0)):
                cur.execute(
                    "insert into process_unit (corporate_entity_id, process_unit_code, process_unit_name) "
                    "values (%s, %s, %s) returning process_unit_id",
                    (corp_id, f"TEST-PU-{band.upper()}", f"{band} unit"),
                )
                unit_id = cur.fetchone()[0]
                for idx in range(4):
                    cur.execute(
                        "insert into source_post "
                        "(author_account_id, corporate_entity_id, process_unit_id, "
                        " post_title, post_body, voc_type_code, visibility_code, created_at) "
                        "values (%s, %s, %s, %s, 'body', 'voc', 'public', %s) returning post_id",
                        (author_id, corp_id, unit_id, f"{band} unit post {idx}", created),
                    )
                    post_id = cur.fetchone()[0]
                    for code in CRITERION_CODES:
                        cur.execute(
                            "insert into post_evaluation_response "
                            "(post_id, criterion_code, rubric_version, response_category) "
                            "values (%s, %s, '2026-08-13', %s)",
                            (post_id, code, category),
                        )
    finally:
        admin_conn.close()

    rebuild = client.post(
        "/api/reports/process_unit/2026-W02/rebuild",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert rebuild.status_code == 200, rebuild.text
    assert rebuild.json()["group_count"] >= 2

    response = client.get(
        "/api/reports/process_unit/2026-W02",
        headers={"Authorization": f"Bearer {demo_analyst_token}"},
    )
    assert response.status_code == 200, response.text
    reports = response.json()["reports"]
    high_report = next(
        report for report in reports if any(m["post_title"].startswith("high unit") for m in report["members"])
    )
    low_report = next(
        report for report in reports if any(m["post_title"].startswith("low unit") for m in report["members"])
    )
    assert high_report["mean_theta"] > low_report["mean_theta"]
    assert high_report["link_method"] == "fipc"
    assert low_report["link_method"] == "fipc"
    for report in (high_report, low_report):
        selected = report["selected_items"]
        assert [item["rank"] for item in selected] == [1, 2, 3]
        assert all(item["information"] > 0.0 for item in selected)
        assert {item["item_code"] for item in selected} == set(CRITERION_CODES)


def test_post_search_matches_source_record_key_and_one_character_typo(
    client, demo_analyst_token, seeded_db
) -> None:
    """The board searches preserved source identity, not only the internal UUID."""
    source_system = "synthetic-source"
    source_key = "SYNTHETIC-SOURCE-REC-001"
    conn = psycopg2.connect(seeded_db["dsn"])
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "update source_post set source_system_code = %s, source_record_key = %s where post_id = %s",
                (source_system, source_key, seeded_db["own_private_post_id"]),
            )
    finally:
        conn.close()

    headers = {"Authorization": f"Bearer {demo_analyst_token}"}
    exact = client.get("/api/posts", params={"search": source_key}, headers=headers)
    assert exact.status_code == 200, exact.text
    exact_row = next(
        post for post in exact.json()["posts"] if post["post_id"] == seeded_db["own_private_post_id"]
    )
    assert exact_row["source_system_code"] == source_system
    assert exact_row["source_record_key"] == source_key

    typo = source_key[:-1] + "2"
    fuzzy = client.get("/api/posts", params={"search": typo}, headers=headers)
    assert fuzzy.status_code == 200, fuzzy.text
    assert any(post["post_id"] == seeded_db["own_private_post_id"] for post in fuzzy.json()["posts"])
