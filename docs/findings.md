# Findings — OpenAlex topic coverage, pulled 2026-09-22

All numbers from the public API, no key. Reproduce with `uv run plumb pull`
(~35 calls). A first pass was run 2026-09-12; figures below are the re-pull.

## The headline number is measuring three things at once

327,790,539 works; 40,206,874 with no primary topic = **12.27%**.

| Slice | Unassigned / total | Rate |
|---|---|---|
| ≤2019 | 9,514,161 / 221,468,822 | 4.3% |
| 2020–24 | 3,843,206 / 54,363,375 | 7.1% |
| 2025 | 3,578,884 / 14,679,240 | 24.4% |
| 2026 | 22,484,378 / 32,068,337 | **70.1%** |

2026 carries 22.5M of the 40.2M gap, on ~3× a normal year's intake.

## Two sources are 45.8% of the gap

| Source | Unassigned | Share of gap |
|---|---|---|
| NIFS | 12,651,379 | 31.5% |
| DiSSCo | 5,752,567 | 14.3% |
| Zenodo | 957,195 | 2.4% |
| IRDB | 824,126 | 2.0% |
| PNNL Repository | 803,365 | 2.0% |
| GBIF | 669,440 | 1.7% |
| ENCODE | 496,659 | 1.2% |
| USC Digital Library | 407,461 | 1.0% |

Fusion-data and specimen records: no abstract, no citations, *by nature*. A
classifier over title + abstract + citations + journal was never going to place
them. They belong in their own denominator with a metadata-only path — which is
what `plumb place` measures — or an explicit decision not to classify.

Strip them and the remaining signal is cadence: recent ingest not yet passed
over, not a model failure.

## Coverage is also overstated

Median topic: 57,439 works. Seven topics sit above 20× median.

| Topic | Works | × median | Filed under |
|---|---|---|---|
| Military Technology and Strategies | 20,632,645 | 359× | Aerospace Engineering / Engineering |
| Magnetic confinement fusion research | 5,409,556 | 94× | Nuclear and High Energy Physics / Physics |
| Diverse Scientific and Economic Studies | 4,927,147 | 86× | Economics and Econometrics / Economics |

The third name is a confession. Works in a sink have a topic in the data and no
topic in reality — `plumb split` tests which.

## The initial placement hypothesis

| Topic | Works | Subfield / field / domain |
|---|---|---|
| Geochemistry and Geologic Mapping | 3,432,384 | **Artificial Intelligence / Computer Science** / Physical Sciences |
| Geochemistry and Elemental Analysis | 75,613 | Geochemistry and Petrology / Earth and Planetary Sciences |
| Groundwater and Isotope Geochemistry | 67,454 | Geochemistry and Petrology / Earth and Planetary Sciences |
| Geochemistry and Geochronology of Asian Mineral Deposits | 24,458 | **Economics and Econometrics / Economics** |

These names prompted the hypothesis that the AI and Economics parents are
misplacements. Names alone cannot establish that the citation clusters are sound
or identify which layer is wrong. The keyword audit and diagnostic paper samples
below expose disagreement between topic names, descriptions and assigned papers.

## Topic metadata is uniform

All 4,516 topics carry the same `created_date` (2024-01) and the same
`updated_date` — bulk-refreshed, never individually evolved. 4,486 of 4,516
report siblings, and siblings are "other topics in the same subfield" — the
hierarchy read sideways, not a relation between topics. There is no
knowledge-map edge in the public taxonomy.

## Keyword auditor — executed 2026-09-22

The initial keyword-only auditor **did not meet its predeclared acceptance gate**.
The target, `T12157`, ranked 914th. The two controls ranked 3,279th (`T11740`)
and 655th (`T10398`), outside the top 50 as required. The second suspected
misplacement, `T13442`, ranked 4,076th and has a zero disagreement score.

