"""CLI wiring and bounded presentation for placement and sink splitting."""
import csv
import json
from pathlib import Path
import sys

from plumb.audit import InputError
from plumb.datasets import (load_place, load_records, read_json, taxonomy, save_json)
from plumb.storage import atomic_text


def add_parsers(sub, integer):
    place = sub.add_parser('place', help='classify metadata, evaluate selective coverage, or prepare Kev training')
    mode = place.add_mutually_exclusive_group()
    mode.add_argument('--evaluate', action='store_true', help='calibrate abstention on calibration records and measure held-out test records')
    mode.add_argument('--probe', action='store_true', help='probe 4/26/252 option widths using calibration records only')
    mode.add_argument('--export-training', type=Path, metavar='DIRECTORY', help='export train-only native Kev JSONL and a provenance manifest')
    place.add_argument('--input', type=Path, help='prediction JSONL, or a benchmark JSON for evaluate/probe/export')
    place.add_argument('--topics', type=Path, default=Path('data/topics.json'))
    place.add_argument('--backend', choices=('gliner', 'kev'), default='gliner')
    place.add_argument('--model', help='GLiNER model id, or the exact expected Kev checkpoint name')
    place.add_argument('--revision', help='GLiNER checkpoint revision; resolved and recorded if omitted')
    place.add_argument('--device', choices=('cpu', 'mps', 'cuda'), default='cpu')
    place.add_argument('--kev-url', default='http://127.0.0.1:8009')
    place.add_argument('--cache', type=Path, default=Path('models/prediction-cache'))
    place.add_argument('--strategy', choices=('flat', 'hierarchical'), default='flat')
    place.add_argument('--level', choices=('domain', 'field', 'subfield'), default='subfield')
    place.add_argument('--calibration', type=Path, help='evaluation JSON whose model/method matches this prediction run')
    place.add_argument('--reference', choices=('primary', 'any_topic'), default='primary')
    place.add_argument('--probe-size', type=integer(1, 200), default=12)
    place.add_argument('--train-limit', type=integer(0), default=128, help='maximum train records to export; 0 means all')
    split = sub.add_parser('split', help='propose sample-level partitions of oversized topics')
    split.add_argument('--input', type=Path, default=Path('data/sink-samples.json'))
    split.add_argument('--topics', type=Path, default=Path('data/topics.json'))
    split.add_argument('--topic', help='restrict output to this sampled topic ID')
    split.add_argument('--max-clusters', type=integer(2, 20), default=8)
    split.add_argument('--minimum-cluster', type=integer(2), default=5)
    split.add_argument('--representation', choices=('multilingual-e5', 'tfidf'), default='multilingual-e5')
    split.add_argument('--device', choices=('cpu', 'mps', 'cuda'), default='cpu')
    split.add_argument('--cache', type=Path, default=Path('models/embedding-cache'))
    split.add_argument('--assignments', type=Path, help='write all proposed sample assignments to CSV')
    for p in (place, split):
        p.add_argument('--format', choices=('table', 'json', 'csv'), default='table')
        p.add_argument('--output', type=Path, help='atomic file output; default stdout')
        p.add_argument('--limit', type=integer(0), default=20, help='maximum presented rows/members; 0 means all (computation always uses the full input)')


def guard_paths(inputs, outputs):
    inputs = {p.resolve() for p in inputs if p is not None}
    outputs = [p.resolve() for p in outputs if p is not None]
    if inputs.intersection(outputs) or len(outputs) != len(set(outputs)):
        raise InputError('Output paths must be distinct from inputs and from each other')


def build_backend(args):
    from plumb.backends import CachedBackend, GlinerBackend, KevBackend
    backend = (GlinerBackend(args.model or 'fastino/gliner2.5-multi-v1', args.revision, args.device)
               if args.backend == 'gliner' else KevBackend(args.kev_url, args.model))
    return CachedBackend(backend, None if args.probe else args.cache)


def place_command(args):
    from plumb import place
    _, topics, labels, digest = taxonomy(args.topics)
    source = args.input or Path('data/place-dataset.json')
    exports = [args.export_training/'train.jsonl', args.export_training/'manifest.json'] if args.export_training else []
    guard_paths([source, args.topics, args.calibration], [args.output, *exports])
    if args.level != 'subfield' and (args.evaluate or args.probe or args.export_training or args.calibration):
        raise InputError('Evaluation, probes, training exports and calibrated prediction use the subfield target')
    if args.evaluate or args.probe or args.export_training:
        data, input_digest = load_place(source, digest)
        if args.export_training:
            result = place.export_training(data, input_digest, topics, labels, digest, args.export_training,
                                           strategy=args.strategy, limit=args.train_limit)
            result['export_directory'] = str(args.export_training)
            return result
        backend = build_backend(args)
        if args.probe:
            return place.width_probe(data, input_digest, backend, topics, labels, digest, args.probe_size)
        return place.evaluate(data, input_digest, backend, topics, labels, digest, args.strategy)
    if args.input is None:
        raise InputError('Provide --input records.jsonl, or use --evaluate for data/place-dataset.json')
    records, input_digest = load_records(source)
    backend = build_backend(args)
    calibration = read_json(args.calibration)[0] if args.calibration else None
    # Fail before expensive inference if a calibration belongs to another model.
    if calibration is not None:
        place.apply_calibration([], calibration, backend.identity, args.strategy, digest, args.reference)
    rows = [place.predict(r, backend, topics, labels, args.strategy, args.level) for r in records]
    if calibration is not None:
        place.apply_calibration(rows, calibration, backend.identity, args.strategy, digest, args.reference)
    else:
        for r in rows:
            if r['status'] == 'predicted':
                r['status'] = 'review_uncalibrated'
    return dict(schema_version=1, kind='place_predictions', input_sha256=input_digest, taxonomy_sha256=digest,
                model=backend.identity, strategy=args.strategy, level=args.level,
                feature_policy=place.FEATURE_POLICY, calibrated=calibration is not None,
                reference=args.reference if calibration else None, rows=rows)


