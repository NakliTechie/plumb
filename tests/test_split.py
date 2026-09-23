import csv
import json

import pytest

from plumb.audit import InputError
from plumb.commands import guard_paths, presentation, write_result
from plumb.split import load_samples, split_sink
from test_place import record


def sink():
    records = []
    for i in range(60):
        title = ('photon laser quantum optical resonance' if i < 30 else 'soil roots fungal plant symbiosis') + f' study {i}'
        r = record(i, title)
        r['truth']['topic_ids'] = ['T1']
        records.append(r)
    return dict(topic_id='T1', topic='mixed sink', works_count=1000000, records=records)


def test_two_distinct_subjects_produce_traceable_partition():
    data = sink()
    result = split_sink(data, max_clusters=2)
    assert result['status'] == 'proposed_split'
    assert result['chosen_k'] == 2
    assert result['silhouette'] > .9
    assert result['coherence'] > result['baseline_coherence']
    assert sum(c['size'] for c in result['clusters']) == 60
    assignments = {r['work_id']:r for r in result['assignments']}
    assert len(assignments) == 60
    assert assignments['W0']['cluster_id'] == assignments['W29']['cluster_id']
    assert assignments['W0']['cluster_id'] != assignments['W30']['cluster_id']
    assert all(r['action'] == 'propose_split' for r in assignments.values())
    data['records'].reverse()
    assert split_sink(data, max_clusters=2) == result


def test_unusable_records_remain_explicitly_accounted_for():
    data = sink()
    data['records'].append(record(100, ''))
    result = split_sink(data, max_clusters=2)
    assert result['sampled'] == 61 and result['usable'] == 60
    empty = next(r for r in result['assignments'] if r['work_id'] == 'W100')
    assert empty['action'] == 'unassigned' and empty['cluster_id'] is None


def test_embedding_partition_keeps_titles_without_shared_word_vocabulary():
    import numpy as np
    data = sink()
    for i, r in enumerate(data['records']):
        r['metadata']['title'] = f'unique{i}'

    class Encoder:
        def encode(self, texts):
            return np.array([[1., 0.] if int(t.strip()[6:]) < 30 else [0., 1.] for t in texts])

    result = split_sink(data, max_clusters=2, encoder=Encoder())
    assert result['usable'] == result['sampled'] == 60
    assert result['chosen_k'] == 2
    assert result['silhouette'] > .99
    assert all(a['action'] == 'propose_split' for a in result['assignments'])
    assert all(c['keywords'] == [] for c in result['clusters'])


def test_uniform_or_small_sample_is_not_fabricated_as_a_split():
    data = sink()
    for r in data['records']:
        r['metadata']['title'] = 'identical title'
    result = split_sink(data)
    assert result['status'] == 'insufficient_evidence'
    assert result['silhouette'] is None
    data['records'] = data['records'][:3]
    assert split_sink(data)['reason'] == 'fewer_than_two_minimum_clusters'


def test_sample_validation_rejects_wrong_sink_assignments(tmp_path):
    data = sink()
    data['records'][0]['truth']['topic_ids'] = ['T2']
    path = tmp_path/'input.json'
    path.write_text(json.dumps(dict(schema_version=1, kind='sink_samples', sinks=[data])))
    with pytest.raises(InputError, match='absent'):
        load_samples(path)


def test_presentation_is_bounded_without_losing_computed_assignments():
    result = dict(kind='sink_splits', rows=[dict(assignments=list(range(60)))])
    view = presentation(result, 20)
    assert len(view['rows'][0]['assignments']) == 20
    assert view['rows'][0]['assignment_count'] == 60
    assert view['rows'][0]['assignments_truncated'] is True
    assert len(result['rows'][0]['assignments']) == 60


def test_output_paths_cannot_overwrite_inputs_or_each_other(tmp_path):
    path = tmp_path/'input.json'
    with pytest.raises(InputError):
        guard_paths([path], [path])
    with pytest.raises(InputError):
        guard_paths([], [path, path])
