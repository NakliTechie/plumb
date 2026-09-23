import copy
import json

import pytest

from plumb.audit import InputError
from plumb.backends import CachedBackend, ModelError, checked_probabilities
from plumb.datasets import assign_partitions, feature_text, load_place
from plumb.place import (apply_calibration, evaluate, export_training, predict,
                         selective_metrics, threshold, wilson)
from test_audit import topic


def record(i, title='research', source=None, primary='T1', partition='train'):
    return dict(id=f'W{i}', doi=None, source_id=source,
                metadata=dict(title=title, source=source or '', type='article', keywords=[]),
                truth=dict(primary_topic_id=primary, topic_ids=[primary]),
                partition=partition, split_group=f'group{i}')


@pytest.fixture
def tax():
    topics = {'T1': topic(1, ['x'], parent=1, field=1), 'T2': topic(2, ['y'], parent=2, field=2)}
    labels = {'domain': {'1': 'Domain'}, 'field': {'1': 'Field 1', '2': 'Field 2'},
              'subfield': {'1': 'Parent 1', '2': 'Parent 2'}}
    return topics, labels


class Backend:
    identity = dict(backend='test', fingerprint='fixed')

    def __init__(self):
        self.texts = []

    def probabilities(self, text, options):
        self.texts.append(text)
        if len(options) == 1:
            return {next(iter(options)): 1.0}
        return {'1': .99, '2': .01}


def test_features_cannot_include_truth_abstracts_or_citations():
    m = record(1)['metadata']
    m.update(abstract='secret abstract', truth='secret label', citations=['hidden reference'])
    text = feature_text(m)
    assert 'secret' not in text and 'hidden' not in text
    assert 'Title: research' in text


def test_group_split_is_order_independent_and_source_duplicate_transitive():
    rows = [record(1, 'shared title', 'A'), record(2, 'shared title', 'B'),
            record(3, 'other title', 'B'), record(4, 'independent', 'C')]
    first = assign_partitions(copy.deepcopy(rows))
    second = assign_partitions(list(reversed(copy.deepcopy(rows))))
    assert {r['id']:r['partition'] for r in first} == {r['id']:r['partition'] for r in second}
    assert len({r['split_group'] for r in first[:3]}) == 1


def test_loader_rejects_forged_disjoint_groups_that_share_a_source(tmp_path):
    rows = [record(1, 'a', 'shared', partition='train'), record(2, 'b', 'shared', partition='test')]
    path = tmp_path/'data.json'
    path.write_text(json.dumps(dict(schema_version=1, kind='place_dataset', records=rows)))
    with pytest.raises(InputError, match='leakage'):
        load_place(path)


def test_threshold_uses_wilson_bound_and_keeps_ties_together():
    good = [dict(status='predicted', confidence=.9, correct_primary=True) for _ in range(50)]
    bad = [dict(status='predicted', confidence=.2, correct_primary=False) for _ in range(50)]
    fitted = threshold(good+bad, 'primary')
    assert fitted['threshold'] == .9 and fitted['accepted'] == 50
    assert fitted['precision_interval'][0] >= .9
    assert threshold(good[:20], 'primary')['threshold'] is None
    tied = [dict(status='predicted', confidence=.9, correct_primary=False) for _ in range(10)]
    assert threshold(good+tied, 'primary')['threshold'] is None


def test_zero_acceptance_has_undefined_precision():
    metrics = selective_metrics([dict(status='predicted', confidence=.9, correct_primary=True)], None, 'primary')
    assert metrics['precision'] is None and metrics['coverage'] == 0
    assert metrics['precision_interval'] == [None, None]
    assert wilson(0, 0) == [None, None]


def test_test_failure_cannot_change_calibration_or_leak_train_data(tax):
    topics, labels = tax
    rows = [record(i, 'calibration title', primary='T1', partition='calibration') for i in range(50)]
    rows += [record(100+i, 'test title', primary='T2', partition='test') for i in range(10)]
    rows += [record(999, 'train-only secret', partition='train')]
    backend = Backend()
    result = evaluate(dict(records=rows), 'input', backend, topics, labels, 'tax')
    measured = result['results']['primary']
    assert measured['calibration']['threshold'] == .99
    assert measured['test']['precision'] == 0
    assert measured['status'] == 'target_not_met_on_test'
    assert all('train-only secret' not in text for text in backend.texts)
    assert len(backend.texts) == 60


def test_hierarchical_confidence_is_path_product_and_no_metadata_abstains(tax):
    topics, labels = tax
    backend = Backend()
    row = predict(record(1), backend, topics, labels, 'hierarchical')
    assert row['prediction'] == '1'
    assert row['confidence'] == .99
    assert [r['level'] for r in row['route']] == ['domain', 'field', 'subfield']
    blank = record(2, title='')
    assert predict(blank, backend, topics, labels)['status'] == 'insufficient_metadata'