The scorer uses exact normalised keyword phrases, Jaccard similarity, ten positive
neighbours, and a similarity-weighted parent distribution. Its score multiplies
the alternative-parent share margin by total overlap divided by ten. At least
three neighbours and two votes for the alternative are required. Ties use topic
ID; no title, description, known-case ID, hierarchy-derived sibling relation or
works-count weight enters the score. Subfield is the default level. These choices
were recorded before the first scoring run; see [spec](spec.md).

The run evaluated 4,516 topics: 2,419 `review`, 1,313 `consistent`, and 784 `insufficient_evidence`.
These are heuristic statuses. A `consistent` row is agreement with nearby
metadata, not evidence that its assigned papers belong under its parent.

Snapshot SHA-256: `c40c446d67677ec9cd52894674fdbe8fd0fcc99a53d29111368043c09db08409`.

Artifacts: [all ranked scores](../data/audit-scores.csv),
[top-50 neighbour evidence](../data/audit-top50.json),
[50 review reasons](audit-review-notes.tsv), and the [topic snapshot](../data/topics.json).

### The known cases expose a metadata problem

The target's description discusses machine learning for mineral prospectivity
mapping. Its nearest neighbours mostly overlap on `machine learning`, `remote
sensing` and `support vector machines`; the alternative subfield has only 21%
of the neighbour weight. This does not recreate a geochemistry neighbourhood.
`T13442` is more striking: its title names Asian mineral deposits, but its
keywords and description concern economics, which agrees with its stated parent.
The keyword audit therefore cannot establish whether the parent or the topic's
metadata is wrong.

A separate diagnostic retrieved the ten most cited works having each of these
two topics as their **primary** topic. `T12157` includes rock-forming minerals,
volcanic-rock geochemistry, crustal element distributions and geological data
analysis alongside remote sensing and Earth-system machine learning. `T13442`
includes the North China Craton, granites, basaltic magmas and crustal growth
alongside economics. This supports investigating the original placement concern,
and shows why the metadata alone cannot settle it. These are selected examples,
not representative samples or an estimate of topic composition. The API returned
170,355 primary-topic matches for `T12157` and 22,925 for `T13442`; those counts
have a different selection from the topic entity's `works_count`.

Evidence: [saved work samples, source queries and retrieval times](../data/acceptance-work-samples.json).
No co-citation graph was built. The next substantive step is to derive topic
neighbourhoods from assigned works/citations and evaluate an independently
reviewed set of placements; this baseline provides no measured detection precision.

### Top-50 qualitative review

I read all 50 topics' names, descriptions, keywords, parent shares and neighbour evidence. The agent review marked **5 placement candidates, 36 plausible current placements / neighbourhood artifacts, and 9 unresolved cases**.
These are metadata-based judgments by the same agent that implemented the tool.
They are not independent human adjudication or confirmed errors. I did not sample
papers for these 50 rows. Generic humanities and education vocabulary dominates
the leading results; method-versus-application boundaries also generate flags.
The five candidates warrant paper-level review before proposing moves.

The table records the scorer's proposed plurality, which is not an endorsed new
parent. The reason for each judgment is in the linked review TSV.

