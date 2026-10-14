---
name: paper-form
description: How to record what a paper says in the store with Commit, as a graph-doc of the paper, its method, the compared methods, datasets, contributions, claims and experiments, each anchored to the paper's lines. Use it when you have read a paper and want its content in the store, or need to correct a paper's records.
metadata:
  type: Skill
---
# paper-form

A paper form is the graph-doc you commit for one paper. It records **what the paper itself states**, at a depth that
lets a later reader find the right paper, table and lines; the numbers and fine details stay in the paper and are read
through the anchors. Your own judgments do not go into it (§6).

The Commit tool description gives the syntax (graph-doc, kinds, fields, relations, errors). This skill says what to put
in it.

## 1. Before writing

- **Is the paper already there?** `Resolve` its arXiv id (`arxiv:2106.09305`) with kind Paper, or `Search` Entity
  Paper by title. If it exists, edit that node and add what is missing instead of creating a second one. If it exists
  as a stub (cited by an earlier paper), fill its empty fields and drop `stub` by writing to its id.
- **Existing objects are referred to by id.** `Resolve` every method, dataset and task you will mention. Never invent
  ids. A dataset with the same name may be different data (Informer's "Weather" is NOAA climate data, not the Jena
  Weather dataset): read its description before reusing it.
- Read the paper's result tables and the text around them (`ReadEvidence`, or the paper file). All locators are
  `<section heading>::<start>:<end>` with the heading and line numbers of the paper's Markdown.

## 2. What to record

| object | what to write | what not to write |
| --- | --- | --- |
| Paper | name (title as printed), description, identifiers, year, material | — |
| the paper's own method | **one** Method with a definition | no nodes for variants or ablation settings |
| compared methods | a stub: `{kind: Method, stub: true, name, note}`; `note` is the citation cue | no definition, no relations to other methods |
| datasets, tasks | ids of existing ones; a new Dataset only when the store has none | — |
| Contribution | each item of the paper's contribution list, `stated_by: paper` | your own assessment (that is `stated_by: agent`) |
| Claim | each main conclusion the paper states (abstract, introduction, conclusion) | conclusions already in an Experiment's text |
| Experiment | **one per result table or figure** of the results section, including figure-only results | one per dataset, metric or horizon |
| CITES | the paper → a cited Paper, when the paper says some of its results are taken from it | background citations |

Record every result table and figure of the results section. An appendix table that completes a main-text table (the
full benchmark) joins that table's Experiment as another anchor. What is not recorded is not evidence that the paper
lacks it.

**Variants.** A variant the reader needs to understand an experiment (e.g. "PatchTST/42 uses look-back 336") gets one
sentence in the Experiment's text; others are left to the paper. A name that later work cites on its own is a method,
not a variant.

**Stubs.** A stub means "not read yet", not "nothing to say". When the stubbed method's own paper is recorded later,
its writer fills the same node.

## 3. Writing each kind

**Experiment.** `anchors` lists the table or figure ids (`[S4.T4]`), the main one first. `FROM` locators cover the table
and the text that describes its design and results. `text` is two to five English sentences in your own words:

1. the question the table answers;
2. the design: who is compared, on what data, and only the conditions needed to read it (look-back, horizons, whether
   baseline values are copied from elsewhere);
3. what the paper reports or claims, written as "The paper reports …"; do not transcribe result numbers.

`note` holds reading notes about what is printed: values that equal another paper's table without saying so, a
misprinted cell, a duplicated reference. `EVALUATES` has a `role` (`target` for the paper's method, `baseline` for the
others) and, in `description`, what the paper says about where the values come from ("Run by the authors",
"Re-implemented by the authors", "Taken from [12]", "Source not stated"). Equal numbers alone do not show that values
were copied. `USES` with `role: evaluation_data` for each dataset; `ON_TASK` for the task.

**Claim.** "The paper claims …", one or two sentences, keeping the paper's own qualifications. `FROM` the lines that
state it; `ABOUT` the methods, datasets and tasks; `SUPPORTED_BY` the experiments that back it.

**Contribution.** "The paper contributes …"; `FROM` the contribution list; `ABOUT` what it proposes or improves. This is
also how "this paper proposed that method" is recorded.

