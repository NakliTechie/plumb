"""Predeclared project acceptance, deliberately separate from the scoring code."""
from pathlib import Path

import pytest

from plumb.audit import audit, load_snapshot


@pytest.fixture(scope='module')
def ranks():
    snapshot, digest = load_snapshot(Path(__file__).parents[1] / 'data' / 'topics.json')
    assert snapshot['topic_count'] == 4516
    result = audit(snapshot, digest)
    return {r['topic_id']: r['rank'] for r in result['rows']}


def test_known_mapping_case_in_top_50(ranks):
    assert ranks['T12157'] <= 50, f"Known case ranked {ranks['T12157']}; the predeclared acceptance gate is unmet"


@pytest.mark.parametrize('topic_id', ['T11740', 'T10398'])
def test_correctly_filed_controls_outside_top_50(ranks, topic_id):
    assert ranks[topic_id] > 50
