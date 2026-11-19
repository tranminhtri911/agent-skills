"""devskills: deterministic helpers bundled with the developer skill set.

The runtime is stdlib-only so every skill can execute it with any Python >= 3.11
without installing packages. Optional capabilities (browser screenshots) detect
their extra dependency at runtime and report `blocked` instead of failing silently.
"""

__version__ = "1.0.2"

# Version of the JSON records written by every command (run.json, checks, manifests).
SCHEMA_VERSION = "1.0"

# tomllib (3.11) and modern typing syntax are required by the runtime.
MIN_PYTHON = (3, 11)
