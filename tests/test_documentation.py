from pathlib import Path


def test_readme_separates_execution_pattern_and_production_limits() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    headings = [
        line
        for line in readme.splitlines()
        if line
        in {
            "## Run locally",
            "## Illustrated pattern",
            "## Production limits",
        }
    ]
    assert headings == [
        "## Run locally",
        "## Illustrated pattern",
        "## Production limits",
    ]
