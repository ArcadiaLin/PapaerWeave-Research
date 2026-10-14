---
name: generate
description: How to write a Generate document in the store, an answer, draft, idea or plan built on stored knowledge, with references that later readers can follow. Use it when you write up a result of your work that others may read or build on.
metadata:
  type: Skill
---
# Generate

A Generate document is free-form Markdown in the store: an answer to a question, a draft, an idea, a plan. It has no
identity key, so each new one is a separate document; others can still check it out, edit it and check it in, and the
store keeps every version and who wrote each line.

What the store enforces is only that every reference you write exists. Everything else in this skill is convention.

## 1. Look first

`Search` with `type: Artifact`, `where: {op: Generate}` and a `query` describing your topic. If a document already
answers the same question, check it out with `FetchArtifact` and extend it rather than writing a second one.

## 2. The document

```markdown
---
type: Generate
title: Does a longer look-back help on ETTh1?
abs: >-
  Compares results reported at different look-back lengths on ETTh1 (multivariate) and what the papers say about it.
---
SCINet reports its own look-back for each horizon, up to 736 at horizon 720
[paper_0002::Appendix C Reproducibility::937], while its baselines keep Informer's settings
[paper_0002::4.2 Results and Analyses::317].

At horizon 24, SCINet's MSE is 0.300 [<board id>#method_0012++paper_0002+24+48] against 0.577 for Informer
[<board id>#method_0001++paper_0002+24+same as Informer]; the look-backs differ, so the gap is not only the model.
```

`<board id>` stands for the id of the ETTh1 Leaderboard (such as art_0002); in a real document write the id.
`title` and `abs` are the text that `Search` matches; write them so that someone with a different question can still
find the document. The body is yours to organize.

## 3. References

Write references in square brackets; several in one pair are separated by `;`.

| reference | form | example |
| --- | --- | --- |
| an object | its id | `[method_0012]` |
| paper lines | `<paper id>::<section heading>::<start>:<end>`, as `ReadEvidence` shows them | `[paper_0001::Datasets::269]` |
| a row of a shared table | `<artifact id>#<row key>` | `[<board id>#method_0012++paper_0002+24+48]` |

- **Numbers, comparisons and judgments** should carry a reference to where they come from. For results, cite the
  Leaderboard row, not a number from memory: the row carries its own source line.
- **Your own reasoning** needs no reference, but say that it is yours ("this suggests", "I assume").
- `CheckIn` rejects a reference to an object, line range or row that does not exist, and reports how many paragraphs
  carry references. That count is information, not a requirement.

## 4. Editing someone else's document

Fix errors and add material. If you disagree with a conclusion, add your own paragraph with your evidence, or write a
separate document; do not rewrite another writer's conclusion into yours. The history keeps who wrote each version.

## 5. Check in

Write the document to any file in your working directory (e.g. `artifacts/lookback-etth1.md`), then call `CheckIn`
with `artifact_doc: [<path>]` and an `update_abstract`. Without `confirm` it only checks; read `errors`
and `warnings`, fix, and call again with `confirm: true` to write.