| Rank | Topic | Current subfield | Neighbour plurality | Score | Agent review |
|---|---|---|---|---:|---|
| 1 | T11198 — Japanese History and Culture | Cultural Studies | Literature and Literary Theory | 0.16190 | plausible placement |
| 2 | T12164 — Education Practices and Challenges | Philosophy | Education | 0.14199 | placement candidate |
| 3 | T13823 — Religious and Theological Studies | Sociology and Political Science | Philosophy | 0.13824 | plausible placement |
| 4 | T13575 — Travel Writing and Literature | History | Literature and Literary Theory | 0.13333 | plausible placement |
| 5 | T12470 — Caribbean and African Literature and Culture | Religious studies | Literature and Literary Theory | 0.12892 | unresolved |
| 6 | T13863 — Cultural History and Identity Formation | History | Literature and Literary Theory | 0.12619 | plausible placement |
| 7 | T11974 — Lepidoptera: Biology and Taxonomy | Genetics | Ecology, Evolution, Behavior and Systematics | 0.12435 | plausible placement |
| 8 | T13977 — Geography and Environmental Studies in Latin America | Geography, Planning and Development | Education | 0.12042 | unresolved |
| 9 | T12455 — Mediterranean and Iberian flora and fauna | Plant Science | Ecology, Evolution, Behavior and Systematics | 0.11699 | plausible placement |
| 10 | T13023 — Synthesis of Organic Compounds | Pharmacology | Organic Chemistry | 0.11127 | plausible placement |
| 11 | T14469 — Renaissance Literature and Culture | Classics | Literature and Literary Theory | 0.11099 | unresolved |
| 12 | T14088 — Generational Differences and Trends | Life-span and Life-course Studies | Education | 0.11046 | plausible placement |
| 13 | T12864 — Psychoanalysis and Social Critique | Cultural Studies | Philosophy | 0.11029 | plausible placement |
| 14 | T10343 — Hydrogels: synthesis, properties, applications | Molecular Medicine | Biomaterials | 0.10670 | unresolved |
| 15 | T13211 — Memory, Trauma, and Testimony | Experimental and Cognitive Psychology | Literature and Literary Theory | 0.10000 | placement candidate |
| 16 | T12807 — Consumer Behavior and Market Dynamics | Sociology and Political Science | Education | 0.09559 | plausible placement |
| 17 | T14403 — Educational Challenges and Innovations | Information Systems | Education | 0.09281 | plausible placement |
| 18 | T11495 — Animal Virus Infections Studies | Animal Science and Zoology | Infectious Diseases | 0.09281 | plausible placement |
| 19 | T14176 — Interdisciplinary Cultural and Social Studies | Sociology and Political Science | Literature and Literary Theory | 0.09265 | plausible placement |
| 20 | T13666 — Postmodernism in Literature and Education | Literature and Literary Theory | General Arts and Humanities | 0.09167 | plausible placement |
| 21 | T12668 — Yeasts and Rust Fungi Studies | Molecular Biology | Ecology, Evolution, Behavior and Systematics | 0.09085 | unresolved |
| 22 | T12437 — Balkans: History, Politics, Society | Cultural Studies | Sociology and Political Science | 0.08987 | plausible placement |
| 23 | T14241 — Evasion and Academic Success Factors | Demography | Education | 0.08899 | placement candidate |
| 24 | T12993 — Psychology of Development and Education | Developmental and Educational Psychology | Education | 0.08889 | plausible placement |
| 25 | T10660 — Conducting polymers and applications | Polymers and Plastics | Biomaterials | 0.08778 | plausible placement |
| 26 | T10005 — Ecology and Vegetation Dynamics Studies | Nature and Landscape Conservation | Ecology | 0.08709 | plausible placement |
| 27 | T13985 — Enterprise Management and Information Systems | Management of Technology and Innovation | Economics and Econometrics | 0.08627 | plausible placement |
| 28 | T13066 — Information Society and Technology Trends | General Social Sciences | Education | 0.08550 | plausible placement |
| 29 | T13663 — Sustainability, Environment, and Optimization Algorithms | Water Science and Technology | Global and Planetary Change | 0.08529 | plausible placement |
| 30 | T13384 — Regional Economic Development and Innovation | Strategy and Management | Economics and Econometrics | 0.08448 | plausible placement |
| 31 | T13529 — Education Systems and Policies | Management of Technology and Innovation | Education | 0.08431 | placement candidate |
| 32 | T13070 — Cultural Identity and Heritage | Archeology | Sociology and Political Science | 0.08333 | unresolved |
| 33 | T12242 — Latin American and Latino Studies | Cultural Studies | Literature and Literary Theory | 0.08333 | plausible placement |
| 34 | T14426 — Religion, Gender, and Enlightenment | Religious studies | Sociology and Political Science | 0.08252 | plausible placement |
| 35 | T14380 — Libraries and Information Services | Museology | Literature and Literary Theory | 0.08170 | plausible placement |
| 36 | T13351 — Critical Theory and Political Philosophy | Education | Philosophy | 0.08170 | plausible placement |
| 37 | T13573 — Government, Law, and Information Management | Law | Political Science and International Relations | 0.07974 | plausible placement |
| 38 | T12671 — Management and Marketing Education | Management of Technology and Innovation | Education | 0.07847 | unresolved |
| 39 | T13229 — Gothic Literature and Media Analysis | Cultural Studies | Literature and Literary Theory | 0.07794 | plausible placement |
| 40 | T13245 — Samuel Beckett and Modernism | Literature and Literary Theory | Philosophy | 0.07794 | plausible placement |
| 41 | T13368 — University Challenges and Reforms | Education | Sociology and Political Science | 0.07794 | plausible placement |
| 42 | T12454 — European Political History Analysis | History | Sociology and Political Science | 0.07778 | plausible placement |
| 43 | T14308 — Psychological and Educational Research Studies | Experimental and Cognitive Psychology | Education | 0.07778 | plausible placement |
| 44 | T14131 — Giambattista Vico and Joyce | History and Philosophy of Science | Classics | 0.07619 | unresolved |
| 45 | T12662 — Digitalization and Economic Development in Agriculture | Strategy and Management | Economics and Econometrics | 0.07598 | plausible placement |
| 46 | T12375 — Cuban History and Society | Sociology and Political Science | Cultural Studies | 0.07598 | plausible placement |
| 47 | T13611 — Education, Management, Technology, Human Resources | Information Systems and Management | Organizational Behavior and Human Resource Management | 0.07516 | unresolved |
| 48 | T14301 — Educational methodologies and cognitive development | Developmental and Educational Psychology | Education | 0.07516 | plausible placement |
| 49 | T13749 — Hungarian Social, Economic and Educational Studies | Geography, Planning and Development | Economics and Econometrics | 0.07500 | plausible placement |
| 50 | T13818 — Cultural Studies and Colonialism | Religious studies | Cultural Studies | 0.07500 | placement candidate |

