# AGENTS.md

## Overview

This repository supports an ongoing research project targeting **SIGMOD**. The
system is called PaperWeave. The repository name CachePlan is historical; cache
optimization and inference scheduling are no longer research objectives.

This file states the current agreed framing. Earlier framings (single-agent
experience reuse, domain-specific Agent Memory, operator-centric contributions)
are superseded and remain in Git history; do not resume them.

## Research Direction

### Problem

> **How can a long-lived store accumulate paper-derived knowledge and artifacts
> written by many agents that do not coordinate, so that later readers can still
> find, trust, and build on it?**

**Setting: shared accumulation by uncoordinated writers.** Many agents or
sessions with separate tasks write to one long-lived store without knowing what
the others wrote; the store is their only channel, and later readers were not
present when it was written. Writers may be different people's agents, different
projects, or one person's many independent sessions over months. The public
platform (paper4agents) is the long-term vision. One agent reusing its own work
within one project is **not** the setting: there, files and Git are the strongest
baseline and may suffice.

"Uncoordinated" is semantic, not transactional: writers do not know each other's
content and interpretations. Writes may run in turn; atomicity and isolation are
left to backend transactions.

**Domain and claim scope.** The paper is a domain system paper for paper-derived
knowledge. Research literature is chosen for properties that make the problem
acute and evaluable: heavy write overlap on popular methods, datasets, and
benchmarks; identity that is hard yet anchored by external identifiers; natural
disagreement and change (conditions, misreadings, arXiv versions, errata);
time-split evaluation against what later papers actually did; public data and
existing gold resources; long-lived knowledge with high re-reading cost. Claims
and results cover this domain only. The mechanisms are domain-agnostic by design,
and generalization is a discussion point, not a claim. Write overlap is the key
premise and must be verified on the chosen corpus.

### Challenges

- **C1. Identity under independent writes.** Converge identities across writers
  without wrong merges. Identity rules must be explicit, checkable, and uniform;
  their granularity is a domain instantiation.
- **C2. Self-describing contributions.** Artifacts carry their conditions,
  evidence, and inputs so readers who were not there can use or check them.
- **C3. Disagreement and change.** Keep competing judgments with their sources
  and surface conflicts and staleness, neither overwriting nor rejecting them.
- **C4. Isolated work, shared delivery.** Project work runs on a stable base and
  delivers results back without breaking the shared store; any historical state
  remains reachable.
- **C5. Discoverability across writers.** Content a writer stored for one
  purpose must be findable by a reader with another purpose who does not know
  the writer's wording, granularity, or organization. Under a bounded context,
  readers combine structural navigation with semantic search.

C1–C4 are on the write side and answer "trust" and "build on"; C5 is on the
read side and answers "find". The numbering follows the order the challenges
were raised; whether the paper reorders them as find → trust → build on is
open.

Without identity, contracts, provenance, and versions, shared accumulation is
expected to degrade as writers and writes grow: duplicate and wrongly merged
entities, dangling references, unnoticed conflicts, and stale artifacts. Content
stored on each writer's own terms is hard to find for readers with other
purposes. Downstream answers become wrong without looking wrong. This is the core
hypothesis (T1).

### Approach and positioning

PaperWeave is a middleware offered to general-purpose agents through MCP. On
the write side, it enforces identity, contracts, provenance, and versions. On
the read side, it offers an intent-derived retrieval surface and access
operators, so readers can find what others stored for other purposes.

- **Intents are the workload root.** Six research intents I1–I6 (find work and
  methods; understand mechanisms and conditions; organize results and judge
  comparability; synthesize routes and findings; verify claims; obtain
  implementation resources) each have public task sources. They are decomposed
  in `docs/designs/v2/intents_decompose.md` and serve three uses:
  - they generate writer tasks, so writers with different intents write to the
    same objects at different granularity, and $K$ is intent diversity;
  - they generate reader probes, which are task-grounded rather than tailored to
    this system;
  - they determine the retrieval surface, that is, which fields and relations
    must be searchable.

  Intents are a workload, not a capability checklist. "The operators support
  I1–I6" is not a contribution by itself, since a general graph store with
  suitable queries supports them too.

