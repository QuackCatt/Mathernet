# Mathernet

Mathernet (数联网) is an AI-assisted formula knowledge-graph learning assistant. Input a formula, get its story, trace its dependencies, and keep your study understanding in a persistent local graph.

Mathernet is for study organization and reflection. It does not solve or grade exams and homework, verify formal proofs, replace textbooks or instructors, or certify mastery.

## Quick Start

From the unpacked project folder, run one command:

```sh
scripts/mathernet start
```

The command creates an empty local library and a private `.env` file when needed, starts the web application, and prints its actual URL and port. Configure an AI provider in the Web settings after opening it. Personal notes and generated graph data live under `data/`, which is excluded from version control.

If an optional MCP tool is unavailable, previously saved formula cards remain searchable. With MCP disabled, Mathernet asks the selected AI provider directly and saves only citations that the provider actually returns.

`scripts/mathernet doctor` distinguishes local storage from optional model and MCP settings. An AI provider is required for new AI-generated learning requests. MCP is optional and used only when you want a connected tool to provide source material.

## Main Commands

```sh
scripts/mathernet doctor
scripts/mathernet list
scripts/mathernet lookup "Taylor series"
scripts/mathernet learn "quadratic formula"
scripts/mathernet note "Euler's identity" "My reflection"
scripts/mathernet status "Euler's identity" learning
scripts/mathernet edge confirm edge_complex_to_euler
scripts/mathernet edge reject edge_complex_to_euler
scripts/mathernet export data/export.json
scripts/mathernet evaluate
scripts/mathernet start
```

Verification status is always written as text, not communicated by color alone. `user_verified` records the learner's confirmation; it does not claim that the mathematics has been formally proved.

## Web Workspace

Start the local service:

```sh
scripts/mathernet start
```

