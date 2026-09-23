# plumb: audit, place and split

## 0. Agent contract

`plumb audit` returns a bounded ranked table and a summary
of evidence coverage. `--format json` exposes the same result with schema
version, input SHA-256, parameters, counts, distributions and neighbour evidence.
Each row is `review`, `consistent`, or `insufficient_evidence`; `review` means
inspect the evidence, never automatically move a topic. These are heuristic
signals, not probabilities or a ground-truth judgment.

Exit 0 means the computation completed, 2 means invalid arguments/input (correct
the input or run `plumb pull --topics-only`), 3 means a network failure (retry the
pull), and 4 means an output write failed (choose a writable output path).
Default output is 20 rows with at most 10 neighbours each; `--limit 0` explicitly
requests all topics, and k is bounded to 1–100. Errors go to stderr; stdout is
only the selected result format. Local audits make no network calls.

Snapshots and file outputs are replaced atomically. Re-running an audit with the
same snapshot and arguments produces identical output. A snapshot records its
source, retrieval time and complete topic metadata. Saved audit JSON plus the
versioned top-50 review form the trajectory; their input hash connects them.
Regression tests preserve escaped defects. The layers are:

1. API acquisition → complete, versioned local topic snapshot.
2. Validated keywords → normalised phrase sets → similarity neighbourhood.
3. Neighbour hierarchy → weighted parent distribution → disagreement score.
4. Ranked evidence → CLI tables/JSON/CSV → a separately authored review.

Acceptance lives in tests and the review record, outside the scoring module.
The known examples never enter the scorer. Missing evidence is reported as
insufficient, never as a passed placement check. A failing acceptance check stays
failed; changing the metric to rescue a named example requires a new decision.

`plumb place` accepts prediction JSONL or a frozen labelled evaluation dataset.
Prediction states are `review_uncalibrated`, `accepted`, `abstain`, and
`insufficient_metadata`; candidate scores alone do not authorise reassignment.
`--evaluate`, `--probe` and `--export-training` are distinct operations. Calibration
is bound to the exact model, taxonomy and inference method. Model failures exit 5;
invalid input exits 2 and file errors exit 4. Input truth is never a model feature.

`plumb split` emits candidate sample partitions, metrics, representative work IDs,
and assignments with explicit missing-text reasons. Default presentation limits
each sink to 20 assignment rows; `--limit 0` and `--assignments` expose all records.
The embedding checkpoint may download on first use; `--representation tfidf`
requires no model. Neither command changes OpenAlex or the taxonomy.

## 1. First implementation

Use all topics' **keyword phrases**. Normalise Unicode (NFKC), case and whitespace;
do not split phrases, stem words, use topic titles/descriptions, or use siblings
(which are derived from the hierarchy being audited). Co-citation is deferred.

Similarity is Jaccard overlap: shared normalised phrases / union of phrases.
Use the k=10 highest positive similarities, excluding the topic itself; ties are
broken by topic ID. Zero-overlap topics never become neighbours. No works-count
weighting: a giant topic does not get to outvote a small one.

At each of subfield, field and domain, compute similarity-weighted parent shares.
The largest share is the neighbourhood's **plurality**, not necessarily a majority.
Break exact share ties in favour of the stated parent, then by parent ID. Default
ranking uses the direct parent, subfield; `--level field|domain` allows inspection
at coarser levels without changing the graph.

For the selected level:

- margin = max(0, plurality share − stated-parent share)
- strength = sum(neighbour similarities) / k (missing neighbours contribute zero)
- score = margin × strength, bounded to [0, 1]

Require at least three positive neighbours, and at least two neighbours supporting
an alternative plurality, before emitting `review`. Otherwise evidence is
insufficient (score zero). A supported stated-parent plurality is `consistent`.
Ranking uses unrounded scores, then topic ID. Outputs include parent shares at
all three levels, actual neighbour count, shared keywords, and each similarity.

This discounts weak overlap and sparse evidence. It cannot identify a whole
misfiled community, validate neighbours' labels, or resolve genuine interdisciplinary
placements. Descriptions may help the separate qualitative review.

## 2. Acceptance fixed before the first scoring run

On the 4,516-topic snapshot, with the default parameters:

- `T12157` (Geochemistry and Geologic Mapping) must rank within the top 50.
- `T11740` (Geochemistry and Elemental Analysis) and `T10398` (Groundwater and
  Isotope Geochemistry) must both rank outside the top 50.
