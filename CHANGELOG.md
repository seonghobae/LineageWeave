# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Renamed "Buyer" terminology to reader/workspace naming across the frontend
  shell, backend evidence helpers, and living docs (ADR 0119). LineageWeave
  has no explicit buyer role, so `BuyerNav`/`BuyerDestination` became
  `WorkspaceNav`/`WorkspaceDestination`, `.buyer-gnb*` CSS became
  `.workspace-gnb*`, and prose referring to the reading user now says
  "reader" instead of "buyer". Historical ADRs and changelog entries keep
  their original wording as a point-in-time record.

### Fixed

- Tenant settings now refresh their audit timestamp on every successful update,
  and the year field stays visibly blank while an administrator edits it.

- Tenant identity metadata migration now repairs blank legacy settings before
  adding non-empty and copyright-year constraints, so existing Compose volumes
  can replay the migration without losing valid tenant-provided values.

- The post-detail dialog focus trap now excludes descendants of `aria-hidden`
  content as well as collapsed `details`, keeping keyboard focus inside the
  visible modal controls.

- `make smoke` and `make seed` now run through the locked project `uv`
  environment, so local OIDC and synthetic-data workflows resolve the same
  pinned dependencies as CI.
- The workspace Event Lineage global Search action now retries focus after the
  board finishes loading, so navigation from Customer master, Calendar, or
  Ask Agent lands the cursor in the search box. The handled request is consumed,
  so later board navigation does not steal focus, and Search closes an open
  mobile drawer like every other destination change.
- Mobile Event Lineage evidence cards now read their translated column labels
  from the rendered cells instead of hardcoded English CSS, and the two drawer
  close controls have distinct accessible names.
- Event Lineage SVG edges now retain their instance-specific direction markers,
  so parent-to-child arrows remain visible when multiple lineage groups render.
- All OpenAI-compatible chat-completion consumers now validate the shared
  response envelope before parsing it, preventing malformed provider bodies
  from escaping as raw `KeyError` or response-shape details.
- Customer Master integration fixtures no longer reference an unshipped
  Global Ask history migration; Global Ask remains stateless as documented by
  ADR 0090, while the shipped scope-facet migration is applied directly.
- The static SQL review contract now counts the Customer Master evidence query
  that uses closed schema fragments and bound entity ids.

## [2.12.6] - 2026-08-20

### Added

- Production OIDC can now use a real Keyverse issuer through
  `KEYVERSE_ISSUER` and `KEYVERSE_CLIENT_ID`. The backend discovers the
  provider's JWKS and verifies the issuer; Compose keeps local Keycloak only
  as an explicit development fallback and does not emulate Keyverse.
- Relation verification now preserves a separately authorized internal source
  post containing normalized organization and relationship context. Open that
  evidence from the counterparty popup without treating it as an external URL.
- Large corpora now use bounded post and Event Lineage landing projections so
  buyers can open complete post-specific detail from a responsive first view.

## [2.12.5] - 2026-08-18

### Fixed

- Migrations 0019 and 0025 (R&R role-catalog identity backfills) both
  used `min(uuid_column)` to pick "the" value from a `having count(*)
  = 1` group -- Postgres has no built-in `min(uuid)` aggregate, so
  both failed outright the first time either was actually run against
  a real, non-trivial dataset. Fixed to
  `min(uuid_column::text)::uuid`, safe given the query's own
  `having count(*) = 1` already guarantees exactly one value per
  group. Applying the full migration set 0001-0029 against a real,
  long-lived dataset also surfaced that this database's original
  bootstrap had left several *earlier* migrations (0001, 0016)
  partially applied -- specific tables/indexes/backfills their own
  later statements defined were missing even though their initial
  `create table` statements had run. All 29 migrations are now
  confirmed genuinely, fully applied end to end against a real
  43,814-post dataset; every table/index any migration defines is now
  present, verified via direct schema comparison, not assumption.

### Known issue (not fixed here, flagged for follow-up)

- `backend/tests/test_api.py::test_start_analysis_run_recovers_the_a100_fork`
  and `::test_tepp_start_persists_published_accepted_evidence`
  deterministically fail against a real live PostgreSQL/Keycloak/Valkey
  stack (this whole test module is `skipif`-guarded and never runs in
  CI) with `CheckViolationError` on `analysis_run_status_time_check`
  (`occurred_at <= recorded_at`): the row's `occurred_at`
  (`datetime.now(timezone.utc)`, captured in `backend/app/analysis_run_start.py`)
  reproducibly lands ~15-20ms *after* `recorded_at`
  (`clock_timestamp()`, evaluated later, at actual insert time, inside
  a `before insert` trigger) -- the wrong direction, given
  `recorded_at` is evaluated strictly after `occurred_at` is captured
  in every code path. Confirmed via a direct clock-sync measurement
  (5 samples, Python vs. Postgres `clock_timestamp()` interleaved)
  that there is no measurable systemic clock drift between the test
  process and this Postgres instance under normal conditions, and
  confirmed the failure is 100% reproducible in isolation (not a
  concurrency/load artifact) and entirely pre-existing (verified via
  `git diff` that no file in this change touches
  `analysis_run_start.py` or the 0018 migration that defines this
  constraint). Root cause not yet conclusively identified; deferred
  as out of scope for this migration-catchup change (a different
  feature area -- analysis-run/TEPP lifecycle, not R&R/summary/
  verification) rather than rushed. 553 other tests unaffected.

- `get_or_create_corporate_entity`'s post-lock duplicate-create re-check
  fuzzy-matched against every cataloged entity, not just an exact
  concurrent duplicate of the entity being created. A newly-created
  parent whose name is a prefix of the child now being created (e.g.
  "Acme" as parent of "Acme Gwangju Plant") scored ~0.7 similarity
  against that child under the shared 0.6 threshold, so the child was
  silently bound to its own parent's id instead of getting its own
  catalog row -- undermining exactly the "통합 고객사 계열 tree AI"
  (integrated customer affiliate tree) hierarchy the feature exists
  for. The re-check now requires an exact post-normalization match
  (`min_similarity=1.0`); real mention resolution against the full
  candidate set is unchanged. Caught locally by
  `test_first_mention_of_a_new_counterparty_creates_a_real_corporate_entity`,
  which requires a live PostgreSQL/Keycloak/Valkey stack and is
  therefore skipped in CI (`make up` required) -- confirmed CI's own
  "Full test suite" run has never actually executed this assertion.
- `test_start_analysis_run_recovers_the_a100_fork` seeded
  `snapshot_sha256`/`configuration_sha256`/`code_revision_sha` with
  `"t"`/`"u"`/`"v"`-repeated literals; none are valid hex characters,
  so the very first insert failed its own `analysis_source_snapshot`
  check constraint every time this test actually ran. Same CI-blind
  gap as above -- fixed to valid hex placeholders matching this file's
  existing convention.

## [2.12.3] - 2026-08-18

### Added

- `make seed` inserts Late Demo public post (2026-01-13) so the
  January 12 Demo Corp lineage and TEPP runs' knowledge cutoff is
  falsifiable: Demo public post still opens; Late Demo does not.
  The live post list still shows Late Demo. The cutoff filter
  itself already lives on this stack (ADR 0016). TEPP honesty is
  unchanged: accepted acks stay Failed transport evidence, not
  Succeeded. Never invent a theta.

## [2.12.2] - 2026-08-18

### Fixed

- Accepted TEPP transport evidence now stores **received** (transport
  response) and **recorded** (row write) as distinct clocks when those
  instants differ (ADR 0035 follow-up). After `make seed`, Demo Analyst
  opens **TEPP measurement · Failed · Demo Corp** Measurement evidence
  and sees one Received clock when seed receipt and persist share an
  instant. A later start that persists in a later minute shows both
  clocks. Digest recomputation is unchanged. Hidden runs stay 404.
  Never invent a theta.

## [2.12.1] - 2026-08-17

### Fixed

- A published TEPP **accepted** acknowledgement is stored as
  **aggregate transport evidence** and stays Failed /
  `tepp_completed_result_unsupported` (ADR 0035). After `make seed`,
  Demo Analyst opens that Failed Demo Corp row to read contract
  version, accepted run id, clocks, and a copyable SHA-256. The
  section says completed-artifact identity is unavailable until TEPP
  publishes a versioned completed-result contract. A
  LineageWeave-local `time_multilevel_multi_affiliation` envelope, or
  any other unpublished completed shape, stays Failed /
  `tepp_result_not_persisted` and must not stamp Succeeded. Missing
  `TEPP_TRANSPORT_URL` stays Failed / `tepp_not_available`. Never
  invent a theta.

## [2.12.0] - 2026-08-17

### Added

- A persistable TEPP **time / multilevel / multi-affiliation** result
  is stored on the analysis-run and marked Succeeded (ADR 0034). After
  `make seed`, Demo Analyst sees **TEPP measurement · Succeeded · Demo
  Corp** next to the Failed missing-transport row. Home list and detail
  show measured clocks and affiliation counts. A screen reader on that
  Succeeded row hears open the run to read those aggregates, not only
  the title. An `accepted` ack or an envelope this product cannot store
  stays Failed / `tepp_result_not_persisted`. Missing
  `TEPP_TRANSPORT_URL` stays Failed / `tepp_not_available`. Never
  invent a theta.

## [2.11.0] - 2026-08-17

### Added

- Home now shows the authorized customer-group tree (Group / Company /
  Plant) instead of only a flat corp list. After `make seed`, Demo
  Analyst walks Demo Group → Demo Corp → Demo Plant; a click opens that
  entity as the corporate-entity report grouping. The post-scoped
  affiliate tree is unchanged (ADR 0033).
- Abbreviations on a post are cross-checked against that tree through
  the existing Searxng client. A unique corroborated hit binds; a down,
  empty, or tied search stays unbound and does not invent a parent or
  AUTO row. Seeded `DC` on Demo Corp is synthetic Demo Corp only.

## [2.10.4] - 2026-08-17

### Fixed

- After a Demo Corp lineage reconstruction has started, the same
  granted retention purge empties `analysis_run_lineage_edge`,
  `analysis_run_reconstruction`, and `analysis_source_snapshot_member`
  when those tables exist, including their delete-reject triggers
  (ADR 0032). Follow the same grant + admin + phrase path — do not
  `DISABLE TRIGGER` as superuser.

## [2.10.3] - 2026-08-17

### Fixed

- Opening a listed analysis-run that then 404s drops that stale row
  from the home list after an authorized re-read. The next action is
  announced as a status alert: open a remaining visible run, or
  request a lineage reconstruction. The message still does not name
  the thread or the cutoff (ADR 0014 / ADR 0018).

## [2.10.2] - 2026-08-17

### Fixed

- Opening a post whose embedded picture uses invoice-like HTML
  (`alt="Invoice > 1000"`, unquoted `width`, newlines in the base64)
  now shows the picture. The raw payload no longer returns when a
  remote-only or SVG tag is the whole body. Re-export as PNG or JPEG
  if the type is rejected. The popup, `extract_base64_images`, and
  `chunk_by_dom` share one raster allowlist (ADR 0031).

## [2.10.1] - 2026-08-17

### Fixed

