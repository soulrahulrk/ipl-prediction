import csv
import glob
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipl_predictor import DATA_DIR, ROOT_DIR


def profile_legacy_csv() -> None:
    legacy_path = ROOT_DIR / "ipl_colab.csv"
    legacy = pd.read_csv(legacy_path)

    print("LEGACY CSV")
    print("rows:", len(legacy))
    print("columns:", list(legacy.columns))
    print("date range:", legacy["date"].min(), "->", legacy["date"].max())
    print("missing values (top 10):")
    print(legacy.isna().sum().sort_values(ascending=False).head(10))
    print("unique batting teams:", legacy["batting_team"].nunique())
    print("unique bowling teams:", legacy["bowling_team"].nunique())

    if "mid" in legacy.columns and "overs" in legacy.columns:
        dup_count = legacy.duplicated(subset=["mid", "overs"]).sum()
        print("duplicate (mid, overs) rows:", dup_count)


def profile_cricsheet_csv2() -> None:
    cricsheet_dir = DATA_DIR / "ipl_csv2"
    match_files = [p for p in glob.glob(str(cricsheet_dir / "*.csv")) if not p.endswith("_info.csv")]
    info_files = [p for p in glob.glob(str(cricsheet_dir / "*_info.csv"))]

    print("\nCRICSHEET CSV2")
    print("match files:", len(match_files))
    print("info files:", len(info_files))

    min_date = None
    max_date = None
    winners = Counter()
    no_results = 0
    for info in info_files:
        with open(info, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 3:
                    continue
                if row[0] == "info" and row[1] == "date":
                    try:
                        dt = datetime.strptime(row[2], "%Y/%m/%d").date()
                    except ValueError:
                        continue
                    if min_date is None or dt < min_date:
                        min_date = dt
                    if max_date is None or dt > max_date:
                        max_date = dt
                if row[0] == "info" and row[1] == "winner":
                    winners[row[2]] += 1
                if row[0] == "info" and row[1] == "result" and row[2] in ("no result", "tie"):
                    no_results += 1

    print("date range:", min_date, "->", max_date)
    print("winners count (top 5):", winners.most_common(5))
    print("no result/tie entries:", no_results)


if __name__ == "__main__":
    profile_legacy_csv()
    profile_cricsheet_csv2()
