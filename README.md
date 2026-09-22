# plumb

> A plumb line for borrowed taxonomies: audit where a topic hangs, place what a
> classifier cannot see, and split the buckets things get dumped into.

Three tools over the OpenAlex topic taxonomy (4 domains → 26 fields → 252
subfields → 4,516 topics). They are independent, run off the public API with no
key, and each emits a table you can check by hand.

The taxonomy is two maps bolted together. The **leaves** are citation clusters —
intrinsic, the subject's own structure. The **hierarchy above them** is Scopus
ASJC — borrowed, a publisher's filing scheme. plumb exists because errors
concentrate in the borrowed layer, and because coverage is reported as one
number when it is measuring at least three different things.

## Install

```bash
git clone https://github.com/NakliTechie/plumb && cd plumb
uv sync            # or: pip install -e .
python -m plumb.pull          # ~35 API calls → data/*.csv
```

## The three tools

### 1. `plumb audit` — hierarchy placement auditor
For each topic, score its ASJC parent against the consensus parent of its own
citation/keyword neighbourhood. Emit a ranked list of suspect placements.

**Acceptance:** `Geochemistry and Geologic Mapping` (3.4M works, filed under
Artificial Intelligence → Computer Science) must land in the top results, while
its three correctly-filed geochemistry siblings must not. If it does not
rediscover the known misplacement, the auditor is wrong.

### 2. `plumb place` — metadata-only topic classifier
12.3% of works (40.2M of 327.8M) have no primary topic. The production
classifier reads title + abstract + citations + journal; the largest
contributors to the gap are dataset and specimen registries — NIFS (12.7M),
DiSSCo (5.8M), together 45.8% of it — whose records have no abstract and no
citations **by nature**. A model built on abstracts and citations was never
going to place them.

`place` asks the narrower question: how far can you get from **title + source +
type + keywords alone**, and at what precision. Open-weights only:

- **Kev-9B** (`jaredpalmer/kev`, Qwen3.5-9B base, LoRA r=16 + pointer head,
  Apache-2.0) — one-pass typed decisions over enumerated options with
  calibration in the checkpoint. 0.852 on sources it never trained on, against
  hosted Jev's 0.857. Drop-in `POST /v1/systemone`. Fine-tune with `--init_from`
  the released checkpoint, never from base.
- **GLiNER2.5** (`fastino/gliner2.5-multi-v1`, 287M, Apache-2.0) — zero-shot
  classification against subfield labels and entity extraction from titles. The
  floor: no training, so it says what is achievable before anyone fits anything.
- **Laya / laya-coreml** — Core ML + Neural Engine port of the same typed-decision
  primitives, 4.98 ms P50 on an M3 Max. The throughput path if 12.7M records
  have to run locally.

**Acceptance:** report coverage at ≥90% precision on a held-out slice of works
that *do* have topics, restricted to metadata the dataset records actually
carry. "Almost none" is a valid and useful answer — it settles the
separate-denominator question with evidence. Kev's own README is blunt that a
fixed temperature cannot reorder confidences, so the usable threshold is fitted
here, on this data, not inherited.

### 3. `plumb split` — sink-topic splitter
Seven topics sit above 20× the median (57,439 works). `Military Technology and
Strategies` holds 20.6M — 359× median, 6% of all assignments. Those works count
as *covered*. Cluster inside a sink and report whether it is one research
community or a default bucket.

**Acceptance:** a silhouette/coherence number per sink, and for the largest, a
proposed split with the works that would move.

## Why these three

They cut the same number — topic coverage — from both sides. `place` and the
denominator question say the gap is overstated (records nothing could classify).
`audit` and `split` say coverage is also overstated in the other direction
(filed, but filed wrong, or dumped). A coverage metric that is wrong in both
directions cannot tell you whether a change helped.

## Non-goals

Not a reimplementation of the topic classifier, not a fork of the taxonomy, not
a service. Three read-only tools that emit tables, plus the pull script that
reproduces their inputs.

## Context

Grew out of an evening's analysis of the OpenAlex public API (2026-09-12,
re-pulled 2026-09-22). Data, queries and findings: see `data/` and
`docs/findings.md`.