- Analysis-run list buttons now include the kind-specific next-action
  sentence in the accessible name (WCAG 2.2 SC 4.1.2). Open a Failed
  TEPP row: a screen reader hears connect the measurement service, not
  only the run title. `aria-label` replaces button contents (ADR 0014).
  No TEPP theta is invented.

## [2.10.0] - 2026-08-17

### Added

- Home Rankings panel fuses visible posts through `RankWeaveClient`
  (ADR 0030). After login with the port disabled or the library
  missing, Demo Analyst sees **Rankings · RankWeave not available**.
  An accepted hit lists the title; click opens that post. A hidden
  post is omitted. Never invent a fused score or a theta.
- Period reports now persist closest and farthest leftover
  post–criterion pairs after the IRT main effects (Jeon leftover
  map, ADR 0028 / 0029). After `make seed`, leftover pairs sit above
  the member list; clicking a pair opens that post. A leftover pair
  for a hidden post is omitted the same way a hidden member is.

## [2.9.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now names the
  next action after landed cited evidence: Linked post evidence is
  current, then read Event Lineage on that post. Home list opens do
  not add that copy. No TEPP theta is invented. No cutoff body is
  invented (ADR 0016).

## [2.8.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now puts the
  first cited evidence immediately under the named citation next
  action, ahead of the chat input. Home list opens still wait for a
  citation click. No TEPP theta is invented. No cutoff body is
  invented (ADR 0016).

## [2.7.2] - 2026-08-17

### Fixed

- R&R person chips now read `cataloged_person_id` from
  `post_summary_role` (ADR 0027). Open a post whose R&R names a
  cataloged person: the chip is a button even when Keyman extraction
  was not run on that post. Click it to walk that person, not a later
  same-named row. Historical backfill leaves a role unbound when two
  same-named mentions already exist.

## [2.7.1] - 2026-08-17

### Fixed

- `POST /api/analysis-runs` records Pending lineage only (ADR 0017).
  TEPP and period-report kinds are 422 so this path cannot invent a
  measurement. Open Analysis runs and wait until affiliated corps
  load; choose a corp if you walk more than one, then click
  **Request a lineage reconstruction**. Preview the picker in
  Storybook (`Analysis/LineageEntityPicker`). Failed TEPP stays
  terminal on this write.

## [2.7.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now names the
  first cited source after the landed first Ask answer: Linked post,
  then open that evidence. Home list opens do not add that copy. No
  TEPP theta is invented. No cutoff body is invented (ADR 0016).

## [2.6.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now puts the
  first Ask answer immediately under the named seed next action, ahead
  of the chat input. Home list opens keep that answer after the input.
  No TEPP theta is invented. No cutoff body is invented (ADR 0016).

## [2.5.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now names the
  first Ask after landed chat: What happened between these events,
  then read that answer. Home list opens do not add that copy. No
  TEPP theta is invented. No cutoff body is invented (ADR 0016).

## [2.4.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now puts Ask
  about this lineage immediately under the Ask next action, ahead of
  Affiliate tree. Home list opens keep Ask after Keyman. No TEPP theta
  is invented. No cutoff body is invented (ADR 0016).

## [2.3.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now focuses
  the Ask heading after Priya Nair related nodes are current. Home
  list opens do not steal that focus. No TEPP theta is invented. No
  cutoff body is invented (ADR 0016).

## [2.2.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now names the
  next action after Priya Nair related nodes are current: **Ask about
  this lineage**. Home list opens do not add that copy. No TEPP theta
  is invented. No cutoff body is invented (ADR 0016).

## [2.1.0] - 2026-08-17

### Added

- Opening a title marked **Updated after cutoff** now shows the body
  that run knew beside the live rewrite. After `make seed`, open Demo
  public post from the Demo Corp lineage run: **Body this run knew** is
  the January follow-up; the live body names the later delivery window.
  `GET /api/posts/{id}?as_of=` reads `source_post_revision`. Analysis-run
  detail stays titles and clocks. A missing revision is omitted — never
  a fabricated cutoff sentence or a TEPP theta (ADR 0025).

## [2.0.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now lands
  Priya Nair related nodes under the first-related next action, ahead
  of Affiliate tree. Home list opens still wait for a related click.
  No TEPP theta is invented. No cutoff body is invented (ADR 0016).

## [1.9.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now names the
  first related node after landed Ada West related: Priya Nair, then
  read that person. Home list opens do not add that copy. No TEPP
  theta is invented. No cutoff body is invented (ADR 0016).

## [1.8.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now lands
  Ada West related nodes under the first-Keyman next action, ahead
  of Affiliate tree. Home list opens still wait for a Keyman click.
  No TEPP theta is invented. No cutoff body is invented (ADR 0016).

## [1.7.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now names the
  first Keyman after landed evaluation: Ada West, then read that
  person. Home list opens do not add that copy. No TEPP theta is
  invented. No cutoff body is invented (ADR 0016).

## [1.6.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members now puts
  Keyman and evaluation immediately under the Event Lineage next
  action, ahead of Affiliate tree. Home list opens keep evaluation
  above Event Lineage. No TEPP theta is invented. No cutoff body is
  invented (ADR 0016).

## [1.5.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members names the next
  action after the current Event Lineage node: read Keyman and
  evaluation. Home list opens do not add that copy. No TEPP theta is
  invented. No cutoff body is invented (ADR 0016).

## [1.4.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members marks that
  post current in the popup Event Lineage DAG, so the focused heading
  has a you-are-here node. The home DAG stays unmarked. No TEPP theta
  is invented. No cutoff body is invented (ADR 0016).

## [1.3.0] - 2026-08-17

### Added

- Opening Public post from the landed Demo Corp members focuses the
  popup Event Lineage heading, matching the next-action copy. Home
  post-list opens do not steal that focus. No TEPP theta is invented.

## [1.2.0] - 2026-08-17

### Added

- Opening **Public post** from the landed Demo Corp report now names
  the next action: that post is open from Demo Corp, so read Event
  Lineage, Keyman, and evaluation. The opened member is current. Mean
  θ stays on the report panel. No TEPP theta is invented. No cutoff
  body is invented (ADR 0016).

## [1.1.0] - 2026-08-17

### Added

- Opening **Open period report 2026-W02** now puts the Demo Corp
  report (mean θ and member posts) immediately under the named next
  action, ahead of Other Corp and the week strip. The Public post
  member stays clickable. Mean θ stays on the report panel. No TEPP
  theta is invented. No cutoff body is invented (ADR 0016).

## [1.0.0] - 2026-08-17

### Added

- Opening **Open period report 2026-W02** now names the next action on
  the landed Demo Corp report: read its mean θ and member posts, then
  open a post. The focused comparison chip uses the visible
  `Corporate entity: Demo Corp` caption and the persisted mean θ
  (WCAG 2.5.3). Changing the week still focuses the report period
  field. Mean θ stays on the report panel. No TEPP theta is invented.

## [0.99.0] - 2026-08-17

### Added

- Opening **Open period report 2026-W02** when the operator is already
  on that week lands the grouping comparison strip on Demo Corp. The
  Demo Corp chip is current and focused. Changing the week still
  focuses the report period field. Mean θ stays on the report panel.
  No TEPP theta is invented.

## [0.98.1] - 2026-08-17

### Fixed

- Authorized analysis-run list and detail queries are now complete
  parameterized SQL literals. Semgrep no longer treats the visibility
  predicate as string-concatenated user input. The $1 / $2 / $3 binds
  are unchanged. No TEPP theta is invented.

## [0.98.0] - 2026-08-17

### Added

- Opening **Open period report 2026-W02** from a corporate-entity
  analysis run also switches Report grouping to Corporate entity and
  marks the Demo Corp grouping current. The opened report is named
  Demo Corp, not a UUID. Mean θ stays on the report panel. No TEPP
  theta is invented.

## [0.97.0] - 2026-08-17

### Added

- A Succeeded period-report analysis run now opens the scored week.
  After `make seed`, open **Period report · Succeeded · Demo Corp**
  and click **Open period report 2026-W02**: the report period field
  is focused on that week. Failed rows stay closed. Mean θ stays on
  the report panel. No TEPP theta is invented.

## [0.96.0] - 2026-08-17

### Added

- `make seed` now records **Period report · Succeeded · Demo Corp** on
  the shared snapshot after the calibrated report tables are written
  (ADR 0024). Open that row to confirm the cutoff posts. Mean θ stays
  on the period-report panel. Start stays 422. No TEPP theta is
  invented.

## [0.95.0] - 2026-08-17

### Added

- Analysis-run detail now lists labeled outbox delivery: Claimed then
  Delivered (ADR 0023). After `make seed`, open the Demo Corp lineage
  run to see those times. Stream entry ids stay off the payload. No
  TEPP theta is invented.

## [0.94.0] - 2026-08-17

### Added

- `POST /api/analysis-runs/{id}/start` now commits Running plus one
  durable outbox row, wakes Valkey (`analysis-run-outbox`), then
  delivers ThreadWeave or `tepp_client` (ADR 0023). A crash after
  Start leaves the work item; refresh finishes it. Period-report
  stays 422. No TEPP theta is invented.

## [0.93.0] - 2026-08-17

### Added

- `make seed` now persists the designed A-100 fork on the Demo Corp
  Succeeded lineage run. Open that run: the revised quote and delivery
  question follow the pricing follow-up and are buttons. Start is
  unchanged. No TEPP theta is invented.

## [0.92.0] - 2026-08-17

### Added

- **Start TEPP measurement** on a Pending TEPP row submits
  `AnalysisRunRequest` through `tepp_client` (ADR 0022). A missing
  `TEPP_TRANSPORT_URL` or a refused URL is Failed /
  `tepp_not_available`. An accepted envelope is Failed /
  `tepp_result_not_persisted`. Failed stays terminal: **Request a new
  TEPP measurement** records a new Pending run. Period-report start
  stays 422. No TEPP theta is invented.

## [0.91.0] - 2026-08-17

### Added

- After **Start reconstruction**, the titled A-100 edges are buttons.
  Click the revised-quote child to open the live post; click the
  pricing-follow-up parent to open that post. A child marked
  **Updated after cutoff** still shows the live-body warning. The
  popup does not invent a cutoff snapshot. No TEPP theta is invented.

## [0.90.0] - 2026-08-17

### Added

- Opening an analysis-run title marked **Updated after cutoff** now
  shows a popup status that the body is live, not a cutoff snapshot
  (ADR 0016). After `make seed`, open the Demo Corp lineage run and
  click Demo public post: the warning appears above the live body
  and tells you to compare it with this run. Demo private post and
  the home post list do not. The popup does not invent the earlier
  text. No TEPP theta is invented.

## [0.89.0] - 2026-08-17

### Added

- Analysis-run detail now compares each in-cutoff title's live
  `updated_at` with that run's knowledge cutoff. After `make seed`,
  open the Demo Corp lineage run: Demo public post is marked
  **Updated after cutoff**; Demo private post is not. Opening a
  marked title still shows the live body -- cutoff body versioning
  stays a later slice (ADR 0016). The list stays aggregates-only.
  No TEPP theta is invented.

## [0.88.0] - 2026-08-16

### Added