def split_command(args):
    from plumb.split import load_samples, split_samples
    _, _, _, digest = taxonomy(args.topics)
    guard_paths([args.input, args.topics], [args.output, args.assignments])
    data, input_digest = load_samples(args.input, digest)
    encoder = None
    if args.representation == 'multilingual-e5':
        from plumb.embeddings import MultilingualEncoder
        encoder = MultilingualEncoder(device=args.device, cache=args.cache)
    result = split_samples(data, input_digest, args.max_clusters, args.minimum_cluster, args.topic, encoder)
    if args.assignments:
        with atomic_text(args.assignments) as stream:
            writer = csv.DictWriter(stream, fieldnames=['work_id', 'title', 'original_topic_id', 'cluster_id', 'action', 'reason', 'cosine_to_centroid'])
            writer.writeheader()
            for row in result['rows']:
                writer.writerows(row['assignments'])
    return result


def presentation(result, limit):
    # Copy only the containers we trim; leave the computed result intact.
    result = dict(result)
    if 'rows' not in result:
        return result
    rows = result['rows']
    result['output'] = dict(limit=limit, total_rows=len(rows), truncated=bool(limit and len(rows)>limit))
    result['rows'] = [dict(row) for row in (rows[:limit] if limit else rows)]
    for row in result['rows']:
        if 'assignments' in row:
            members = row['assignments']
            row['assignment_count'] = len(members)
            row['assignments_truncated'] = bool(limit and len(members)>limit)
            row['assignments'] = members[:limit] if limit else members
    return result


def write_result(result, fmt, stream):
    if fmt == 'json':
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        return
    rows = result.get('rows', [])
    if fmt == 'csv':
        if result['kind'] == 'sink_splits':
            fields = ['topic_id', 'topic', 'sampled', 'usable', 'status', 'chosen_k', 'silhouette', 'coherence', 'baseline_coherence', 'reason', 'clusters']
        else:
            fields = list(dict.fromkeys(key for row in rows for key in row))
        if not fields:
            fields, rows = list(result), [result]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items() if k in fields})
        return
    if result['kind'] == 'place_evaluation':
        print(f"Held-out evaluation · {result['partition_counts']} · {result['model']['backend']} · {result['strategy']}", file=stream)
        for reference, measured in result['results'].items():
            test = measured['test']
            precision = f"{test['precision']:.1%}" if test['precision'] is not None else 'undefined (none accepted)'
            print(f"{reference}: coverage {test['coverage']:.1%}, precision {precision}, accepted {test['accepted']}/{test['total']} · {measured['status']}", file=stream)
    elif result['kind'] == 'place_width_probe':
        for level, summary in result['summary'].items():
            print(f"{level}: {summary['option_count']} options · primary accuracy {summary['primary_accuracy']:.1%} · {summary['evaluated']} calibration records · median {summary['median_seconds']:.2f}s", file=stream)
    elif result['kind'] == 'kev_training_export':
        print(f"Exported {result['records']} training records to {result['export_directory']} · warm start {result['checkpoint']} · {result['strategy']}", file=stream)
        return
    if result['kind'] == 'sink_splits':
        print('topic_id\ttopic\tsampled\tusable\tclusters\tsilhouette\tcoherence\tstatus', file=stream)
        for r in rows:
            _line([r[k] for k in ('topic_id', 'topic', 'sampled', 'usable', 'chosen_k', 'silhouette', 'coherence', 'status')], stream)
    else:
        print('work_id\ttitle\tprediction\tconfidence\tstatus', file=stream)
        for r in rows:
            _line([r.get(k) for k in ('work_id', 'title', 'prediction', 'confidence', 'status')], stream)


def _line(values, stream):
    print('\t'.join(str(v).replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') if v is not None else '—' for v in values), file=stream)


def run(args):
    from plumb.backends import ModelError
    try:
        result = place_command(args) if args.cmd == 'place' else split_command(args)
    except InputError as exc:
        print(f'input_error: {exc}. Remedy: check the input and plumb {args.cmd} --help.', file=sys.stderr)
        return 2
    except ModelError as exc:
        print(f'model_error: {exc}', file=sys.stderr)
        return 5
    except OSError as exc:
        print(f'io_error: {exc}. Remedy: check input files and writable output/cache paths.', file=sys.stderr)
        return 4
    try:
        view = presentation(result, args.limit)
        if args.output:
            with atomic_text(args.output) as stream:
                write_result(view, args.format, stream)
        else:
            write_result(view, args.format, sys.stdout)
    except BrokenPipeError:
        return 0
    except OSError as exc:
        print(f'output_error: {exc}. Remedy: choose a writable --output.', file=sys.stderr)
        return 4
    return 0
