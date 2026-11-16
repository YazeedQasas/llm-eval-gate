"""evalgate.toml: one file that pins the dataset, system, scorers, guards and gate.

Relative paths resolve against the config file's directory, so a config can be run
from anywhere. See docs/config.md.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evalgate.adapters import GenerationParams
from evalgate.hashing import content_hash

GUARD_MODES = ("fail", "exclude", "warn")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ScorerSpec:
    name: str
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "options": dict(self.options)}


@dataclass(frozen=True)
class GuardConfig:
    mode: str = "fail"
    self_retrieval: dict[str, Any] = field(default_factory=dict)
    answer_bearing: dict[str, Any] = field(default_factory=dict)
    whole_text_trap: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "self_retrieval": dict(self.self_retrieval),
            "answer_bearing": dict(self.answer_bearing),
            "whole_text_trap": dict(self.whole_text_trap),
        }


@dataclass(frozen=True)
class GateConfig:
    primary: str
    baseline: Path
    max_drop: float = 0.02
    max_tag_drop: float = 0.10
    min_tag_cases: int = 5
    max_regressed: int | None = None
    alpha: float = 0.05

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "max_drop": self.max_drop,
            "max_tag_drop": self.max_tag_drop,
            "min_tag_cases": self.min_tag_cases,
            "max_regressed": self.max_regressed,
            "alpha": self.alpha,
        }


@dataclass(frozen=True)
class SystemConfig:
    name: str
    model: str
    prompt: Path
    recordings: Path
    params: GenerationParams = field(default_factory=GenerationParams)
    live: str | None = None  # "module:factory", factory(prompt_text) -> fn(case, params)

    def prompt_text(self) -> str:
        try:
            return self.prompt.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ConfigError(f"prompt file not found: {self.prompt}") from None

    def prompt_version(self) -> str:
        """The adapter version: a hash of the prompt text, so any edit is a new version."""
        return content_hash(self.prompt_text())[:12]


@dataclass(frozen=True)
class Config:
    path: Path
    root: Path
    dataset: Path
    dataset_tags: tuple[str, ...]
    system: SystemConfig
    scorers: tuple[ScorerSpec, ...]
    guards: GuardConfig
    gate: GateConfig

    def with_prompt(self, prompt: str | Path | None) -> Config:
        """Copy with a different prompt file (used to try a candidate prompt)."""
        if prompt is None:
            return self
        sys_cfg = SystemConfig(
            name=self.system.name,
            model=self.system.model,
            prompt=Path(prompt).resolve(),
            recordings=self.system.recordings,
            params=self.system.params,
            live=self.system.live,
        )
        return Config(
            path=self.path,
            root=self.root,
            dataset=self.dataset,
            dataset_tags=self.dataset_tags,
            system=sys_cfg,
            scorers=self.scorers,
            guards=self.guards,
            gate=self.gate,
        )

    def eval_config_hash(self) -> str:
        """Everything besides dataset and scorers that changes what a score means."""
        return content_hash({"guards": self.guards.to_dict(), "primary": self.gate.primary})


def _section(data: dict, name: str, required: bool = True) -> dict:
    value = data.get(name)
    if value is None:
        if required:
            raise ConfigError(f"missing [{name}] section")
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _req(table: dict, key: str, section: str) -> Any:
    if key not in table:
        raise ConfigError(f"missing '{key}' in [{section}]")
    return table[key]


def load_config(path: str | Path) -> Config:
    p = Path(path).resolve()
    try:
        with p.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"config not found: {p}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{p}: invalid TOML ({exc})") from exc
    root = p.parent

    def rel(value: str) -> Path:
        return (root / value).resolve()

    ds = _section(data, "dataset")
    sys_t = _section(data, "system")
    params_t = sys_t.get("params", {})
    known_params = {"temperature", "seed", "max_tokens"}
    params = GenerationParams(
        temperature=float(params_t.get("temperature", 0.0)),
        seed=params_t.get("seed", 0),
        max_tokens=params_t.get("max_tokens"),
        extra={k: v for k, v in params_t.items() if k not in known_params},
    )
    system = SystemConfig(
        name=_req(sys_t, "name", "system"),
        model=_req(sys_t, "model", "system"),
        prompt=rel(_req(sys_t, "prompt", "system")),
        recordings=rel(_req(sys_t, "recordings", "system")),
        params=params,
        live=sys_t.get("live"),
    )

    scorers_raw = data.get("scorers", [])
    if not isinstance(scorers_raw, list) or not scorers_raw:
        raise ConfigError("define at least one [[scorers]] entry")
    scorers = []
    for entry in scorers_raw:
        if not isinstance(entry, dict) or "name" not in entry:
            raise ConfigError("each [[scorers]] entry needs a 'name'")
        options = {k: v for k, v in entry.items() if k != "name"}
        scorers.append(ScorerSpec(name=entry["name"], options=options))
    names = [s.name for s in scorers]
    if len(set(names)) != len(names):
        raise ConfigError(f"duplicate scorer names: {names}")

    g = _section(data, "guards", required=False)
    mode = g.get("mode", "fail")
    if mode not in GUARD_MODES:
        raise ConfigError(f"[guards] mode must be one of {GUARD_MODES}, got {mode!r}")
    guards = GuardConfig(
        mode=mode,
        self_retrieval=g.get("self_retrieval", {}),
        answer_bearing=g.get("answer_bearing", {}),
        whole_text_trap=g.get("whole_text_trap", {}),
    )

    gt = _section(data, "gate")
    primary = gt.get("primary", names[0])
    if primary not in names:
        raise ConfigError(f"[gate] primary {primary!r} is not one of the scorers {names}")
    max_regressed = gt.get("max_regressed")
    gate = GateConfig(
        primary=primary,
        baseline=rel(_req(gt, "baseline", "gate")),
        max_drop=float(gt.get("max_drop", 0.02)),
        max_tag_drop=float(gt.get("max_tag_drop", 0.10)),
        min_tag_cases=int(gt.get("min_tag_cases", 5)),
        max_regressed=None if max_regressed is None else int(max_regressed),
        alpha=float(gt.get("alpha", 0.05)),
    )

    tags = ds.get("tags", [])
    return Config(
        path=p,
        root=root,
        dataset=rel(_req(ds, "path", "dataset")),
        dataset_tags=tuple(tags),
        system=system,
        scorers=tuple(scorers),
        guards=guards,
        gate=gate,
    )
