from __future__ import annotations

import yaml

from app.services.knowledge_export import _paper_to_markdown, to_bibtex


def _front_matter(md: str) -> dict:
    # Front-matter is the block between the first pair of '---' fences.
    _, fm, _rest = md.split("---", 2)
    return yaml.safe_load(fm)


def test_paper_frontmatter_is_valid_yaml_with_quotes_and_backslash() -> None:
    paper = {
        "id": "pk_1",
        "metadata": {
            "title": 'He said "hello" \\ world: a study',
            "authors": [{"name": 'O\'Neil, "J"'}],
            "keywords": ["graph, networks", "rl"],
            "doi": "10.1/x",
        },
    }

    data = _front_matter(_paper_to_markdown(paper))

    assert data["title"] == 'He said "hello" \\ world: a study'
    assert data["authors"] == ['O\'Neil, "J"']
    assert data["tags"] == ["graph, networks", "rl"]


def test_bibtex_escapes_special_chars_and_sanitizes_key() -> None:
    metadata = {
        "title": "Cost & Effect: 50% gains in {RL}",
        "authors": [{"name": "Doe, Jane"}, {"name": "Smith, A."}],
        "year": 2024,
        "venue": "Proc. of C&C",
    }

    entry = to_bibtex(metadata, "pk 1!@#")

    # LaTeX specials are escaped so the .bib stays parseable.
    assert r"\&" in entry
    assert r"\%" in entry
    # Cite key contains only safe characters.
    cite_key = entry.split("{", 1)[1].split(",", 1)[0]
    assert cite_key and all(c.isalnum() or c in "-_:" for c in cite_key)
    assert "Doe, Jane and Smith, A." in entry
