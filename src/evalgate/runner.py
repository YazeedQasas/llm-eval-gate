"""Produce outputs for a dataset: replay (default, offline) or live recording."""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path

from evalgate.adapters import Adapter, LiveAdapter, ReplayAdapter, ReplayCache
from evalgate.config import Config, ConfigError
from evalgate.datasets import Dataset, load_dataset
from evalgate.schema import Case


def dataset_for(config: Config) -> Dataset:
    return load_dataset(config.dataset, tags=config.dataset_tags)


def load_cache(config: Config) -> ReplayCache:
    path = config.system.recordings
    return ReplayCache.load(path) if path.exists() else ReplayCache()


def replay_adapter(config: Config, cache: ReplayCache | None = None) -> ReplayAdapter:
    s = config.system
    return ReplayAdapter(
        name=s.name,
        version=s.prompt_version(),
        model=s.model,
        cache=cache if cache is not None else load_cache(config),
        params=s.params,
    )


def _load_factory(config: Config):
    spec = config.system.live
    if not spec or ":" not in spec:
        raise ConfigError("[system] live must be 'module:factory' to record outputs")
    module_name, attr = spec.split(":", 1)
    root = str(config.root)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    try:
        module = importlib.import_module(module_name)
    finally:
        if added:
            sys.path.remove(root)
    try:
        return getattr(module, attr)
    except AttributeError:
        raise ConfigError(f"{module_name} has no attribute {attr!r}") from None


def live_adapter(config: Config, cache: ReplayCache) -> LiveAdapter:
    s = config.system
    factory = _load_factory(config)
    return LiveAdapter(
        name=s.name,
        version=s.prompt_version(),
        model=s.model,
        fn=factory(s.prompt_text()),
        cache=cache,
        params=s.params,
    )


def generate_all(adapter: Adapter, cases: Iterable[Case]) -> dict[str, str]:
    return {case.id: adapter.generate(case) for case in cases}


def record(config: Config, cases: Iterable[Case] | None = None) -> int:
    """Call the live system for every case and merge the outputs into the recordings file."""
    cache = load_cache(config)
    adapter = live_adapter(config, cache)
    cases = list(cases) if cases is not None else list(dataset_for(config))
    for case in cases:
        if adapter.key_for(case) in cache:
            continue
        adapter.generate(case)
    cache.save(config.system.recordings)
    return len(cases)


def write_outputs(outputs: dict[str, str], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as fh:
        for cid in sorted(outputs):
            fh.write(json.dumps({"case_id": cid, "output": outputs[cid]}, ensure_ascii=False))
            fh.write("\n")


def read_outputs(path: str | Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with Path(path).open(encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                rec = json.loads(line)
                out[rec["case_id"]] = rec["output"]
    return out
