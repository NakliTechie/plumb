"""Versioned multilingual E5 embeddings for scientific-title clustering."""
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys

from plumb.backends import ModelError
from plumb.datasets import read_json, save_json


class MultilingualEncoder:
    def __init__(self, device='cpu', cache='models/embedding-cache', model='intfloat/multilingual-e5-small'):
        self.model_id, self.device = model, device
        ref = Path.home()/'.cache/huggingface/hub'/('models--'+model.replace('/', '--'))/'refs/main'
        if ref.exists():
            revision = ref.read_text().strip()
        else:
            try:
                from huggingface_hub import model_info
                revision = model_info(model).sha
            except Exception as exc:
                raise ModelError(f'Cannot resolve embedding model: {exc}') from exc
        try:
            runtime = {p: importlib.metadata.version(p) for p in ('torch', 'transformers')}
        except importlib.metadata.PackageNotFoundError as exc:
            raise ModelError(f'Embedding dependencies missing ({exc}); run uv sync --extra split') from exc
        self.identity = dict(model=model, revision=revision, pooling='query-prefix-masked-mean-l2-v1',
                             max_tokens=512, device=device,
                             runtime=runtime)
        self.cache = Path(cache) if cache else None
        self.model = self.tokenizer = None
        self.truncated_inputs = 0

    def encode(self, texts):
        import numpy as np
        vectors, missing, paths = {}, [], {}
        for text in dict.fromkeys(texts):
            key = hashlib.sha256(json.dumps([self.identity, text], sort_keys=True).encode()).hexdigest()
            path = self.cache/(key+'.json') if self.cache else None
            paths[text] = (key, path)
            if path and path.exists():
                saved, _ = read_json(path)
                if not isinstance(saved, dict):
                    raise ModelError(f'Invalid embedding cache entry: {path}')
                vector = saved.get('vector')
                if saved.get('key') != key or not isinstance(vector, list) or not vector or any(type(v) not in (int,float) or not math.isfinite(v) for v in vector) or not math.isclose(sum(v*v for v in vector),1.0,abs_tol=1e-3):
                    raise ModelError(f'Invalid embedding cache entry: {path}')
                vectors[text] = vector
                self.truncated_inputs += int(saved.get('truncated', False))
            else:
                missing.append(text)
        if missing:
            try:
                import torch
                from transformers import AutoModel, AutoTokenizer
                if self.model is None:
                    self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, revision=self.identity['revision'])
                    self.model = AutoModel.from_pretrained(self.model_id, revision=self.identity['revision']).to(self.device).eval()
                for start in range(0, len(missing), 16):
                    chunk = missing[start:start+16]
                    inputs = ['query: '+text for text in chunk]
                    lengths = [len(ids) for ids in self.tokenizer(inputs, truncation=False)['input_ids']]
                    batch = self.tokenizer(inputs, padding=True, truncation=True, max_length=512, return_tensors='pt').to(self.device)
                    with torch.inference_mode():
                        hidden = self.model(**batch).last_hidden_state
                        mask = batch['attention_mask'].unsqueeze(-1)
                        pooled = (hidden*mask).sum(dim=1)/mask.sum(dim=1).clamp(min=1)
                        embedded = torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().float().tolist()
                    for text, vector, length in zip(chunk, embedded, lengths):
                        if not all(math.isfinite(v) for v in vector):
                            raise ModelError('Embedding model returned non-finite values')
                        vectors[text] = vector
                        key, path = paths[text]
                        self.truncated_inputs += int(length>512)
                        if path:
                            save_json(path, dict(key=key, vector=vector, truncated=length>512))
                    print(f'Embedded {min(start+16,len(missing))}/{len(missing)} uncached titles', file=sys.stderr, flush=True)
            except ModelError:
                raise
            except Exception as exc:
                raise ModelError(f'Multilingual embedding failed: {exc}. Check uv sync --extra split and model downloads.') from exc
        if len({len(vectors[text]) for text in texts}) != 1:
            raise ModelError('Embedding dimensions disagree; remove invalid cache entries')
        return np.asarray([vectors[text] for text in texts], dtype=np.float64)