- `POST /api/analysis-runs/{id}/start` runs ThreadWeave on a visible
  Pending lineage cutoff bag and persists run-scoped parent choices
  (ADR 0021). Open the Pending Demo Corp row, then start reconstruction.
  The designed A-100 fork (revised quote and delivery question under the
  pricing follow-up) is the acceptance tree. TEPP and period-report
  start are 422 — this path does not invent a theta. A Succeeded retry
  returns the stored digest. A Running restart is 409. Create freezes
  authorized post ids so start cannot pick up a later backfill. Live
  Event Lineage stays a separate rebuild.

## [0.87.0] - 2026-08-16

### Added

- Operators can empty a run-bearing analysis-run registry without a
  superuser trigger disable. Insert an unrevoked
  `analysis_run_retention_grant` for `session_user`, grant
  `analysis_run_retention_admin`, then
  `select purge_analysis_run_registry('approved-retention-purge')`
  (ADR 0020). Export `analysis_run_retention_event`, delete those
  rows, then roll back 0020 and 0018. A raw `DELETE`, a published
  token without a grant, and a runtime role that is not the admin
  role still fail.
- Repeated citation chips and close buttons use named design tokens
  in `frontend/src/styles/tokens.css`. Preview them in Storybook
  (`cd frontend && pnpm run storybook`).

## [0.86.2] - 2026-08-16

### Fixed

- An R&R organization button now walks the catalog id stored on that
  role row (ADR 0019). Two catalog orgs can share a display name; open
  the post, click the name, and you stay on the resolved org — not a
  homonym. `GET /api/teams/{id}/related` matches person/entity authz:
  another corp's private-only team is 403; an unknown UUID is 404.

## [0.86.1] - 2026-08-16

### Changed

- Opening a post or its evidence panel now shows each embedded
  `data:image` picture in document order, with the surrounding sentences
  as text. The raw base64 string is no longer dumped into the popup.
  Remote `http(s)` image URLs stay unloaded. After `make seed`, a post
  whose body includes a data-URI image shows the picture; Extract Keyman
  or Ask still runs OCR on that image for search.

### Fixed

- Opening a Pending lineage run repeats that reconstruction has not
  started. Pending next-action copy is pinned to the registered run
  kinds, so a Pending TEPP row does not say reconstruction.

## [0.86.0] - 2026-08-16

### Added

- Related-node walks now include team and organization mention edges.
  After `make seed` and a summary that names 설계팀 on two posts, open
  either post, click the R&R team, and open the sibling post (ADR 0018).
  A team-only follow-up is no longer an island.
- `GET /api/teams/{team_id}/related` starts the same RWR walk Keyman
  and corporate-entity related already use. Related team chips are
  buttons.

### Fixed

- Thread-group analysis-run *lists* now require an in-cutoff visible
  post. A later public post in that thread group no longer surfaces a
  January run the account was not allowed to know.
- Failed period-report rows tell the operator to rebuild the report.
  Next-action copy is pinned to the registered run kinds. A pending
  TEPP corpus does not claim a calibrated measurement.

## [0.85.0] - 2026-08-16

### Added

- `POST /api/analysis-runs` records a Pending lineage or TEPP run on an
  authorized cutoff capture (ADR 0017). The home panel's **Request a
  lineage reconstruction** button writes that row so an operator can
  confirm the cutoff corpus immediately. Reconstruction and live TEPP
  execution stay later slices — this write never invents a theta.
- Failed lineage rows tell the operator to retry reconstruction; only
  Failed TEPP rows mention the measurement service. Pending rows say
  reconstruction has not started yet.

## [0.84.1] - 2026-08-16

### Fixed

- Analysis-run detail keeps 12-character digest prefixes as visible
  text (so assistive technology hears `Code` / `Config` values) and
  puts the full digest on hover. Open the Demo Corp lineage run, hover
  a prefix, and match it to the API payload. The home list still hides
  digests even when the list JSON includes them.
- Opening a cutoff title now says the live body may have changed after
  that run. Compare the opened post with the cutoff date before you
  treat it as reconstructed evidence (ADR 0016).

## [0.84.0] - 2026-08-16

### Added

- `make seed` records a Demo Corp TEPP measurement run through
  `tepp_client` on the same snapshot as the lineage run (ADR 0013).
  The default transport is unavailable, so the home list shows
  "TEPP measurement · Failed · Demo Corp" and tells the operator to
  open the run, then connect the measurement service. Detail history
  keeps `tepp_not_available` -- never a fabricated theta. TEPP stays
  a wire client, not a local psychometric engine. `make seed` skips
  snapshot-count inserts once counts exist so a re-run does not hit
  the freeze trigger. A failed lineage row tells the operator to retry
  reconstruction; only a failed TEPP row mentions the measurement
  service. A failed period-report row tells the operator to rebuild
  the report from a current snapshot. A pending TEPP row does not
  claim a calibrated measurement. Stacked PRs now run the same
  GitHub Checks as PRs to main.

## [0.83.0] - 2026-08-16

### Fixed

- Analysis-run detail now lists only ABAC-visible posts whose
  `created_at` is at or before that run's `knowledge_cutoff`. After
  `make seed`, open the Demo Corp lineage run: Demo public post is
  there; a later own-corp follow-up is not. The live post list is
  unchanged. Click a listed title to inspect what that cutoff
  reconstructed (ADR 0016).
- Upgrading through `0016_cross_post_actor_identity.sql` copies R&R
  person names into `post_summary_person_mention` and leaves Keyman
  `post_person_mention.mention_context` in place. Re-run Keyman only
  when you want a new Keyman set -- a later summary no longer erases
  the stolen row.

## [0.82.0] - 2026-08-16

### Added

- Analysis-run detail lists ABAC-visible posts in the run's scope.
  After `make seed`, the Demo Corp lineage run opens the Demo public
  post. Hidden other-corp private posts never appear. List payloads
  stay aggregates-only.

## [0.81.0] - 2026-08-16

### Added

- Analysis-run detail shows the labeled lifecycle: Pending, Running,
  then Succeeded, with occurrence times from `analysis_run_status_event`.
  The list stays latest-status only. Hidden runs still 404 and never
  leak events. Failure codes stay machine tokens -- no invented label.
  Synthetic Demo Corp seed only.

## [0.80.0] - 2026-08-16

### Added

- Home Analysis runs rows are buttons. Clicking the seeded Demo Corp
  lineage run opens `GET /api/analysis-runs/{id}` and shows cutoff,
  requested date, and document count. A hidden run is "This analysis
  run is not visible." -- never a raw 404 or a DSN. Still synthetic
  aggregates only.

## [0.79.0] - 2026-08-16

### Added

- Authorized analysis-run evidence on the product home page. After
  `make seed`, Demo Analyst sees "Lineage reconstruction · Succeeded ·
  Demo Corp" with the synthetic document count. `GET /api/analysis-runs`
  is scoped in SQL: another tenant's run 404s and never appears in the
  list. The payload is labels and aggregates -- never source SQL, a DSN,
  or a raw record. TEPP stays behind `tepp_client`; Null channels are
  unchanged.

## [0.78.0] - 2026-08-15

### Changed

- Related-node person chips now use the localized `person_side` lookup label
  supplied by the authorized API payload. Users see business context such as
  `Our side` or `Counterparty`, while ontology class metadata remains available
  separately for semantic processing and provenance.
- Related-person buttons now expose that same caption in the accessible name, so
  assistive technology hears `Related nodes for Priya Nair (Counterparty)`
  instead of the name alone.
- Structured extraction, summarization, commitment, relationship-classification,
  and LLM-as-a-Judge consumers now request contextual-orchestrator `auto` mode
  so the orchestration plane can meet the quality requirement and then minimize
  known execution cost. Explicit checked `verify` paths remain unchanged
  (ADR 0015).

## [0.77.0] - 2026-08-14

### Fixed

- Keyman and R&R person mentions now replace independent source projections. Knowledge Graph edges have one canonical identity plus post-level evidence, so removed actors and concurrent writes cannot leave stale or duplicate buyer-visible relationships.
- Vision-response parsing now strips balanced outer Markdown emphasis from field values
  while still accepting emphasized field labels, so OCR such as
  ``TEXT: **LT7**`` is not truncated.
- A real live synthetic regression batch run surfaced a genuine
  `DeadlockDetectedError` from concurrent corporate-entity creation:
  two concurrent transactions each creating a different new entity,
  mentioned in opposite order across two different posts, took
  row-level locks in opposite order and deadlocked. Entity *creation*
  (the rare, first-mention-only branch) now serializes through a
  single named Postgres advisory transaction lock, taken only right
  before the write and auto-released at commit/rollback -- the
  lock-free similarity-matching fast path every already-cataloged
  entity resolves through is unaffected. See ADR 0012.

## [0.76.0] - 2026-08-14

### Added

- Standards-complete W3C PROV-O support: all 30 classes, all 50
  normative properties, both qualification tables, qualified-to-
  unqualified implication, property hierarchy, defined inverses,
  Appendix B inverse-name normalization, RDF serialization, and a
  normalized PostgreSQL assertion store with fail-closed domain,
  range, object-kind, and datatype enforcement (ADR 0011).
- A dedicated exact-head PROV-O contract workflow runs the complete
  registry/inference suite, real PostgreSQL migration tests, public
  docstring checks, and 100% statement/branch coverage for the owned
  runtime module.

### Changed

- The product navigation graph remains an explicit projection;
  literal-valued and qualified provenance is no longer forced into
  `knowledge_graph_edge`.

### Fixed

- Review hardening verifies complete hierarchy placement, rejects parent
  failures and cycles, propagates canonical affiliations, replaces stale
  actor projections, enforces atomic team identity, validates timezone-aware
  `xsd:dateTime` literals (including the XSD `±14:00` offset bound), and
  protects referenced provenance rows.

## [0.75.0] - 2026-08-14

### Added

- A real counterparty organization mentioned for the first time now
  gets auto-created into the corporate hierarchy, not left permanently
  unresolved. Synthetic regression fixtures prove the first-mention gap.
  An LLM proposes a
  Group/Company/Plant placement from context; a real new
  `corporate_entity` row is only created once the proposal is
  search-corroborated (reusing the existing Searxng verification
  client, no new search integration). Auto-created rows get a
  deterministic `AUTO-`-prefixed code, kept structurally separate from
  the real login corp-code namespace. Wired into both Keyman
  affiliation resolution and R&R organization-actor resolution.

## [0.74.0] - 2026-08-14

### Added

- R&R team and organization actors now get a shared identity across
  posts, not just per-post free text -- the same "설계팀" (design
  team) named in ten posts resolves to one `cataloged_team` row
  (identity key: team name + parent org, since a bare team name is not
  by itself identifying), and an organization actor resolves against
  the existing `corporate_entity` catalog. Each resolved actor gets a
  real Knowledge Graph mention edge (`edge_mention_team`,
  `edge_team_affiliation`, `edge_mention_organization`), so extraction
  results now genuinely become cross-post lineage clues instead of
  per-post islands. A person R&R actor is opportunistically joined to
  an existing Keyman-cataloged person by name (documented gap: R&R does
  not yet originate new person identities itself -- see ADR 0009).

## [0.73.0] - 2026-08-14

### Fixed

