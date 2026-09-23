"""Bounded public-work sampling and leakage-resistant benchmark partitions."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import urllib.parse

from plumb.audit import InputError, load_snapshot
from plumb.pull import BASE, FetchError, get
from plumb.storage import atomic_text

PARTITIONS = ('train', 'calibration', 'test')


def save_json(path, value):
    with atomic_text(path) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def read_json(path):
    raw = Path(path).read_bytes()
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InputError(f'Invalid JSON in {path}: {exc}') from exc
    return data, hashlib.sha256(raw).hexdigest()


def short_id(value):
    return value.rsplit('/', 1)[-1]


def taxonomy(path):
    snapshot, digest = load_snapshot(path)
    topics = {short_id(t['id']): t for t in snapshot['topics']}
    labels = {level: {} for level in ('domain', 'field', 'subfield')}
    for t in topics.values():
        for level in labels:
            p = t[level]
            labels[level][short_id(p['id'])] = p['display_name']
    return snapshot, topics, labels, digest


def sample_works(filter_text, size, seed):
    if not 1 <= size <= 10000:
        raise InputError('sample-size must be 1–10000')
    rows, urls, seen = [], [], set()
    available = None
    for page in range(1, math.ceil(size / 200) + 1):
        query = urllib.parse.urlencode(dict(filter=filter_text, sample=size, seed=seed,
                                           page=page, **{'per-page': min(200, size),
                                           'select': 'id,doi,title,type,primary_location,primary_topic,topics'}))
        url = f'{BASE}/works?{query}'
        payload = get(url)
        if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
            raise FetchError('Invalid works response; no sample was saved')
        urls.append(url)
        available = payload.get('meta', {}).get('count', available)
        for work in payload['results']:
            if work['id'] in seen:
                raise FetchError('Duplicate work in seeded pagination; retry the sample')
            seen.add(work['id'])
            rows.append(work)
        if len(payload['results']) < min(200, size) or len(rows) >= size:
            break
    return rows[:size], dict(urls=urls, requested=size, returned=len(rows[:size]), api_count=available)


def normalise_work(work, known_topics):
    location = work.get('primary_location') or {}
    source = location.get('source') or {}
    primary = (work.get('primary_topic') or {}).get('id')
    ids = [short_id(t['id']) for t in (work.get('topics') or [])[:3] if t.get('id')]
    primary = short_id(primary) if primary else None
    if primary and primary not in ids:
        ids.insert(0, primary)
        ids = ids[:3]
    if (primary and primary not in known_topics) or any(tid not in known_topics for tid in ids):
        raise InputError(f"{work['id']}: assigned topic is absent from the frozen taxonomy")
    return dict(id=work['id'], doi=work.get('doi'), source_id=source.get('id'),
                metadata=dict(title=work.get('title') or '', source=source.get('display_name') or '',
                              type=work.get('type') or '', keywords=[]),
                truth=dict(primary_topic_id=primary, topic_ids=[tid for tid in ids if tid in known_topics]))


def assign_partitions(records, seed=42):
    """Union connected source/duplicate families before assigning any partition."""
    parent = list(range(len(records)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    keys = {}
    for i, record in enumerate(records):
        metadata = record['metadata']
        title = ' '.join(re.findall(r'\w+', metadata['title'].casefold()))
        family = [('id', record['id'])]
        if record.get('source_id'):
            family.append(('source', record['source_id']))
        if record.get('doi'):
            family.append(('doi', record['doi'].casefold()))
        if title:
            family.append(('title', title))
        for key in family:
            if key in keys:
                parent[root(i)] = root(keys[key])
            keys[key] = i
    groups = {}
    for i, record in enumerate(records):
        groups.setdefault(root(i), []).append(record['id'])
    for i, record in enumerate(records):
        group = min(groups[root(i)])
        digest = hashlib.sha256(f'{seed}:{group}'.encode()).hexdigest()
        bucket = int(digest[:8], 16) / 2**32
        record['partition'] = 'train' if bucket < .6 else 'calibration' if bucket < .8 else 'test'
        record['split_group'] = digest
    return records


def collect_place(topics_path, size=600, seed=42):
    _, known, _, digest = taxonomy(topics_path)
    raw, sampling = sample_works('primary_topic.id:!null', size, seed)
    records = [normalise_work(work, known) for work in raw]
    exclusions = dict(missing_primary_topic=sum(not r['truth']['primary_topic_id'] for r in records))
    records = [r for r in records if r['truth']['primary_topic_id']]
    assign_partitions(records, seed)
    return dict(schema_version=1, kind='place_dataset', taxonomy_sha256=digest,
                retrieved_at=datetime.now(timezone.utc).isoformat(), seed=seed, sampling=sampling,
                feature_policy='title, source, type; OpenAlex inferred keywords excluded',
                split_policy='source/duplicate connected groups, hash 60/20/20',
                exclusions=exclusions, partition_counts=dict(Counter(r['partition'] for r in records)), records=records)


def collect_sinks(topics_path, size=300, seed=42):
    snapshot, known, _, digest = taxonomy(topics_path)
    median = statistics.median(t['works_count'] for t in snapshot['topics'])
    sinks = sorted((t for t in snapshot['topics'] if t['works_count'] > 20 * median), key=lambda t: (-t['works_count'], t['id']))
    samples = []
    import sys
    for t in sinks:
        tid = short_id(t['id'])
        print(f'Sampling {tid}: {t["display_name"]}', file=sys.stderr, flush=True)
        raw, sampling = sample_works(f'topics.id:{tid}', size, seed)
        samples.append(dict(topic_id=tid, topic=t['display_name'], works_count=t['works_count'],
                            sampling=sampling, records=[normalise_work(w, known) for w in raw]))
    return dict(schema_version=1, kind='sink_samples', taxonomy_sha256=digest,
                retrieved_at=datetime.now(timezone.utc).isoformat(), seed=seed,
                threshold_multiple=20, median_topic_works=median, sinks=samples)


def validate_record(record, *, labelled=False):
    if not isinstance(record, dict) or not isinstance(record.get('id'), str) or not record['id'].strip():
        raise InputError('Each work needs a nonempty string id')
    m = record.get('metadata')
    if not isinstance(m, dict) or any(not isinstance(m.get(k), str) for k in ('title', 'source', 'type')):
        raise InputError(f"{record['id']}: metadata requires string title, source and type")
    if not isinstance(m.get('keywords', []), list) or any(not isinstance(k, str) for k in m.get('keywords', [])):
        raise InputError(f"{record['id']}: keywords must be a string list")
    if labelled:
        truth = record.get('truth')
        if not isinstance(truth, dict) or not isinstance(truth.get('primary_topic_id'), str) or not isinstance(truth.get('topic_ids'), list):
            raise InputError(f"{record['id']}: benchmark truth is missing")
        if any(not isinstance(t, str) for t in truth['topic_ids']) or truth['primary_topic_id'] not in truth['topic_ids'] or not 1 <= len(truth['topic_ids']) <= 3:
            raise InputError(f"{record['id']}: expected primary topic and up to three truth topics")
        if record.get('partition') not in PARTITIONS or not isinstance(record.get('split_group'), str):
            raise InputError(f"{record['id']}: invalid benchmark partition/group")


def load_place(path, taxonomy_sha256=None):
    doc, digest = read_json(path)
    if not isinstance(doc, dict) or doc.get('schema_version') != 1 or doc.get('kind') != 'place_dataset' or not isinstance(doc.get('records'), list) or not doc['records']:
        raise InputError('Expected a nonempty place_dataset; run plumb pull --works place')
    if taxonomy_sha256 and doc.get('taxonomy_sha256') != taxonomy_sha256:
        raise InputError('Dataset taxonomy hash differs from --topics')
    ids, groups = set(), {}
    for r in doc['records']:
        validate_record(r, labelled=True)
        if r['id'] in ids:
            raise InputError(f"Duplicate work id: {r['id']}")
        ids.add(r['id'])
        for key in [('group', r['split_group']), ('source', r.get('source_id')), ('doi', (r.get('doi') or '').casefold()),
                    ('title', ' '.join(re.findall(r'\w+', r['metadata']['title'].casefold())))]:
            if not key[1]:
                continue
            if key in groups and groups[key] != r['partition']:
                raise InputError(f'Partition leakage across {key[0]} groups')
            groups[key] = r['partition']
    return doc, digest


def load_records(path):
    raw = Path(path).read_bytes()
    try:
        records = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    except (ValueError, UnicodeDecodeError) as exc:
        raise InputError(f'Expected input JSONL: {exc}') from exc
    if not records:
        raise InputError('Input JSONL is empty')
    seen = set()
    for r in records:
        validate_record(r)
        if r['id'] in seen:
            raise InputError(f"Duplicate work id: {r['id']}")
        seen.add(r['id'])
    return records, hashlib.sha256(raw).hexdigest()


def feature_text(metadata):
    """Strict allowlist: this function never receives the truth-bearing record."""
    return '\n'.join([f"Title: {metadata['title'][:2000]}", f"Source: {metadata['source'][:300]}",
                      f"Type: {metadata['type'][:100]}",
                      'Keywords: ' + '; '.join(k[:100] for k in metadata.get('keywords', [])[:20])])
