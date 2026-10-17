# AGENTS.md

## Overview

This repository supports a data management research project. The system is
called PaperWeave. The near-term goal is a quick arXiv preprint; the longer-term
target is a top database venue (SIGMOD, VLDB, ICDE, or similar). The repository
name CachePlan is historical; cache optimization and inference scheduling are no
longer research objectives.

This file states the direction and the rules for working here. Agreed details
live in the documents listed under "Documentation and Context"; when they and
this file disagree on a detail, the document holds, and the mismatch should be
reported. Earlier framings (single-agent experience reuse, domain-specific Agent
Memory, operator-centric contributions) are superseded and remain in Git
history; do not resume them.

## Research Direction

### Problem

> **How can a long-lived store accumulate paper-derived knowledge and artifacts
> written by many agents that do not coordinate, so that later readers can still
> find, trust, and build on it?**

**Setting: shared accumulation by uncoordinated writers.** Many agents or
sessions with separate tasks write to one long-lived store without knowing what
the others wrote. The store is their only channel, and later readers were not
present at the writes. "Uncoordinated" is semantic, not transactional: writers
run in turn, and atomicity is left to backend transactions. One agent reusing
its own work within one project is **not** the setting; there, files and Git are
the strongest baseline and may suffice.

**Domain.** Paper-derived knowledge, starting with time-series forecasting.
Claims cover this domain only; the mechanisms are domain-agnostic by design, and
generalization is a discussion point. Heavy write overlap is the key premise and
must be verified on the corpus.

### Challenges

- **C1. Identity under independent writes:** converge identities across writers
  without wrong merges.
- **C2. Self-describing contributions:** artifacts carry their conditions,
  evidence, and inputs, so readers who were not there can use or check them.
- **C3. Disagreement and change:** keep competing judgments with their sources,
  and surface conflicts and staleness instead of overwriting or rejecting.
- **C4. Building on shared work:** writers extend shared results without
  silently breaking what others wrote, and any historical state stays
  reachable.
- **C5. Discoverability across writers:** a reader with another purpose can
  find what a writer stored, without knowing the writer's wording or
  organization.

The core hypothesis: without these mechanisms, shared accumulation degrades as
writers and writes grow (duplicates, wrong merges, dangling references, lost or
unnoticed conflicts, stale artifacts), and downstream answers become wrong
without looking wrong.

### Approach

- **A middleware over Neo4j and graph-vc, offered to general-purpose agents
  through MCP.** Knowledge-access tools: search, get, traverse, read_evidence.
  Version-management tools: checkout, commit, log, show, diff, as_of.
  Artifacts are typed, versioned documents (Leaderboard, CompareSettings,
  Verify, Summarize, Generate, Skill) that writers check out, edit, and commit;
  the middleware checks each against its type's contract. Artifacts declare
  their inputs: reads flag artifacts that may be stale, and a commit tells its
  writer which artifacts it may have made stale.
- **Responsibility boundary.** External agents interpret materials, make
  semantic judgments, and plan calls. The middleware validates structure and
  references, executes, persists, and records lineage. It does no internal LLM
  reasoning. Structure is required only where the store acts on it: keys,
  references, sources.
- **Accountability, not authority.** The grounded layer (entity identities,
  `stated_by: paper` records) is checked against source anchors: single value,
  revision only with anchor and reason. The interpretive layer (Observations,
  agent claims, `SUPPORTS` / `OPPOSES`, Artifacts) keeps coexisting values with
  provenance; the store never adjudicates or ranks.
- **Meta-model, not schema; thin graph, thick documents.** The contribution is
  the accumulation meta-model (Entity / Concept / Content / Artifact, identity,
  provenance, artifact semantics). The domain vocabulary is a given parameter.
- **Intents are the workload root.** Six research intents I1–I6 generate writer
  tasks, reader probes, and the retrieval surface. They are a workload, not a
  capability checklist.
- **Classical mechanisms, adapted.** Each mechanism has a DB predecessor (entity
  resolution, provenance, view invalidation, coexisting alternatives,
  check-out/check-in, dataspaces). The contribution is adapting them to agent
  writers and showing empirically which matter; engage the predecessors
  substantively.

### Paper

- **Tentative title:** *Collaboration without Coordination: Managing Scientific
  Knowledge for Agentic Research*. The managed objects are paper-derived
  knowledge and artifacts; the word "memory" must not pull in features (skill
  distillation, consolidation, forgetting) that the workload does not require.
  The abstract and related work still position the paper in the agent memory
  lineage, and must say that this knowledge is anchored to sources, not
  rewritten by a consolidator. Avoid "shared memory".
- **A data management systems paper**, not a middleware or agent paper: new
  abstractions and an effective combination of existing techniques, backed by a
  principled design, a working prototype, and end-to-end evaluation.
- **Topics:** primary is AI and knowledge bases (agent memory as a data
  management problem, the GEM lineage). Secondaries: knowledge graphs;
  provenance and versioning; data discovery and metadata; entity resolution and
  extraction; data models and semantics; collaborative data sharing
  (ORCHESTRA); scientific data management; LLM-assisted data processing. Data
  cleaning and data quality are deliberately not claimed.