- Image OCR/caption parsing no longer discards a real vision response
  just because its formatting was close but not exact (bolded labels
  like `**TEXT:**`, reordered labels, or a missing TAGS line) --
  observed live against synthetic embedded-image fixtures in the synthetic regression batch
  in format-variation fixtures. Fields are now recovered independently; only a
  response with neither TEXT nor CAPTION content is treated as
  unusable. A strict format mismatch was silently producing the same
  "[image: content unavailable]" placeholder as a genuinely unavailable
  vision channel, discarding real, already-paid-for content.

## [0.72.0] - 2026-08-14

### Added

- Abbreviated/slang organization names (e.g. "AGP") are now resolved
  to their canonical name ("Aurora Grid Power") via LLM context, then
  cross-verified against external search before being trusted -- new
  `lineageweave/organization_name_resolution.py`, reusing the existing
  Searxng verification client rather than a second web-search
  integration. Cached in a new `organization_name_resolution` table
  keyed by the raw name.
- Wired into Keyman affiliation ingestion (both the API path and the
  offline synthetic-batch script): a search-corroborated resolution feeds
  `resolve_corporate_entity`, an unverified one leaves the raw name
  unchanged.

### Fixed

- The offline synthetic-batch script's own re-implementation of Keyman
  affiliation persistence was missing `role_title` entirely (a stale
  copy that predated that feature) -- fixed alongside this change.

## [0.71.0] - 2026-08-14

### Added

- VOC evidence now quotes the extractive excerpt under the counterparty
  it names. After `make seed`, Northridge Grid in VOC evidence shows
  the sentence that mentions it, instead of a detached excerpt list
  above the names. Unassigned excerpts stay in the list; a post with
  no named organization still says so.

## [0.70.0] - 2026-08-14

### Added

- R&R's `actor_type_code` gains `prov_team`, a meso-level actor type for
  a named sub-unit of a company (e.g. "설계팀"/design team) -- distinct
  from both a person and the company itself. Grounded in the W3C
  Organization Ontology's `org:OrganizationalUnit` (Reynolds, 2014).
- A team actor now requires `affiliated_organization_name` in the same
  way a person actor does -- a team's own name never answers "which
  company."
- R&R badge shows a distinct "Team" label/color, not the prior binary
  Person/Organization ternary (which would have mislabeled a team as
  "Organization").

## [0.69.0] - 2026-08-14

### Added

- Keyman extraction now captures a stated job title/position
  (`PersonMention.job_title`), since two different real people can
  share a name and a title is real evidence for telling them apart.
  Persisted to `person_affiliation.role_title` (an existing schema
  column, previously never populated) and a new
  `cataloged_person.last_known_job_title` for a title stated without a
  named organization to attach it to.
- `_upsert_person` no longer blindly merges a same-name+side match: a
  genuinely conflicting stated title creates a fresh person row instead
  of reusing one, verified by a real test with two posts naming the
  same name and different titles.
- Keyman panel shows the person's title next to their name. After
  `make seed`, Ada West is "Account manager" and Priya Nair is
  "Procurement lead" so the title is visible without a live LLM.

### Fixed

- `scripts/seed_demo_data.py` no longer embeds the local Keycloak admin
  password. `make seed` still supplies the compose default via
  `KEYCLOAK_ADMIN_PASSWORD`; a direct script run requires that env var
  or `--keycloak-admin-password`.

## [0.68.0] - 2026-08-14

### Changed

- R&R's named actor is no longer forced into a person slot. A
  business post can name an organization acting in its own name
  ("당사," "Demo Corp"), not an individual --
  `RoleResponsibility.actor_name` (renamed from `person_name`) now
  carries `actor_type_code` (Person / Organization, W3C PROV-O
  grounded) and an LLM-inferred `affiliated_organization_name` for
  person actors. The popup's R&R list shows a Person/Organization
  badge and the inferred affiliation; only a person actor still links
  to the Keyman panel. See ADR 0006.

## [0.67.0] - 2026-08-14

### Added

- Keyman affiliation names that resolve to a cataloged org start
  the same related-node walk as a related-entity click. After
  `make seed`, Demo Corp next to Ada West opens
  `GET /api/corporate-entities/{id}/related`. Unresolved affiliation
  names stay text -- never a guessed neighborhood.

## [0.66.0] - 2026-08-14

### Added

- Classified counterparty names that resolve to a cataloged org start
  the same related-node walk as an affiliate-tree org click. After
  `make seed`, Demo Corp in Counterparties opens
  `GET /api/corporate-entities/{id}/related`. Unresolved names
  (Northridge Grid) stay text -- never a guessed neighborhood.

## [0.65.0] - 2026-08-14

### Added

- Resolved affiliate-tree organizations start the same related-node
  walk as a Keyman org click. After `make seed`, Demo Corp / Test
  Corp in the tree open `GET /api/corporate-entities/{id}/related`.
  Unresolved names stay text -- never a guessed neighborhood.

## [0.64.0] - 2026-08-14

### Added

- Related corporate-entity nodes in the Keyman walk are the same
  RWR as a person. Clicking `Demo Corp` / `Test Corp` loads
  `GET /api/corporate-entities/{id}/related` so the buyer can
  continue the walk from the org. An entity with no visible
  affiliation stays 403 -- never a guessed neighborhood.

## [0.63.0] - 2026-08-14

### Added

- A third seeded Ask question, "What is the next commitment?", on
  every fixture that already answers the first two chips. A-100
  names Send Northridge Grid the revised quote due 2026-01-12;
  B-200 names the Westfield specification due 2026-01-14; Riverbend
  names its calendar ticket due 2026-01-09; rec-006 says it has no
  open commitment. After `make seed` the popup chips connect Ask
  to the same dated tickets home Calendar already lists.

## [0.62.0] - 2026-08-14

### Added

- VOC evidence counterparties that already appear on the affiliate
  tree are the same Keyman walk. Clicking `Northridge Grid` loads
  related nodes for Priya Nair so the buyer does not have to find
  the same org again under Affiliate tree.

### Security

- Verification badges only become links for `http:` / `https:`
  evidence URLs. A `javascript:` or `data:` value stays a non-link
  badge.

## [0.61.0] - 2026-08-14

### Changed

- Activity event-type badges show Ticket created / Status changed /
  Commitment derived instead of snake_case codes. Unknown types stay
  as the raw code; the badge never invents a name.

## [0.60.0] - 2026-08-14

### Changed

- Activity-feed `ticket_status_changed` summaries use the lookup
  label (`In progress`, `Closed`) instead of the raw code. Same
  `common_lookup_value` labels the popup select, Calendar, and
  period-report members already show.

## [0.59.0] - 2026-08-14

### Added

- Period-report members show the ticket status lookup label next to
  the title and due date. After `make seed` the A-100 pricing
  follow-up reads Open plus `due 2026-01-12`, same label the
  Calendar and popup select already use.

## [0.58.0] - 2026-08-14

### Changed

- After an unmatched Verify 503, the Verify against web search
  button is hidden the same way as Evaluate / Extract / Derive.
  Seeded counterparty badges stay; the button that can only 503
  again does not. Still never fabricates a search result.

## [0.57.0] - 2026-08-14

### Added

- Home Calendar rows show the ticket status lookup label next to the
  due date. After `make seed` the A-100 pricing ticket reads Open
  plus `due 2026-01-12`, same label the popup select already uses.

## [0.56.0] - 2026-08-14

### Added

- A second seeded Ask question, "Who is involved?", on every fixture
  that already answers "What happened between these events?" A-100
  names Ada West and Priya Nair; B-200 names Jordan Hale; rec-006
  and Riverbend say they do not name a Keyman. After `make seed`
  the popup shows two chips instead of one canned prompt.

## [0.55.0] - 2026-08-14

### Added

- Ticket status on the popup select shows `common_lookup_value`
  labels (`Open`, `In progress`, `Closed`) instead of raw codes.
  Codes stay on the payload. A missing lookup falls back to the code.

## [0.54.0] - 2026-08-14

### Changed

- After an unmatched 503, Evaluate, Extract Keymen, and Derive
  commitment are hidden the same way as free-text Ask. Seeded
  evaluation, Keyman, and ticket rows stay; the buttons that can
  only 503 again do not. Still never fabricates a live LLM result.

## [0.53.0] - 2026-08-14

### Added

- `make seed` opens a ticket on the B-200 specification-revision
  fixture. A B-200 report-member click now shows "Send Westfield
  Power the revised specification" (due 2026-01-14) instead of
  "No tickets yet," and home Calendar lists it next to the A-100
  pricing ticket.

## [0.52.0] - 2026-08-14

### Changed

- After an unmatched Ask 503, the free-text input is hidden. Seeded
  answers stay on screen with "Only seeded questions can be answered
  without an orchestrator." Still never fabricates a live reply.

## [0.51.0] - 2026-08-14

### Added

- Home Calendar lists the seeded A-100 pricing ticket due 2026-01-12.
  After `make seed`, GET /api/calendar includes "Send Northridge Grid
  the revised quote" next to the Riverbend commitment, so the buyer
  sees the same dated ticket already shown on the period-report row.

## [0.50.0] - 2026-08-14

### Added

- Seeded fixture summaries include R&R from the Event Lineage cast.
  An A-100 DAG click now shows Ada West / Priya Nair, and a B-200
  click shows Jordan Hale -- not an empty R&R list. rec-006 and the
  calendar commitment stay empty because they have no cast people.
  An R&R name that matches a Keyman opens the same related-node walk
  as the Keyman and affiliate-tree buttons.

## [0.49.0] - 2026-08-14

### Added

- Period-report members show the earliest open ticket title next to
  the due date. The home-page report list now reads "Send Northridge
  Grid the revised quote" plus `due 2026-01-12` on the A-100 pricing
  follow-up, so the buyer sees the seeded ticket before opening the
  post.

## [0.48.0] - 2026-08-14

### Added

- Period-report members include the earliest open ticket due date.
  The home-page report list shows `due 2026-01-12` on the A-100
  pricing follow-up so the buyer sees the seeded ticket before
  opening the post.

## [0.47.0] - 2026-08-14

### Added

- Seeded Ask answers for the demo public post, A-100/B-200 Event
  Lineage fixtures, and the Riverbend calendar post. `GET`/`POST
  /api/posts/{id}/chat` read `post_chat_result` first so the popup
  transcript answers "What happened between these events?" without an
  orchestrator. An unmatched question still 503s -- never a fabricated
  live reply.

## [0.46.0] - 2026-08-14

### Changed

- Evaluate, Extract Keymen, Derive commitment, and Verify show the
  same kind of empty state as chat when the backing service is 503
  (`Evaluation unavailable…`, `Keyman extraction unavailable…`,
  `Commitment derivation unavailable…`, `Verification unavailable…`)
  instead of `HTTP 503`. Still never fabricates a result.

## [0.45.0] - 2026-08-14

### Changed

- Chat 503 (orchestrator unset) shows
  `Chat unavailable (LLM orchestrator not configured).` instead of
  `HTTP 503`. Still never fabricates an answer.

## [0.44.0] - 2026-08-14

### Added

- `make seed` XADDs a `ticket_created` event onto Valkey for the
  seeded A-100 and calendar tickets. A report-member click now shows
  "Ticket created: Send Northridge Grid the revised quote" instead of
  "No activity yet."

## [0.43.0] - 2026-08-14

### Added

