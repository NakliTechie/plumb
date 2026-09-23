"""Real local GLiNER and self-hosted Kev adapters with checked output schemas."""
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
import urllib.error
import urllib.request

from plumb.datasets import read_json, save_json


class ModelError(RuntimeError):
    pass


def checked_probabilities(values, options):
    if not isinstance(values, dict) or set(values) != set(options):
        raise ModelError('Model omitted or invented labels; check model context length/options')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values.values()):
        raise ModelError('Model returned invalid probabilities')
    total = math.fsum(values.values())
    if not math.isclose(total, 1.0, rel_tol=1e-4, abs_tol=1e-5):
        raise ModelError(f'Model probabilities sum to {total}, not one')
    return {key: float(values[key]) / total for key in sorted(options)}


class GlinerBackend:
    def __init__(self, model='fastino/gliner2.5-multi-v1', revision=None, device='cpu'):
        self.model_name, self.revision, self.device = model, revision, device
        self.classifier = None
        if revision is None:
            ref = Path.home() / '.cache/huggingface/hub' / ('models--' + model.replace('/', '--')) / 'refs/main'
            if ref.exists():
                self.revision = ref.read_text().strip()
            else:
                try:
                    from huggingface_hub import model_info
                    self.revision = model_info(model).sha
                except Exception as exc:
                    raise ModelError(f'Cannot resolve model revision: {exc}') from exc
        elif not re.fullmatch(r'[0-9a-fA-F]{40}', revision):
            # A moving branch/tag must never share a prediction cache or
            # calibration identity with a different checkpoint at that name.
            try:
                from huggingface_hub import model_info
                self.revision = model_info(model, revision=revision).sha
            except Exception as exc:
                raise ModelError(f'Cannot resolve model revision: {exc}') from exc
        self.identity = dict(backend='gliner', model=model, revision=self.revision, device=device, scoring='exclusive-softmax-v1')
        try:
            self.identity['runtime'] = {name: importlib.metadata.version(name) for name in ('gliner2', 'torch', 'transformers')}
        except importlib.metadata.PackageNotFoundError as exc:
            raise ModelError(f'GLiNER dependencies missing ({exc}); run uv sync --extra place') from exc

    def probabilities(self, text, options):
        try:
            from gliner2.classification import Classifier, ClassificationSchema
            if self.classifier is None:
                self.classifier = Classifier.from_pretrained(self.model_name, revision=self.revision).to(device=self.device).eval()
            # The GLiNER schema parser reserves parentheses and marker brackets.
            names = {key: f'{key}: {name}'.translate(str.maketrans({'(': ',', ')': '', '[': '', ']': ''})) for key, name in sorted(options.items())}
            schema = ClassificationSchema().single('subject', list(names.values()))
            scores = self.classifier.score(text, schema)
            logits = scores.tasks['subject']
            if set(logits) != set(names.values()):
                raise ModelError('GLiNER did not encode all requested labels; reduce option width or input length')
            maximum = max(logits.values())
            weights = {key: math.exp(logits[name] - maximum) for key, name in names.items()}
            total = math.fsum(weights.values())
            return checked_probabilities({key: value / total for key, value in weights.items()}, options)
        except ModelError:
            raise
        except ImportError as exc:
            raise ModelError(f'GLiNER dependencies missing ({exc}); run uv sync --extra place') from exc
        except Exception as exc:
            raise ModelError(f'GLiNER inference failed: {exc}') from exc


class KevBackend:
    def __init__(self, url='http://127.0.0.1:8009', model=None, timeout=180):
        self.url, self.timeout = url.rstrip('/'), timeout
        try:
            description = self.request('/v1/models')['models'][0]
            # Our launch helper exposes hashes of the actual loaded checkpoint.
            provenance = self.request('/plumb/provenance')
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError('Kev returned an invalid model descriptor') from exc
        if model and description.get('run') != model:
            raise ModelError(f"Kev serves {description.get('run')!r}, expected {model!r}")
        if not isinstance(provenance.get('fingerprint'), str) or len(provenance['fingerprint']) != 64:
            raise ModelError('Kev checkpoint fingerprint is missing; launch scripts/serve_kev.py')
        if provenance.get('probability_api') != 'full-precision-choice-v1':
            raise ModelError('Kev full-precision endpoint is missing; restart with the current scripts/serve_kev.py')
        self.identity = dict(backend='kev', model=description['run'], base=description.get('base'),
                             fingerprint=provenance['fingerprint'], device=description.get('device'),
                             runtime=provenance.get('runtime'),
                             dtype=description.get('dtype'), temperature=description.get('temperature'),
                             scoring='full-precision-choice-v1')

    def request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.url + path, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ModelError(f'Kev request failed: {exc}. Launch scripts/serve_kev.py and check --kev-url') from exc

    def probabilities(self, text, options):
        if not 1 <= len(options) <= 255:
            raise ModelError('Kev choice requests require 1–255 options')
        response = self.request('/plumb/choice-probabilities', dict(state=text, model='kev-latest', questions={
            'subject': dict(type='choice', instructions='Choose the research subject that best describes this record using its metadata.', criteria=dict(sorted(options.items())))}))
        try:
            values = response['answers']['subject']['probabilities']
        except (KeyError, TypeError) as exc:
            raise ModelError('Kev response has no subject probability distribution') from exc
        return checked_probabilities(values, options)


class CachedBackend:
    def __init__(self, backend, directory=None):
        self.backend, self.directory = backend, Path(directory) if directory else None
        self.identity = backend.identity
        self.hits = 0
        self.calls = 0

    def probabilities(self, text, options):
        payload = dict(model=self.identity, text=text, options=dict(sorted(options.items())))
        key = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = self.directory / (key + '.json') if self.directory else None
        if path and path.exists():
            saved, _ = read_json(path)
            if not isinstance(saved, dict) or saved.get('key') != key:
                raise ModelError(f'Corrupt prediction cache: {path}; remove this entry and retry')
            self.hits += 1
            return checked_probabilities(saved.get('probabilities'), options)
        values = checked_probabilities(self.backend.probabilities(text, options), options)
        self.calls += 1
        if path:
            save_json(path, dict(key=key, probabilities=values))
        return values
