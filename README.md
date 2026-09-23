# plumb

> A plumb line for borrowed taxonomies: audit where a topic hangs, place what a
> classifier cannot see, and split the buckets things get dumped into.

Three tools over the OpenAlex topic taxonomy (4 domains → 26 fields → 252
subfields → 4,516 topics). They are independent, run off the public API with no
key, and each emits a table you can check by hand.

The taxonomy is two maps bolted together. The **leaves** are citation clusters —
intrinsic, the subject's own structure. The **hierarchy above them** is Scopus
ASJC — borrowed, a publisher's filing scheme. plumb tests placement in that
borrowed layer, and separates the different phenomena hidden inside a single
coverage number.

## Install

```bash
git clone https://github.com/NakliTechie/plumb && cd plumb
uv sync --extra dev           # or: pip install -e '.[dev]'
uv run plumb pull --topics-only  # 23 requests → data/topics.json + topics.csv
uv run plumb audit              # offline; bounded to 20 rows
```

## The three tools

### 1. `plumb audit` — hierarchy placement auditor
For each topic, compare its ASJC parent with the parents of its ten nearest
keyword neighbours. Emit a ranked list with shared phrases and parent shares.
The first version uses Jaccard overlap of whole keyword phrases; co-citation is
deferred. Its score is the alternative parent's share minus the stated parent's
share, multiplied by neighbourhood overlap strength. Scores are review priorities,
not error probabilities. Sparse evidence is explicitly marked insufficient.

```bash
uv run plumb audit --format json --limit 50 --output data/audit-top50.json
uv run plumb audit --format csv --limit 0 --output /tmp/plumb-audit.csv
uv run plumb audit --level field --k 10
uv run plumb audit --input /path/to/topics.json
uv run plumb pull              # refresh all three original tables + snapshot
uv run pytest                 # unit checks and the predeclared acceptance gate
```

JSON includes the snapshot hash, method, parameters, coverage counts and complete
neighbour evidence. CSV carries the same per-row evidence in JSON columns. Output
files are replaced atomically. Run from the repo root or specify `--input` /
`--output-dir`; audits need no network or numerical dependencies. The snapshot
is included for offline reproduction. Design and agent contract: [spec](docs/spec.md).
`place` and `split` use the same local taxonomy snapshot; their workflows are below.

**Acceptance:** `Geochemistry and Geologic Mapping` (3.4M works, filed under
Artificial Intelligence → Computer Science) must land in the top results, while
`Geochemistry and Elemental Analysis` and `Groundwater and Isotope Geochemistry`
must rank outside the top 50. The acceptance target itself is a hypothesis: its
API description discusses machine learning for mineral mapping, so Artificial
Intelligence may be defensible. A missed target leaves this gate unmet; the
scorer does not special-case the target. See [findings](docs/findings.md) for the
executed result and qualitative review.

**Current result:** the baseline ranks the target 914th; its acceptance test
fails. Both controls are outside the top 50. Review of the leading 50 found five
placement candidates, 36 plausible current placements and nine unresolved cases;
these are agent assessments from metadata, not measured precision. The saved
paper samples show why keyword metadata cannot settle the known cases.

### 2. `plumb place` — metadata-only topic classifier

The command supports local GLiNER2.5 and self-hosted Kev. It emits ranked
subfields from title, source, type and supplied keywords, with optional calibrated
abstention. It also evaluates held-out records, probes option widths and exports
train-only examples for a real Kev fine-tune.

```bash
uv sync --extra place --extra split --extra dev
uv run plumb pull --works place              # 600 seeded assigned works
uv run --extra place plumb place --evaluate --device mps --limit 0 \
  --format json --output data/place-gliner-evaluation.json
uv run --extra place plumb place --input data/place-example.jsonl --device mps
uv run --extra place plumb place --input data/place-example.jsonl --device mps \
  --calibration data/place-gliner-evaluation.json --reference primary
```

Prediction input is JSONL. Each record has `id` and `metadata` containing string
`title`, `source`, `type`, plus an optional string list `keywords`. Unknown fields,
including labels, abstracts and citations, are excluded from model input. Source
and duplicate groups stay together in the benchmark's train/calibration/test
partitions. The benchmark excludes OpenAlex-generated keywords because they can
carry information from its existing classifier.