- VOC evidence counterparties show the same verification badge as the
  Counterparties panel (`Not yet checked` / `Corroborated` plus the
  evidence URL when present). The extractive quote is not an unchecked
  second claim.

## [0.42.0] - 2026-08-14

### Added

- `make seed` opens tickets on the A-100 pricing follow-up and
  delivery-schedule fixtures. A report-member click now shows
  "Send Northridge Grid the revised quote" (due 2026-01-12) instead
  of "No tickets yet."

## [0.41.0] - 2026-08-14

### Changed

- Period-report members with Event Lineage, Keyman, and evaluation
  sort ahead of dummy high/low band rows. A-100 fixtures score on the
  high process unit and B-200 on the low unit, so a member click opens
  a reconstruct post that already has those panels.

## [0.40.0] - 2026-08-14

### Added

- Seeded period reports fold A-100/B-200 Event Lineage fixtures and
  the Riverbend calendar post (already carrying IRT cells) into the
  shared-metric 2026-W02 bank. The comparison strip can open those DAG
  posts; dummy high/low band posts remain for the PU ranking test.

## [0.39.0] - 2026-08-14

### Added

- Affiliate-tree people are the same Keyman walk as the Keyman panel.
  Clicking `Ada West` or `Priya Nair` on the tree loads related nodes
  (`GET /api/keymen/{id}/related`) so the buyer does not have to find
  the same name again under Keyman.

## [0.38.0] - 2026-08-14

### Added

- Seeded Keyman and VOC counterparty for B-200 Event Lineage fixtures
  (Jordan Hale / Westfield Power, Voice of Market). Clicking a B-200
  DAG node is no longer an empty Keyman or VOC panel. A-100 and
  rec-006 casts are unchanged.

## [0.37.0] - 2026-08-14

### Added

- Seeded Keymen, affiliate-tree leaves, and VOC counterparties for
  every A-100 proj-alpha Event Lineage fixture and the calendar
  Riverbend post. Clicking a DAG node now shows Ada West / Priya Nair,
  Northridge Grid, and an extractive excerpt without a live
  orchestrator. rec-006 stays uncast so it remains its own root. A
  post with no named org still has empty VOC excerpts -- never a
  fabricated quote.

## [0.36.0] - 2026-08-14

### Added

- `make seed` writes constructed IRT rubric cells for the demo public
  post, A-100/B-200 Event Lineage fixtures, and the calendar
  commitment. The Post quality panel shows those categories after a
  fresh stack -- not "Not yet evaluated." Cells are title-derived, not
  an LLM judge; thetas still come only from `calibrate_period_report`.

## [0.35.0] - 2026-08-13

### Added

- Post list and popup show `common_lookup_value` labels for VOC type
  and visibility (`Voice of Customer`, `Public`) instead of raw codes.
  Codes stay on the payload. A missing lookup falls back to the code.

## [0.34.0] - 2026-08-13

### Added

- Seeded Korean summaries for every A-100/B-200 reconstruct fixture and
  the calendar commitment post. Clicking an Event Lineage DAG node or a
  calendar row now serves `GET /api/posts/{id}/summary` from
  `post_summary_result` without a live orchestrator. A non-fixture post
  with no stored row still 503s -- never a fabricated summary.

## [0.33.0] - 2026-08-13

### Added

- Home-page grouping comparison strip: `GET /api/reports/compare/{period}`
  returns every process unit, corporate entity, and thread group scored
  on the shared FIPC metric. Rebuild now writes all three kinds.
  Clicking a row switches the Period reports grouping. Seed assigns
  high posts to thread A-100 and low posts to B-200 so the strip is
  not empty after `make seed`.

## [0.32.0] - 2026-08-13

### Added

- CAT item-information selection on the shared FIPC bank: after a
  group is scored, `information_polytomous` ranks rubric items by
  Fisher information at that group's mean θ (Lord, 1980). Rank 1 is
  the max-info pick -- a high PU and a low PU can be measured by
  different items on the same bank. Rankings persist to
  `report_item_information` and the Period reports panel labels
  `CAT: sales-lead I=0.70`. Information comes from fast-mlsirm's
  Rust GRM/GPCM curves, never a hand-rolled I(θ).

## [0.31.0] - 2026-08-13

### Added

- Shared-metric FIPC: the first period free-calibrates one item bank
  on the pooled posts; every process unit (and other grouping) is
  then scored on that bank so a high PU and a low PU stay comparable.
  Independent per-group refits would each re-center near 0. The
  Period reports panel labels first-period groups `shared metric`.

## [0.30.0] - 2026-08-13

### Added

- Persisted Korean summaries (`post_summary_result` /
  `post_summary_event` / `post_summary_role`). `GET /api/posts/{id}/summary`
  returns a stored row first so a seeded demo popup is not empty when
  the LLM orchestrator is off. Live derivation still writes through
  the same tables. Seed writes a synthetic summary for the demo public
  post. A missing stored row and a missing LLM stay 503 -- never a
  fabricated summary.

## [0.29.0] - 2026-08-13

### Added

- True cross-period FIPC linking: the first week for a grouping
  free-calibrates and persists `report_item_parameter`; later weeks
  EAP-score on those fixed item parameters so mean θ is comparable
  across weeks (Kim, 2006). An independent all-high week would
  re-center near 0; the linked week stays high on the reference
  metric. `GET /api/reports/{grouping}` lists the trend; the Period
  reports panel shows `vs 2026-W02: +0.92`. Seed writes a constructed
  2026-W02 reference and 2026-W03 all-high follow-up.

## [0.28.2] - 2026-08-13

### Added

- Period reports lists each member post with its fitted EAP θ and
  opens that post on click -- the same pattern as the calendar.

## [0.28.1] - 2026-08-13

### Added

- `make seed` inserts constructed high/low IRT rows for 2026-W02 and
  persists a real FIPC report, so the Period reports panel is not empty
  after a fresh stack. Thetas still come only from
  `calibrate_period_report`.

## [0.28.0] - 2026-08-13

### Added

- ADR 0003 slice 3: `lineageweave/period_report.py` fits GRM and GPCM
  with `fast_mlsirm.fit_polytomous`, EAP-scores posts, and picks the
  model via `fixed_item_calibration_diagnostics`. Scores persist to
  `report_period_score` / `report_member_score`.
  `GET /api/reports/{grouping}/{period}` and `POST .../rebuild`
  (`post_admin`) plus a home-page Period reports panel. The accuracy
  test constructs high vs low category groups and asserts the fitted
  mean θ ranks them correctly -- no hardcoded score.

## [0.27.0] - 2026-08-13

### Added

- ADR 0003 slice 2: a post can be LLM-as-a-Judge evaluated through
  `fast-mlsirm`'s `ContextualOrchestratorJudge`. Scores persist only
  via `LLMJudgeResult.to_irt_row()` into `post_evaluation_response`
  (one row per post per rubric criterion). Null client is unavailable,
  never a fabricated score.
- Versioned rubric: constructive stance, negative stance, sales-lead
  specificity. `POST /api/posts/{id}/evaluate` +
  `GET /api/posts/{id}/evaluation`, and an "Evaluate post" panel on
  the post popup.

## [0.26.0] - 2026-08-13

### Added

- External search verification for Knowledge Graph relation inferences:
  `lineageweave/relation_verification.py`'s `SearxngRelationVerificationClient`
  checks an LLM-classified counterparty organization/relationship
  against a self-hosted Searxng instance, catching a hallucinated
  organization name with zero real-world footprint (FEVER grounding:
  Thorne, Vlachos, Christodoulopoulos, & Mittal, 2018). A search hit
  only corroborates when a distinctive org-name token appears in the
  result host or snippet and the host is not itself a search page --
  engines echo any query in the title, so "any result" is not evidence.
- New Docker Compose service `searxng` (`docker/searxng/`), wired into
  the backend via `SEARXNG_BASE_URL`.
- `post_counterparty_entity` gained `verification_status_code`
  (`verify_pending` / `verify_corroborated` / `verify_uncorroborated`),
  `verification_evidence_url`, `verification_checked_at`
  (`migrations/0004_relation_verification.sql`). A re-classification
  resets these back to pending.
- New `POST /api/posts/{id}/verify-relations` endpoint and a
  `CounterpartyPanel` UI section (status badge, linked to the evidence
  URL when corroborated, with a "Verify against web search" action).
- ADR 0005 documents the design decision.

## [0.25.0] - 2026-08-13

### Added

- Post bodies are normalized before ever reaching an LLM or embedding
  call: HTML tags are stripped to clean text, per-block formatting
  (`style`, heading level) is kept as separate `FormattingHint` metadata
  instead of being embedded, and base64-embedded images are described
  by a vision-capable model and placed as `[image: caption | text: ocr]`
  at their original document position instead of being sent raw or
  dropped (`lineageweave/post_content_normalization.py`, VIPS grounding:
  Cai, Yu, Wen, & Ma, 2003). Plain-text comparison operators (`qty < 50`)
  are not treated as HTML.
- `chunking.py`'s DOM chunker now captures each block's `style`
  attribute and splits on `h1`-`h6` heading boundaries.
- New `VISION_MODEL` setting; `extract-keymen`, post summary, commitment
  derivation, and chat source retrieval (including linked posts pulled
  in as RAG context) all normalize `post_body` before the LLM sees it.
  The raw post-detail read (`GET /api/posts/{id}`) is intentionally
  left untouched so the frontend still renders the post as-authored.

## [0.24.0] - 2026-08-13

### Added

- Related Keyman nodes are now walkable: a related post opens that
  post, a related person loads *their* RWR neighbourhood. Dead text
  next to "Related to Ada West" is no longer a dead end.
- Chat citation chips show the source post's title
  (`cited_posts` from `POST /api/posts/{id}/chat`) instead of a
  truncated UUID. `cited_post_summaries` drops unknown ids rather than
  inventing a label.

## [0.23.0] - 2026-08-13

### Added

- Keyman side and corporate-entity level now carry lookup labels from
  `common_lookup_value` (`person_side_label`, `entity_level_label`).
  The popup shows "Ada West (Our side)" and "Demo Corp (Company)"
  instead of raw `our_side` / `company` / `plant` codes. Missing lookup
  rows still fall back to the code, never an invented name.

## [0.22.0] - 2026-08-13

### Added

- Related Keyman nodes now carry the ontology class (`ontology_iri`,
  `ontology_label`) from `docs/ontology/lineageweave-kg.ttl`, so the
  popup shows "Priya Nair (Person)" instead of the raw `node_person`
  lookup code. Missing terms stay unlabeled rather than inventing a
  string -- same missing-vs-negative rule as every Null channel.
  `GET /api/keymen/{id}/related` is the wire; the frontend falls back
  to `node_type_code` only when the ontology has no term.

### Fixed

- `frontend/package.json` was invalid JSON after #24 dropped the
  comma on the version line, so `pnpm run test` / CI frontend could
  not even parse the manifest.

## [0.21.2] - 2026-08-13

### Added