Reproduce from the repository root:

```bash
uv run plumb audit --format json --limit 0 --output .venv/audit-all.json
uv run python scripts/record_audit.py
uv run pytest -q
```

The final command deliberately retains the failing target acceptance assertion.
The audit command's exit 0 only means the computation finished; it does not
mean the scientific acceptance gate passed.

## Metadata placement — GLiNER run, 2026-09-22

The frozen benchmark contains 600 works with existing OpenAlex topic assignments:
364 train, 146 calibration and 90 test. Source, DOI and normalised-title connected
groups are disjoint across partitions. Only title, source and type were provided;
OpenAlex-generated keywords, abstracts, citations and truth were excluded.
The test partition covers 55 of 252 subfields and contains 71 articles but only
one dataset. This is not a representative test of unassigned dataset registries.

The real `fastino/gliner2.5-multi-v1` checkpoint was evaluated locally on MPS,
using all 252 subfield labels in one exclusive classification task. The checkpoint
revision, runtime, all 236 calibration/test predictions and separate reference
metrics are saved in [`place-gliner-evaluation.json`](../data/place-gliner-evaluation.json).

| Reference | Unthresholded test accuracy | Eligible calibration threshold | Test accepted / total | Test coverage | Selective precision |
|---|---:|---|---:|---:|---|
| Primary topic’s subfield | 5/90 (5.56%) | None | 0/90 | 0% | Undefined |
| Any of up to three assigned topic subfields | 11/90 (12.22%) | None | 0/90 | 0% | Undefined |

The threshold was selected only from calibration predictions, requiring at least
20 acceptances and a nominal 95% Wilson lower precision bound ≥90%. No threshold
met that rule under either reference. Zero coverage is an executed finding for
this flat, wide-label baseline; it is not 100% precision and does not establish
that all metadata-only approaches fail. The held-out labels themselves inherit
OpenAlex’s mapping and sink artifacts.

