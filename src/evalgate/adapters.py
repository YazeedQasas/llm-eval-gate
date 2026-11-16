"""System-under-test adapters and the replay cache.

An adapter turns a golden case into an output. There are two modes:

* **live**: calls a real model through a function you provide, and records every
  output to a cache file. Used on a developer machine to (re)record outputs.
* **replay**: reads outputs from the cache file. It never touches the network and
  fails loudly on a cache miss. CI only ever runs replay.

A recorded output is keyed by `cache_key(...)`: a hash of the adapter name and version
(the prompt version), the model, the generation params, and the parts of the case the
model can see (`Case.model_view()`). The expected answer is not part of the key.

See docs/replay.md.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from evalgate.hashing import content_hash
from evalgate.schema import Case

CACHE_FORMAT_VERSION = 1


class CacheMiss(LookupError):
    """Replay was asked for an output that was never recorded."""


class NondeterministicParams(ValueError):
    """Live mode was configured with sampling that cannot be reproduced."""


@dataclass(frozen=True)
class GenerationParams:
    """Sampling settings. Defaults are the deterministic ones."""

    temperature: float = 0.0
    seed: int | None = 0
    max_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": self.max_tokens,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerationParams:
        return cls(
            temperature=data.get("temperature", 0.0),
            seed=data.get("seed", 0),
            max_tokens=data.get("max_tokens"),
            extra=dict(data.get("extra", {})),
        )


@runtime_checkable
class Adapter(Protocol):
    """Anything that can produce an output for a case."""

    name: str
    version: str

    def generate(self, case: Case) -> str: ...


def cache_key(
    *, adapter: str, adapter_version: str, model: str, params: GenerationParams, case: Case
) -> str:
    return content_hash(
        {
            "format": CACHE_FORMAT_VERSION,
            "adapter": adapter,
            "adapter_version": adapter_version,
            "model": model,
            "params": params.to_dict(),
            "case": case.model_view(),
        }
    )


@dataclass(frozen=True)
class Recording:
    key: str
    case_id: str
    adapter: str
    adapter_version: str
    model: str
    params: GenerationParams
    output: str
    recorded_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "case_id": self.case_id,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "model": self.model,
            "params": self.params.to_dict(),
            "output": self.output,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Recording:
        return cls(
            key=data["key"],
            case_id=data["case_id"],
            adapter=data["adapter"],
            adapter_version=data["adapter_version"],
            model=data["model"],
            params=GenerationParams.from_dict(data.get("params", {})),
            output=data["output"],
            recorded_at=data.get("recorded_at", ""),
        )


class ReplayCache:
    """Recorded outputs, stored as JSONL (one Recording per line).

    Loading the same key twice with different outputs is an error: a cache must
    describe one deterministic system.
    """

    def __init__(self, recordings: Iterable[Recording] = ()):
        self._by_key: dict[str, Recording] = {}
        for rec in recordings:
            self.add(rec)

    def __len__(self) -> int:
        return len(self._by_key)

    def __contains__(self, key: str) -> bool:
        return key in self._by_key

    def add(self, rec: Recording) -> None:
        existing = self._by_key.get(rec.key)
        if existing is not None and existing.output != rec.output:
            raise ValueError(
                f"conflicting outputs recorded for case {rec.case_id!r} (key {rec.key[:12]}); "
                "re-record the cache instead of appending to it"
            )
        self._by_key[rec.key] = rec

    def get(self, key: str) -> Recording:
        try:
            return self._by_key[key]
        except KeyError:
            raise CacheMiss(key) from None

    def recordings(self) -> list[Recording]:
        """Stable order (by case id, then key) so written files diff cleanly."""
        return sorted(self._by_key.values(), key=lambda r: (r.case_id, r.key))

    @classmethod
    def load(cls, path: str | Path) -> ReplayCache:
        p = Path(path)
        recs: list[Recording] = []
        with p.open(encoding="utf-8-sig") as fh:
            for lineno, raw in enumerate(fh, start=1):
                if not raw.strip():
                    continue
                try:
                    recs.append(Recording.from_dict(json.loads(raw)))
                except (json.JSONDecodeError, KeyError) as exc:
                    raise ValueError(f"{p}: line {lineno}: bad recording ({exc})") from exc
        return cls(recs)

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8", newline="\n") as fh:
            for rec in self.recordings():
                fh.write(json.dumps(rec.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


@dataclass
class ReplayAdapter:
    """Serves recorded outputs. No network, no model, no randomness."""

    name: str
    version: str
    model: str
    cache: ReplayCache
    params: GenerationParams = field(default_factory=GenerationParams)

    def key_for(self, case: Case) -> str:
        return cache_key(
            adapter=self.name,
            adapter_version=self.version,
            model=self.model,
            params=self.params,
            case=case,
        )

    def generate(self, case: Case) -> str:
        key = self.key_for(case)
        try:
            return self.cache.get(key).output
        except CacheMiss:
            raise CacheMiss(
                f"no recorded output for case {case.id!r} with adapter "
                f"{self.name}@{self.version}, model {self.model!r} (key {key[:12]}). "
                "The prompt, model, params or case changed since recording: "
                "re-record with live mode."
            ) from None


GenerateFn = Callable[[Case, GenerationParams], str]


@dataclass
class LiveAdapter:
    """Calls a real model through `fn` and records every output into `cache`.

    `fn(case, params)` is yours to write (it builds the prompt and calls the provider).
    Bump `version` whenever the prompt changes, so old recordings stop matching.
    """

    name: str
    version: str
    model: str
    fn: GenerateFn
    cache: ReplayCache
    params: GenerationParams = field(default_factory=GenerationParams)
    allow_nondeterministic: bool = False
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def __post_init__(self) -> None:
        if not self.allow_nondeterministic and self.params.temperature != 0:
            raise NondeterministicParams(
                f"temperature={self.params.temperature}: live recording is pinned to "
                "temperature 0. Pass allow_nondeterministic=True to override."
            )

    def key_for(self, case: Case) -> str:
        return cache_key(
            adapter=self.name,
            adapter_version=self.version,
            model=self.model,
            params=self.params,
            case=case,
        )

    def generate(self, case: Case) -> str:
        output = self.fn(case, self.params)
        if not isinstance(output, str):
            raise TypeError(f"generate fn returned {type(output).__name__}, expected str")
        self.cache.add(
            Recording(
                key=self.key_for(case),
                case_id=case.id,
                adapter=self.name,
                adapter_version=self.version,
                model=self.model,
                params=self.params,
                output=output,
                recorded_at=self.clock().isoformat(timespec="seconds"),
            )
        )
        return output
