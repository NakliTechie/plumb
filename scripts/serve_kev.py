"""Serve a real Kev checkpoint with immutable checkpoint provenance.

Run using the separate Kev environment documented in README.md.
The server binds only to localhost; tunnel it for a remote machine.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

os.environ.setdefault('KEV_PREFIX_CACHE', '0')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True)
    p.add_argument('--device', choices=('mps', 'cpu', 'cuda'), default='mps')
    p.add_argument('--port', type=int, default=8009)
    p.add_argument('--dtype', choices=('bf16', 'fp32'), default='bf16')
    a = p.parse_args()
    import torch
    import uvicorn
    from fastapi import HTTPException
    from kev.api import SystemOneRequest, to_record
    from kev.checkpoint import Checkpoint, LoadOptions
    from kev.serve import app, Server
    ck = Checkpoint(a.run)
    fingerprint = hashlib.sha256()
    files = {}
    for name in ('adapter_config.json', 'adapter_model.safetensors', 'head.pt'):
        h = hashlib.sha256()
        with ck.file(name).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                h.update(chunk)
        files[name] = h.hexdigest()
    fingerprint.update(json.dumps(dict(files=files, base=ck.meta.base, base_revision=ck.meta.base_revision), sort_keys=True).encode())
    provenance = dict(fingerprint=fingerprint.hexdigest(), checkpoint=a.run, files=files,
                      probability_api='full-precision-choice-v1',
                      base=ck.meta.base, base_revision=ck.meta.base_revision,
                      runtime={name: importlib.metadata.version(name) for name in ('kev', 'torch', 'transformers', 'peft')})
    tok, model = ck.load(a.device, LoadOptions(dtype=torch.bfloat16 if a.dtype == 'bf16' else torch.float32,
                                              merge=False, attn='sdpa'))
    app.state.server = Server(ck, tok, model, a.device)

    @app.get('/plumb/provenance')
    def describe():
        return provenance

    @app.post('/plumb/choice-probabilities')
    def probabilities(request: SystemOneRequest):
        if any(q.type != 'choice' for q in request.questions.values()):
            raise HTTPException(422, 'This endpoint accepts choice questions only')
        record, meta = to_record(request)
        values, metrics = app.state.server.probs(record)
        # The standard Kev API rounds to two decimals. Keep the actual head
        # probabilities for wide-label ranking and abstention calibration.
        return dict(answers={m['id']: dict(probabilities=dict(zip(m['keys'], p)))
                             for m, p in zip(meta, values)}, metrics=metrics)

    print(json.dumps(provenance), flush=True)
    uvicorn.run(app, host='127.0.0.1', port=a.port)


if __name__ == '__main__':
    main()
