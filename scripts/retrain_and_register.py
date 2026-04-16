from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT_DIR / "models"
REGISTRY_PATH = MODELS_DIR / "model_registry.json"
PIPELINE_REPORT_PATH = MODELS_DIR / "canonical_pipeline_report.json"

DEPLOYMENT_REPORT_PATH = MODELS_DIR / "deployment_report.json"
BEST_SEARCH_REPORT_PATH = MODELS_DIR / "best_model_search_report.json"
PRE_MATCH_REPORT_PATH = MODELS_DIR / "pre_match_model_report.json"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_step(script_name: str) -> float:
    script_path = ROOT_DIR / "scripts" / script_name
    cmd = [sys.executable, str(script_path)]
    print(f"[retrain] running: {' '.join(cmd)}")
    started = datetime.now(timezone.utc)
    subprocess.run(cmd, check=True, cwd=str(ROOT_DIR))
    finished = datetime.now(timezone.utc)
    return float((finished - started).total_seconds())


def run_tests() -> float:
    cmd = [sys.executable, "-m", "pytest", "-q"]
    print(f"[retrain] running: {' '.join(cmd)}")
    started = datetime.now(timezone.utc)
    subprocess.run(cmd, check=True, cwd=str(ROOT_DIR))
    finished = datetime.now(timezone.utc)
    return float((finished - started).total_seconds())


