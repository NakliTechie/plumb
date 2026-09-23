"""Reproducible exploratory partitions of sampled oversized topic assignments."""
from collections import Counter
import math

from plumb.audit import InputError
from plumb.datasets import read_json, validate_record


def load_samples(path, taxonomy_sha256=None):
    doc, digest = read_json(path)
    if not isinstance(doc, dict) or doc.get('schema_version') != 1 or doc.get('kind') != 'sink_samples' or not isinstance(doc.get('sinks'), list) or not doc['sinks']:
        raise InputError('Expected sink_samples; run plumb pull --works split')
    if taxonomy_sha256 and doc.get('taxonomy_sha256') != taxonomy_sha256:
        raise InputError('Sink sample taxonomy hash differs from --topics')
    seen_topics = set()
    for sink in doc['sinks']:
        if not isinstance(sink, dict) or not isinstance(sink.get('topic_id'), str) or not isinstance(sink.get('topic'), str) or not isinstance(sink.get('records'), list):
            raise InputError('Invalid sink topic descriptor')
        if type(sink.get('works_count')) is not int or sink['works_count'] < 0:
            raise InputError('Sink works_count must be a nonnegative integer')
        if sink['topic_id'] in seen_topics:
            raise InputError('Duplicate sink topic')
        seen_topics.add(sink['topic_id'])
        ids = set()
        for r in sink['records']:
            validate_record(r)
            if r['id'] in ids:
                raise InputError(f"Duplicate sampled work in {sink['topic_id']}")
            ids.add(r['id'])
            if sink['topic_id'] not in (r.get('truth') or {}).get('topic_ids', []):
                raise InputError(f"{r['id']}: sampled sink is absent from its topic assignments")
    return doc, digest


def text_for_split(record):
    m = record['metadata']
    # Source/journal names would make a journal classifier instead of a subject split.
    return m['title'][:2000] + ' ' + ' '.join(k[:100] for k in m.get('keywords', [])[:20])


def coherence(matrix):
    """Mean off-diagonal cosine similarity of L2-normalised nonempty vectors."""
    n = matrix.shape[0]
    if n < 2:
        return None
    summed = matrix.sum(axis=0)
    norm_squared = float((summed @ summed.T).item())
    return max(-1.0, min(1.0, (norm_squared - n)/(n*(n-1))))