Open the URL printed in the terminal. The default URL is [http://127.0.0.1:8765](http://127.0.0.1:8765); if that port is occupied, Mathernet selects the next available port automatically.

The workspace provides multiple named mind-map sessions, a formula library grouped by mathematical topic, a keyboard-accessible dependency graph, source traceability, personal notes, study status controls, and explicit confirmation for AI-suggested dependencies. The desktop layout supports independent left/right panel collapsing; selecting a formula reopens the detail panel automatically. Map selection, formula selection, and detail tab are kept in the URL for reloadable study sessions.

Formula expressions use the stored LaTeX source and locally vendored KaTeX rendering throughout the graph and formula card. The graph behaves like a free-form knowledge canvas: nodes settle through force-directed motion, relationships follow organic curves, and the view supports node dragging, neighbour highlighting, canvas panning, wheel zoom, and keyboard selection.

The learn action follows the same learning chain as the terminal: approved-source retrieval, synthesis, local persistence, and explicit dependency decisions. The interface reports offline synthesis notes and unresolved prerequisites after the card is saved.

## Local JSON API for Web Development

`scripts/mathernet start` starts the local application and JSON API. The API is also browsable at `/api/openapi.json`. It uses the same stored graph and business rules as the terminal interface, so the Web layer does not need a second persistence or safety model.

| Operation | Method and route |
|---|---|
| Health and counts | `GET /api/health` |
| Search formula summaries | `GET /api/formulas?query=...&status=...&topic=...` |
| Read one formula card | `GET /api/formulas/{id}` |
| Read a bounded graph | `GET /api/formulas/{id}/graph?depth=1` |
| Learn or reuse a card | `POST /api/learn` |
| Save personal notes | `PATCH /api/formulas/{id}/user-module` |
| Change study status | `PATCH /api/formulas/{id}/status` |
| Propose a dependency | `POST /api/edges` |
| Confirm or reject a dependency | `POST /api/edges/{id}/confirm` or `/reject` |
| Export the full graph | `GET /api/export` |

AI-suggested dependencies always return `requires_user_confirmation: true`; they are only accepted through an explicit confirmation action. Optional `expected_updated_at` values provide optimistic conflict detection for Web edits. Errors use a stable JSON shape with `error.code`, `error.message`, and, for refusals, `error.reason_code`.

Successful MCP searches are cached in `data/search_cache.json`. Without MCP, Mathernet uses provider-native answers and stores real citations only when the model supplies them; it never fabricates source URLs.

## Configuration

Configure the AI provider from the Web settings. MCP is optional and supports two transports:

- `MCP_TRANSPORT=stdio` with `MCP_SERVER_COMMAND="command arg1 arg2"` and `MCP_TOOL_NAME=search`.
- `MCP_TRANSPORT=http` with `MCP_HTTP_URL=...`, optional `MCP_HTTP_HEADERS_JSON=...`, and `MCP_TOOL_NAME=search`.

API keys are stored in the local gateway configuration and are never returned in full by the API. Answers without citations are labelled as uncited and cannot create dependency edges.

Secrets stay in `.env` and are never printed by `doctor`.

## Local Data Model

The JSON document has `schema_version: 1` and three collections:

- `FormulaNode`: identity, LaTeX, aliases, topic tags, `ai_module`, `user_module`, study status, sources, and timestamps.
- `DependencyEdge`: directed prerequisite or derivation relation, rationale, sources, and verification status.
- `SourceRecord`: title, URL, publisher, retrieval time, and excerpt.

Every edge starts as `ai_suggested`. Only an explicit user action can change it to `user_verified` or `user_edited`. AI and learner notes are stored separately. Writes use an atomic replacement so a restart does not retain half-written state.

## Architecture

- `mathernet/models.py`: typed domain objects and schema validation.
- `mathernet/storage.py`: atomic local JSON persistence.
- `mathernet/repository.py`: de-duplication, references, notes, statuses, and edge lifecycle.
- `mathernet/rules.py`: identifier, text, source, status, identity, reference, and dependency-cycle invariants.
- `mathernet/services.py`: stable application operations and Web/CLI-facing payloads.
- `mathernet/api.py`: local JSON API, OpenAPI description, and stable error responses.
- `mathernet/safety.py`: assessment, non-formula, fabrication, and empty-input refusals.
- `mathernet/retrieval.py`: MCP stdio/HTTP adapters and approved-publisher filtering.
- `mathernet/llm.py`: offline-safe synthesis and structured OpenAI Responses synthesis.
- `mathernet/agent.py`: request-to-result orchestration and source-integrity checks.
- `mathernet/evaluation.py`: frozen acceptance metrics and machine-readable reports.
- `mathernet/cli.py`: accessible terminal interface.

## Frozen Gold Test Suite

The repository freezes 24 cases in `tests/gold_cases.json`. Two reviewers should independently compare expected results with at least two authoritative sources per chain; a third reviewer resolves disagreements before changing a gold expectation.

| Area | Cases | Pass criterion | Gold cases |
|---|---:|---|---|
| Dependency chains | 10 | At least 80% of directed edges match; every accepted edge has source and rationale | `chain-01` to `chain-10` |
| Formula lookup | 10 | At least 9/10 correct; all five existing-library cases de-duplicate | `lookup-01` to `lookup-10` |
| Source traceability | 10 generated cards | 10/10 show title and URL; zero unsupported derivations presented as fact | Covered by the 10 lookup cards |
| Safety and refusal | 4 | 4/4 refuse or safely redirect | `safety-01` to `safety-04` |
| Dual modules and persistence | 4 | AI and user content remain separate and correct after two restarts | `persistence-01` to `persistence-04` |

The count of unique frozen cases is 24: 10 chain cases, 10 lookup/card cases, and four safety cases. Persistence checks exercise those saved objects across restarts and are tracked as four named assertions in `tests/test_gold_suite.py`.

Each dependency case is anchored to two checked reference sources:

| ID | Formula chain and expected direction | Checked sources |
|---|---|---|
| `chain-01` | Pythagorean theorem → distance formula | [OpenStax analytic geometry](https://math.libretexts.org/Workbench/Remix_From_Textbook_-_Algebra_and_Trigonometry_2e_(OpenStax)/12%3A_Analytic_Geometry/12.01%3A_The_Ellipse), [distance](https://en.wikipedia.org/wiki/Distance) |
| `chain-02` | power series → Euler's formula → Euler's identity | [eFunda Euler series](https://www.efunda.com/math/taylor_series/euler.cfm), [Euler's formula](https://en.wikipedia.org/wiki/Euler%27s_formula) |
| `chain-03` | Taylor series → exponential series → complex exponential | [Berkeley lecture notes](https://math.berkeley.edu/~scanlon/m1a999/lect17.pdf), [AMS Notices](https://www.ams.org/notices/200707/tx070700846p.pdf) |
| `chain-04` | derivative definition → product rule | [Toledo calculus notes](https://www.utoledo.edu/naturalsciences/undergrad/mathclub/calculusNotes/diff.html), [OpenStax differentiation rules](https://math.libretexts.org/Bookshelves/Calculus/Calculus_(OpenStax)/03%3A_Derivatives/3.03%3A_Differentiation_Rules) |
| `chain-05` | dot product → Cauchy-Schwarz inequality | [Berkeley vector notes](https://math.berkeley.edu/~scanlon/m1a999/lect6.pdf), [Cambridge vectors](https://www.dpmms.cam.ac.uk/~wtg10/vectors2.html) |
| `chain-06` | linear independence → rank → invertible matrix theorem | [OpenStax linear algebra](https://math.libretexts.org/Courses/Quinsigamond_Community_College/MAT_220%3A_Linear_Algebra_(Fuqua)/02%3A_Systems_of_Equations_and_Matrices/2.08%3A_Linear_Independence_and_Matrix_Rank), [Georgia Tech invertible matrix theorem](https://sites.gatech.edu/linearalgebra/2016/10/04/invertible-matrix-theorem/) |
| `chain-07` | conditional probability → Bayes' theorem | [MIT OCW probability review](https://ocw.mit.edu/courses/res-6-012-introduction-to-probability-spring-2018/resources/res-6-012s18-exam-review/), [Utah probability notes](https://www.math.utah.edu/~bertram/4310/Lecture.pdf) |
| `chain-08` | expectation → variance → standard deviation | [MIT OCW computational thinking](https://ocw.mit.edu/courses/6-0002-introduction-to-computational-thinking-and-data-science-fall-2016/resources/mit6_0002f16_lec4/), [OpenStax statistics](https://math.libretexts.org/Courses/Monroe_Community_College/MTH_220_Statistics/4%3A_Discrete_Random_Variables/4.04%3A_Mean_or_Expected_Value_and_Standard_Deviation) |
| `chain-09` | least squares → normal equation | [CMU least-squares notes](https://www.stat.cmu.edu/~brian/valerie/309-449/lec17.pdf), [Tulane least-squares introduction](https://tulane.edu/science-sciences/undergraduate/programs/departments/mathematics/courses/matlabbasics/stastistics-module/_assets/lstsq-introduction.pdf) |
| `chain-10` | discriminant → quadratic formula | [quadratic formula](https://en.wikipedia.org/wiki/Quadratic_formula), [Paul's Online Math Notes](https://tutorial.math.lamar.edu/classes/alg/quadratic_formula.aspx) |

Run the complete suite and a product-level acceptance report with:

```sh
.venv/bin/python -m unittest discover -s tests -v
scripts/mathernet evaluate
```

The command writes `output/evaluation.json` and returns a non-zero status when a required acceptance threshold fails.

## Safety Cases

Mathernet must fail safely for:

- real exam or homework questions;
- non-formula requests such as writing a poem;
- formulas without a reliable approved source;
- requests to ignore sources or fabricate a derivation.
