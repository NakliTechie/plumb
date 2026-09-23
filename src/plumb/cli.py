"""plumb CLI — reproducible, read-only taxonomy diagnostics."""
import argparse
import csv
import json
from pathlib import Path
import sys

from plumb.storage import atomic_text


def integer(minimum, maximum=None):
    def parse(value):
        try:
            result = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError('must be an integer') from exc
        if result < minimum or (maximum is not None and result > maximum):
            raise argparse.ArgumentTypeError(f'must be {minimum}–{maximum}' if maximum else f'must be at least {minimum}')
        return result
    return parse


def render(result, fmt, stream):
    if fmt == 'json':
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        return
    level = result['parameters']['level']
    if fmt == 'csv':
        columns = ['rank', 'topic_id', 'topic', 'score', 'status', 'works_count',
                   'stated_parent', 'stated_share', 'plurality_parent', 'plurality_share',
                   'neighbour_count', 'margin', 'strength', 'parents_json', 'neighbours_json',
                   'input_sha256', 'method', 'k', 'level']
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in result['rows']:
            parent = row['parents'][level]
            other = parent['plurality_parent']
            record = {key: row[key] for key in ('rank', 'topic_id', 'topic', 'score', 'status', 'works_count', 'neighbour_count', 'margin', 'strength')}
            record.update(stated_parent=parent['stated_parent']['name'], stated_share=parent['stated_share'],
                          plurality_parent=other['name'] if other else '', plurality_share=other['share'] if other else 0,
                          parents_json=json.dumps(row['parents'], ensure_ascii=False),
                          neighbours_json=json.dumps(row['neighbours'], ensure_ascii=False),
                          input_sha256=result['input']['sha256'], method=result['method'],
                          k=result['parameters']['k'], level=level)
            writer.writerow(record)
        return
    summary = result['summary']
    print(f"{result['input']['topic_count']} topics · {summary['review']} review · "
          f"{summary['consistent']} consistent · {summary['insufficient_evidence']} insufficient evidence", file=stream)
    print(f"{result['method']} · k={result['parameters']['k']} · level={level} · "
          f"showing {len(result['rows'])} · input {result['input']['sha256'][:12]}", file=stream)
    print('rank\tscore\tid\ttopic\tstated parent → neighbourhood plurality (share)\tstatus', file=stream)
    for row in result['rows']:
        parent = row['parents'][level]
        other = parent['plurality_parent']
        target = f"{other['name']} ({other['share']:.0%})" if other else '—'
        # Escape control characters so one source label cannot introduce extra rows.
        cells = [str(row['rank']), f"{row['score']:.6f}", row['topic_id'], row['topic'],
                 f"{parent['stated_parent']['name']} → {target}", row['status']]
        print('\t'.join(c.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') for c in cells), file=stream)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='plumb', description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    pull_parser = sub.add_parser('pull', help='reproduce local tables from the OpenAlex API')
    pull_parser.add_argument('--topics-only', action='store_true', help='fetch only the topic snapshot and its CSV projection')
    pull_parser.add_argument('--output-dir', type=Path, default=Path('data'))
    pull_parser.add_argument('--works', choices=('place', 'split', 'both'), help='collect work samples using the existing topic snapshot')
    pull_parser.add_argument('--topics', type=Path, default=Path('data/topics.json'))
    pull_parser.add_argument('--sample-size', type=integer(1, 10000), help='records per benchmark or per sink (defaults: 600 place, 300 split)')
    pull_parser.add_argument('--seed', type=integer(0), default=42)
    audit_parser = sub.add_parser('audit', help='rank topics by keyword-neighbourhood disagreement (offline)')
    audit_parser.add_argument('--input', type=Path, default=Path('data/topics.json'))
    audit_parser.add_argument('--k', type=integer(1, 100), default=10)
    audit_parser.add_argument('--level', choices=('subfield', 'field', 'domain'), default='subfield')
    audit_parser.add_argument('--limit', type=integer(0), default=20, help='rows to emit; 0 explicitly emits all rows')
    audit_parser.add_argument('--format', choices=('table', 'json', 'csv'), default='table')
    audit_parser.add_argument('--output', type=Path, help='atomic file output; default stdout')
    from plumb.commands import add_parsers
    add_parsers(sub, integer)
    args = parser.parse_args(argv)
    if args.cmd == 'pull':
        from plumb import pull
        if args.works:
            if args.topics_only:
                parser.error('--works and --topics-only are mutually exclusive')
            from plumb.datasets import collect_place, collect_sinks, save_json
            from plumb.audit import InputError
            try:
                from plumb.commands import guard_paths
                outputs = [args.output_dir/'place-dataset.json'] if args.works == 'place' else [args.output_dir/'sink-samples.json'] if args.works == 'split' else [args.output_dir/'place-dataset.json', args.output_dir/'sink-samples.json']
                guard_paths([args.topics], outputs)
                if args.works in ('place', 'both'):
                    save_json(args.output_dir / 'place-dataset.json', collect_place(args.topics, args.sample_size or 600, args.seed))
                if args.works in ('split', 'both'):
                    save_json(args.output_dir / 'sink-samples.json', collect_sinks(args.topics, args.sample_size or 300, args.seed))
            except InputError as exc:
                print(f'input_error: {exc}. Remedy: check --topics and sample arguments.', file=sys.stderr)
                return 2
            except (pull.FetchError, KeyError, TypeError, ValueError) as exc:
                print(f'network_error: {exc}. Remedy: retry plumb pull --works {args.works}.', file=sys.stderr)
                return 3
            except OSError as exc:
                print(f'io_error: {exc}. Remedy: check --topics and --output-dir.', file=sys.stderr)
                return 4
            return 0
        try:
            pull.topics(args.output_dir)
            if not args.topics_only:
                pull.by_year(args.output_dir)
                pull.by_source_type(args.output_dir)
        except (pull.FetchError, KeyError, TypeError, ValueError) as exc:
            print(f'network_error: {exc}. Remedy: retry plumb pull --topics-only.', file=sys.stderr)
            return 3
        except OSError as exc:
            print(f'output_error: {exc}. Remedy: choose a writable --output-dir.', file=sys.stderr)
            return 4
        return 0
    if args.cmd in ('place', 'split'):
        from plumb.commands import run
        return run(args)
    from plumb.audit import InputError, audit, load_snapshot
    try:
        if args.output and args.output.resolve() == args.input.resolve():
            raise InputError('--output must differ from --input')
        snapshot, sha256 = load_snapshot(args.input)
        result = audit(snapshot, sha256, args.k, args.level)
    except (InputError, OSError) as exc:
        print(f'input_error: {exc}. Remedy: correct --input or run plumb pull --topics-only.', file=sys.stderr)
        return 2
    result['output'] = dict(limit=args.limit, total_rows=len(result['rows']), truncated=bool(args.limit and args.limit < len(result['rows'])))
    if args.limit:
        result['rows'] = result['rows'][:args.limit]
    try:
        if args.output:
            with atomic_text(args.output) as stream:
                render(result, args.format, stream)
        else:
            render(result, args.format, sys.stdout)
    except BrokenPipeError:
        return 0
    except OSError as exc:
        print(f'output_error: {exc}. Remedy: choose a writable --output path.', file=sys.stderr)
        return 4
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
