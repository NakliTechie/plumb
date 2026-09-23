[RISK observed]
BLOCKS: The keyword auditor missed the required top-50 target.
I observed T12157 at rank 914.
I retained the original acceptance assertion.
Mitigation: use assigned-paper evidence to investigate the keyword proxy before revising the model.
evidence: [test output](audit-tests.txt), [acceptance definition](spec.md), [ranked scores](../data/audit-scores.csv).

[RESULT verified]
I ran 28 tests after implementation; 27 passed.
The two comparison-topic acceptance tests passed.
The target acceptance test failed.
evidence: `uv run pytest -q`, exit 1; [test output](audit-tests.txt); `tests/test_acceptance.py:17`.

[RESULT verified]
I checked 4,516 unique ranked topic records against the saved audit.
I matched the published top-50 JSON byte-for-byte with a direct CLI export.
I checked that all 50 review records reference the input snapshot hash.
evidence: [artifact checks](audit-artifacts-check.txt), [ranked scores](../data/audit-scores.csv), [top-50 evidence](../data/audit-top50.json).

[RESULT inferred]
I classified five reviewed topics as placement candidates.
I classified 36 as plausible current placements or neighbourhood artifacts.
I left nine unresolved.
These judgments use topic descriptions, keyword overlaps and parent evidence.
They do not measure detection precision or establish independently adjudicated errors.
evidence: [50 individually authored review reasons](audit-review-notes.tsv), [topic snapshot](../data/topics.json), [top-50 evidence](../data/audit-top50.json).

[RESULT observed]
I retrieved ten highly cited primary-topic paper titles for each disputed geochemistry topic.
I observed geology titles under both the Artificial Intelligence and Economics parents.
I observed a mixture of geology and economics titles for T13442.
The selection is not a representative sample.
evidence: [20 paper records with source queries](../data/acceptance-work-samples.json), [interpretation](findings.md#the-known-cases-expose-a-metadata-problem).

[STATUS observed]
Batch A, state: in-progress at scientific verification.
I implemented the CLI, snapshots, exports, scoring, specification and findings table.
I did not build a co-citation graph.
I did not obtain independent human review of the top 50.
I did not start Batch B or Batch C.
evidence: `src/plumb/audit.py:1`, `src/plumb/cli.py:1`, [specification](spec.md), [findings](findings.md#keyword-auditor--executed-2026-09-22).