def test_any_topic_reference_is_not_top_three_prediction_accuracy(tax):
    from plumb.place import labelled
    topics, labels = tax
    r = record(1, primary='T2')
    r['truth']['topic_ids'] = ['T2','T1']
    row = labelled(predict(r, Backend(), topics, labels), r, topics, 'subfield')
    assert row['correct_primary'] is False
    assert row['correct_any_topic'] is True
    assert row['primary_in_top3_predictions'] is True


def test_export_only_train_and_record_warm_start(tmp_path, tax):
    topics, labels = tax
    data = dict(records=[record(1, 'train'), record(2, 'held-out', partition='test')])
    report = export_training(data, 'input', topics, labels, 'tax', tmp_path/'export')
    rows = [json.loads(line) for line in (tmp_path/'export/train.jsonl').read_text().splitlines()]
    assert [r['id'] for r in rows] == ['W1']
    assert 'held-out' not in (tmp_path/'export/train.jsonl').read_text()
    assert set(rows[0]['questions']) == {'domain','field','subfield'}
    assert report['checkpoint'].startswith('jaredpalmer/kev-9b@')
    assert report['partition'] == 'train'
    with pytest.raises(InputError, match='different run'):
        export_training(data, 'different-input', topics, labels, 'tax', tmp_path/'export')


@pytest.mark.parametrize('bad', [{'1':1.0}, {'1':.8,'2':.8}, {'1':float('nan'),'2':0}, {'1':-1,'2':2}, {'1':True,'2':0}])
def test_bad_model_output_fails_closed(bad):
    with pytest.raises(ModelError):
        checked_probabilities(bad, {'1':'a','2':'b'})


def test_cache_binds_model_features_and_options_and_rejects_corruption(tmp_path):
    backend = Backend()
    cache = CachedBackend(backend, tmp_path)
    choices = {'1':'one','2':'two'}
    assert cache.probabilities('a', choices) == cache.probabilities('a', choices)
    assert cache.hits == 1 and len(backend.texts) == 1
    cache.probabilities('b', choices)
    cache.probabilities('a', {'1':'different','2':'two'})
    assert len(backend.texts) == 3
    for p in tmp_path.iterdir():
        p.write_text(json.dumps({'key':'wrong'}))
    with pytest.raises(ModelError, match='Corrupt'):
        cache.probabilities('a', choices)


def test_calibration_cannot_be_reused_across_models():
    from plumb.place import FEATURE_POLICY
    report = dict(schema_version=1, kind='place_evaluation', model={'fingerprint':'old'}, strategy='flat',
                  taxonomy_sha256='tax', feature_policy=FEATURE_POLICY, level='subfield',
                  results={'primary':{'calibration':{'threshold':.9}}})
    with pytest.raises(InputError, match='model differs'):
        apply_calibration([], report, {'fingerprint':'new'}, 'flat', 'tax', 'primary')


def test_moving_model_revision_cannot_reuse_checkpoint_identity(monkeypatch):
    import sys
    from types import SimpleNamespace
    from plumb.backends import GlinerBackend
    monkeypatch.setattr('plumb.backends.importlib.metadata.version', lambda _: 'test')
    current = ['a' * 40]
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        model_info=lambda model, revision: SimpleNamespace(sha=current[0])))
    first = GlinerBackend(model='example/model', revision='main')
    current[0] = 'b' * 40
    second = GlinerBackend(model='example/model', revision='main')
    assert first.identity['revision'] == 'a' * 40
    assert second.identity['revision'] == 'b' * 40
    assert first.identity != second.identity


def test_kev_wide_probabilities_use_unrounded_endpoint(monkeypatch):
    from plumb.backends import KevBackend
    paths = []

    def request(self, path, payload=None):
        paths.append(path)
        if path == '/v1/models':
            return dict(models=[dict(run='checkpoint')])
        if path == '/plumb/provenance':
            return dict(fingerprint='a'*64, probability_api='full-precision-choice-v1')
        assert path == '/plumb/choice-probabilities'
        options = payload['questions']['subject']['criteria']
        return dict(answers=dict(subject=dict(probabilities={key:1/len(options) for key in options})))

    monkeypatch.setattr(KevBackend, 'request', request)
    backend = KevBackend()
    probabilities = backend.probabilities('metadata', {str(i):str(i) for i in range(252)})
    assert sum(probabilities.values()) == pytest.approx(1)
    assert all(value > 0 for value in probabilities.values())
    assert paths[-1] == '/plumb/choice-probabilities'
