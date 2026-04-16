# Changelog

## 2026-04-09

### Changed (Historical)

- Rewrote README to match current code paths, training scripts, and promoted artifact flow.
- Updated setup and run instructions for CLI, Flask, Streamlit, and all training workflows.
- Added current deployment snapshot details from models/deployment_report.json.

### Documentation (Historical)

- Replaced docs/API.md with an updated live and pre-match contract reference.
- Replaced docs/ARCHITECTURE.md to reflect the current multi-workflow training and promotion design.
- Removed stale statements that conflicted with current scripts.

## 2026-04-08

### Changed

- Added and iterated on deployment-selection reporting.
- Expanded training scripts to compare candidate model families and write deployment summaries.

### Added

- Flask JSON route: POST /api/predict
- Flask pre-match UI flow
- tests for:
  - real saved-model live inference
  - real saved-model pre-match inference
  - Flask /api/predict

### Documentation

- Rewrote README and core docs to match the actual code and current metrics.
- Removed stale references to the old predict_match API and outdated leaderboard claims.

### Current Deployment Artifacts

- models/score_model.pkl
- models/win_model.pkl

### Current Deployment Metrics

- Metrics captured in the corresponding model report files generated at run time.

### Notes

- Deployment win-model selection currently optimizes held-out probability quality, not raw classification accuracy.
- The recent-season win task remains the weakest part of the project.