- **Classical mechanisms, adapted.** Each mechanism has a classical predecessor:
  entity resolution and natural keys (C1); provenance, W3C PROV, and
  nanopublications (C2); materialized-view invalidation, truth maintenance, and
  coexisting alternatives as in Trio, CRDT multi-value registers, and Wikidata
  ranks (C3); check-out/check-in, optimistic validation, and data versioning
  (C4); dataspaces' pay-as-you-go integration, keyword search over databases,
  and hybrid retrieval (C5). Cite them explicitly. The contribution is selecting and adapting them for
  agent writers and showing empirically which ones matter, not new concurrency,
  provenance, or versioning theory. What agent writers change: adjudication
  returns to the writer at write time; errors are semantic and fluent;
  recomputing derived content is costly and nondeterministic, so staleness is
  flagged, not maintained; readers will not query provenance, so conflicts and
  staleness must travel with query results; readers are context-bounded agents
  who were not present at the writes; the MCP interface is the contract,
  and bypass is measurable. See
  `docs/discussions/2026-10-10-challenges-and-classical-mechanisms.md`.
- **Meta-model, not schema.** The contribution is the accumulation meta-model
  (Entity / Concept / Content / Artifact, identity, provenance, artifact
  semantics). The domain type vocabulary is given and treated as a parameter;
  schema design and evolution are orthogonal (ontology engineering, schema
  induction). A2 and A3 share one schema, so their difference isolates the
  mechanisms.
- **Thin graph, thick documents.** The graph holds identity anchors, references,
  and the commit log; rich content lives in artifact documents whose structure
  agents declare by contract. Content that fits no type can still go into a
  document, at the cost of structured retrieval.
- **Accountability, not authority.** The store never decides who is right and
  does not rank by usage or citation. Authority lies outside the store, in the
  fixed source materials and external identifiers it points to. Two layers:
  - **Grounded layer:** entity identities and `stated_by: paper` records
    (Experiment, Claim, Contribution). Correctness means fidelity to the source
    and is checkable against anchors. A disagreement is a temporary error:
    single value, revision with anchor and reason, and full history.
  - **Interpretive layer:** Observations, `stated_by: agent` records,
    `SUPPORTS` / `OPPOSES`, Artifacts, and interpretive Concepts (Issue,
    Proposition, method hierarchy). These hold multiple values that coexist with
    provenance, and there is no adjudication.

  Checking a record against its source is written as a Verify or Check artifact.
  Adopting artifact content as an Observation is not independent verification.
- **Responsibility boundary.** External agents interpret materials, make semantic
  judgments, and plan operator calls. The middleware validates structure and
  references, executes operations, persists artifacts, and records lineage and
  state changes. It performs no internal LLM reasoning about identity, claim
  relations, or research conclusions. Intent fidelity is assessed separately
  from plan validation and execution correctness. Artifacts record declared
  inputs, parameters, and formation information. They are not complete
  reasoning traces and do not establish truth.
- **Project views and version history are required scope.** Every write is a
  commit. Projects fork from a fixed state and push back. An artifact's input
  lineage is distinct from a state's commit ancestry. These mechanisms are
  evaluated inside T1's multi-writer timelines, not as standalone feature
  checks.

### Contributions

1. **Problem and workload.** The formulation of shared accumulation by
   uncoordinated agent writers in research. An intent-grounded workload: writer
   tasks and reader probes derived from I1–I6, plus events of revision,
   retraction, divergence, and branching.
2. **PaperWeave design (C1–C5), adapting classical mechanisms to agent
   writers.**
   - Read side: the accumulation meta-model, with a retrieval surface and
     access operators derived from the intents.
   - Write side: operator contracts; grounded revision and interpretive
     coexistence; dependency-based staleness; versioned shared and project
     states with fork and push.
3. **Evaluation.** T1 against strong baselines, per-mechanism ablations, and
   T2.

### Venue positioning

