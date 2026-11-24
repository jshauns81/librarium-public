"""Inventory/verify an existing stopped backup; never capture or restore live state."""

import argparse
import json
import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from librarium.delivery_recovery import (
        RecoveryError,
        capture_baseline,
        verify_baseline,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    options = parser.parse_args()
    try:
        result = (capture_baseline if options.action == "capture" else verify_baseline)(
            options.root, options.session_id
        )
    except RecoveryError as error:
        print(json.dumps({"error": error.code}))
        return 1
    print(json.dumps({key: result[key] for key in ("schema", "generation_id", "session_id")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