- Review every top-50 row, keeping a reason and distinguishing likely placement
  errors, plausible placements/keyword artifacts, and unresolved cases. An agent's
  metadata review is not independent human confirmation or measured precision.

The older README's “three correctly-filed siblings” was a handoff error: only two
are named as controls. `T13442`, filed under Economics, is another suspected error.
The target's API description explicitly describes machine learning for mineral
prospectivity mapping; the review must consider that evidence even if it conflicts
with the initial premise that its Artificial Intelligence parent is wrong.

Build the implementation and documentation before running acceptance or unit tests.

## 3. Metadata placement and evaluation

`plumb place` classifies JSONL records using title, source, type and supplied
keywords. Features are bounded to 2,000 title characters, 300 source characters,
100 type characters, and 20 supplied keywords of 100 characters each. Adapters
support GLiNER2.5 locally and a self-hosted Kev endpoint.
No abstracts, citations, topic names or ground-truth labels enter model input.
OpenAlex's inferred keywords are excluded from the benchmark to avoid using
upstream topic-model outputs as ostensibly independent metadata.

`plumb pull --works place` collects a seeded random sample with assigned primary
topics. Records sharing a source stay in one deterministic train/calibration/test
partition (60/20/20); duplicate DOI/title groups also stay together. Sampling,
exclusions, source URLs, seed and snapshot hash are saved. Predictions report
ranked subfields; truth is mapped to subfields from the frozen taxonomy.

`plumb place --evaluate` chooses abstention thresholds on calibration records
only, then reports test coverage and precision against (a) the primary topic's
subfield and (b) any of the work's up to three topic subfields. These are two
reference definitions, not a confusion between top-three predictions and truth.
Thresholds maximise calibration coverage subject to a 95% Wilson confidence
interval lower bound of at least 90% precision and at least 20 accepted records. No eligible threshold means
abstain on all records, with precision null rather than a fictitious 100%.
Test uncertainty, unthresholded accuracy, class coverage, and per-type counts
are always reported. This small benchmark is exploratory and does not establish
performance on unassigned datasets/specimen records.

The Kev width probe uses calibration records only, at domain/field/subfield
widths, and records option coverage, accuracy, latency and errors. Flat and
hierarchical inference are explicit modes. The hierarchical choice routes
through domain then field then subfield and uses the product of conditional
probabilities as its score. Test labels never choose model/strategy/threshold.
Fine-tuning exports only the train partition into Kev's native JSONL schema;
it must warm-start the released Kev-9B checkpoint with `--init_from`. A prepared
training command is not evidence of an executed fine-tune.

All runs save input/model/method identity and per-record predictions. Persistent
prediction caches are keyed by input features, options and backend/model; corrupt or mismatched cache entries fail instead of being reused.
Output defaults to 20 rows; full output is explicit. Missing metadata, model
failures, invalid outputs and missing calibration have distinct typed errors.

## 4. Sink-topic splitting

`plumb pull --works split` selects every topic above 20 times the frozen median
works count and collects a seeded sample of records containing each topic.
The sampling predicate is `topics.id`, so secondary assignments are included.
The record carries which sampled sink selected it; a single work may occur in
multiple sink samples. Sample sizes/counts are not estimates of total assignments.

`plumb split` clusters metadata text with versioned multilingual E5-small
embeddings (query prefix, masked mean pooling, L2 normalisation, 512-token
limit with truncation counts) and k-means. TF-IDF word unigrams/bigrams supply
descriptive keywords. `--representation tfidf` retains the lexical baseline.
The multilingual path was added after the baseline grouped the largest sink
primarily by language and left 179 of 300 records without shared-word features. Fixed candidate k values 2–8 compete on cosine
silhouette with a minimum cluster size of five; ties prefer fewer clusters.
Report mean within-cluster pairwise cosine coherence, silhouette and the selected
k per sink, with cluster keywords and representative record IDs. Insufficient
text, degenerate representations and singleton/invalid solutions are reported as
insufficient evidence; no numeric success score is fabricated.

A positive silhouette proposes an exploratory partition, not proof of a taxonomy
error. Every sampled record is accounted for as a proposed cluster member or an
explicitly unassigned record with a reason. Proposed assignments include original
topic, cluster ID and work ID. No OpenAlex records are changed. The largest sink
gets the same outputs as the other six, including the actual proposed moves.
These are sample-level, metadata-based splits; citation/community validation and
extrapolation to millions of records require further evidence.

Implementation, native training/export integration and regression tests are built
before evaluation/model probes. Dataset and model downloads are preparation.
