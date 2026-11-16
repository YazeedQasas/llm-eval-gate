from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "judgments"


@pytest.fixture
def demo_config_path() -> Path:
    return DEMO / "evalgate.toml"


@pytest.fixture
def v1_prompt() -> Path:
    """A frozen copy of the baseline prompt, independent of what judgment.txt holds."""
    return DEMO / "prompts" / "candidates" / "v1-terse.txt"


@pytest.fixture
def v2_prompt() -> Path:
    return DEMO / "prompts" / "candidates" / "v2-fluent.txt"