- The Knowledge Graph is now grounded in a real, machine-checked
  Ontology and Semantic Layer (see
  [ADR 0004](docs/adr/0004-knowledge-graph-ontology.md)) -- the
  brief's latest revision required this everywhere the KG is used
  (Keyman traversal, corporate hierarchy tree, entity-relationship
  classification, indirect lineage linking, in-popup chat evidence).
  `docs/ontology/lineageweave-kg.ttl`: a real OWL 2 / RDFS / SKOS
  ontology (Turtle) formalizing `knowledge_graph_edge`'s node/edge
  vocabulary and the `entity_relationship_type`/`person_side`/
  `corporate_entity_level` controlled vocabularies -- classes with
  declared subclass relations, object properties with
  `rdfs:domain`/`rdfs:range`, and the corporate-level hierarchy
  (Group -> Company -> Plant) as a proper SKOS concept scheme.
  `lineageweave/ontology.py` parses it with `rdflib` and exposes the
  vocabulary as importable IRI constants.
- `tests/test_ontology.py`: a real round-trip check, not just "does
  the file parse" -- every lookup code `scripts/seed_demo_data.py`
  actually seeds (for the categories this ontology covers) must have
  a matching ontology term, and vice versa, so the ontology cannot
  silently drift from the relational schema's real vocabulary.

## [0.21.1] - 2026-08-13

### Fixed

- `test_seed_calendar_commitment_surfaces_on_get_calendar` drives the
  same `_seed_demo_calendar_commitment` helper `make seed` uses, then
  `GET /api/calendar`, and asserts the Riverbend ticket is due
  2026-01-09. Without this, a seed helper that wrote the wrong date
  would only fail in a live compose stack.

## [0.21.0] - 2026-08-13

### Added

- `make seed` now inserts the synthetic Riverbend commitment post
  (`fixtures.ambiguous_commitment_post`, created_at 2026-01-05) plus
  one open dated ticket (due 2026-01-09). Fresh stacks show a row on
  the home-page Calendar instead of an empty panel that made 0.18.0's
  surface look unfinished. Re-seed is idempotent. The empty-state copy
  tells the buyer how to populate the calendar (Derive, or a ticket
  with a due date) when there really are none.

## [0.20.0] - 2026-08-13

### Added

- The post-detail Event Lineage panel now draws the same git-branch SVG
  as the home page, scoped to that post's reconstruct group
  (`subgraphForPost`). Opening an A-100 post shows the `rec-002` fork
  and keeps B-200 out; the direct/indirect lists stay as the
  why-linked distinction. Tests drive `subgraphForPost` on the
  designed A-100 fixture.

## [0.19.0] - 2026-08-13

### Added

- `fast-mlsirm` as a pinned git dependency (`pyproject.toml`) -- the
  first of three staged slices toward weekly/monthly PU/team/project
  reports (see [ADR 0003](docs/adr/0003-fast-mlsirm-report-integration.md)).
  It already implements the brief's LLM-as-a-Judge -> IRT-row ->
  Fixed-Item Parameter Calibration pipeline, provider-neutrally against
  contextual-orchestrator; reused rather than reimplemented. No
  product behavior change in this slice -- infra only.
- `requires-python` moved from `>=3.10` to `>=3.12` to match
  `fast-mlsirm`'s own floor. `backend/Dockerfile`'s build stage gained
  a pinned, non-interactive `rustup` install (`build-essential` for
  the linker), since `fast-mlsirm` ships a PyO3/maturin Rust core with
  no fallback wheel. The pytest CI job installs the same toolchain
  before `pip install -e ".[backend]"`. Verified the compiled
  extension actually loads (not the NumPy parity fallback) both
  locally and in a freshly built `backend` Docker image. TEPP stays
  the temporal/event measurement platform -- this pin is the IRT
  compute library, not a fork of TEPP.

## [0.18.0] - 2026-08-13

### Added

- Customer commitment derivation and a calendar/to-do surface -- the
  brief's "이슈 관리는 To Do 와 캘린더로 자동 등록" and "고객과의
  약속에 관해서 LLM 자동 도출" items, unified into one design: a
  derived commitment *is* the ticket that shows up on the calendar,
  not a separate concept. `lineageweave/commitment_extraction.py`:
  pluggable LLM client that decides whether a post contains a genuine
  customer commitment (a promise with a deadline, not just any event)
  and resolves relative phrases ("by next Friday") against a supplied
  reference date. `POST /api/posts/{post_id}/derive-commitment`
  (`post_admin`) runs it and, when found, persists an `issue_ticket`
  with `due_date`/`commitment_summary` set; `has_commitment: false` is
  a normal 200, not an error, since most posts have no commitment.
  `GET /api/calendar` lists every dated ticket the account may see,
  soonest first, ABAC-filtered per row like every other cross-post
  endpoint.
- `issue_ticket` gained `due_date` and `commitment_summary` columns
  (folded into `migrations/0001_initial_schema.sql`, plus
  `migrations/0003_ticket_commitment_calendar.sql` for upgrading an
  existing volume, matching the `0002` precedent).
- Frontend: a "Derive commitment" action in the ticket panel, due
  dates shown on ticket rows, and a Calendar panel on the product home
  page listing upcoming commitments across every visible post,
  clickable through to the source post.
- Verified with a real LLM call through a locally-launched
  contextual-orchestrator instance: `ambiguous_commitment_post`'s
  relative "by next Friday" deadline resolved to the correct absolute
  date against a supplied reference date, and a second sentence that
  merely *looks* date-adjacent (a past event) was correctly not
  treated as a commitment.

### Fixed

- `due_date` was a `timestamptz`. Binding a Python `date` becomes
  midnight in the session timezone, then `.date()` on the UTC
  (or local) datetime shifts the calendar day -- "2026-01-09"
  came back as "2026-01-08". The column is now a `date`, matching
  the LLM's YYYY-MM-DD. A malformed string still surfaces as 422.
- Derive used wall-clock `now()` as the reference date. Relative
  phrases in a historical post ("by next Friday") must resolve against
  the post's `created_at` (TimeML document creation time), or the
  calendar entry lands on the Friday after the click, not the Friday
  the commitment was made.
- Re-deriving the same post stacked a second open ticket. The persist
  path now upserts the existing open commitment ticket.
- `GET /api/calendar` included closed tickets, so finished work still
  looked upcoming. Closed rows are excluded; a dated ticket created
  through the regular ticket API still appears while it is open.
- The "Derive commitment" button was shown to accounts without
  `post_admin` and then 403'd. It is now gated the same way as Extract
  Keymen. Calendar rows also show the source post title.
- Ticket SQL stopped interpolating a column-list constant via f-string
  (`asyncpg-sqli` Semgrep). The column list is a static literal in
  each query; values stay parameterized.

## [0.17.0] - 2026-08-13

### Added

- Valkey as a real event queue -- not a cache, not a second database. It
  had been running in `docker-compose.yml` since Phase 1 with nothing in
  the codebase ever publishing or reading from it (the brief's "Event
  Queue, not MQ" requirement was unfulfilled infrastructure).
  `backend/app/activity_stream.py`: ticket create/status-change
  mutations `XADD` an event onto a per-post stream
  (`activity:{post_id}`, approximately trimmed to the most recent 1000
  entries); `GET /api/posts/{post_id}/activity` reads it straight back
  with `XREVRANGE` -- no consumer group, no background worker, the
  smallest slice where Valkey is actually load-bearing.
- Frontend: an Activity panel in the popup (list + manual Refresh),
  genuinely wired to the new endpoint.
- Verified through the real Docker Compose network end to end (not just
  `pytest`): created and patched a ticket via the actual backend
  container, confirmed the events on `GET .../activity`, and confirmed
  directly with `valkey-cli XLEN` against the actual `valkey` container
  that the stream is real.

## [0.16.0] - 2026-08-13

### Added

- Affiliate tree and VOC evidence on the post-detail popup. The schema
  already stored a self-referencing `corporate_entity` hierarchy and a
  `voc_type_code`, but the buyer only saw a raw code and a comma-separated
  affiliation list.
  `lineageweave/affiliate_tree.py` builds the ancestor forest of the
  organizations a post's Keymen actually touch (Bhattacharya & Getoor,
  2007's candidate-generation stage: an unresolved name is its own root,
  never a guessed parent). `lineageweave/voc_evidence.py` quotes the
  sentence that names a classified organization (ACE mention extent;
  Doddington et al., 2004) and returns nothing when the name is absent.
- Backend: `GET /api/posts/{post_id}/affiliate-tree` and
  `GET /api/posts/{post_id}/voc-evidence`, same RBAC+ABAC gate as every
  other post endpoint. Seed now inserts Demo Group → Demo Corp so the
  tree is visible on a freshly seeded stack.
- Frontend: Affiliate tree panel, VOC excerpt block, clickable Keyman
  (loads `GET /api/keymen/{id}/related`), Event Lineage links that open
  the linked post, and Extract Keymen for `post_admin`.

## [0.15.0] - 2026-08-13

### Added

- Milestone 4, Phase 5: issue ticket management -- the one explicit
  product-brief item with a schema table (`issue_ticket`) but no
  implementation until now. `backend/app/issue_ticket_ingestion.py`:
  CRUD helpers, deliberately not a pluggable-LLM channel -- ticket
  status is a closed enum in `common_lookup_value`.
  `GET`/`POST /api/posts/{post_id}/tickets`,
  `PATCH /api/tickets/{issue_ticket_id}` -- same RBAC (`post_read` for
  reads, `post_admin` for writes) + ABAC as every other post-scoped
  endpoint. `PATCH` resolves the ticket's owning post first and
  ABAC-checks that. An invalid `ticket_status_code` hits the real FK
  and surfaces as 422.
- Frontend: `IssueTicketPanel` in the popup -- list, create, and inline
  status-update.

### Fixed

