import copy
import csv
import io
import json
from pathlib import Path

import pytest

from plumb.audit import InputError, audit, load_snapshot, neighbourhoods
from plumb.cli import main
from plumb.storage import atomic_text


def topic(number, keywords, parent=1, field=1):
    return dict(id=f'https://openalex.org/T{number}', display_name=f'Topic {number}',
                keywords=keywords, works_count=10,
                subfield=dict(id=f'https://openalex.org/subfields/{parent}', display_name=f'Parent {parent}'),
                field=dict(id=f'https://openalex.org/fields/{field}', display_name=f'Field {field}'),
                domain=dict(id='https://openalex.org/domains/1', display_name='Domain'))


def document(topics):
    return dict(schema_version=1, topic_count=len(topics), topics=topics)


@pytest.fixture
def small():
    return document([topic(1, ['geology', 'rocks'], 2),
                     topic(2, ['geology', 'rocks']), topic(3, ['geology', 'rocks']),
                     topic(4, ['geology', 'water']), topic(5, ['unrelated']), topic(6, [])])


def save(tmp_path, doc):
    path = tmp_path / 'topics.json'
    path.write_text(json.dumps(doc))
    return path


def test_known_disagreement_has_calculable_score_and_evidence(small):
    result = audit(small, 'test', k=3)
    row = result['rows'][0]
    assert row['topic_id'] == 'T1'
    assert row['status'] == 'review'
    assert row['score'] == pytest.approx(7 / 9)
    assert row['parents']['subfield']['stated_share'] == 0
    assert row['parents']['subfield']['plurality_parent']['share'] == 1
    assert [n['similarity'] for n in row['neighbours']] == [1, 1, pytest.approx(1 / 3)]
    assert all(n['topic_id'] != row['topic_id'] for n in row['neighbours'])
    assert row['neighbours'][0]['shared_keywords'] == ['geology', 'rocks']
    assert sum(result['summary'].values()) == 6


def test_no_overlap_is_insufficient_and_never_padded(small):
    rows = {r['topic_id']: r for r in audit(small, 'test')['rows']}
    for tid in ('T5', 'T6'):
        assert rows[tid]['status'] == 'insufficient_evidence'
        assert rows[tid]['score'] == 0
        assert rows[tid]['neighbours'] == []
        assert rows[tid]['parents']['subfield']['plurality_parent'] is None


def test_sparse_neighbourhood_and_single_vote_do_not_claim_error():
    sparse = document([topic(1, ['x'], 9), topic(2, ['x']), topic(3, ['x'])])
    assert all(r['status'] == 'insufficient_evidence' for r in audit(sparse, 'test')['rows'])
    single = document([topic(1, ['x', 'y'], 9), topic(2, ['x', 'y'], 1),
                       topic(3, ['x', 'a', 'b'], 2), topic(4, ['y', 'c', 'd'], 3)])
    first = next(r for r in audit(single, 'test')['rows'] if r['topic_id'] == 'T1')
    assert first['status'] == 'insufficient_evidence'
    assert first['score'] == 0


def test_normalisation_and_duplicate_keywords_do_not_inflate_overlap():
    topics = [topic(1, ['  MACHINE  Learning ', 'machine learning', 'ＡＩ']),
              topic(2, ['machine learning', 'AI']), topic(3, ['machine', 'learning'])]
    graph = list(neighbourhoods(topics, 10))
    assert graph[0] == [(1, 1.0, ['ai', 'machine learning'])]
    assert graph[2] == []


def test_ties_prefer_stated_parent():
    data = document([topic(1, ['x'], 2), topic(2, ['x'], 1), topic(3, ['x'], 1),
                     topic(4, ['x'], 2), topic(5, ['x'], 2)])
    row = next(r for r in audit(data, 'test')['rows'] if r['topic_id'] == 'T1')
    assert row['parents']['subfield']['plurality_parent']['id'].endswith('/2')
    assert row['status'] == 'consistent'
    assert row['score'] == 0


def test_order_invariance_no_title_or_size_leakage(small):
    original = audit(small, 'test')
    changed = copy.deepcopy(small)
    changed['topics'].reverse()
    assert audit(changed, 'test') == original
    for t in changed['topics']:
        t['display_name'] = 'misleading label'
        t['works_count'] = 10**12
    after = audit(changed, 'test')
    assert [(r['topic_id'], r['score'], r['status']) for r in after['rows']] == [(r['topic_id'], r['score'], r['status']) for r in original['rows']]


def test_coarser_level_changes_verdict_but_not_graph(small):
    coarse = audit(small, 'test', level='field')
    assert coarse['summary']['review'] == 0
    assert all(r['score'] == 0 for r in coarse['rows'])
    fine = {r['topic_id']: r for r in audit(small, 'test')['rows']}
    assert all(r['neighbours'] == fine[r['topic_id']]['neighbours'] for r in coarse['rows'])


@pytest.mark.parametrize('change', [
    lambda d: d.update(topic_count=99),
    lambda d: d['topics'].append(d['topics'][0]),
    lambda d: d['topics'][0].update(keywords=None),
    lambda d: d['topics'][0].update(keywords=['']),
    lambda d: d['topics'][0].update(field=None),
    lambda d: d['topics'][0].update(works_count=-1),
    lambda d: d['topics'][0]['domain'].update(id='bad'),
    lambda d: d['topics'][1]['subfield'].update(display_name='inconsistent name'),
])
def test_malformed_input_is_rejected(tmp_path, small, change):
    change(small)
    with pytest.raises(InputError):
        load_snapshot(save(tmp_path, small))


def test_duplicate_ids_rejected_even_with_matching_count(tmp_path, small):
    small['topics'][1] = small['topics'][0]
    with pytest.raises(InputError, match='Duplicate'):
        load_snapshot(save(tmp_path, small))


def test_cli_json_bounded_and_csv_roundtrip(tmp_path, small, capsys):
    source = save(tmp_path, small)
    assert main(['audit', '--input', str(source), '--format', 'json', '--limit', '2']) == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output['rows']) == 2
    assert output['output'] == dict(limit=2, total_rows=6, truncated=True)
    assert len(output['input']['sha256']) == 64
    target = tmp_path / 'result.csv'
    assert main(['audit', '--input', str(source), '--format', 'csv', '--limit', '0', '--output', str(target)]) == 0
    assert capsys.readouterr().out == ''
    rows = list(csv.DictReader(io.StringIO(target.read_text())))
    assert len(rows) == 6
    assert isinstance(json.loads(rows[0]['neighbours_json']), list)


def test_errors_preserve_output_and_input(tmp_path, small, capsys):
    source = save(tmp_path, small)
    original = source.read_bytes()
    assert main(['audit', '--input', str(source), '--output', str(source)]) == 2
    assert source.read_bytes() == original
    assert capsys.readouterr().out == ''
    assert main(['audit', '--input', str(tmp_path / 'missing')]) == 2
    out = capsys.readouterr()
    assert out.out == '' and 'input_error' in out.err and 'Remedy:' in out.err
    source.write_text('{broken')
    dest = tmp_path / 'old.json'
    dest.write_text('old')
    assert main(['audit', '--input', str(source), '--output', str(dest)]) == 2
    assert dest.read_text() == 'old'


def test_interrupted_output_retains_previous_file(tmp_path):
    dest = tmp_path / 'out.json'
    dest.write_text('old')
    with pytest.raises(RuntimeError):
        with atomic_text(dest) as stream:
            stream.write('partial')
            raise RuntimeError('interrupted')
    assert dest.read_text() == 'old'
    assert list(tmp_path.iterdir()) == [dest]
