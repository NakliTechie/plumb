"""Validate a plumb export and warm-start Kev's native trainer; never train from base.

Use the separate Kev environment. An output directory must not already exist.
This script starts local computation only; it provisions no cloud resources.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--export', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--device', choices=('mps', 'cpu', 'cuda'), default='mps')
    a = p.parse_args()
    manifest = json.loads((a.export/'manifest.json').read_text())
    data = a.export/'train.jsonl'
    if manifest.get('kind') != 'kev_training_export' or manifest.get('partition') != 'train':
        p.error('Expected a train-only plumb export manifest')
    if hashlib.sha256(data.read_bytes()).hexdigest() != manifest.get('train_sha256'):
        p.error('Training data differs from its manifest')
    if a.out.exists():
        p.error('Output exists; choose a new checkpoint directory')
    from kev.checkpoint import Checkpoint
    from kev.data import load_records, materialize
    from kev.model import fits, load_tokenizer
    ck = Checkpoint(manifest['checkpoint'])
    if ck.meta.base != manifest['base'] or not ck.meta.lora:
        p.error('Warm-start checkpoint architecture does not match the manifest')
    tok = load_tokenizer(ck.meta.base, revision=ck.meta.base_revision)
    records = load_records(data)
    if len(records) != manifest['records'] or {r['id'] for r in records} != set(manifest['record_ids']):
        p.error('Training record identities differ from the manifest')
    rejected = [r['id'] for r in records if not fits(materialize(r), tok)]
    if rejected:
        p.error(f'{len(rejected)} records exceed Kev training context; shorten metadata or export hierarchical questions. No records silently dropped.')
    command = [sys.executable, '-m', 'kev.train', '--data', str(data.resolve()),
               '--base', ck.meta.base, '--init_from', manifest['checkpoint'],
               '--epochs', str(manifest['recipe']['epochs']), '--lr', str(manifest['recipe']['learning_rate']),
               '--batch', str(manifest['recipe']['batch']), '--accum', str(manifest['recipe']['accumulation']),
               '--lora', str(ck.meta.lora), '--head_dim', str(ck.meta.head_dim),
               '--option_isolation', str(int(ck.meta.option_isolation)),
               '--special_embeddings', str(int(ck.meta.special_embeddings)),
               '--checkpointing', '1', '--device', a.device,
               '--weights_dtype', 'bf16', '--dtype', 'bf16' if a.device == 'cuda' else 'fp32',
               '--p_none', '0', '--p_none_distract', '0', '--p_distract', '0', '--p_none_pair', '0',
               '--seed', '42', '--out', str(a.out.resolve())]
    if ck.meta.base_revision:
        command.extend(['--base_revision', ck.meta.base_revision])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    provenance = dict(command=command, manifest=manifest, state='launching',
                      checkpoint_path=ck.path, records_admitted=len(records))
    launch = a.out.with_suffix('.launch.json')
    launch.write_text(json.dumps(provenance, indent=2)+'\n')
    print(json.dumps(provenance), flush=True)
    env = {**os.environ, 'PYTORCH_ENABLE_MPS_FALLBACK': '1'}
    code = subprocess.run(command, env=env).returncode
    provenance.update(state='trained' if code == 0 else 'failed', exit_code=code)
    launch.write_text(json.dumps(provenance, indent=2)+'\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