- `frontend/Dockerfile`: pid-file sed now matches `/run/nginx.pid`
  (the alpine image's real path), so non-root `USER nginx` can start.

## [0.14.0] - 2026-08-13

### Added

- Product home page renders the reconstruct DAG as a git-branch SVG
  (same layout language as `web/index.html`), grouped by reconstruct's
  `thread_group_key`. Branch points are orange, isolated roots stay
  visible, and a node click opens that post. `GET /api/lineage` now
  includes `group` from the same `reconstruct_group_key()` rebuild uses,
  so the UI cannot split A-100 / B-200 differently than reconstruct.
- `Rebuild lineage` on the home page for `post_admin` accounts
  (`POST /api/lineage/rebuild`). Viewers still only see the graph.

## [0.13.1] - 2026-08-13

### Fixed

- Rebuild no longer derives reconstruct `group_key`/`secondary_key` from
  process unit or voc type. Those collapsed A-100/B-200 and
  proj-alpha/proj-beta and lost the designed `rec-002` fork.
  `source_post` now persists `thread_group_key` and
  `secondary_grouping_key`; seed writes fixture `occurred_at` into
  `created_at`. `test_rebuild_lineage_recovers_the_a100_fork` drives
  rebuild on the same A-100+B-200 rows seed inserts.

## [0.13.0] - 2026-08-13

### Added

- `POST /api/lineage/rebuild` (`post_admin`): runs `reconstruct()` over
  every `source_post` and writes `post_lineage_edge`. Grouping keys are
  persisted on the post (`thread_group_key` / `secondary_grouping_key`).
- `GET /api/lineage`: ABAC-filtered `{nodes, edges}` in the same shape as
  the stdlib demo server, so the product UI can show the reconstructed
  DAG. The React home page now lists those parent→child edges.
- `backend/tests/test_api.py::test_rebuild_lineage_recovers_the_a100_fork`
  inserts the designed A-100 fixture as real `source_post` rows, rebuilds,
  and asserts the fork is visible on both the graph and per-post lineage.

## [0.12.0] - 2026-08-13

### Added

- `lineageweave/lineage_persistence.py`: flattens `reconstruct()` trees
  into the `(parent, child, fused_score)` rows `post_lineage_edge`
  stores. `tests/test_lineage_persistence.py` proves the designed A-100
  fork (`rec-002` → `rec-003` and `rec-004`) is in that contract, and
  that unrelated `rec-006` is not forced onto a parent.
- `scripts/seed_demo_data.py` now inserts the synthetic A-100 / B-200
  fixture posts and persists those reconstruct edges, so
  `GET /api/posts/{id}/lineage` (the Event Lineage panel) is not empty
  on a freshly seeded demo stack.

## [0.11.0] - 2026-08-13

### Added

- Milestone 4, Phase 4: the post-detail popup's remaining panels.
  `lineageweave/post_summary.py` -- LLM-derived Korean summary, key
  events (ACE-style, Doddington et al. 2004), and R&R (semantic role
  labeling, Gildea & Jurafsky, 2002), via contextual-orchestrator.
  `lineageweave/post_chat.py` -- in-popup chat as retrieval-augmented
  generation (Lewis et al., 2020): an explicit retrieve step
  (`backend/app/post_chat_ingestion.py` assembles a post's own content
  plus its Event-Lineage-linked posts, direct and Knowledge-Graph-
  indirect, as numbered sources) then a reason-and-cite step (the model
  answers using only those sources and reports which it drew from).
- Backend: `GET /api/posts/{post_id}/lineage` (direct vs. indirect links,
  kept as two separate lists), `GET /api/posts/{post_id}/summary`,
  `POST /api/posts/{post_id}/chat` -- all RBAC+ABAC-gated the same way as
  every other post endpoint, verified end to end against a live
  Postgres + Keycloak + contextual-orchestrator stack (including through
  the actual Docker-built images, not just the FastAPI TestClient).
  Caught and fixed a real bug while building the chat's retrieve step:
  `backend/app/knowledge_graph.py::load_visible_subgraph` only loads
  edges among an *already-known* post set -- it does not itself discover
  sibling posts sharing a mentioned person (its only prior caller,
  `related_for_person`, pre-resolves that full set itself before calling
  it). `find_linked_post_ids` now does that expansion first; regression-
  tested (`test_post_chat_cites_a_post_linked_only_via_a_shared_keyman`).
- Frontend: `frontend/src/App.tsx`'s popup gained real Summary, Event
  Lineage (direct/indirect visually distinguished), Keyman, Counterparty,
  and Chat sections, plus a real sliding evidence panel (`EvidencePanel`,
  CSS animation, not a mock) that opens the cited source post's actual
  content when a citation chip is clicked. Fixed a real, pre-existing
  test-infrastructure bug found while adding more tests to the same file:
  `@testing-library/react`'s automatic per-test cleanup never actually
  ran (this project's `vite.config.ts` deliberately doesn't set
  `test.globals`, which auto-cleanup silently depends on), so DOM from
  one test was bleeding into the next; `src/setupTests.ts` now registers
  `cleanup` in an explicit `afterEach`.
- `docs/adr/0002-figma-access-boundary.md`: the referenced Figma frame is
  genuinely reachable in this environment, but its own cover page is the
  source organization's real confidential content (and it does not yet
  contain a frame for this screen) -- the popup is built from the
  product brief's text instead, named as an explicit, honest gap rather
  than either faking a "Figma-matched" claim or stalling on it.
- New citations: See, Liu, & Manning (2017); Gildea & Jurafsky (2002);
  Lewis et al. (2020).

## [0.10.0] - 2026-08-13

### Added

- Milestone 4, Phase 3: `lineageweave/entity_relationship_classification.py`
  -- LLM classification (via contextual-orchestrator, `mode="route"`) of a
  named organization's relationship to the post author's org into the
  product's own six-way vocabulary (`rel_voc`/`rel_vom`/`rel_vop`/
  `rel_vocc`/`rel_voco`/`rel_vos` -- `rel_`-prefixed because
  `common_lookup_value.lookup_code` is unique globally across categories
  and bare `voc`/`vom` were already claimed by `source_post.voc_type_code`'s own
  category). Proven with a real LLM call against a genuinely hard fixture
  (`fixtures.ambiguous_entity_relationship_post`): an organization that is
  both a repeat customer and a newly-competing division in the same post.
- `lineageweave/corporate_hierarchy_resolution.py` -- similarity-based
  resolution of a free-text organization name to an existing
  `corporate_entity` row (Bhattacharya & Getoor, 2007's candidate-
  generation/blocking stage of collective entity resolution, honestly
  documented as that stage and not the full joint-inference version).
  Wired into `backend/app/keyman_ingestion.py`, replacing the exact-
  case-insensitive-match lookup it had before. `tests/test_corporate_hierarchy_resolution.py`
  proves it against the same "Acme Group / Acme Electronics Korea / Acme
  Electronics Gwangju Plant" hierarchy `tests/test_schema.py` already
  uses: an abbreviation and a trailing legal suffix still resolve to the
  right entity (not a sibling with a similar name), and a genuinely
  unrelated organization resolves to `None`, not a guess.
- `tests/test_indirect_lineage_linking.py`: demonstrates the Knowledge
  Graph layer finds a real relation `lineageweave.reconstruct` has no
  mechanism to find at all -- two posts in different `reconstruct.py`
  groups (structurally never compared against each other) still surface
  as related once they share a Keyman, via `random_walk_with_restart`.
- Backend: `GET /api/posts/{post_id}/counterparties`, and
  `POST /api/posts/{post_id}/extract-keymen` now also classifies and
  persists each extracted Keyman's affiliated organizations'
  relationships (`backend/app/entity_relationship_ingestion.py`), all on
  the same RBAC+ABAC gate as the post/Keyman endpoints. Proven end to end
  against a live Postgres + Keycloak + contextual-orchestrator stack.
- `docs/lineage-bi-research-notes.md`: added Zelenko, Aone, & Richardella
  (2003) (relation extraction); moved Bhattacharya & Getoor (2007) from
  "staged for later phases" into a real section now that it grounds
  shipped code.

## [0.9.0] - 2026-08-13

### Added

- Milestone 4, Phase 2 continues: `lineageweave/keyman_extraction.py`
  extracts two-sided Keymen (our-side vs counterparty, 0..N organization
  affiliations) from a post's title+body. The live client calls
  contextual-orchestrator with `mode="route"` -- never a raw LLM API.
  `NullKeymanExtractionClient` stays unavailable rather than inventing
  mentions.
- `lineageweave.knowledge_graph.knowledge_graph_edges_for_post` populates
  the three Phase 2 edge kinds (person<->post mention, person<->corporate
  entity affiliation, person<->person co-mention) as typed
  `knowledge_graph_edge` specs. RWR then runs on that graph.
- Backend endpoints `GET /api/posts/{post_id}/keymen`,
  `GET /api/keymen/{person_id}/related`, and
  `POST /api/posts/{post_id}/extract-keymen`, RBAC+ABAC-gated the same
  way as post detail: a Keyman who is only mentioned on another corp's
  private post 403s, related-node traversal never returns those hidden
  posts, and extraction is `post_admin` (a write with a real LLM cost).
  Persist goes through `backend/app/keyman_ingestion.py` into
  `cataloged_person` / `person_affiliation` / `post_person_mention` /
  `knowledge_graph_edge`. Directed RWR sinks teleport remaining walk
  mass back to the start node so relevance stays a distribution.
- `fixtures.ambiguous_keyman_post`: a synthetic, non-templated workshop
  follow-up used by the parser tests and the real-orchestrator Keyman test.

## [0.8.0] - 2026-08-13

### Added

- Milestone 4, Phase 2 begins (Phase 1 complete): `lineageweave/knowledge_graph.py`
  -- random walk with restart (Tong, Faloutsos, & Pan, 2006) giving every
  node in a Knowledge Graph a continuous relevance score from a starting
  node, plus `select_related_nodes`'s per-node adaptive relevance-ratio
  cutoff. No hop-count constant appears anywhere in the algorithm -- the
  same ratio threshold naturally yields a larger related-set for a
  well-connected node than a sparse one, which is the actual product
  requirement ("각 Node와 Node마다 Depth가 다를 수 있다").
- `tests/test_knowledge_graph.py`: proves this against a synthetic graph
  built so the correct answer is known by construction -- a disconnected
  node scores exactly 0, symmetric spokes score identically, and a
  well-connected "hub" node's adaptive related-set (5 nodes) is
  measurably larger than a sparse "loner" node's (1 node) under the same
  threshold.
- `docs/lineage-bi-research-notes.md`: Tong et al. (2006) moved from
  "staged for later phases" into a real "Knowledge Graph traversal"
  section now that it grounds shipped code.

## [0.7.0] - 2026-08-13

### Added

- `frontend/`: React + Vite + TypeScript, pinned Node via `mise.toml`,
  pnpm via Corepack -- a real client, not mocked and not static HTML.
  `react-oidc-context` drives an actual Authorization Code redirect
  through Keycloak; the post list and detail popup call the FastAPI
  backend over real `fetch()` with the token Keycloak issued.
  `src/App.test.tsx` covers the login-redirect and fetch-then-render
  paths (`useAuth` mocked -- the real OIDC round-trip is proven
  elsewhere, by `scripts/smoke_test_oidc.py` and `backend/tests/test_api.py`).
- `frontend/Dockerfile` + `nginx.conf`: two-stage build (`pnpm run build`
  then nginx serving the static bundle) added as docker-compose's fourth
  service, `VITE_*` config baked in at build time from the same `.env`
  ports every other service uses. Both stages pin the base image by
  digest; the runtime stage declares `USER nginx` and listens on 8080
  so the master process does not need root to bind a port.
- `backend/app/main.py`: `CORSMiddleware`, scoped to exactly the
  frontend's origin(s) (`FRONTEND_ORIGINS`), `GET` only, `Authorization`
  header only -- verified with a real cross-origin preflight + GET against
  the live stack, not just unit-tested in isolation.
- `.github/workflows/tests.yml`: added a `frontend` job (lint, test,
  build) alongside the existing Python `pytest` job.

### Fixed

- Keycloak's `lineageweave-frontend` client (`docker/keycloak/realm-export.json`)
  now allows both the Vite dev-server origin (`:5173`) and the
  docker-compose-served frontend's origin (`:15173`) as redirect URIs and
  web origins -- the login redirect only worked from one of the two
  before this.

## [0.6.0] - 2026-08-13

### Added

- `backend/`: a FastAPI app connecting directly to PostgreSQL (`asyncpg`,
  no ORM, no file-backed DB). OIDC bearer-token login verified against a
  live Keycloak JWKS (`backend/app/auth.py`, fetched via
  `lineageweave.http_client` rather than PyJWKClient/`urllib`); RBAC
  (`post_read` permission via role membership) plus row-level ABAC
  (private `source_post` rows scoped to the requesting account's
  affiliated corporate entity) enforced on `GET /api/posts` and
  `GET /api/posts/{post_id}` (`backend/app/main.py`).
