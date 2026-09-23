"""An offline keyword-neighbourhood audit; no named acceptance examples here."""
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

LEVELS = ('subfield', 'field', 'domain')
METHOD = 'keyword-jaccard-v1'


class InputError(ValueError):
    pass


def phrase(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def load_snapshot(path):
    raw = Path(path).read_bytes()
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InputError(f'Invalid JSON: {exc}') from exc
    validate_snapshot(document)
    return document, hashlib.sha256(raw).hexdigest()


def validate_snapshot(document):
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int or document['schema_version'] != 1:
        raise InputError('Expected a topic snapshot with schema_version 1')
    topics = document.get('topics')
    if not isinstance(topics, list) or not topics:
        raise InputError('Snapshot must contain a nonempty topics list')
    expected = document.get('topic_count')
    if type(expected) is not int or expected != len(topics):
        raise InputError('Snapshot topic_count does not match its topics list')
    seen = set()
    hierarchy = {}
    for t in topics:
        if not isinstance(t, dict):
            raise InputError('Each topic must be an object')
        tid = t.get('id')
        if not isinstance(tid, str) or not re.fullmatch(r'https://openalex.org/T[0-9]+', tid):
            raise InputError('Each topic needs a full OpenAlex topic id')
        if tid in seen:
            raise InputError(f'Duplicate topic: {tid}')
        seen.add(tid)
        if not isinstance(t.get('display_name'), str) or not t['display_name'].strip():
            raise InputError(f'{tid}: missing display_name')
        keywords = t.get('keywords')
        if not isinstance(keywords, list) or any(not isinstance(v, str) or not phrase(v) for v in keywords):
            raise InputError(f'{tid}: keywords must be a list of nonempty strings')
        for level in LEVELS:
            parent = t.get(level)
            if not isinstance(parent, dict) or any(not isinstance(parent.get(key), str) or not parent[key].strip() for key in ('id', 'display_name')):
                raise InputError(f'{tid}: missing {level} id or display_name')
            if not re.fullmatch(rf'https://openalex.org/{level}s/[0-9]+', parent['id']):
                raise InputError(f'{tid}: invalid {level} id')
        if type(t.get('works_count')) is not int or t['works_count'] < 0:
            raise InputError(f'{tid}: works_count must be a nonnegative integer')
    for t in topics:
        for level in LEVELS:
            parent = t[level]
            ancestors = tuple(t[l]['id'] for l in LEVELS[LEVELS.index(level) + 1:])
            identity = (parent['display_name'], ancestors)
            key = (level, parent['id'])
            if key in hierarchy and hierarchy[key] != identity:
                raise InputError(f'{t["id"]}: inconsistent hierarchy for {parent["id"]}')
            hierarchy[key] = identity


def neighbourhoods(topics, k):
    """Inverted phrase index avoids evaluating pairs with no shared keyword."""
    terms = [{phrase(v) for v in t['keywords']} for t in topics]
    postings = defaultdict(list)
    for i, values in enumerate(terms):
        for value in sorted(values):
            postings[value].append(i)
    for i, values in enumerate(terms):
        overlap = Counter(j for value in sorted(values) for j in postings[value] if j != i)
        candidates = [(j, count / (len(values) + len(terms[j]) - count)) for j, count in overlap.items()]
        candidates.sort(key=lambda p: (-p[1], topics[p[0]]['id']))
        yield [(j, sim, sorted(values & terms[j])) for j, sim in candidates[:k]]


def parent_evidence(topic, neighbours, topics, level):
    weights = defaultdict(list)
    counts = Counter()
    names = {topic[level]['id']: topic[level]['display_name']}
    for j, sim, _ in neighbours:
        parent = topics[j][level]
        weights[parent['id']].append(sim)
        counts[parent['id']] += 1
        names[parent['id']] = parent['display_name']
    total = math.fsum(sim for _, sim, _ in neighbours)
    own = topic[level]['id']
    distribution = [dict(id=pid, name=names[pid], share=math.fsum(weight) / total, count=counts[pid]) for pid, weight in weights.items()]
    distribution.sort(key=lambda d: (-d['share'], d['id'] != own, d['id']))
    if own not in weights:
        distribution.append(dict(id=own, name=names[own], share=0.0, count=0))
    plurality = distribution[0] if total else None
    own_share = next(d['share'] for d in distribution if d['id'] == own)
    return dict(stated_parent=dict(id=own, name=names[own]), stated_share=own_share,
                plurality_parent=plurality, distribution=distribution)


def audit(document, sha256, k=10, level='subfield'):
    if type(k) is not int or not 1 <= k <= 100 or level not in LEVELS:
        raise InputError('k must be 1–100 and level must be subfield, field or domain')
    topics = sorted(document['topics'], key=lambda t: t['id'])
    rows = []
    for topic, neighbours in zip(topics, neighbourhoods(topics, k)):
        parents = {l: parent_evidence(topic, neighbours, topics, l) for l in LEVELS}
        selected = parents[level]
        alternative = selected['plurality_parent']
        strength = math.fsum(sim for _, sim, _ in neighbours) / k
        margin = max(0.0, alternative['share'] - selected['stated_share']) if alternative else 0.0
        if len(neighbours) < 3 or (margin > 0 and alternative['count'] < 2):
            status, score = 'insufficient_evidence', 0.0
        elif margin > 0:
            status, score = 'review', margin * strength
        else:
            status, score = 'consistent', 0.0
        rows.append(dict(topic_id=topic['id'].rsplit('/', 1)[-1], topic=topic['display_name'],
                         works_count=topic['works_count'], status=status, score=score,
                         margin=margin, strength=strength, neighbour_count=len(neighbours),
                         parents=parents, keywords=topic['keywords'],
                         neighbours=[dict(topic_id=topics[j]['id'].rsplit('/', 1)[-1],
                                          topic=topics[j]['display_name'], similarity=sim,
                                          shared_keywords=shared,
                                          parents={l: topics[j][l] for l in LEVELS})
                                     for j, sim, shared in neighbours]))
    rows.sort(key=lambda r: (-r['score'], r['topic_id']))
    for rank, row in enumerate(rows, 1):
        row['rank'] = rank
    counts = Counter(row['status'] for row in rows)
    return dict(schema_version=1, method=METHOD,
                input=dict(sha256=sha256, source=document.get('source'), retrieved_at=document.get('retrieved_at'), topic_count=len(topics)),
                parameters=dict(k=k, level=level, minimum_neighbours=3, minimum_alternative_support=2),
                summary={status: counts[status] for status in ('review', 'consistent', 'insufficient_evidence')},
                rows=rows)
