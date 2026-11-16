"""Load golden datasets with a content hash and optional tag filtering."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from evalgate.hashing import content_hash
from evalgate.schema import Case, read_cases


def dataset_hash(cases: Iterable[Case]) -> str:
    """Hash of the full dataset content, independent of line order.

    Includes `expected`, tags and metadata: changing a golden answer is a new dataset
    version and makes old baselines incomparable.
    """
    return content_hash(sorted((c.to_dict() for c in cases), key=lambda d: d["id"]))


@dataclass(frozen=True)
class Dataset:
    path: str
    cases: tuple[Case, ...]
    hash: str
    tags_filter: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.cases)

    def __iter__(self):
        return iter(self.cases)

    def by_id(self) -> dict[str, Case]:
        return {c.id: c for c in self.cases}

    def tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            for tag in case.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items()))


def filter_by_tags(cases: Iterable[Case], tags: Sequence[str]) -> list[Case]:
    """Keep cases that carry at least one of `tags`. Empty `tags` keeps everything."""
    wanted = set(tags)
    if not wanted:
        return list(cases)
    return [c for c in cases if wanted.intersection(c.tags)]


def load_dataset(path: str | Path, *, tags: Sequence[str] = ()) -> Dataset:
    """Read, validate and hash a golden JSONL file.

    The hash covers the cases that survive the tag filter, so a filtered run is its
    own dataset version and cannot be compared against an unfiltered baseline.
    """
    cases = filter_by_tags(read_cases(path), tags)
    return Dataset(
        path=Path(path).as_posix(),
        cases=tuple(cases),
        hash=dataset_hash(cases),
        tags_filter=tuple(sorted(set(tags))),
    )