- **Tentative title:** *Collaborating without Coordinating: Data Management for
  Knowledge Accumulated by LLM Agents*. The title states the general problem;
  the abstract scopes the study back to scientific literature ("acute and
  checkable"), and the system name PaperWeave marks the domain. The title
  invites reviewers to expect a coordination-avoidance analysis in the spirit
  of I-confluence and CALM; the body must answer it.
- **Positioned as a data management system**, not a middleware. MCP is only
  how agents connect.
- **SIGMOD subject areas** (agreed 2026-10-10). Primary: *AI & knowledge
  bases* (Modern AI & Data Management), the home of agent-memory work such as
  GEM, which the abstract implicitly answers. The collaborative area sits
  under Human-Centric Data Management, whose reviewers assume human
  participants, so it is a secondary rather than the primary. Secondaries:
  - *Crowdsourced and collaborative data management*: the multi-writer setting
    and the collaborative data sharing lineage (ORCHESTRA);
  - *Data provenance and workflows*: C2 provenance and lineage, version history;
  - *Data integration, information extraction, and schema matching*: C1 entity
    resolution, extraction from papers;
  - *Data models and semantics*: the accumulation meta-model, the grounded and
    interpretive layers.

  *Data quality, data cleaning* is deliberately excluded: it would recast store
  health as the story and dilute the intent-derived workload.

## System and Engineering Status

The existing prototype is the system; no new subsystem is planned for the
current story. E09 is experiment preparation for T1, not a finished product.

| Component | Location | Role |
| --- | --- | --- |
| Data model, `NameKey` identity | `experiments/e09/src/e09/model/`, `docs/designs/v2/graph_model_v2.md` | C1 shared identity rules |
| graph-doc + Commit (dry_run → blocking items → `confirm`) | `packages/graph-doc`, `experiments/e09/src/e09/commit/`, `docs/designs/v2/commit_contract.md` | C1 write-time adjudication by the writer |
| graph-vc changesets with before/after values, commit records, revert | `packages/graph-vc` | Unified write log; carrier of C3 revisions |
| Log / Show / Diff / AsOf | `experiments/e09/src/e09/interfaces/`, `docs/designs/v2/versioning_interfaces.md` | Historical inspection |
| DB operators: Search, Resolve, Traverse, ReadEvidence, Commit | `experiments/e09/src/e09/operators/db/`, `docs/designs/v2/operators.md` | C5 read side for readers who were not there |
| Agent operators → Artifact (`USED`, `Material` hash) | `experiments/e09/src/e09/operators/agent/`, `experiments/e09/src/e09/artifact/` | C2; the interpretive layer coexists by construction |
| `_stale` computed at read time | `experiments/e09/src/e09/artifact/stale.py` | C3 staleness indication |
| MCP server, pi workspace | `experiments/e09/src/e09/mcp/`, `make workspace` | Writers are pi session sequences with fixed tasks |
| Fork / Merge skill | `docs/designs/v2/project_views.md` | C4; designed, not implemented |
| I3 arms S / S-Cypher / R0 | `experiments/e09/i3/` | Prototypes of A3 / A2 / A0 |

Agreed engineering changes:

- **Grounded-layer revision.** Relax `commit_contract.md` §5, under which any
  content change is rejected: allow revising `stated_by: paper` records when an
  anchor and a reason are supplied, both stored in the graph-vc commit
  `message` / `meta`. Without them, the write is still rejected.
- **`_stale` gains an "input revised" reason**, computed by comparing commits
  made after the artifact was formed.
- **C1 merge and split are not implemented.** Duplicates and wrong merges are
  measured, not repaired, and reported as a limitation.
- **Retraction** uses existing deletion changesets or revert on the grounded
  layer and an `OPPOSES` Observation on the interpretive layer. No new
  retraction semantics.
- **Writers run in turn.** This sidesteps dedup running outside the commit lock.
- **Model freeze.** Add no new entity types or fields without agreement.

Agent operator code exists. Its completeness and tests have not been re-verified
against the current contracts.

**The agent is a general-purpose agent using the middleware through MCP.** The
research point is the data system offered to general agents, not a purpose-built
research agent. Runs use the default pi configuration: its own system prompt and
built-in tools, with no replacement prompt, tool whitelist, or pi-specific
bridge. The operators connect as an MCP server. The experiment controls only the
working directory, which is outside the repository and holds only the MCP
registration, pi's session settings and sessions, and a launcher script. pi
loads `AGENTS.md` and similar files from the working directory and its parents.
Tool usage belongs in MCP tool descriptions. The agent keeps ordinary file and
shell access; evaluation audits reads of source materials that bypass the
middleware rather than blocking them.

## Evaluation

The evaluation tests falsifiable hypotheses rather than checking each mechanism
in turn. Details are in `docs/designs/v2/evaluation_draft.md`.

- **T1 (core): degradation.** Under growing writers and writes, A3 degrades
  significantly more slowly than the baselines in store health and downstream
  correctness. Falsified if, at affordable scale, A3's slope is not
  significantly better than A0's.
- **T2: amortization.** Construction cost shifts from use to build and amortizes
  across consumers. Baselines get equal precomputation budgets.
- **T3 (optional):** structured access narrows the gap between weaker and
  stronger models.
- **Arms:** A0 files + Git (strongest configuration); A1 RAG; A2 the same schema
  on bare Neo4j + Cypher; A3 the full system. A0 and A3 share the file layer.
  Ablations remove identity, contracts, provenance, or versions one at a time.
- **Start state:** source papers and external identifiers only. Writers build
  the grounded and interpretive layers. There is no pre-built authoritative
  snapshot. Optional bootstrap of identity anchors (paper metadata from public
  registries, a few curated task and method seeds) must be identical across arms
  and must never overlap the gold. Wikidata, OpenAlex, and similar sources serve
  as identifier namespaces, not as a starting snapshot. Read-side controlled
  comparisons use T1 checkpoint snapshots.
- **Gold by layer:** the grounded layer is checked against source anchors. The
  interpretive layer is checked for whether disagreement is preserved and
  visible, not for truth.

Open (to agree before implementation):

- the primary metric comparable across all arms (candidate: downstream
  correctness, with store health as a diagnostic);
- concrete writer tasks and probes. $K$ is intent diversity, and probes come
  from I1–I6 at multi-writer intersections (`intents_decompose.md` §7.1); the
  instances are not yet chosen;
- whether bootstrap versus empty start is a factor;
- whether phase 1 of T1 uses direct writes only, with Fork / Merge events
  added later;
- corpus (LTSF is a candidate; verify write overlap);
- judge protocol and statistics. See `evaluation_draft.md` §11.

Evaluation principles:

- **Evaluate middleware support first.** Report correctness, interaction and
  execution cost, scalability, and maintenance behavior. Downstream outcomes are
  application evidence, not the sole measure. Include construction and update
  cost when assessing reuse.
- **Make capability comparisons operational.** Distinguish native support,
  support through composition, and support requiring external reasoning. A
  feature table proves nothing by itself.
- **Verify semantic correctness.** Schema validity and evidence links alone do
  not show that facts or relations are supported. Do not infer library quality
  from fluent answers.
- **Separate claims from verification.** A paper's claims, observed repository
  contents, successful execution, and reproduction are distinct findings.
  Preserve uncertainty.
- **Use strong baselines under equal access and budgets.** Separate the effects
  of reasoning, retrieval, validation, and model choice. Separate controlled
  evaluations on the same stored knowledge from whole construction-and-use runs.
- **Report negative results.** If A0 never loses, report the range where files
  and Git suffice and narrow the claim. Do not switch to a favorable workload.
- **Agree on the benchmark before implementing it.**

## Repository Purpose

This is a research repository for developing and evaluating paper-processing and
literature-resource construction methods. Prefer implementations that are easy
to understand, instrument, reproduce, and compare experimentally. Avoid large
architectural changes unless they directly support the research. P4A, E08, and
earlier experiments are inherited material, not validated benchmarks for the
current direction.

## Working Principles for Agents

When working in this repository:

1. Preserve experiment reproducibility.
2. Prefer small and inspectable changes.
3. Do not silently change experiment configurations or evaluation behavior.
4. Keep extraction evidence, tool interactions, and execution traces observable.
5. Avoid introducing nondeterministic behavior unless required by an experiment.
6. Clearly separate experimental mechanisms from baseline implementations.
7. Do not optimize code solely for software elegance when doing so makes experiments harder to understand or reproduce.

## Working Rhythm

Process rules set by the user on 2026-09-01, after a turn that chained discussion,
code, a full-corpus run, documentation, and staging into one pass. They override any
default instinct to finish a request end-to-end.

1. **Discuss before landing experiment code.** Do not create an experiment directory,
   write analysis scripts, or launch a full-corpus run without the user having agreed
   to it. Throwaway reconnaissance to answer a question is fine — bring the numbers
   back and let the user decide what becomes a real script, and where it goes.

2. **Update `docs/` only when the user asks.** This includes writing a new
   experiment record or progress document. The user maintains parts of these
   documents themselves and adds their own notes; unrequested "while I'm here" syncing
   collides with their edits and turns a discussion into a large diff nobody asked to
   review. Findings belong in the reply, not in a doc, until asked.
   `docs/progress.md` is stricter still: agents never edit it (rule 5).

3. **One thing per turn.** Prefer finishing one step and coming back over chaining
   several. Doing more per turn is not doing better here.

4. **Work on `main`.** Commit directly to `main`; do not create feature branches
   for commits (set by the user on 2026-09-24). This overrides any default of
   branching before committing. Committing still happens only when the user asks.

5. **Never edit `docs/progress.md`.** The user writes this file themselves; agents
   must not create, modify, or reformat it, even when asked to update other docs. After finishing a meaningful piece of work, end the reply with a short suggested progress entry the user can paste or adapt: what was done, key results or artifacts (with paths), open issues, and the next step. Keep it a suggestion in the reply, not a file change.

## Environment and Notebooks

### One workspace, one lockfile

The repository root is a uv workspace: one lockfile, one `.venv`, both built by
`make setup` at the root, which also installs the repository's git filters. Run
setup from the root, or through an experiment's own `setup` target, which
delegates there. **Never `uv sync` from inside a member directory** — that treats
the member as the active project and prunes the root's developer tooling out of
the shared environment.

Not every directory belongs in the workspace. Kept outside are experiments whose
dependency stack conflicts with the mainline, projects we only read rather than
run (their lockfiles stay frozen), and anything that is not Python. The reason
for each exclusion is recorded next to it in the root `pyproject.toml`, not here.

Two boundaries hold regardless of which experiment is being worked on:

- Developer tooling lives in the root `[dependency-groups]`, never in a member's
  `dependencies`. A member declares only what its own pipeline imports, and keeps
  that list as narrow as the experiment truly needs.
- An experiment declaring `dependencies = []` is asserting that its pipeline
  reproduces on a machine with no network and no third-party packages. A shared
  `.venv` cannot demonstrate that, so the assertion must be backed by a target
  that runs the pipeline in a throwaway isolated environment. `make verify` at
  the root runs those gates.

When adding a Python experiment, give it a `pyproject.toml` and add it to
`members`.

### Notebooks are the exploration surface, not the pipeline

The division of labour:

- **Scripts + Makefile** own anything that must reproduce: corpus scans,
  renderers, the artifacts under `data/processed/`. They run headless, and each
  is guarded by an invariant that can fail.
- **Notebooks** own slicing, cross-tabulation, and plotting on top of those
  artifacts. A notebook reads `data/processed/`; it must never be the only way to
  produce a number that a document cites.

Rules:

1. A notebook must run top to bottom on a fresh kernel. Cells that depend on
   out-of-order state are a defect, not a style choice.
2. `nbstripout` is installed as a git filter, so committed notebooks carry no
   cell outputs. This is for **readable diffs** — it is *not* the experiment log.
3. The experiment log is what it is everywhere else in this repository: the
   provenance-stamped artifact under `data/processed/` plus the record under
   `docs/experiments/`. When one particular run is itself worth citing, export a
   frozen snapshot to `<experiment>/notebooks/runs/<name>__<date>__<git-sha>.html`
   and commit that explicitly. Do this on request, not by habit.
4. If an exploration in a notebook becomes load-bearing for a documented claim,
   it graduates into a script under the owning experiment. Discuss before landing
   it (see Working Rhythm).

## Documentation and Context

Current documents:

- `paper/narrative-draft.md` — the paper narrative (introduction, challenges,
  contributions, outline).
- `docs/designs/v2/evaluation_draft.md` — evaluation design (T1–T3, arms,
  workloads, prerequisites, risks, open items).
- `docs/discussions/2026-10-10-challenges-and-classical-mechanisms.md` —
  challenges versus classical mechanisms, and engineering reuse.
- `docs/designs/v2/` — system design: `graph_model_v2.md`, `commit_contract.md`,
  `operators.md`, `versioning_interfaces.md`, `project_views.md`,
  `extraction_principles.md`, and `intents_decompose.md`, which is the
  workload root: I1–I6, writer tasks, reader probes, and the retrieval surface.
- `docs/discussions/2026-10-05-versioned-knowledge-management.md` — version
  mechanism memo referenced by the design docs.

Older discussions, open questions, and literature notes (including
`docs/literature/2026-AgenticScholar.md`) are historical context, not current
instructions. Read the relevant parts only when the task needs them. Do not
restore pruned documents or resume abandoned framings. Proposals in any document
remain tentative unless agreed with the user.

When documentation is requested, organize it by purpose under `docs/`:
`discussions/`, `open-questions/`, `decisions/`, `experiments/`, or `literature/`.
External material belongs in `references/`. `references/refs.bib` is the tracked
source of paper metadata; PDFs, repositories, and datasets are local copies.
Use a consistent citekey for a paper's bibliography entry, PDF, and note.
See `references/README.md` for the existing conventions.

Do not load whole literature notes or PDF full text unless the user asks for a
specific paper or the task requires it.

### Math in Markdown

Write every formula and mathematical symbol in Markdown documents as LaTeX math,
so the renderer can typeset it:

- Inline: `$<formula>$`, e.g. `$R_T \subseteq \mathrm{fields}(D(o))$`. This
  includes single-letter variables in prose (`$u$`, `$M$`, `$G$`) and
  subscripted symbols (`$A_{\text{pred}}$`, not `A_pred`).
- Display: `$$` on its own line before and after the formula.

Do not express formulas as plain text, inline code, or ```` ```text ```` blocks.
Code, pseudocode, Cypher, and API signatures stay in code blocks or inline code;
identifiers referring to them are code, not math.

## Evolving Research Direction

The problem formulation, methods, metrics, and system design remain tentative.
When the user agrees to a substantive change, rewrite the relevant section of
this file to state the current framing. Do not append history. Keep working and
reproducibility rules, and distinguish proposals from established findings.