The threshold is fitted exclusively on calibration data. It requires a 95%
Wilson lower bound of at least 90% precision and at least 20 accepted records.
Test precision and coverage are measured separately against the primary topic's
subfield and any of the work's top-three topic subfields. No eligible threshold
means abstain on all, with precision undefined. Without a calibration file,
predictions are explicitly marked `review_uncalibrated`.

**Executed GLiNER baseline:** 5/90 primary-subfield and 11/90 any-assigned-subfield
hits on the held-out test slice; no eligible ≥90% calibration threshold, so
selective coverage is 0%. [Full results and limitations](docs/findings.md).

**Executed Kev warm-start:** the bounded 128-record run completed from the
released checkpoint with no rejected or truncated records. On the held-out test
slice it reached 15/90 primary-subfield and 29/90 any-assigned-subfield accuracy
before thresholding. No calibration threshold met the ≥90% precision rule, so
selective coverage is also 0%. The trained checkpoint is retained locally in
`models/kev-plumb-v1`; metrics and limitations are in the findings.

Kev needs a separate environment because its Transformers requirements differ
from GLiNER's. The helpers use Kev's actual adapter and pointer head, expose
checkpoint fingerprints and unrounded choice probabilities, and reject silent
training-record truncation. The standard Kev endpoint rounds probabilities to
two decimals; plumb uses its helper’s `/plumb/choice-probabilities` endpoint
for wide-label scoring and calibration.

```bash
git clone https://github.com/jaredpalmer/kev models/kev-source
git -C models/kev-source checkout 1c351992ba3df4a0a0f2ae03051b25466a2c7bcb
uv sync --project models/kev-source --extra serve
models/kev-source/.venv/bin/python scripts/serve_kev.py \
  --run jaredpalmer/kev-9b@2629c06a5aeb0feb3b9783bafed17ed8f39ecf5c --device mps
# In another terminal, using that server:
uv run plumb place --probe --backend kev --probe-size 12 --limit 0 \
  --format json --output data/place-kev-width-probe.json
uv run plumb place --export-training models/plumb-training --strategy hierarchical
models/kev-source/.venv/bin/python scripts/train_kev.py \
  --export models/plumb-training --out models/kev-plumb-v1 --device mps
# Restart the server with --run models/kev-plumb-v1, then:
uv run plumb place --evaluate --backend kev --strategy hierarchical --limit 0 \
  --format json --output data/place-kev-evaluation.json
```

The 9B model needs substantial memory; this project's execution uses the existing
64 GB Mac Studio with its cooperative compute lock. Local CPU/GLiNER runs and
`split` are independent of that machine. CUDA is supported by the helpers; no
command provisions a paid instance. Training export defaults to 128 train records
for the initial bounded experiment; use `--train-limit 0` to export all training
records. Record-count and checkpoint provenance accompany every run.

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

The command clusters sampled titles and supplied keywords with multilingual E5
embeddings and k-means. It compares 2–8 clusters using cosine silhouette, requires
at least five records per cluster, and reports within-cluster cosine coherence.
TF-IDF supplies descriptive keywords; representative titles make each proposal
inspectable. `--representation tfidf` reproduces the lexical baseline. The model
revision and runtime are recorded, and embeddings are cached by model and text.

```bash
uv run plumb pull --works split               # 300 records per oversized topic
uv run --extra split plumb split --device mps
uv run --extra split plumb split --limit 0 --format json \
  --output data/sink-splits.json --assignments data/sink-assignments.csv
uv run --extra split plumb split --topic T14423
```

Every sampled work receives a proposed cluster or an explicit unassigned reason.
The assignment CSV contains the work IDs that would move to each proposed
subcluster. These are exploratory sample partitions: the command does not alter
the taxonomy or claim to classify every work inside a sink. Degenerate or too-small
samples produce `insufficient_evidence` instead of invented quality numbers.

**Executed sink run:** all seven have saved metrics and explicit work-level
assignments (2,097 nonempty texts out of 2,100 sampled assignments). The largest
still groups mainly by language; these are exploratory proposals.
[Results and interpretation](docs/findings.md).

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
