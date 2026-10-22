# Shared knowledge repository

This git repository is a shared knowledge store built from CS papers by many sessions, with the artifacts they produced. Sessions do not know each other; this repository is the only thing they share, and later readers were not there when things were written.

- `store/nodes/<kind>/<id>.yaml`: one file per node (an entity, a concept or a record of what a paper says).
- `store/artifacts/<title>.md`: shared documents sessions edit together (leaderboards, comparisons, verifications, summaries, answers).
- `templates/`: a blank file for every node kind and artifact type; copy one to start a new file.

Find things with your own tools (ls, grep, read).

## Publishing

Put contributions you want to share in /work/store/. Stage the files you choose with git add and publish them with git commit. Keep private downloads and drafts elsewhere under /work/. Uncommitted changes are not visible to later sessions.

Make one commit per task, with a one-line message saying what you did and why. `git log` and `git show` give the history; git keeps every old version.

## Sources

Papers and code are sources with fixed ids: a paper with its version, like `2205.13504v2`; a code repository at a commit, like `Autoformer@09994619`. Fetch them with read_source; they arrive under `/work/sources/` (`sources/2205.13504v2/paper.md`, `sources/Autoformer@09994619/<files>`).

Record the source ID for claims and results. You may add a file path or line range to identify the supporting passage:

- `<source_id>`
- `<source_id>::<start>:<end>`: lines of a paper's `paper.md`
- `<repo>@<commit>::<file>`
- `<repo>@<commit>::<file>::<start>:<end>`

Write these in a node's `anchor` list and an edge's `anchor`, quoted, and in artifacts in brackets, like `[2205.13504v2::120:135]` or `[2205.13504v2]`. A source id names one fixed version, so a reference stays on the text it was written against.

## Nodes

A node file is YAML: `id`, `kind`, its fields, and its outgoing relations as UPPERCASE keys mapping target ids to properties. Refer to other nodes by id only.

```yaml
id: exp_0003
kind: Experiment
paper: paper_0001                    # the paper it comes from
anchor: ["2205.13504v3::120:135", "2205.13504v3::141:150"]   # its sources, quoted (see Sources)
figures: [S4.T2]
description: |
  Long-horizon forecasting on six benchmarks against Transformer baselines ...
EVALUATES:                           # methods, not Models
  method_0002: {role: target, result: own}
  method_0004: {role: baseline, result: cited}
USES:
  dataset_0002: {role: evaluation_data, printed_as: ETTh1}
```

A Paper node also has `identities` (like `[arxiv:2205.13504]`, without the version), `year` and `source` (the versions read, by source id, like `[2205.13504v3]`). A Code node has `source` too: the repository at its commit, like `[Autoformer@09994619]`.

Ids are `<prefix>_<4 digits>`: paper, dataset, code, model, tool, method, task, issue, exp (Experiment), claim, contrib (Contribution). Take the next free number for the kind.

Kinds:
- Entity:
  - Paper: a paper's bibliographic object; also year, source
  - Dataset: data itself, or a named benchmark suite (members via PART_OF)
  - Code: a code repository; also source
  - Model: released weights or a checkpoint, or a model called through an API; a method a paper trains and compares is a Method
  - Tool: software, a library or a service that is not a model
- Concept:
  - Method: a method or method family (variants and configurations are not nodes)
  - Task: a research task
  - Issue: a research problem; name is a short title
- Content:
  - Experiment: one group of experiments a paper reports (one research question); also figures
  - Claim: one claim by the paper's authors, with the context it needs
  - Contribution: one contribution the paper states for itself

Fields (* required; a stub needs only name): Entity: name*, alias, identities, description, extra, stub; Concept: name*, alias, description*, extra, stub; Content: paper*, anchor*, description*, extra

Relations (start → end; * marks required properties):
- EVALUATES: Experiment → Code | Model | Tool | Method: a method (or model, code, tool) compared in the experiment [role* (target | baseline), result (own | cited | unstated)]
- USES: Experiment → Dataset | Code | Model | Tool: data (or code, model, tool) the experiment uses [role (evaluation_data | training_data | analysis_input | tooling | retrieval_corpus), printed_as]; when one edge plays two roles, write role as a list, like [training_data, evaluation_data]
- ON_TASK: Experiment → Task: the task the experiment is on
- SUPPORTS: Experiment | Claim → Claim: evidence for a claim
- OPPOSES: Experiment | Claim → Claim: evidence against a claim
- ABOUT: Content → any node: what the content is about (the method proposed, a dataset, ...)
- CITES: Paper → Paper: the paper cites another; description says what for [description*]
- PART_OF: Dataset → Dataset: a subset, or a member of a benchmark suite
- IMPLEMENTS: Code | Model → Method: code or weights implementing a method
- FOR_TASK: Dataset → Task: a task the dataset serves
- BROADER: Concept → Concept: a broader concept of the same kind
- RELATES_TO: any node → any node: any other relation; description says which [description*]

Any edge may also carry anchor (its sources, see Sources), description and extra.

Rules:
- Before creating an Entity or Concept, look for an existing one (by name, alias and identities). If one is the same thing, use its id; if a similar one is a different thing, say so in your node's `extra` (`distinct_from: [<ids>]`).
- Content (Experiment, Claim, Contribution) records what a paper says. When you add edges to an existing record, give the anchor; when you change its fields or edges, add an entry to its `revisions` list (`{reason, anchor, by}`) and say why in the commit message; when you delete it, give the reason in the commit message. The old version stays in the git history.
- A paper's new version: add the new version's source id to the Paper's `source`. Anchors written earlier keep the old id and stay on the text they were written against; revise only the records the new version changes, with anchors on the new id.
- Quote short text containing ": " or starting with a special character; put long text in a | block.

## Artifacts

Artifacts are shared documents: Leaderboard (results of methods on one task, dataset and setting), CompareSettings (whether two results are comparable, setting by setting), Verify (whether a claim holds, with the evidence), Summarize (a cited summary of a topic), Note (your cited write-up for later readers: an answer, a method choice, what you found about an implementation, a plan). Start one from `templates/<type>.md`; the header says its type, title and a one-sentence abstract. Cite what each statement rests on in brackets: a node `[exp_0003]`, a source `[2205.13504v2::120:135]` or `[2205.13504v2]` (see Sources), or an artifact row `[<artifact file title>#<row key>]`, where a leaderboard row key is its method id, variant, paper id, lookback and pred_len joined with `+` (like `method_0004++paper_0001+336+96`).

- There is one Leaderboard per task, dataset and setting, one CompareSettings per pair of compared items, and one Verify per claim: look for an existing one before starting another, and edit it together with the others who wrote it. Summarize and Note documents may coexist.
- When you change or delete lines others wrote, say why in the commit message.
- An artifact may be out of date when something it used has changed since it was written.
