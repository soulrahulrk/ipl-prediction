from __future__ import annotations

import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipl_predictor import DATA_DIR
from ipl_predictor.live_data import VENUE_COORDS, fetch_live_weather_context


CRICSHEET_IPL_CSV2_URL = "https://cricsheet.org/downloads/ipl_csv2.zip"


def download_latest_cricsheet_csv2() -> None:
    target_dir = DATA_DIR / "ipl_csv2"
    target_dir.mkdir(parents=True, exist_ok=True)

    print("Downloading latest IPL CSV2 archive from Cricsheet...")
    with urllib.request.urlopen(CRICSHEET_IPL_CSV2_URL, timeout=60) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Failed to download Cricsheet archive: HTTP {resp.status}")
        payload = resp.read()

    print("Extracting archive into data/ipl_csv2 ...")
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        zf.extractall(target_dir)

    print("Done: latest Cricsheet IPL CSV2 data downloaded.")


def snapshot_live_weather() -> None:
    out_path = DATA_DIR / "processed" / "live_weather_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    snapshot = {}
    for venue in sorted(VENUE_COORDS):
        snapshot[venue] = fetch_live_weather_context(venue)

    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"Done: wrote weather snapshot to {out_path}")


def main() -> None:
    download_latest_cricsheet_csv2()
    snapshot_live_weather()


if __name__ == "__main__":
    main()
