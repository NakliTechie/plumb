"""Render the saved audit and separately authored review into reproducible artifacts.

Run after: plumb audit --format json --limit 0 --output .venv/audit-all.json
The review judgments are human-readable agent assessments, never scorer outputs.
"""
import csv
import hashlib
import json
from pathlib import Path

from plumb.storage import atomic_text

ROOT = Path(__file__).resolve().parents[1]
result = json.loads((ROOT / '.venv/audit-all.json').read_text())
if result['method'] != 'keyword-jaccard-v1' or result['parameters'] != dict(k=10, level='subfield', minimum_neighbours=3, minimum_alternative_support=2):
    raise SystemExit('This review covers only the default keyword-jaccard-v1 audit')
source_hash = hashlib.sha256((ROOT / 'data/topics.json').read_bytes()).hexdigest()
if result['input']['sha256'] != source_hash:
    raise SystemExit('Snapshot hash differs from the saved audit; rerun the audit first')
if len(result['rows']) != result['input']['topic_count']:
    raise SystemExit('Expected all audit rows; rerun with --limit 0')
with (ROOT / 'docs/audit-review-notes.tsv').open() as stream:
    notes = list(csv.DictReader(stream, delimiter='\t'))
review = {row['topic_id']: row for row in notes}
top = result['rows'][:50]
if len(notes) != 50 or set(review) != {row['topic_id'] for row in top}:
    raise SystemExit('Review must cover the current top 50 exactly once; review changed rows before rendering')
if any(row.get('input_sha256') != source_hash for row in notes):
    raise SystemExit('Review belongs to a different snapshot; review the new metadata before rendering')
classes = ('placement_candidate', 'plausible_placement', 'unresolved')
if any(row['judgment'] not in classes or not row['reason'] for row in notes):
    raise SystemExit('Review needs a recognized judgment and reason for every row')
counts = {label: sum(r['judgment'] == label for r in notes) for label in classes}
with atomic_text(ROOT / 'data/audit-top50.json') as stream:
    json.dump({**result, 'rows': top, 'output': dict(limit=50, total_rows=len(result['rows']), truncated=True)}, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
with atomic_text(ROOT / 'data/audit-scores.csv') as stream:
    writer = csv.writer(stream)
    writer.writerow(['rank', 'topic_id', 'topic', 'score', 'status', 'stated_parent', 'stated_share', 'plurality_parent', 'plurality_share', 'neighbour_count', 'input_sha256'])
    for row in result['rows']:
        parent = row['parents'][result['parameters']['level']]
        alt = parent['plurality_parent']
        writer.writerow([row['rank'], row['topic_id'], row['topic'], row['score'], row['status'],
                         parent['stated_parent']['name'], parent['stated_share'],
                         alt['name'] if alt else '', alt['share'] if alt else 0,
                         row['neighbour_count'], source_hash])
by_id = {row['topic_id']: row for row in result['rows']}
section = '''## Keyword auditor — executed 2026-09-22

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

'''
summary = result['summary']
section += f"The run evaluated {len(result['rows']):,} topics: {summary['review']:,} `review`, {summary['consistent']:,} `consistent`, and {summary['insufficient_evidence']:,} `insufficient_evidence`.\n"
section += '''These are heuristic statuses. A `consistent` row is agreement with nearby
metadata, not evidence that its assigned papers belong under its parent.

Snapshot SHA-256: `''' + source_hash + '''`.

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

'''
section += f"I read all 50 topics' names, descriptions, keywords, parent shares and neighbour evidence. The agent review marked **{counts['placement_candidate']} placement candidates, {counts['plausible_placement']} plausible current placements / neighbourhood artifacts, and {counts['unresolved']} unresolved cases**.\n"
section += '''These are metadata-based judgments by the same agent that implemented the tool.
They are not independent human adjudication or confirmed errors. I did not sample
papers for these 50 rows. Generic humanities and education vocabulary dominates
the leading results; method-versus-application boundaries also generate flags.
The five candidates warrant paper-level review before proposing moves.

The table records the scorer's proposed plurality, which is not an endorsed new
parent. The reason for each judgment is in the linked review TSV.

| Rank | Topic | Current subfield | Neighbour plurality | Score | Agent review |
|---|---|---|---|---:|---|
'''
def clean(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')
for row in top:
    parents = row['parents']['subfield']
    label = review[row['topic_id']]['judgment'].replace('_', ' ')
    section += '| ' + ' | '.join(map(clean, [row['rank'], f"{row['topic_id']} — {row['topic']}", parents['stated_parent']['name'], parents['plurality_parent']['name'], f"{row['score']:.5f}", label])) + ' |\n'
section += '''
Reproduce from the repository root:

```bash
uv run plumb audit --format json --limit 0 --output .venv/audit-all.json
uv run python scripts/record_audit.py
uv run pytest -q
```

The final command deliberately retains the failing target acceptance assertion.
The audit command's exit 0 only means the computation finished; it does not
mean the scientific acceptance gate passed.
'''
path = ROOT / 'docs/findings.md'
prior = path.read_text().split('## Keyword auditor — executed 2026-09-22')[0].rstrip()
with atomic_text(path) as stream:
    stream.write(prior + '\n\n' + section)
print(json.dumps(dict(review_counts=counts, input_sha256=source_hash, reviewed=len(notes), ranked=len(result['rows']))))