- `backend/tests/test_api.py`: real-integration tests -- a genuine access
  token from a live Keycloak, verified against a throwaway migrated
  Postgres database. Proves both the allow and the deny path: a private
  post scoped to a *different* corporate entity is excluded from the list
  and 403s on direct fetch; a forged token is rejected; a missing token is
  401. Skipped unless both a local PostgreSQL and Keycloak are reachable.
- `scripts/seed_demo_data.py` (`make seed`): seeds synthetic corp/PU/
  account/`source_post` rows keyed to the *real* subject ids Keycloak's
  admin REST API reports for the two demo users -- not a locally-fabricated
  guess at what those ids might be. Talks to Keycloak through
  `lineageweave.http_client` (`post_form` / `get_json_list`), never
  `urllib.request.urlopen`.
- `backend/Dockerfile`: `python:3.12-slim` pinned by digest, runtime
  `USER appuser` (DS-0002).
- `migrations/0001_initial_schema.sql`: added `corporate_entity.
  corporate_entity_code` (unique short code, e.g. `DEMO-CORP-01`) -- the
  column the login-time `corp_code` claim actually maps to; the original
  Phase 1 migration (still unmerged) only had the human-readable
  `entity_name`. Postgres's app database is now auto-migrated with this
  exact file on first `docker compose up` (`docker/postgres-init/Dockerfile`),
  so what's tested and what ships never drift apart.
- docker-compose.yml's default host ports moved off Postgres/Redis/common
  local-dev ports entirely (15432, 16379, 18080, 18420) -- found during
  this work that a colliding already-running service on a container's
  published port can silently answer curl/psql requests instead of the
  container, with no error; picking non-default ports avoids that
  ambiguity outright rather than relying on operators noticing.

### Fixed

- JWKS fetch and the demo seeder go through `lineageweave.http_client`
  instead of `PyJWKClient` / `urllib.request.urlopen`.

## [0.5.0] - 2026-08-13

### Added

- `docker-compose.yml`: PostgreSQL, Valkey, and a real Keycloak OIDC
  provider, genuinely functional (not a stub/mocked adapter). `make up`
  brings up all three from a clean checkout; `make smoke` runs
  `scripts/smoke_test_oidc.py`, which logs in as a synthetic demo user
  seeded by `docker/keycloak/realm-export.json`, fetches Keycloak's live
  JWKS, and cryptographically verifies the returned JWT's RS256 signature,
  issuer, and `corp_code`/`pu_code` custom claims -- a real round-trip
  proof, not a "the container started" check.
- `docker/postgres-init/` and `docker/keycloak/`: both services are `build:`
  targets (Dockerfiles that `COPY` in the keycloak-db init script and the
  realm seed) rather than bind mounts, so the images are self-contained and
  reproducible on any Docker host or CI runner.
- Keycloak stores its own state in a second database (`keycloak`) on the
  same PostgreSQL instance -- one running database service for the whole
  stack, no second file-backed store.
- `.env.example` documents the (already-defaulted) compose variables,
  including how to remap host ports if 5432/6379/8080 are already taken
  locally.

### Fixed

- Dockerfiles declare an explicit non-root `USER` (DS-0002) and pin
  `postgres:16-alpine`, `quay.io/keycloak/keycloak:26.0`, and
  `valkey/valkey:8-alpine` by digest.
- `scripts/smoke_test_oidc.py` talks to Keycloak through
  `lineageweave.http_client` (`get_json` / `post_form`) instead of
  `urllib.request.urlopen`, so the same `file://` allowlist used by the
  library clients applies to the OIDC smoke path.

## [0.4.0] - 2026-08-13

### Added

- Milestone 4, Phase 1 begins: LineageWeave's product schema.
  `migrations/0001_initial_schema.sql` -- a 3NF PostgreSQL schema
  (snake_case, 2+ word object names) covering accounts (corp/PU code as
  attributes, not the login key), a shared `common_lookup_value` ENUM
  table, posts + visibility, ABAC/RBAC, VOC-type and entity-relationship
  classification, Keyman (`cataloged_person` + N:N `person_affiliation`), a
  `knowledge_graph_edge` table, `issue_ticket`, and a self-referencing
  `corporate_hierarchy` via `corporate_entity.parent_entity_id`.
- `docs/adr/0001-demo-identity-and-data-boundary.md`: the identity/data
  scope decision for this expansion -- real infrastructure (Postgres,
  Valkey, a real OIDC provider), synthetic identities and content, because
  Keyman extraction catalogs real named individuals (including
  non-consenting external counterparties) and a real production identity
  provider would re-identify the source organization through account/data
  structure even with zero literal company-name strings in source files.
- `tests/test_schema.py`: real-database tests (skipped without a
  reachable PostgreSQL server) proving the migration applies cleanly, a
  multi-level corporate-hierarchy recursive query returns the right
  shape, and an invalid lookup code is genuinely rejected by a foreign
  key -- caught and fixed a real bug in the process (an accidental
  `deferrable initially deferred` on one FK silently weakened its
  integrity check within a transaction).
- New citations staged for Phase 2/3: Tong et al. (2006, random walk with
  restart -- Knowledge Graph per-node traversal depth) and Bhattacharya &
  Getoor (2007, collective entity resolution -- corporate hierarchy).

## [0.3.0] - 2026-08-13

### Fixed

- Embedding, adjudication, and vision clients now POST through a shared
  `http_client.post_json` helper that allowlists `http`/`https` and never
  calls `urllib.request.urlopen`. That closes the `file://` read concern
  Semgrep's `dynamic-urllib-use-detected` rule was flagging on the
  operator-configured base URLs. HTTPS posts wrap the connected socket
  with a certifi-backed `SSLContext` instead of constructing
  `http.client.HTTPSConnection`, so certificate verification is explicit
  on the Python 3.10+ runtime this project requires.

### Added

- `lineageweave/chunking.py`: semantic-unit chunking so the embedding
  channel compares meaning-identifiable units instead of whole flattened
  documents -- `chunk_by_paragraph` (Hearst, 1997, TextTiling subtopic
  boundaries), `chunk_by_sentence`, `chunk_by_dom` (WHATWG HTML Living
  Standard sectioning/flow block elements), and `chunk_by_conversation_turn`
  (RFC 5322 sender/receiver boundaries).
- `embedding_client.chunked_max_similarity`: chunks two documents, embeds
  every chunk, and returns the single highest-scoring pair -- the standard
  passage-retrieval strategy for "a relevant unit is buried in a longer
  document." Degrades to plain whole-text embedding for any document that
  chunks to zero or one piece (this project's real short-title dataset
  behaves exactly as it did before chunking existed).
- Real-provider test proving chunking works, not just that it type-checks:
  a short relevant paragraph buried inside a longer synthetic document
  scored higher via `chunked_max_similarity` than via whole-document
  embedding, against the live embedding provider.
- `docs/lineage-bi-research-notes.md`: new "Chunking" section with the
  four units' grounding and an explicit, honest note that this project's
  unseen dataset's only free-text field is too short to need chunking in
  practice -- the module exists for richer content sources (e.g. the raw
  MHTML artifacts that dataset's records were derived from).
- `lineageweave/image_content.py`: pluggable vision channel for base64
  images embedded in DOM content -- real OCR (Li et al., 2023, TrOCR) and
  object recognition/tagging (Radford et al., 2021, CLIP) via
  `OpenAiCompatibleVisionClient`, same never-fake-a-missing-channel
  discipline as the embedding/adjudication clients. `chunk_by_dom` now
  extracts embedded images as `"image"` chunks interleaved with text
  chunks in true document order, so an image's position relative to its
  surrounding text is preserved and reconstructable.
- Real-provider test proving OCR works, not just that it type-checks: a
  real PNG generated with real rendered text (not a fixture file) was
  read back correctly by `OpenAiCompatibleVisionClient` against the live
  vision-capable model.
- `docs/image-content-schema.md`: proposed DB schema (snake_case, 2+ word
  object names) for persisting and searching extracted image content,
  designed so a text/tag search hit stays traceable to which document and
  which position produced it, and so the same image (by content hash) is
  never *stored* twice (the primary key guarantees that part). Avoiding a
  duplicate vision-provider *call* for two concurrent ingests of the same
  new image is a separate concern the schema documents but does not solve
  by itself -- a real write path still needs an atomic claim/lease step.

## [0.2.0] - 2026-08-13

### Added

- ADR-0016 grounding: `docs/lineage-bi-research-notes.md` now cites
  Doddington et al. (2004, ACE) and Anagnostopoulos et al. (2013, CHRONOS)
  alongside Allan (2002, TDT), and explains how `reconstruct.py` maps onto
  TEPP's three-layer event-intelligence separation (mention/instance,
  calibrated detection, temporal-consistency).
- `tests/test_real_provider_integration.py`: opt-in (env-var-gated, skipped
  by default so a credential-free clone stays green) tests proving
  `OpenAiCompatibleEmbeddingClient` and `ContextualOrchestratorAdjudicationClient`
  work end-to-end against real providers, not just that their interfaces
  are satisfiable by a stub.

### Fixed

- `embedding_client.py` / `adjudication_client.py`: both real-provider HTTP
  clients now build their SSL context from `certifi`'s CA bundle instead of
  the platform default. Some interpreter distributions (observed: a
  standalone uv-managed CPython on macOS) don't reliably inherit the OS
  trust store, which made every real-provider call fail closed with
  `CERTIFICATE_VERIFY_FAILED` even against a validly, publicly-trusted
  certificate. Full chain validation still applies -- nothing is weakened,
  the bundle source just changed.

## [0.1.0] - 2026-08-13

### Added

- Initial prototype: `reconstruct()` pipeline (group → bounded candidate
  window → multi-channel fusion via RankWeave → tree assembly via
  ThreadWeave).
- Four scoring channels: `temporal`, `secondary_key`, `text`
  (dependency-free stand-in for embedding-cosine similarity), and an
  optional `llm` channel via a pluggable `AdjudicationClient`.
- `ContextualOrchestratorAdjudicationClient`, calling
  [contextual-orchestrator](https://github.com/ContextualWisdomLab/contextual-orchestrator)'s
  `mode="verify"` with `reasoning_effort="high"`.
- `OpenAiCompatibleEmbeddingClient` for a real embedding-cosine text
  channel against any OpenAI-compatible `/v1/embeddings` endpoint.
- `TeppClient` / `AnalysisRunRequest`: validated wire shape matching
  [TEPP](https://github.com/ContextualWisdomLab/TEPP)'s published
  `analysis_run_request_v1.json` schema, pluggable transport (fails closed
  with `TeppNotAvailable` until TEPP ships a live HTTP endpoint).
- Minimum fused-score floor so weakly-related records surface as their own
  root instead of being force-attached to the best of a bad set of
  candidates.
- Stdlib HTTP demo server (`lineageweave/server.py`) and a self-contained
  SVG DAG viewer (`web/index.html`), no build step or external script
  dependency.
- Synthetic-only demo dataset (`lineageweave/fixtures.py`).
- `docs/lineage-bi-research-notes.md`: the literature this design is
  grounded in, APA 7th.
