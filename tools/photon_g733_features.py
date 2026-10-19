#!/usr/bin/env python3
"""Read-only lookup of G733 runtime features, including event feature IDs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.hid_transport import HidTransport
from photon.hidpp import HidppClient
from tools.photon_hidpp_query import _g733_path


WIRELESS_DEVICE_STATUS = 0x1D4B
UNIFIED_BATTERY = 0x1004


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    with HidTransport().open_session(_g733_path()) as session:
        client = HidppClient(session, force_long_reports=True)
        known_features = {
            f"0x{feature_id:04X}": client.get_feature_index(feature_id)
            for feature_id in (WIRELESS_DEVICE_STATUS, UNIFIED_BATTERY)
        }
        advertised_features = client.list_features()
    result = {
        "known_features": {
            feature_id: (
            {"index": feature.index, "flags": feature.flags, "version": feature.version}
            if feature is not None
            else None
            )
            for feature_id, feature in known_features.items()
        },
        "advertised_features": [
            {"id": f"0x{feature.feature_id:04X}", "index": feature.index, "flags": feature.flags}
            for feature in advertised_features
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
