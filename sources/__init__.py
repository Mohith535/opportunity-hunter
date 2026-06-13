"""
Source registry.

Each source module exposes a `fetch() -> list[Opportunity]`. They are registered
here by name. main.py iterates the registry; `--sources a,b` filters it; adding a
new source later is "write the module + add one line here".
"""

from . import github, news, research

# name -> fetch callable
REGISTRY = {
    "arxiv": research.fetch,
    "github": github.fetch,
    "hackernews": news.fetch_hackernews,
    # added later: "reddit", "devpost", "mlh", "unstop", "devfolio", "clist"
}


def available_sources() -> list[str]:
    return list(REGISTRY)


def get_sources(names: list[str] | None = None) -> dict:
    """Return the subset of the registry to run.

    `names=None` -> all registered sources. Unknown names are ignored.
    """
    if not names:
        return dict(REGISTRY)
    return {n: REGISTRY[n] for n in names if n in REGISTRY}
