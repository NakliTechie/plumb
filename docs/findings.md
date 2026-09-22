# Findings — OpenAlex topic coverage, pulled 2026-09-22

All numbers from the public API, no key. Reproduce with `python -m plumb.pull`
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

## The borrowed layer is where placement fails

| Topic | Works | Subfield / field / domain |
|---|---|---|
| Geochemistry and Geologic Mapping | 3,432,384 | **Artificial Intelligence / Computer Science** / Physical Sciences |
| Geochemistry and Elemental Analysis | 75,613 | Geochemistry and Petrology / Earth and Planetary Sciences |
| Groundwater and Isotope Geochemistry | 67,454 | Geochemistry and Petrology / Earth and Planetary Sciences |
| Geochemistry and Geochronology of Asian Mineral Deposits | 24,458 | **Economics and Econometrics / Economics** |

Same family, four different answers, two of them wrong. The citation clusters
look sound; the ASJC layer above them is where the errors live — consistent with
the leaves being intrinsic and the hierarchy borrowed. `plumb audit` is the
mechanical version of reading this table.

## Topic metadata is uniform

All 4,516 topics carry the same `created_date` (2024-01) and the same
`updated_date` — bulk-refreshed, never individually evolved. 4,486 of 4,516
report siblings, and siblings are "other topics in the same subfield" — the
hierarchy read sideways, not a relation between topics. There is no
knowledge-map edge in the public taxonomy.
