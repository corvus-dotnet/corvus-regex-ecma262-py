"""The examples of the getting-started page the documentation site publishes (docs/getting-started.md), each block of
Python run on its own, so that the page shows only code that works."""

import pathlib
import re

import pytest

PAGE = pathlib.Path(__file__).resolve().parent.parent / "docs" / "getting-started.md"
BLOCKS = re.findall(r"^```python\n(.*?)^```$", PAGE.read_text(encoding="utf-8"), flags=re.S | re.M)


def test_the_page_has_examples():
    assert len(BLOCKS) >= 5


@pytest.mark.parametrize("block", BLOCKS, ids=[f"block-{n + 1}" for n in range(len(BLOCKS))])
def test_example(block):
    exec(compile(block, str(PAGE), "exec"), {})
