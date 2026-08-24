"""Make the demo runnable offline: turn committed fixtures into cache entries.

    python scripts/seed_cache.py

Run this once on a fresh checkout. The cache itself is derived and gitignored;
`fixtures/` plus `fixtures/INDEX.json` are the committed source of truth, and
this script rebuilds the cache from them.

Makes no network calls.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from acclimate.sources.cache import DiskCache  # noqa: E402
from acclimate.sources.fixtures import FixtureStore  # noqa: E402
from acclimate.sources.seed import seed_cache  # noqa: E402


def main():
    store = FixtureStore()
    cache = DiskCache()
    print("fixtures  %s" % store.root)
    print("cache     %s\n" % cache.root)

    result = seed_cache(cache=cache, store=store)

    for name, key in result.seeded:
        print("  seeded    %-46s %s" % (name, key))
    for name in result.already_present:
        print("  present   %s" % name)
    for name in result.derived_skipped:
        print("  derived   %-46s (summary, not an API response)" % name)
    for name in result.missing_files:
        print("  MISSING   %s" % name)

    stats = cache.stats()
    print("\n%s" % result.summary())
    print("cache now holds %d entries, %.1f MB"
          % (stats["entries"], stats["bytes"] / 1e6))

    if not result.ok:
        print("\nFAIL: fixtures declared in INDEX.json are absent from disk.")
        return 1
    print("\nThe demo can now run with the network disconnected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
