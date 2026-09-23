"""Metadata classification, frozen-threshold evaluation and Kev training export."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

from plumb.audit import InputError
from plumb.datasets import feature_text, save_json, short_id
from plumb.storage import atomic_text

RELEASED_KEV = 'jaredpalmer/kev-9b@2629c06a5aeb0feb3b9783bafed17ed8f39ecf5c'
FEATURE_POLICY = 'title-source-type-supplied-keywords-v1'


def children(topics, level, parent_id):
    parent_level = 'domain' if level == 'field' else 'field'
    return {short_id(t[level]['id']): t[level]['display_name'] for t in topics.values()
            if short_id(t[parent_level]['id']) == parent_id}


def ranked(values, labels):
    return [dict(id=key, name=labels[key], probability=values[key])
            for key in sorted(values, key=lambda key: (-values[key], key))]


def predict(record, backend, topics, labels, strategy='flat', level='subfield'):
    m = record['metadata']
    row = dict(work_id=record['id'], title=m['title'], type=m['type'], status='predicted',
               prediction=None, confidence=0.0, candidates=[], route=[])
    if not (m['title'].strip() or m['source'].strip() or any(k.strip() for k in m.get('keywords', []))):
        row['status'] = 'insufficient_metadata'
        return row
    text = feature_text(m)
    if strategy == 'flat':
        choices = ranked(backend.probabilities(text, labels[level]), labels[level])
        confidence = choices[0]['probability']
    elif strategy == 'hierarchical':
        probability = 1.0
        selected = None
        for current in ('domain', 'field', 'subfield'):
            options = labels['domain'] if current == 'domain' else children(topics, current, selected)
            if not options:
                raise InputError('Taxonomy route has no children')
            values = {next(iter(options)): 1.0} if len(options) == 1 else backend.probabilities(text, options)
            choices = ranked(values, options)
            selected = choices[0]['id']
            row['route'].append(dict(level=current, id=selected, probability=choices[0]['probability']))
            for choice in choices:
                choice['probability'] *= probability
            probability = choices[0]['probability']
            if current == level:
                break
        confidence = probability
    else:
        raise InputError('Unknown placement strategy')
    row.update(prediction=choices[0]['id'], confidence=confidence, candidates=choices[:3])
    return row


def labelled(row, record, topics, level):
    truth = record['truth']
    ids = truth['topic_ids']
    if truth['primary_topic_id'] not in topics or any(t not in topics for t in ids):
        raise InputError('Benchmark truth contains a topic absent from the frozen taxonomy')
    primary = short_id(topics[truth['primary_topic_id']][level]['id'])
    alternatives = sorted({short_id(topics[tid][level]['id']) for tid in ids})
    return {**row, 'partition': record['partition'], 'true_primary': primary, 'true_any_topic': alternatives,
            'correct_primary': row['prediction'] == primary,
            'correct_any_topic': row['prediction'] in alternatives,
            'primary_in_top3_predictions': primary in [c['id'] for c in row['candidates']]}


def wilson(successes, total, z=1.959963984540054):
    if not total:
        return [None, None]
    p = successes / total
    denominator = 1 + z*z / total
    center = (p + z*z / (2*total)) / denominator
    radius = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return [max(0.0, center-radius), min(1.0, center+radius)]


def threshold(calibration, reference, target=.9, minimum=20):
    rows = sorted((r for r in calibration if r['status'] == 'predicted'), key=lambda r: -r['confidence'])
    best = None
    correct = 0
    for i, row in enumerate(rows):
        correct += int(row['correct_' + reference])
        # Never split a tied confidence group to manufacture a better threshold.
        if i + 1 < len(rows) and rows[i+1]['confidence'] == row['confidence']:
            continue
        count = i + 1
        interval = wilson(correct, count)
        if count >= minimum and interval[0] >= target:
            best = dict(threshold=row['confidence'], accepted=count, correct=correct,
                        precision=correct/count, precision_interval=interval,
                        coverage=count/len(calibration))
    return best or dict(threshold=None, accepted=0, correct=0, precision=None,
                        precision_interval=[None, None], coverage=0.0)


def selective_metrics(rows, cutoff, reference):
    accepted = [r for r in rows if r['status'] == 'predicted' and cutoff is not None and r['confidence'] >= cutoff]
    correct = sum(r['correct_' + reference] for r in accepted)
    return dict(total=len(rows), accepted=len(accepted), correct=correct,
                coverage=len(accepted)/len(rows) if rows else 0.0,
                precision=correct/len(accepted) if accepted else None,
                precision_interval=wilson(correct, len(accepted)))


def evaluate(dataset, input_digest, backend, topics, labels, taxonomy_digest,
             strategy='flat', target=.9, minimum=20):
    partitions = {p: [r for r in dataset['records'] if r['partition'] == p] for p in ('train', 'calibration', 'test')}
    if not partitions['calibration'] or not partitions['test']:
        raise InputError('Evaluation requires nonempty calibration and test partitions; collect a larger sample')
    for r in dataset['records']:
        if any(tid not in topics for tid in r['truth']['topic_ids']):
            raise InputError('Dataset truth is absent from the frozen taxonomy')
    rows = []
    selected = partitions['calibration'] + partitions['test']
    for i, record in enumerate(selected, 1):
        row = labelled(predict(record, backend, topics, labels, strategy), record, topics, 'subfield')
        rows.append(row)
        if i == 1 or i % 20 == 0 or i == len(selected):
            print(f'place {i}/{len(selected)}', file=sys.stderr, flush=True)
    cal = [r for r in rows if r['partition'] == 'calibration']
    test = [r for r in rows if r['partition'] == 'test']
    results = {}
    for reference in ('primary', 'any_topic'):
        fitted = threshold(cal, reference, target, minimum)
        measured = selective_metrics(test, fitted['threshold'], reference)
        results[reference] = dict(calibration=fitted, test=measured,
            status='abstain_all' if fitted['threshold'] is None else
                   'no_test_acceptances' if not measured['accepted'] else
                   'target_met_on_test' if measured['precision'] >= target else 'target_not_met_on_test',
            unthresholded_test_accuracy=sum(r['correct_'+reference] for r in test)/len(test),
            by_type={kind: selective_metrics([r for r in test if r['type'] == kind], fitted['threshold'], reference)
                     for kind in sorted({r['type'] for r in test})})
    return dict(schema_version=1, kind='place_evaluation', input_sha256=input_digest,
                taxonomy_sha256=taxonomy_digest, model=backend.identity, strategy=strategy,
                feature_policy=FEATURE_POLICY, level='subfield',
                parameters=dict(target_precision=target, minimum_calibration_acceptances=minimum,
                                threshold_rule='max coverage with 95% Wilson lower bound >= target'),
                partition_counts={p: len(v) for p, v in partitions.items()},
                label_counts=dict(available=len(labels['subfield']), train=len({short_id(topics[r['truth']['primary_topic_id']]['subfield']['id']) for r in partitions['train']}),
                                  calibration=len({r['true_primary'] for r in cal}), test=len({r['true_primary'] for r in test})),
                results=results, rows=rows)


def apply_calibration(rows, report, model, strategy, taxonomy_digest, reference):
    if not isinstance(report, dict) or report.get('kind') != 'place_evaluation' or report.get('schema_version') != 1:
        raise InputError('Calibration file must be a place_evaluation report')
    for key, expected in [('model', model), ('strategy', strategy), ('taxonomy_sha256', taxonomy_digest), ('feature_policy', FEATURE_POLICY), ('level', 'subfield')]:
        if report.get(key) != expected:
            raise InputError(f'Calibration {key} differs from this prediction run')
    try:
        cutoff = report['results'][reference]['calibration']['threshold']
    except (KeyError, TypeError) as exc:
        raise InputError('Calibration report lacks the selected reference threshold') from exc
    if cutoff is not None and (type(cutoff) not in (float, int) or not math.isfinite(cutoff) or not 0 <= cutoff <= 1):
        raise InputError('Calibration threshold is invalid')
    for row in rows:
        if row['status'] == 'predicted':
            row['status'] = 'accepted' if cutoff is not None and row['confidence'] >= cutoff else 'abstain'
    return rows


def width_probe(dataset, digest, backend, topics, labels, taxonomy_digest, limit=12):
    records = sorted((r for r in dataset['records'] if r['partition'] == 'calibration'), key=lambda r: r['id'])[:limit]
    if not records:
        raise InputError('Option-width probe requires calibration records')
    rows, summary = [], {}
    for level in ('domain', 'field', 'subfield'):
        measurements = []
        for record in records:
            start = time.perf_counter()
            row = labelled(predict(record, backend, topics, labels, level=level), record, topics, level)
            row.update(level=level, option_count=len(labels[level]), elapsed_seconds=time.perf_counter()-start)
            rows.append(row)
            measurements.append(row)
            print(f'probe {level}: {len(measurements)}/{len(records)}', file=sys.stderr, flush=True)
        summary[level] = dict(option_count=len(labels[level]), evaluated=len(records),
                              primary_accuracy=sum(r['correct_primary'] for r in measurements)/len(records),
                              any_topic_accuracy=sum(r['correct_any_topic'] for r in measurements)/len(records),
                              median_seconds=statistics.median(r['elapsed_seconds'] for r in measurements))
    return dict(schema_version=1, kind='place_width_probe', input_sha256=digest, taxonomy_sha256=taxonomy_digest,
                model=backend.identity, partition='calibration', summary=summary, rows=rows,
                limitation='Small exploratory probe; latency includes cache effects; no test labels used')


def export_training(dataset, digest, topics, labels, taxonomy_digest, directory, strategy='hierarchical', limit=128):
    records = sorted((r for r in dataset['records'] if r['partition'] == 'train'),
                     key=lambda r: hashlib.sha256(r['id'].encode()).hexdigest())
    if limit:
        records = records[:limit]
    if not records:
        raise InputError('No train records available for export')
    output = Path(directory)
    requests = []
    for r in records:
        t = topics.get(r['truth']['primary_topic_id'])
        if not t:
            raise InputError('Training truth is absent from taxonomy')
        questions = {}
        for level in (('domain', 'field', 'subfield') if strategy == 'hierarchical' else ('subfield',)):
            if strategy == 'flat' or level == 'domain':
                options = labels[level]
            else:
                parent_level = 'domain' if level == 'field' else 'field'
                options = children(topics, level, short_id(t[parent_level]['id']))
            questions[level] = dict(type='choice', instructions='Choose the research subject that best describes this record using its metadata.',
                                    criteria=dict(sorted(options.items())), label=short_id(t[level]['id']))
        requests.append(dict(id=r['id'], state=feature_text(r['metadata']), questions=questions))
    payload = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in requests)
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    manifest = dict(schema_version=1, kind='kev_training_export', input_sha256=digest, taxonomy_sha256=taxonomy_digest,
                    strategy=strategy, feature_policy=FEATURE_POLICY, partition='train', records=len(requests),
                    train_sha256=fingerprint, checkpoint=RELEASED_KEV, base='Qwen/Qwen3.5-9B-Base',
                    recipe=dict(epochs=1, learning_rate=2e-5, batch=1, accumulation=8, checkpointing=True),
                    record_ids=[r['id'] for r in records])
    if (output/'manifest.json').exists():
        old = json.loads((output/'manifest.json').read_text())
        if old != manifest:
            raise InputError('Training export directory belongs to a different run; choose a new directory')
    with atomic_text(output/'train.jsonl') as stream:
        stream.write(payload)
    save_json(output/'manifest.json', manifest)
    return manifest
