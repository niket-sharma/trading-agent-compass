"""Thin wrapper around `tradectl refresh all`.

Run by GitHub Actions on a schedule, or manually:
  python scripts/refresh_static_data.py

Equivalent to: tradectl refresh all --since 2010-01-01
"""

import subprocess
import sys

if __name__ == "__main__":
    result = subprocess.run(
        [sys.executable, "-m", "tradeagent.cli", "refresh", "all", "--since", "2010-01-01"],
        check=False,
    )
    sys.exit(result.returncode)
