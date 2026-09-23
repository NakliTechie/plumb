"""Reproduce local OpenAlex tables and the keyword snapshot (anonymous requests)."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from plumb.storage import atomic_text

UA = 'openalex-topic-notes (mailto:chirag.patnaik@gmail.com)'
BASE = 'https://api.openalex.org'
NULL = 'primary_topic.id:null'


class FetchError(RuntimeError):
    pass


def get(url):
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=40) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise FetchError(f'HTTP {exc.code} fetching {url}') from exc
            error = exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            error = exc
        if attempt < 4:
            print(f'Retrying request ({attempt + 1}/4): {error}', file=sys.stderr)
            time.sleep(2 + 2 * attempt)
    raise FetchError(f'Request failed after 5 attempts: {url}: {error}')


def write_csv(path, columns, rows):
    with atomic_text(path) as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)


def group(filt, key, per_page=200):
    q = {'filter': filt, 'group_by': key, 'per-page': per_page}
    return get(f'{BASE}/works?{urllib.parse.urlencode(q)}')['group_by']


def by_year(output_dir='data'):
    unassigned = {g['key']: g['count'] for g in group(NULL, 'publication_year')}
    total = {g['key']: g['count'] for g in group('type:!null', 'publication_year')}
    write_csv(Path(output_dir) / 'unassigned_by_year.csv',
              ['publication_year', 'unassigned_works', 'total_works'],
              ([y, unassigned[y], total.get(y, '')] for y in sorted(unassigned, key=lambda k: -int(k))))


def by_source_type(output_dir='data'):
    rows = []
    for kind in ('dataset', 'article', 'report', 'other', 'paratext'):
        for g in group(f'{NULL},type:{kind}', 'primary_location.source.id'):
            if g['count'] >= 1000:
                rows.append([kind, g['key'].rsplit('/', 1)[-1], g['key_display_name'], g['count']])
        time.sleep(0.2)
    rows.sort(key=lambda row: -row[3])
    write_csv(Path(output_dir) / 'unassigned_by_source_type.csv',
              ['type', 'source_id', 'source', 'unassigned_works'], rows)


def topics(output_dir='data'):
    cursor, out, seen_cursors = '*', [], set()
    expected = None
    while cursor:
        if cursor in seen_cursors or len(seen_cursors) >= 100:
            raise FetchError('Topic pagination repeated or exceeded 100 pages; previous snapshot retained')
        seen_cursors.add(cursor)
        query = urllib.parse.urlencode({'per-page': 200, 'cursor': cursor})
        data = get(f'{BASE}/topics?{query}')
        count = data['meta']['count']
        if expected is None:
            expected = count
        if count != expected:
            raise FetchError('Topic count changed during pagination; retry to obtain a complete snapshot')
        for topic in data['results']:
            fields = ('id', 'display_name', 'description', 'keywords', 'subfield', 'field', 'domain',
                      'works_count', 'cited_by_count', 'created_date', 'updated_date')
            record = {key: topic.get(key) for key in fields}
            record['sibling_count'] = len(topic.get('siblings') or [])
            out.append(record)
        cursor = data['meta'].get('next_cursor')
        print(f'topics {len(out)}/{expected}', file=sys.stderr)
        if cursor:
            time.sleep(0.12)
    if not out or len(out) != expected or len({t['id'] for t in out}) != expected:
        raise FetchError('Incomplete or duplicate topic results; previous snapshot retained')
    out.sort(key=lambda t: t['id'])
    snapshot = dict(schema_version=1, source=f'{BASE}/topics',
                    retrieved_at=datetime.now(timezone.utc).isoformat(), topic_count=len(out), topics=out)
    from plumb.audit import validate_snapshot
    validate_snapshot(snapshot)
    # Prepare the CSV projection before publishing either file.
    rows = []
    for t in sorted(out, key=lambda t: (-t['works_count'], t['id'])):
        row = [t['id'].rsplit('/', 1)[-1], t['display_name']]
        for level in ('subfield', 'field', 'domain'):
            row.extend([t[level]['id'].rsplit('/', 1)[-1], t[level]['display_name']])
        row.extend([t['works_count'], t['cited_by_count'], t['sibling_count'], len(t['keywords']), t['created_date'], t['updated_date']])
        rows.append(row)
    with atomic_text(Path(output_dir) / 'topics.json') as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    write_csv(Path(output_dir) / 'topics.csv',
              ['topic_id', 'topic', 'subfield_id', 'subfield', 'field_id', 'field',
               'domain_id', 'domain', 'works_count', 'cited_by_count', 'sibling_count',
               'keyword_count', 'created_date', 'updated_date'], rows)
    return snapshot


if __name__ == '__main__':
    from plumb.cli import main
    raise SystemExit(main(['pull', *sys.argv[1:]]))
