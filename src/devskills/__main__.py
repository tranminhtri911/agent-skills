"""Allow `python -m devskills` when the package is importable."""

import sys

from devskills.cli import main

sys.exit(main())