Because the result was weak, an integration check compared the adapter against
GLiNER’s native `classify_text` on the same 252-label calibration example: both
returned Computer Graphics and Computer-Aided Design at probability 0.043716.
The encoded sequence had 2,105 tokens. Three simple synthetic four-choice inputs
were classified correctly. This checks loading/scoring, not benchmark accuracy;
evidence is [`gliner-integration-check.json`](../data/gliner-integration-check.json).
No scoring or label changes were made after observing the test result.

### Kev width and routing probes

The released, pinned Kev-9B checkpoint was run on the existing M4 Max / 64 GB
Mac Studio in BF16 on MPS. All four base-weight shards passed SHA256 verification.
The standard Kev API rounds probabilities to two decimals; the initial probe
stopped when its distribution summed to 0.99. The helper now exposes the original
unrounded head probabilities, and the complete probe below was rerun through
that endpoint. No rounded scores were used for calibration.

| Task | Options | Primary agreement | Any-assigned-topic agreement | Median request seconds |
|---|---:|---:|---:|---:|
| Domain | 4 | 6/12 | 9/12 | 0.615 |
| Field | 26 | 4/12 | 8/12 | 1.257 |
| Subfield, flat | 252 | 1/12 | 4/12 | 8.993 |
| Subfield, hierarchical | Routed | 1/12 | 2/12 | 2.203 |

All rows use the same 12 calibration records. Changing hierarchy level changes
both task granularity and option width, so the first three rows do not isolate
a causal effect of label count. This small probe does not establish a general
accuracy ranking. Request times include the SSH tunnel and runtime/cache effects.
Evidence: [`place-kev-width-probe.json`](../data/place-kev-width-probe.json) and
[`place-kev-routing-probe.json`](../data/place-kev-routing-probe.json).

The bounded warm-start experiment uses hierarchical questions: all 128 exported
training records fit Kev’s native training limits, with at most 625 packed tokens,
and routed requests are faster. The primary probe result was tied and the
any-topic result was worse; this choice is based on feasibility and latency,
not a demonstrated accuracy improvement. Test labels did not select this choice.
The native tokenizer admission evidence is in
[`kev-training-preflight.json`](../data/kev-training-preflight.json).

### Kev warm-start and held-out evaluation

The bounded run completed from the released Kev checkpoint rather than the base
model. It admitted and trained on all 128 requested train records for one epoch:
16 optimizer steps, 44,193 forward tokens, no rejected records and no truncated
records. Training took 996.9 seconds on MPS. The exported checkpoint's immutable
fingerprint is `e8c996169c1440cee5554e2a9e8ea42d0f6c3fa2dcbaf131b61c40316b603812`.
Training evidence is in
[`kev-training-metrics.json`](../data/kev-training-metrics.json).

The trained model was then evaluated once on all 146 calibration and 90 test
records with the preselected hierarchical route and unrounded probabilities.

| Reference | Unthresholded test accuracy | Eligible calibration threshold | Test accepted / total | Test coverage | Selective precision |
|---|---:|---|---:|---:|---|
| Primary topic's subfield | 15/90 (16.67%) | None | 0/90 | 0% | Undefined |
| Any of up to three assigned topic subfields | 29/90 (32.22%) | None | 0/90 | 0% | Undefined |

This improved the unthresholded result over GLiNER on this slice, but it did not
meet the product acceptance rule: no calibration threshold had at least 20
acceptances with a nominal 95% Wilson lower precision bound of 90%. The correct
selective result is abstain-all, not a precision claim. The small training set,
limited test coverage (55 subfields), inherited OpenAlex labels and near absence
of dataset records limit generalisation. The full report, including all
predictions and runtime provenance, is
[`place-kev-evaluation.json`](../data/place-kev-evaluation.json).

## Sink splitting — executed 2026-09-22

