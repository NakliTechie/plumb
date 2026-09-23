import json

import pytest

from plumb import pull
from test_audit import topic


def test_complete_snapshot_and_csv_share_topics(tmp_path, monkeypatch):
    records = [topic(1, ['a']), topic(2, ['b'])]
    for row in records:
        row.update(description='description', cited_by_count=3, siblings=[], created_date='2026-01-01', updated_date='2026-09-22')
    replies = iter([dict(meta=dict(count=2, next_cursor='next'), results=records[:1]),
                    dict(meta=dict(count=2, next_cursor=None), results=records[1:])])
    monkeypatch.setattr(pull, 'get', lambda url: next(replies))
    monkeypatch.setattr(pull.time, 'sleep', lambda _: None)
    pull.topics(tmp_path)
    from plumb.audit import load_snapshot
    snapshot, _ = load_snapshot(tmp_path / 'topics.json')
    assert snapshot['topic_count'] == 2
    assert snapshot['topics'][0]['keywords'] == ['a']
    assert (tmp_path / 'topics.csv').read_text().count('\n') == 3


@pytest.mark.parametrize('meta,results', [
    (dict(count=2, next_cursor=None), [topic(1, ['a'])]),
    (dict(count=2, next_cursor=None), [topic(1, ['a']), topic(1, ['a'])]),
    (dict(count=0, next_cursor=None), []),
    (dict(count=2, next_cursor='*'), [topic(1, ['a'])]),
])
def test_incomplete_pull_preserves_old_snapshot(tmp_path, monkeypatch, meta, results):
    old = tmp_path / 'topics.json'
    old.write_text('old')
    monkeypatch.setattr(pull, 'get', lambda url: dict(meta=meta, results=results))
    monkeypatch.setattr(pull.time, 'sleep', lambda _: None)
    with pytest.raises(pull.FetchError):
        pull.topics(tmp_path)
    assert old.read_text() == 'old'


def test_malformed_metadata_preserves_old_snapshot(tmp_path, monkeypatch):
    from plumb.audit import InputError
    old = tmp_path / 'topics.json'
    old.write_text('old')
    malformed = topic(1, ['a'])
    malformed['field'] = None
    monkeypatch.setattr(pull, 'get', lambda url: dict(meta=dict(count=1, next_cursor=None), results=[malformed]))
    with pytest.raises(InputError):
        pull.topics(tmp_path)
    assert old.read_text() == 'old'