- **Subject areas** (SIGMOD wording, agreed 2026-10-10; map to the closest
  area at other venues). Primary: *AI & knowledge bases* (Modern AI & Data
  Management). Secondaries: *Crowdsourced and collaborative data management*;
  *Data provenance and workflows*; *Data integration, information extraction,
  and schema matching*; *Data models and semantics*. *Data quality, data
  cleaning* is deliberately excluded.
- **Keywords:** agent memory; shared accumulation; uncoordinated writers;
  scientific knowledge; entity resolution; provenance; data versioning;
  coexisting alternatives; staleness; MCP.

## Scope

**In scope.** The existing prototype is the system; no new subsystem is planned.

- `system/` (package `paperweave`, formerly `experiments/e09`): data model,
  Commit, operators, `_stale`, MCP server; `packages/graph-doc` and
  `packages/graph-vc` underneath. Its outside interface is the `paperweave`
  CLI and the `paperweave-mcp` server.
- `eval/` (package `pweval`, formerly `experiments/t1`): the evaluation
  harness. It is evaluation engineering and does not change the system.
  `system/` and `eval/` never import each other; the evaluation reaches the
  system only through its CLI and MCP server (subprocesses), Cypher reads, and
  files.
- **Writers are general-purpose agents.** Runs use the default pi
  configuration: its own system prompt and built-in tools, with the operators
  connected as an MCP server. The experiment controls only the working
  directory, which is outside the repository. Tool usage belongs in MCP tool
  descriptions. Agents keep file and shell access; reads that bypass the
  middleware are audited, not blocked.

Implementation status lives in the status line of each design document.

**Out of scope or deferred.**

- C1 merge and split: not implemented. Duplicates and wrong merges are measured
  and reported as a limitation.
- New retraction semantics: none. Retraction is deletion (with a reason,
  history kept) on the grounded layer and an `OPPOSES` Observation on the
  interpretive layer; any past state can be rebuilt (`as_of`). Commit revert
  is not offered to agents.
- Transactional concurrency: writers run in turn.
- Model changes: no new entity types or fields without agreement.

## Evaluation

The evaluation tests falsifiable propositions. Details, arms, metrics, and the
plan are in `docs/designs/v2/evaluation_draft.md`; `docs/designs/v3/evaluation.md`
adds the V3 settings and overrides it where they differ. The pilot runs under
the mandate in `docs/decisions/2026-10-17-pilot-mandate.md`.

- **E1 integrity (core):** adding uncoordinated writers costs PaperWeave
  significantly less than files + Git, in store health and in probe accuracy.
  Falsified if, at affordable scale, the difference is not significant.
- **E2 sufficiency:** how much of each intent the store alone can answer.
- **E3 parity:** not worse than a general memory system (Graphiti) on reads,
  with a cost ledger.

Principles:

- **Evaluate the store first.** Report correctness, interaction and execution
  cost, scalability, and maintenance behavior; downstream answers are
  application evidence. Count construction and update cost.
- **Strong baselines, equal terms.** Same materials, agent, model, and budget.
  Keep controlled read-side comparisons separate from whole runs.
- **Check semantics against sources.** Schema validity, evidence links, and
  fluent answers do not show correctness. Checks PaperWeave already enforces at
  write time are not evidence against other arms.
- **Freeze before running.** Operators, seeds, probes, gold, and rubrics are
  fixed before formal runs, and agreed with the user before implementation.
- **Report negative results.** If files + Git never lose, report where they
  suffice and narrow the claim; do not switch to a favorable workload.

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

Current documents (these hold the agreed details):

- `paper/narrative-draft.md` — the paper narrative: title, introduction,
  challenges, contributions, positioning against related systems.
- `docs/designs/v2/evaluation_draft.md` — evaluation: E1–E3, arms, workload,
  metrics, plan, risks, open items.
- `docs/designs/v3/` — current system design: `data_model.md` and `tools.md`
  (the MCP tools and artifact types), plus `evaluation.md`, the V3 additions to
  the evaluation. Where they conflict with V2, V3 holds.
- `docs/designs/v2/` — background system design that V3 revises:
  `graph_model_v2.md`, `commit_contract.md`, `operators.md`, `draft_files.md`,
  `versioning_interfaces.md`, `extraction_principles.md`, and
  `intents_decompose.md`, still the workload root (I1–I6, writer tasks, reader
  probes, retrieval surface).
- `docs/decisions/2026-10-17-pilot-mandate.md` — what the agent decides alone
  and what it confirms with the user during the pilot.
- `docs/experiments/2026-10-17-v3-rpc-lab.md` — the V3 lab rounds with pi.
- `docs/discussions/2026-10-12-task-operators-and-leaderboard.md` — artifact
  operators and co-editable artifacts.
- `docs/discussions/2026-10-10-challenges-and-classical-mechanisms.md` —
  challenges versus classical mechanisms, what agent writers change, and
  engineering reuse.
- `docs/discussions/2026-10-05-versioned-knowledge-management.md` — version
  mechanism memo referenced by the design docs.

Older discussions, open questions, and literature notes (including
`docs/designs/v2/research_design_v2.md` and
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
this file to state the current direction, and keep it at that level: details
go into the documents above. Do not append history. Keep working and
reproducibility rules, and distinguish proposals from established findings.