Seven seeded samples of 300 assignments each were collected using `topics.id`,
including secondary topic assignments. The primary run uses multilingual E5-small
embeddings, k-means, cosine silhouette over k=2–8, and at least five records per
cluster. Full provenance and representative titles are in
[`sink-splits.json`](../data/sink-splits.json); every sampled work is accounted for
in [`sink-assignments.csv`](../data/sink-assignments.csv).

| Sink | Text usable / sampled | k | Silhouette | Within-cluster coherence | Unsplit coherence |
|---|---:|---:|---:|---:|---:|
| T14423 — Military Technology and Strategies | 299/300 | 4 | 0.1412 | 0.8191 | 0.7859 |
| T10346 — Magnetic confinement fusion research | 300/300 | 5 | 0.0420 | 0.8312 | 0.8181 |
| T13370 — Diverse Scientific and Economic Studies | 300/300 | 8 | 0.0963 | 0.8386 | 0.8205 |
| T12157 — Geochemistry and Geologic Mapping | 299/300 | 2 | 0.0710 | 0.8211 | 0.8138 |
| T10451 — Mycorrhizal Fungi and Plant Interactions | 299/300 | 2 | 0.1385 | 0.8163 | 0.8143 |
| T10895 — Species Distribution and Climate Change | 300/300 | 5 | 0.6781 | 0.9864 | 0.8884 |
| T11367 — Particle accelerators and beam dynamics | 300/300 | 2 | 0.0624 | 0.8215 | 0.8152 |

2,097 of 2,100 assignments have nonempty text; the other three retain explicit
`insufficient_text` reasons. No input required the encoder’s 512-token truncation.
Coherence is the mean pairwise cosine within clusters, weighted by pair count.
E5 cosine similarities naturally have a high baseline; absolute values near 0.8
do not independently demonstrate coherent scientific communities.

### Largest sink: T14423, Military Technology and Strategies

| Proposed cluster | Sampled works | Inspection of representative titles |
|---|---:|---|
| T14423.C01 | 60 | Predominantly Chinese titles across unrelated subjects |
| T14423.C02 | 55 | Predominantly Russian titles across unrelated subjects |
| T14423.C03 | 50 | Mixed Korean, Arabic and Persian titles |
| T14423.C04 | 134 | Predominantly Japanese titles, including dentistry, piglet health and asthma |
| Unassigned | 1 | Empty title and no supplied keywords |

These four groups are inspectable **language-heavy candidate partitions**, not
validated research communities or endorsed replacement taxonomy nodes. The
multilingual model does not eliminate language effects. Their work IDs and
cluster memberships are explicit in the assignment CSV. The observed mixture
raises a bucket-quality question but does not establish that every assignment
in the 20.6M-work topic is wrong.

### Other observations from saved representatives

- T10346 separates fusion engineering, particles/waves, magnetic configurations,
  general plasma and tokamak titles; silhouette is only 0.0420.
- T13370 is dominated by front matter and metadata: contents, author instructions,
  editorial boards, covers, images and meeting minutes. These are document-type
  partitions rather than new scientific subjects.
- T12157 separates a 114-record mapping/data-analysis group and a 185-record
  rocks/deposits/geochemistry group, with silhouette 0.0710. This supports further
  review of the mixture, not a categorical hierarchy correction.
- T10451 isolates 17 generic occurrence downloads from 282 other titles.
- T10895’s unusually strong score is partly a repeated-title artifact: one
  199-record cluster is titled “Occurrence Download”. It does not demonstrate
  that the entire sink splits into five natural communities.
- T11367 separates beam/particle subjects (206) from accelerator design and
  development (94), with silhouette 0.0624.

The lexical comparison is preserved in
[`sink-splits-tfidf.json`](../data/sink-splits-tfidf.json) and
[`sink-assignments-tfidf.csv`](../data/sink-assignments-tfidf.csv). It used only
1,786 of 2,100 assignments, including 121/300 in the largest sink. This concrete
coverage failure prompted the multilingual implementation; no placement test
labels were used to choose it. Both runs are exploratory, sample-level analyses.