def try_git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT_DIR),
            text=True,
        ).strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_record(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {
            "path": str(path.relative_to(ROOT_DIR)),
            "exists": False,
        }
    return {
        "path": str(path.relative_to(ROOT_DIR)),
        "exists": True,
        "size_bytes": int(path.stat().st_size),
        "sha256": sha256_of(path),
        "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def validate_artifact_consistency(run_started_at: datetime, require_pre_match: bool) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    deployment_report = read_json_if_exists(DEPLOYMENT_REPORT_PATH)
    best_search_report = read_json_if_exists(BEST_SEARCH_REPORT_PATH)
    pre_match_report = read_json_if_exists(PRE_MATCH_REPORT_PATH)

    add_check(
        "deployment_report_exists",
        bool(deployment_report),
        str(DEPLOYMENT_REPORT_PATH.relative_to(ROOT_DIR)),
    )
    add_check(
        "best_search_report_exists",
        bool(best_search_report),
        str(BEST_SEARCH_REPORT_PATH.relative_to(ROOT_DIR)),
    )
    if require_pre_match:
        add_check(
            "pre_match_report_exists",
            bool(pre_match_report),
            str(PRE_MATCH_REPORT_PATH.relative_to(ROOT_DIR)),
        )

    selected_score = str(best_search_report.get("selected_score_model", ""))
    selected_win = str(best_search_report.get("selected_win_model", ""))
    deployed_score = str(deployment_report.get("deployment_score_model", ""))
    deployed_win = str(deployment_report.get("deployment_win_model", ""))

    add_check(
        "score_model_consistent",
        bool(selected_score) and selected_score == deployed_score,
        f"selected={selected_score}, deployed={deployed_score}",
    )
    add_check(
        "win_model_consistent",
        bool(selected_win) and selected_win == deployed_win,
        f"selected={selected_win}, deployed={deployed_win}",
    )

    required_artifacts = [
        MODELS_DIR / "score_model.pkl",
        MODELS_DIR / "win_model.pkl",
        MODELS_DIR / "score_uncertainty.json",
        MODELS_DIR / "win_stability_profile.json",
        DEPLOYMENT_REPORT_PATH,
        BEST_SEARCH_REPORT_PATH,
    ]
    if require_pre_match:
        required_artifacts.extend(
            [
                MODELS_DIR / "pre_match_score_model.pkl",
                MODELS_DIR / "pre_match_win_model.pkl",
                PRE_MATCH_REPORT_PATH,
            ]
        )

    for artifact in required_artifacts:
        exists = artifact.exists() and artifact.is_file()
        add_check(
            f"artifact_exists:{artifact.name}",
            exists,
            str(artifact.relative_to(ROOT_DIR)),
        )
        if exists:
            modified_at = datetime.fromtimestamp(artifact.stat().st_mtime, tz=timezone.utc)
            add_check(
                f"artifact_fresh:{artifact.name}",
                modified_at >= run_started_at,
                f"modified={modified_at.isoformat()}, run_started={run_started_at.isoformat()}",
            )

    return {
        "ok": bool(all(c["passed"] for c in checks)),
        "checked_at_utc": now_utc_iso(),
        "checks": checks,
    }


def load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"latest_version": None, "entries": []}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if "entries" not in data or not isinstance(data["entries"], list):
            data["entries"] = []
        return data
    except Exception:
        return {"latest_version": None, "entries": []}


def save_registry(registry: dict[str, Any]) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def build_registry_entry(
    version_id: str,
    executed_steps: list[str],
    consistency: dict[str, Any],
    pipeline_report_path: Path,
) -> dict[str, Any]:
    deployment_report = read_json_if_exists(MODELS_DIR / "deployment_report.json")
    best_search_report = read_json_if_exists(MODELS_DIR / "best_model_search_report.json")
    pre_match_report = read_json_if_exists(MODELS_DIR / "pre_match_model_report.json")

    artifact_paths = [
        MODELS_DIR / "score_model.pkl",
        MODELS_DIR / "win_model.pkl",
        MODELS_DIR / "pre_match_score_model.pkl",
        MODELS_DIR / "pre_match_win_model.pkl",
        MODELS_DIR / "score_uncertainty.json",
        MODELS_DIR / "win_stability_profile.json",
        MODELS_DIR / "deployment_report.json",
        MODELS_DIR / "best_model_search_report.json",
        MODELS_DIR / "pre_match_model_report.json",
    ]

    return {
        "version_id": version_id,
        "created_at_utc": now_utc_iso(),
        "git_commit": try_git_commit(),
        "executed_steps": executed_steps,
        "metrics": {
            "live": {
                "scope": deployment_report.get("deployment_scope"),
                "score_model": deployment_report.get("deployment_score_model"),
                "win_model": deployment_report.get("deployment_win_model"),
                "score_test": deployment_report.get("deployment_score_metrics_test", {}),
                "win_test": deployment_report.get("deployment_win_metrics_test", {}),
            },
            "pre_match": {
                "split": pre_match_report.get("split", {}),
                "score_test": pre_match_report.get("score_metrics", {}).get("test", {}),
                "win_test": pre_match_report.get("win_metrics", {}).get("test", {}),
            },
            "selected_win_stability": best_search_report.get("selected_win_stability", {}),
        },
        "consistency": consistency,
        "canonical_report": str(pipeline_report_path.relative_to(ROOT_DIR)),
        "artifacts": [artifact_record(path) for path in artifact_paths],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retraining pipeline and register artifacts/versions.")
    parser.add_argument("--skip-update", action="store_true", help="Skip external data refresh step.")
    parser.add_argument("--skip-pre-match", action="store_true", help="Skip pre-match model retraining.")
    parser.add_argument("--run-tests", action="store_true", help="Run pytest after retraining.")
    parser.add_argument(
        "--skip-consistency-check",
        action="store_true",
        help="Skip strict artifact consistency checks before registry update.",
    )
    args = parser.parse_args()

    run_started_at = datetime.now(timezone.utc)
    steps: list[str] = []
    step_timings: list[dict[str, Any]] = []

    if not args.skip_update:
        duration = run_step("update_external_data.py")
        steps.append("update_external_data.py")
        step_timings.append({"step": "update_external_data.py", "seconds": round(duration, 2)})

    duration = run_step("preprocess_ipl.py")
    steps.append("preprocess_ipl.py")
    step_timings.append({"step": "preprocess_ipl.py", "seconds": round(duration, 2)})

    duration = run_step("train_best_model_search.py")
    steps.append("train_best_model_search.py")
    step_timings.append({"step": "train_best_model_search.py", "seconds": round(duration, 2)})

    if not args.skip_pre_match:
        duration = run_step("train_pre_match.py")
        steps.append("train_pre_match.py")
        step_timings.append({"step": "train_pre_match.py", "seconds": round(duration, 2)})

    if args.run_tests:
        duration = run_tests()
        steps.append("pytest -q")
        step_timings.append({"step": "pytest -q", "seconds": round(duration, 2)})

    consistency = validate_artifact_consistency(run_started_at, require_pre_match=not args.skip_pre_match)
    if not args.skip_consistency_check and not consistency.get("ok", False):
        failed = [c for c in consistency.get("checks", []) if not c.get("passed", False)]
        raise RuntimeError(f"Canonical consistency checks failed: {failed}")

    version_id = datetime.now(timezone.utc).strftime("v%Y%m%d_%H%M%S")
    pipeline_report = {
        "version_id": version_id,
        "created_at_utc": now_utc_iso(),
        "steps": steps,
        "step_timings": step_timings,
        "consistency": consistency,
    }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    PIPELINE_REPORT_PATH.write_text(json.dumps(pipeline_report, indent=2), encoding="utf-8")

    entry = build_registry_entry(
        version_id=version_id,
        executed_steps=steps,
        consistency=consistency,
        pipeline_report_path=PIPELINE_REPORT_PATH,
    )

    registry = load_registry()
    registry.setdefault("entries", []).append(entry)
    registry["latest_version"] = version_id
    save_registry(registry)

    print("[retrain] completed")
    print(f"[retrain] latest version: {version_id}")
    print(f"[retrain] registry path: {REGISTRY_PATH}")
    print(f"[retrain] canonical report path: {PIPELINE_REPORT_PATH}")


if __name__ == "__main__":
    main()