def split_sink(sink, seed=42, max_clusters=8, minimum_cluster=5, encoder=None):
    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics import silhouette_score
        from sklearn.preprocessing import normalize
        from scipy.sparse import csr_matrix
        from threadpoolctl import threadpool_limits
    except ImportError as exc:
        raise InputError('Clustering dependencies missing; run uv sync --extra split') from exc
    records = sorted(sink['records'], key=lambda r: r['id'])
    assignments = [dict(work_id=r['id'], title=r['metadata']['title'], original_topic_id=sink['topic_id'],
                        cluster_id=None, action='unassigned', reason='insufficient_text', cosine_to_centroid=None)
                   for r in records]
    result = dict(topic_id=sink['topic_id'], topic=sink['topic'], works_count=sink['works_count'],
                  sampled=len(records), usable=0, status='insufficient_evidence', reason=None,
                  chosen_k=None, silhouette=None, coherence=None, baseline_coherence=None,
                  candidates=[], clusters=[], assignments=assignments)
    nonempty = [i for i, r in enumerate(records) if text_for_split(r).strip()]
    if len(nonempty) < 2 * minimum_cluster:
        result['reason'] = 'fewer_than_two_minimum_clusters'
        return result
    vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2), min_df=2,
                                 max_df=.95, max_features=10000, sublinear_tf=True,
                                 norm='l2', dtype=np.float64)
    try:
        word_matrix = vectorizer.fit_transform([text_for_split(records[i]) for i in nonempty])
    except ValueError as exc:
        if 'vocabulary' not in str(exc) and 'terms remain' not in str(exc):
            raise
        if encoder is None:
            result['reason'] = 'no_shared_vocabulary'
            return result
        word_matrix = None
    matrix = (csr_matrix(encoder.encode([text_for_split(records[i]) for i in nonempty]))
              if encoder is not None else word_matrix)
    usable_mask = np.asarray(matrix.getnnz(axis=1)).ravel() > 0
    usable_ids = [i for i, keep in zip(nonempty, usable_mask) if keep]
    for i in nonempty:
        assignments[i]['reason'] = 'no_shared_vocabulary'
    matrix = matrix[usable_mask]
    if word_matrix is not None:
        word_matrix = word_matrix[usable_mask]
    for i in usable_ids:
        assignments[i]['reason'] = 'no_supported_partition'
    n = matrix.shape[0]
    result['usable'] = n
    result['baseline_coherence'] = coherence(matrix)
    if n < 2 * minimum_cluster:
        result['reason'] = 'fewer_than_two_minimum_clusters_after_vectorisation'
        return result
    best = None
    with threadpool_limits(limits=1):
        for k in range(2, min(max_clusters, n // minimum_cluster) + 1):
            fitted = KMeans(n_clusters=k, random_state=seed, n_init=10).fit(matrix)
            counts = Counter(int(v) for v in fitted.labels_)
            if len(counts) != k or min(counts.values()) < minimum_cluster:
                result['candidates'].append(dict(k=k, status='rejected_small_or_empty_cluster', sizes=sorted(counts.values()), silhouette=None))
                continue
            value = float(silhouette_score(matrix, fitted.labels_, metric='cosine', sample_size=min(n, 1000), random_state=seed))
            result['candidates'].append(dict(k=k, status='evaluated', sizes=sorted(counts.values()), silhouette=value))
            if best is None or value > best[0] + 1e-12:
                best = (value, k, fitted.labels_)
    if best is None:
        result['reason'] = 'no_candidate_meets_minimum_cluster_size'
        return result
    result['silhouette'] = best[0]
    result['status'] = 'proposed_split' if best[0] > 0 else 'no_supported_split'
    result['chosen_k'] = best[1] if best[0] > 0 else 1
    chosen = best[2] if best[0] > 0 else np.zeros(n, dtype=int)
    names = vectorizer.get_feature_names_out() if word_matrix is not None else []
    groups = []
    for label in sorted(set(chosen)):
        mask = chosen == label
        members = np.flatnonzero(mask)
        center = np.asarray(matrix[mask].mean(axis=0)).reshape(1, -1)
        center = normalize(center)
        keyword_center = np.asarray(word_matrix[mask].mean(axis=0)).ravel() if word_matrix is not None else np.array([])
        order = np.argsort(-keyword_center, kind='stable')
        terms = [str(names[i]) for i in order[:8] if keyword_center[i] > 0]
        groups.append((terms, members, center))
    groups.sort(key=lambda g: (g[0], records[usable_ids[int(g[1][0])]]['id']))
    pair_sum = 0.0
    pairs = 0
    for number, (terms, members, center) in enumerate(groups, 1):
        cid = f"{sink['topic_id']}.C{number:02d}"
        similarities = np.asarray(matrix[members] @ center.T).ravel()
        member_coherence = coherence(matrix[members])
        member_records = [records[usable_ids[int(i)]] for i in members]
        representative_order = sorted(range(len(members)), key=lambda i: (-similarities[i], member_records[i]['id']))[:5]
        result['clusters'].append(dict(cluster_id=cid, size=len(members), keywords=terms, coherence=member_coherence,
            representatives=[dict(work_id=member_records[i]['id'], title=member_records[i]['metadata']['title']) for i in representative_order]))
        pair_count = len(members)*(len(members)-1)
        pair_sum += member_coherence*pair_count
        pairs += pair_count
        for i, similarity in zip(members, similarities):
            assignment = assignments[usable_ids[int(i)]]
            assignment.update(cluster_id=cid, action='propose_split' if best[0] > 0 else 'retain_original',
                              reason=None, cosine_to_centroid=float(similarity))
    result['coherence'] = pair_sum/pairs if pairs else None
    result['reason'] = None if best[0] > 0 else 'no_positive_silhouette'
    return result


def split_samples(document, digest, max_clusters=8, minimum_cluster=5, topic_id=None, encoder=None):
    if not 2 <= max_clusters <= 20 or minimum_cluster < 2:
        raise InputError('max-clusters must be 2–20 and minimum-cluster must be at least 2')
    selected = [s for s in document['sinks'] if topic_id is None or s['topic_id'] == topic_id]
    if not selected:
        raise InputError('Requested topic is not in the sink sample')
    rows = []
    import sys
    for s in selected:
        print(f"Splitting {s['topic_id']}: {len(s['records'])} sampled records", file=sys.stderr, flush=True)
        rows.append(split_sink(s, seed=document['seed'], max_clusters=max_clusters, minimum_cluster=minimum_cluster, encoder=encoder))
    return dict(schema_version=1, kind='sink_splits', input_sha256=digest,
                taxonomy_sha256=document['taxonomy_sha256'],
                method='multilingual-e5-kmeans-cosine-v1' if encoder else 'tfidf-l2-kmeans-cosine-v1',
                encoder=encoder.identity if encoder else None,
                truncated_inputs=encoder.truncated_inputs if encoder else 0,
                parameters=dict(seed=document['seed'], max_clusters=max_clusters, minimum_cluster=minimum_cluster,
                                features='title and supplied keywords; no source, labels, abstracts or citations',
                                silhouette_sample_limit=1000),
                limitation='Exploratory partitions of the sampled records; no full-topic assignment or causal attribution',
                summary=dict(sinks=len(rows), statuses=dict(Counter(r['status'] for r in rows)),
                             sampled_assignments=sum(r['sampled'] for r in rows), usable_assignments=sum(r['usable'] for r in rows)),
                rows=rows)
