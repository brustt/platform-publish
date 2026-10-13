"""A licence is an SPDX identifier or the word `custom`. The SPDX list is bundled so validation stays offline."""
from functools import lru_cache
from importlib import resources

CUSTOM = "custom"


@lru_cache(maxsize=1)
def spdx_ids() -> frozenset[str]:
    return frozenset(resources.files("platform_publish").joinpath("spdx_ids.txt").read_text().split())


def is_valid(licence: str) -> bool:
    return licence == CUSTOM or licence in spdx_ids()


def problem(licence: str) -> str:
    return f"licence '{licence}' is not an SPDX identifier (such as CC-BY-4.0) or 'custom'"