**CITES.** `{to: <paper ref>, description, source_refs}`: the description says which tables and methods' results are
taken from that paper; at least one source ref is a place in the body, not only the bibliography entry. The cited
paper, if new, is a Paper stub named by the title printed in the bibliography.

## 4. Names

Write names as the paper prints them. If the paper misspells an existing object, refer to it by id and do not add
the misspelling as an alias; add an alias only for a genuinely different name. Bibliography titles often differ in
case from the paper's own title: match cited papers by their identifier, not by name.

## 5. Example (from the SCINet paper)

```yaml
graph-doc: v0.1
confirm:
  $scinet:
    distinct_from:            # the candidates the dedup check listed
    - method_0001
    - method_0003
nodes:
  $paper:
    kind: Paper
    name: 'SCINet: Time Series Modeling and Forecasting with Sample Convolution and Interaction'
    identifiers: ['arxiv:2106.09305']
    description: >-
      Proposes SCINet, a hierarchical downsample-convolve-interact network built from SCI-Blocks for time series
      forecasting, and evaluates it on short-term, long-term and spatial-temporal forecasting benchmarks.
    year: 2022
    material: papers/2106.09305v3/paper.md
  $scinet:
    kind: Method
    name: SCINet
    definition: >-
      An encoder-decoder forecasting network whose encoder arranges SCI-Blocks in a binary tree, ...
  $tcn: {kind: Method, stub: true, name: TCN, note: 'Cited as [4] Bai, Kolter and Koltun, An empirical evaluation of generic convolutional ...'}
  $x_t4:
    kind: Experiment
    anchors: [S4.T4]
    text: >-
      Multivariate long sequence forecasting on ETTh1, ETTh2 and ETTm1 under Informer's setting, comparing SCINet with
      LogTrans, Reformer, LSTMa, LSTNet, Informer, TCN, Pyraformer and Autoformer. Input lengths kept the same as
      Informer; horizons {24, 48, 168, 336, 720} for ETTh and {24, 48, 96, 288, 672} for ETTm1. The paper reports
      SCINet best in most settings, with Autoformer better on ETTh1 at horizon 720.
    note: >-
      The LogTrans, Reformer, LSTMa, LSTNet and Informer values are identical to Table 2 of the Informer paper, but the
      paper does not say they are taken from it. LSTNet's MAE on ETTm1 at horizon 24 is printed as "L1700".
    FROM:
    - {to: $paper, locators: ['4.2 Results and Analyses::289:323']}
    EVALUATES:
    - {to: $scinet, role: target, description: Run by the authors of this paper.}
    - {to: method_0001, role: baseline, description: Values equal Informer's Table 2; source not stated.}
    - {to: $tcn, role: baseline, description: Re-implemented by the authors.}
    USES:
    - {to: dataset_0002, role: evaluation_data}
    ON_TASK:
    - task_0002
```

## 6. Your own judgments go elsewhere

That a table looks inconsistent, that two papers' numbers are not comparable, that a claim is not supported: these are
your judgments, not the paper's statements. A reader who finds them in an Experiment would take them for the paper's
content. Write them as an Observation (`ABOUT` the objects, `FROM` the paper lines or artifact lines it rests on), or
as a Contribution or `SUPPORTS` / `OPPOSES` with `stated_by: agent`. They keep your name, and others may disagree by
writing their own.

## 7. Commit

1. Write the graph-doc to a YAML file in your working directory and call `Commit` with `doc_file`, a `message` and a
   `source` such as `paper:2021-SCINet`. `apply: false` previews without writing.
2. `status: blocked` means nothing was written; fix the lines that `errors` points to and call again.
3. A dedup error lists stored candidates for a new Method, Dataset or Paper. If one is the same object, use its id
   instead of your `$name`; if none is, add `confirm: {$name: {distinct_from: [<candidate ids>]}}`, with a short
   comment saying why.
4. Records of what a paper says stay faithful to it. To change or delete an Experiment, Claim or Contribution
   `stated_by: paper`, add `confirm: {<id>: {revise: {reason: ..., anchor: '<section>::<start>:<end>'}}}` citing the
   paper lines that support the change; the old version stays in the history.
5. The reply's `related_artifacts` lists the Leaderboards on the datasets your experiments use, and datasets that have
   none. Transcribing the numbers into a Leaderboard is described in the `leaderboard` skill.
