from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any


IGNORED_DIRS = {
    ".git",
    ".venv",
    ".venv-1",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".vscode",
    "catboost_info",
    "ipl_predictor.egg-info",
}

TEXT_EXTENSIONS = {
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".json",
    ".js",
    ".md",
    ".mako",
    ".py",
    ".sql",
    ".tex",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

CATEGORY_ORDER = [
    "entrypoint",
    "package",
    "scripts",
    "templates",
    "static",
    "config",
    "tests",
    "data",
    "models",
    "docs",
    "other",
]

CATEGORY_LABELS = {
    "entrypoint": "Entry Points",
    "package": "Core Package",
    "scripts": "Scripts",
    "templates": "Templates",
    "static": "Static",
    "config": "Config",
    "tests": "Tests",
    "data": "Data",
    "models": "Models",
    "docs": "Docs",
    "other": "Other",
}

RELATION_LABELS = {
    "imports": "Imports",
    "reads": "Reads",
    "writes": "Writes",
    "renders": "Renders",
    "references": "References",
    "defines_path": "Defines Path",
}

SUMMARY_DIRECTORIES = {
    "data/ipl_csv2": ("data", "Raw Cricsheet CSV2 source archive."),
    "data/monitoring": ("data", "Monitoring event and outcome logs."),
    "models/archive": ("models", "Archived experiment artifacts."),
    "docs/reports": ("docs", "Generated project reports."),
    "notebooks": ("docs", "Exploration notebooks and scratch analysis."),
    "alembic": ("config", "Database migration environment and revisions."),
}

TOP_LEVEL_INCLUDE = {
    ".env.example",
    ".gitignore",
    "CHANGELOG.md",
    "Dockerfile",
    "README.md",
    "alembic.ini",
    "predict_cli.py",
    "pyproject.toml",
    "requirements.txt",
    "streamlit_app.py",
    "web_app.py",
}

GENERATED_MAP_REL_PATH = "docs/project_map.html"

DOC_EXTENSIONS = {".md", ".tex"}
DATA_EXTENSIONS = {".csv", ".json", ".zip"}
MODEL_EXTENSIONS = {".csv", ".json", ".pkl"}

REPO_REF_RE = re.compile(
    r"(?P<path>(?:data|docs|ipl_predictor|models|scripts|static|templates|tests|alembic)"
    r"(?:[\\/][A-Za-z0-9_. ()-]+)+)"
)


@dataclass(frozen=True)
class Node:
    node_id: str
    label: str
    rel_path: str
    abs_path: str
    category: str
    kind: str
    description: str
    file_url: str
    file_count: int | None = None


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    detail: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_posix(path: Path) -> str:
    return path.as_posix().strip("./")


def _is_ignored(path: Path, repo_root: Path) -> bool:
    rel_parts = path.relative_to(repo_root).parts
    return any(part in IGNORED_DIRS for part in rel_parts)


def _is_text_file(path: Path) -> bool:
    rel_path = _as_posix(path)
    if rel_path.endswith(GENERATED_MAP_REL_PATH):
        return False
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in TOP_LEVEL_INCLUDE


def _should_include_file(path: Path, repo_root: Path) -> bool:
    rel_path = _as_posix(path.relative_to(repo_root))
    if rel_path == GENERATED_MAP_REL_PATH:
        return False
    if path.name in TOP_LEVEL_INCLUDE:
        return True
    if rel_path.startswith("ipl_predictor/"):
        return path.suffix == ".py"
    if rel_path.startswith("scripts/"):
        return path.suffix == ".py"
    if rel_path.startswith("tests/"):
        return path.suffix == ".py"
    if rel_path.startswith("templates/"):
        return path.suffix == ".html"
    if rel_path.startswith("static/"):
        return path.suffix in {".css", ".js"}
    if rel_path.startswith("docs/"):
        return path.suffix.lower() in DOC_EXTENSIONS
    if rel_path.startswith("models/"):
        return (
            len(path.relative_to(repo_root).parts) <= 2
            and path.suffix.lower() in MODEL_EXTENSIONS
            and "archive" not in path.parts
        )
    if rel_path.startswith("data/processed/"):
        return path.suffix.lower() in {".csv", ".json"}
    if rel_path.startswith("data/") and len(path.relative_to(repo_root).parts) <= 2:
        return path.suffix.lower() in DATA_EXTENSIONS
    if rel_path.startswith("alembic/"):
        return path.suffix.lower() in {".py", ".sql", ".mako"}
    return False


def _classify_path(rel_path: str, is_dir: bool) -> tuple[str, str]:
    parts = rel_path.split("/")
    first = parts[0]

    if rel_path in {"web_app.py", "streamlit_app.py", "predict_cli.py"}:
        return "entrypoint", "python-file"
    if first == "ipl_predictor":
        return "package", "python-file" if not is_dir else "directory"
    if first == "scripts":
        return "scripts", "python-file" if not is_dir else "directory"
    if first == "templates":
        return "templates", "template" if not is_dir else "directory"
    if first == "static":
        return "static", "asset" if not is_dir else "directory"
    if first in {"alembic"} or rel_path in {"pyproject.toml", "requirements.txt", "alembic.ini", ".env.example", "Dockerfile", ".gitignore"}:
        return "config", "config-file" if not is_dir else "directory"
    if first == "tests":
        return "tests", "test-file" if not is_dir else "directory"
    if first == "data" or rel_path.endswith(".csv") or rel_path.endswith(".zip"):
        return "data", "data-file" if not is_dir else "directory"
    if first == "models" or rel_path.endswith(".pkl"):
        return "models", "artifact" if not is_dir else "directory"
    if first == "docs":
        return "docs", "document" if not is_dir else "directory"
    return "other", "file" if not is_dir else "directory"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _infer_description(path: Path, repo_root: Path, file_count: int | None = None) -> str:
    rel_path = _as_posix(path.relative_to(repo_root))
    if path.is_dir():
        base = SUMMARY_DIRECTORIES.get(rel_path, ("other", "Directory"))[1]
        if file_count is not None:
            return f"{base} Contains {file_count} tracked items in this map summary."
        return base

    if path.suffix == ".py":
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        docstring = ast.get_docstring(tree)
        if docstring:
            return _truncate(docstring.strip().splitlines()[0], 140)
        if rel_path.startswith("tests/"):
            return "Automated test file."
        if rel_path.startswith("scripts/"):
            return "Project automation or model workflow script."
        if rel_path in {"web_app.py", "streamlit_app.py", "predict_cli.py"}:
            return "User-facing entrypoint for this project."
        return "Python module."

    if path.suffix == ".html":
        return "Flask/Jinja template."
    if path.suffix == ".css":
        return "Static stylesheet."
    if path.suffix == ".md":
        return "Project documentation."
    if path.suffix == ".tex":
        return "Paper or report source."
    if path.suffix == ".json":
        if rel_path.startswith("models/"):
            return "Model metadata, report, or calibration artifact."
        return "Structured JSON data."
    if path.suffix == ".csv":
        if rel_path.startswith("data/processed/"):
            return "Processed dataset or support table used by inference/training."
        return "CSV data file."
    if path.suffix == ".pkl":
        return "Serialized model artifact."
    if path.name == "Dockerfile":
        return "Container build definition."
    if path.suffix in {".toml", ".ini"}:
        return "Project configuration."
    return "Project file."


def _module_name_for_path(path: Path, repo_root: Path) -> str | None:
    rel = path.relative_to(repo_root)
    if path.suffix != ".py":
        return None
    if rel.name == "__init__.py":
        return ".".join(rel.with_suffix("").parts[:-1])
    return ".".join(rel.with_suffix("").parts)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _literal_int(node: ast.AST) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def _literal_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _evaluate_path_expr(node: ast.AST, env: dict[str, Path | str], source_path: Path) -> Path | str | None:
    if isinstance(node, ast.Name):
        return env.get(node.id)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        return None

    if isinstance(node, ast.Call):
        func_name = _call_name(node.func)
        if func_name == "Path" and len(node.args) == 1:
            arg = _evaluate_path_expr(node.args[0], env, source_path)
            if arg == "__file__":
                return source_path.resolve()
            if isinstance(arg, str):
                return Path(arg)
        if func_name.endswith(".resolve") and isinstance(node.func, ast.Attribute):
            base = _evaluate_path_expr(node.func.value, env, source_path)
            return base
        return None

    if isinstance(node, ast.Attribute):
        base = _evaluate_path_expr(node.value, env, source_path)
        if isinstance(base, Path) and node.attr == "parent":
            return base.parent
        if isinstance(base, str) and node.attr == "name":
            return Path(base).name
        return None

    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
            base = _evaluate_path_expr(node.value.value, env, source_path)
            index = _literal_int(node.slice)
            if isinstance(base, Path) and index is not None:
                return base.parents[index]
        return None

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _evaluate_path_expr(node.left, env, source_path)
        right = _evaluate_path_expr(node.right, env, source_path)
        if isinstance(left, Path) and isinstance(right, str):
            return left / right
        if isinstance(left, Path) and isinstance(right, Path):
            return left / right
        if isinstance(left, str) and isinstance(right, str):
            return Path(left) / right
        return None

    return None


class ProjectMapBuilder:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.nodes: dict[str, Node] = {}
        self.edges: set[Edge] = set()
        self.module_index: dict[str, str] = {}
        self.text_files: list[Path] = []

    def build(self) -> dict[str, Any]:
        self._seed_summary_directories()
        self._discover_files()
        self._index_modules()
        self._analyze_python_files()
        self._analyze_text_files()
        payload = self._finalize_payload()
        return payload

    def _seed_summary_directories(self) -> None:
        for rel_path, (category, description) in SUMMARY_DIRECTORIES.items():
            full_path = self.repo_root / rel_path
            if not full_path.exists():
                continue
            file_count = sum(
                1
                for candidate in full_path.rglob("*")
                if candidate.is_file() and not _is_ignored(candidate, self.repo_root)
            )
            self._add_node(
                full_path,
                category=category,
                description=description,
                file_count=file_count,
            )

    def _discover_files(self) -> None:
        for candidate in self.repo_root.rglob("*"):
            if not candidate.is_file():
                continue
            if _is_ignored(candidate, self.repo_root):
                continue
            if _should_include_file(candidate, self.repo_root):
                self._add_node(candidate)
            if _is_text_file(candidate):
                self.text_files.append(candidate)

    def _index_modules(self) -> None:
        for node in self.nodes.values():
            if not node.rel_path.endswith(".py"):
                continue
            module_name = _module_name_for_path(self.repo_root / node.rel_path, self.repo_root)
            if module_name:
                self.module_index[module_name] = node.rel_path

    def _add_node(
        self,
        path: Path,
        *,
        category: str | None = None,
        description: str | None = None,
        file_count: int | None = None,
    ) -> str | None:
        try:
            rel_path = _as_posix(path.relative_to(self.repo_root))
        except ValueError:
            return None

        if rel_path == GENERATED_MAP_REL_PATH:
            return None

        if rel_path in self.nodes:
            return rel_path

        if path.is_dir():
            kind = "directory"
        else:
            category_guess, kind = _classify_path(rel_path, False)
            category = category or category_guess

        if category is None:
            category, kind = _classify_path(rel_path, path.is_dir())

        node = Node(
            node_id=rel_path,
            label=path.name if not path.is_dir() else f"{path.name}/",
            rel_path=rel_path,
            abs_path=str(path.resolve()),
            category=category,
            kind=kind if not path.is_dir() else "directory",
            description=description or _infer_description(path, self.repo_root, file_count=file_count),
            file_url=path.resolve().as_uri(),
            file_count=file_count,
        )
        self.nodes[rel_path] = node
        return rel_path

    def _add_edge(self, source_rel: str, target_path: Path, relation: str, detail: str = "") -> None:
        try:
            target_rel = _as_posix(target_path.relative_to(self.repo_root))
        except ValueError:
            return

        if target_rel == GENERATED_MAP_REL_PATH:
            return

        if not target_path.exists():
            return

        if _is_ignored(target_path, self.repo_root):
            return

        if target_path.is_dir():
            if target_rel in SUMMARY_DIRECTORIES:
                self._add_node(target_path)
            elif target_rel.startswith("data/ipl_csv2"):
                target_rel = "data/ipl_csv2"
                target_path = self.repo_root / target_rel
            elif target_rel.startswith("models/archive"):
                target_rel = "models/archive"
                target_path = self.repo_root / target_rel
            elif target_rel.startswith("docs/reports"):
                target_rel = "docs/reports"
                target_path = self.repo_root / target_rel
            elif target_rel.startswith("data/monitoring"):
                target_rel = "data/monitoring"
                target_path = self.repo_root / target_rel
            else:
                self._add_node(target_path)
        else:
            if not _should_include_file(target_path, self.repo_root):
                parent_rel = target_rel.rsplit("/", 1)[0] if "/" in target_rel else ""
                if parent_rel in SUMMARY_DIRECTORIES:
                    target_rel = parent_rel
                    target_path = self.repo_root / target_rel
                elif parent_rel.startswith("data/ipl_csv2"):
                    target_rel = "data/ipl_csv2"
                    target_path = self.repo_root / target_rel
                elif parent_rel.startswith("models/archive"):
                    target_rel = "models/archive"
                    target_path = self.repo_root / target_rel
                elif parent_rel.startswith("docs/reports"):
                    target_rel = "docs/reports"
                    target_path = self.repo_root / target_rel
                elif parent_rel.startswith("data/monitoring"):
                    target_rel = "data/monitoring"
                    target_path = self.repo_root / target_rel
            self._add_node(target_path)

        if source_rel == target_rel or source_rel not in self.nodes or target_rel not in self.nodes:
            return

        self.edges.add(Edge(source=source_rel, target=target_rel, relation=relation, detail=detail))

    def _resolve_import_target(self, source_rel: str, module_name: str, imported_name: str | None = None) -> str | None:
        if module_name in self.module_index:
            return self.module_index[module_name]
        if imported_name:
            nested = f"{module_name}.{imported_name}"
            if nested in self.module_index:
                return self.module_index[nested]
        if module_name.endswith(".__init__") and module_name[:-9] in self.module_index:
            return self.module_index[module_name[:-9]]
        return None

    def _resolve_relative_import(self, source_module: str, node: ast.ImportFrom) -> str | None:
        current_package = source_module
        if not source_rel_is_init(self.module_index.get(source_module, "")):
            current_package = source_module.rsplit(".", 1)[0] if "." in source_module else source_module
        package_parts = current_package.split(".") if current_package else []
        level = max(node.level, 0)
        if level > 0:
            package_parts = package_parts[: max(0, len(package_parts) - (level - 1))]
        if node.module:
            package_parts.extend(node.module.split("."))
        return ".".join(part for part in package_parts if part)

    def _analyze_python_files(self) -> None:
        for rel_path, node in list(self.nodes.items()):
            if not rel_path.endswith(".py"):
                continue
            full_path = self.repo_root / rel_path
            try:
                source_text = full_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                source_text = full_path.read_text(encoding="utf-8", errors="ignore")

            try:
                tree = ast.parse(source_text)
            except SyntaxError:
                continue

            source_module = _module_name_for_path(full_path, self.repo_root) or rel_path.replace("/", ".")
            env: dict[str, Path | str] = {"__file__": "__file__"}

            for stmt in tree.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                    resolved = _evaluate_path_expr(stmt.value, env, full_path)
                    if resolved is None:
                        continue
                    env[stmt.targets[0].id] = resolved
                    if isinstance(resolved, Path) and self.repo_root in {resolved, *resolved.parents} and resolved != self.repo_root:
                        relation = "defines_path" if stmt.targets[0].id.endswith("_PATH") or stmt.targets[0].id.endswith("_DIR") else "references"
                        self._add_edge(rel_path, resolved, relation, stmt.targets[0].id)

            for import_node in ast.walk(tree):
                if isinstance(import_node, ast.Import):
                    for alias in import_node.names:
                        target_rel = self._resolve_import_target(rel_path, alias.name)
                        if target_rel:
                            self.edges.add(Edge(rel_path, target_rel, "imports", alias.name))

                if isinstance(import_node, ast.ImportFrom):
                    module_name = self._resolve_relative_import(source_module, import_node)
                    if not module_name:
                        continue
                    target_rel = self._resolve_import_target(rel_path, module_name)
                    if target_rel:
                        self.edges.add(Edge(rel_path, target_rel, "imports", module_name))
                    for alias in import_node.names:
                        nested_target = self._resolve_import_target(rel_path, module_name, alias.name)
                        if nested_target:
                            self.edges.add(Edge(rel_path, nested_target, "imports", f"{module_name}.{alias.name}"))

                if isinstance(import_node, ast.Call):
                    func_name = _call_name(import_node.func)

                    if func_name.endswith("render_template") and import_node.args:
                        template_name = _literal_str(import_node.args[0])
                        if template_name:
                            self._add_edge(rel_path, self.repo_root / "templates" / template_name, "renders", template_name)

                    if func_name in {"open", "Path.open"}:
                        path_arg = None
                        if func_name == "open" and import_node.args:
                            path_arg = _evaluate_path_expr(import_node.args[0], env, full_path)
                        elif isinstance(import_node.func, ast.Attribute):
                            path_arg = _evaluate_path_expr(import_node.func.value, env, full_path)
                        mode = "r"
                        if len(import_node.args) >= 2:
                            literal_mode = _literal_str(import_node.args[1])
                            if literal_mode:
                                mode = literal_mode
                        for keyword in import_node.keywords:
                            if keyword.arg == "mode":
                                literal_mode = _literal_str(keyword.value)
                                if literal_mode:
                                    mode = literal_mode
                        if isinstance(path_arg, Path):
                            relation = "writes" if any(flag in mode for flag in {"w", "a", "x", "+"}) else "reads"
                            self._add_edge(rel_path, path_arg, relation, func_name)

                    if func_name.endswith("joblib.load") and import_node.args:
                        path_arg = _evaluate_path_expr(import_node.args[0], env, full_path)
                        if isinstance(path_arg, Path):
                            self._add_edge(rel_path, path_arg, "reads", func_name)

                    if func_name.endswith("joblib.dump") and len(import_node.args) >= 2:
                        path_arg = _evaluate_path_expr(import_node.args[1], env, full_path)
                        if isinstance(path_arg, Path):
                            self._add_edge(rel_path, path_arg, "writes", func_name)

                    if func_name.endswith("read_csv") and import_node.args:
                        path_arg = _evaluate_path_expr(import_node.args[0], env, full_path)
                        if isinstance(path_arg, Path):
                            self._add_edge(rel_path, path_arg, "reads", func_name)

                    if func_name.endswith("to_csv") and import_node.args:
                        path_arg = _evaluate_path_expr(import_node.args[0], env, full_path)
                        if isinstance(path_arg, Path):
                            self._add_edge(rel_path, path_arg, "writes", func_name)

                    if func_name.endswith("write_text") or func_name.endswith("write_bytes"):
                        if isinstance(import_node.func, ast.Attribute):
                            path_arg = _evaluate_path_expr(import_node.func.value, env, full_path)
                            if isinstance(path_arg, Path):
                                self._add_edge(rel_path, path_arg, "writes", func_name)

                    if func_name.endswith("read_text") or func_name.endswith("read_bytes"):
                        if isinstance(import_node.func, ast.Attribute):
                            path_arg = _evaluate_path_expr(import_node.func.value, env, full_path)
                            if isinstance(path_arg, Path):
                                self._add_edge(rel_path, path_arg, "reads", func_name)

    def _analyze_text_files(self) -> None:
        node_paths = [rel_path for rel_path in self.nodes if "/" in rel_path]
        static_assets = {
            node.rel_path.split("/", 1)[1]: node.rel_path
            for node in self.nodes.values()
            if node.rel_path.startswith("static/")
        }

        for path in self.text_files:
            try:
                rel_path = _as_posix(path.relative_to(self.repo_root))
            except ValueError:
                continue
            if rel_path not in self.nodes:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="ignore")

            if rel_path.endswith(".html"):
                for asset_name, asset_rel in static_assets.items():
                    if asset_name in text:
                        self.edges.add(Edge(rel_path, asset_rel, "references", asset_name))

            for candidate_rel in node_paths:
                if candidate_rel == rel_path:
                    continue
                if candidate_rel in text:
                    self.edges.add(Edge(rel_path, candidate_rel, "references", candidate_rel))

            for match in REPO_REF_RE.finditer(text):
                raw = match.group("path").replace("\\", "/")
                candidate = self.repo_root / raw
                if candidate.exists():
                    self._add_edge(rel_path, candidate, "references", raw)

    def _finalize_payload(self) -> dict[str, Any]:
        nodes = list(self.nodes.values())
        layout = compute_layout(nodes)
        node_payload: list[dict[str, Any]] = []
        for node in nodes:
            node_payload.append(
                {
                    "id": node.node_id,
                    "label": node.label,
                    "rel_path": node.rel_path,
                    "abs_path": node.abs_path,
                    "category": node.category,
                    "category_label": CATEGORY_LABELS.get(node.category, node.category.title()),
                    "kind": node.kind,
                    "description": node.description,
                    "file_url": node.file_url,
                    "file_count": node.file_count,
                    **layout["positions"][node.node_id],
                }
            )

        edge_payload = [
            {
                "source": edge.source,
                "target": edge.target,
                "relation": edge.relation,
                "relation_label": RELATION_LABELS.get(edge.relation, edge.relation.replace("_", " ").title()),
                "detail": edge.detail,
            }
            for edge in sorted(self.edges, key=lambda item: (item.relation, item.source, item.target))
            if edge.source in self.nodes and edge.target in self.nodes
        ]

        return {
            "meta": {
                "title": "IPL Prediction Project Map",
                "generated_at": _utc_now(),
                "repo_root": str(self.repo_root),
                "categories": [
                    {"id": category, "label": CATEGORY_LABELS[category]}
                    for category in CATEGORY_ORDER
                    if any(node.category == category for node in nodes)
                ],
                "relations": [
                    {"id": relation, "label": RELATION_LABELS[relation]}
                    for relation in RELATION_LABELS
                    if any(edge["relation"] == relation for edge in edge_payload)
                ],
                "canvas": layout["canvas"],
                "groups": layout["groups"],
                "node_count": len(node_payload),
                "edge_count": len(edge_payload),
            },
            "nodes": node_payload,
            "edges": edge_payload,
        }


def source_rel_is_init(rel_path: str) -> bool:
    return rel_path.endswith("__init__.py")


def compute_layout(nodes: list[Node]) -> dict[str, Any]:
    left_margin = 36
    top_margin = 92
    group_width = 280
    node_width = 220
    node_height = 56
    vertical_gap = 14

    groups: list[dict[str, Any]] = []
    positions: dict[str, dict[str, int]] = {}

    visible_categories = [category for category in CATEGORY_ORDER if any(node.category == category for node in nodes)]
    max_bottom = top_margin

    for column_index, category in enumerate(visible_categories):
        category_nodes = sorted(
            [node for node in nodes if node.category == category],
            key=lambda item: (item.rel_path.count("/"), item.rel_path.lower()),
        )
        x = left_margin + column_index * group_width
        current_y = top_margin
        for node in category_nodes:
            positions[node.node_id] = {"x": x, "y": current_y, "width": node_width, "height": node_height}
            current_y += node_height + vertical_gap
        group_height = max(120, current_y - top_margin + 24)
        groups.append(
            {
                "id": category,
                "label": CATEGORY_LABELS.get(category, category.title()),
                "x": x - 16,
                "y": 44,
                "width": node_width + 32,
                "height": group_height,
            }
        )
        max_bottom = max(max_bottom, current_y)

    canvas = {
        "width": max(left_margin + len(visible_categories) * group_width + 40, 1200),
        "height": max(max_bottom + 48, 720),
    }
    return {"positions": positions, "canvas": canvas, "groups": groups}


def _edge_path(source: dict[str, Any], target: dict[str, Any]) -> str:
    start_x = source["x"] + source["width"]
    start_y = source["y"] + (source["height"] // 2)
    end_x = target["x"]
    end_y = target["y"] + (target["height"] // 2)

    if source["x"] == target["x"]:
        mid_x = start_x + 60
        return f"M {start_x} {start_y} C {mid_x} {start_y}, {mid_x} {end_y}, {end_x} {end_y}"

    delta = max(60, abs(end_x - start_x) // 2)
    control_1 = start_x + delta
    control_2 = end_x - delta
    return f"M {start_x} {start_y} C {control_1} {start_y}, {control_2} {end_y}, {end_x} {end_y}"


def render_html(payload: dict[str, Any]) -> str:
    node_lookup = {node["id"]: node for node in payload["nodes"]}
    for edge in payload["edges"]:
        edge["path"] = _edge_path(node_lookup[edge["source"]], node_lookup[edge["target"]])

    data_json = json.dumps(payload, indent=2)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{payload["meta"]["title"]}</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffdf8;
      --ink: #1f2a2e;
      --muted: #607178;
      --grid: rgba(31, 42, 46, 0.08);
      --edge: rgba(96, 113, 120, 0.42);
      --entrypoint: #d96c3a;
      --package: #0f7c82;
      --scripts: #2a9d5b;
      --templates: #bf8b30;
      --static: #7a6fd0;
      --config: #8f4e8b;
      --tests: #ca4b57;
      --data: #2a6bd6;
      --models: #2d8f6f;
      --docs: #996f2d;
      --other: #6f7d86;
      --shadow: 0 18px 45px rgba(31, 42, 46, 0.12);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: "Segoe UI", "Aptos", "Trebuchet MS", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(217, 108, 58, 0.16), transparent 24%),
        radial-gradient(circle at bottom right, rgba(15, 124, 130, 0.14), transparent 28%),
        linear-gradient(135deg, #f8f4ec 0%, #f3efe6 54%, #ece5d6 100%);
      min-height: 100vh;
    }}

    .shell {{
      display: grid;
      grid-template-columns: 320px minmax(720px, 1fr) 360px;
      min-height: 100vh;
      gap: 16px;
      padding: 16px;
    }}

    .panel {{
      background: rgba(255, 253, 248, 0.92);
      border: 1px solid rgba(31, 42, 46, 0.1);
      border-radius: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}

    .sidebar,
    .details {{
      padding: 18px;
      overflow: auto;
    }}

    .canvas {{
      display: flex;
      flex-direction: column;
      min-width: 0;
      overflow: hidden;
    }}

    .canvas-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 18px 18px 12px;
      border-bottom: 1px solid rgba(31, 42, 46, 0.08);
    }}

    .canvas-header h1,
    .sidebar h2,
    .details h2 {{
      margin: 0;
      font-size: 1.05rem;
      letter-spacing: 0.02em;
    }}

    .canvas-header p,
    .sidebar p,
    .details p {{
      margin: 6px 0 0;
      color: var(--muted);
      line-height: 1.45;
    }}

    .search {{
      width: 100%;
      padding: 11px 12px;
      border: 1px solid rgba(31, 42, 46, 0.16);
      border-radius: 12px;
      font: inherit;
      background: rgba(255, 255, 255, 0.85);
      color: var(--ink);
    }}

    .section {{
      margin-top: 18px;
    }}

    .filter-list {{
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }}

    .filter-item {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 0.95rem;
      color: var(--ink);
    }}

    .color-chip {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      flex: 0 0 auto;
    }}

    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}

    .stat {{
      background: rgba(31, 42, 46, 0.04);
      border-radius: 14px;
      padding: 12px;
    }}

    .stat strong {{
      display: block;
      font-size: 1.3rem;
    }}

    .toolbar {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}

    .button {{
      border: 0;
      border-radius: 999px;
      padding: 9px 12px;
      background: rgba(31, 42, 46, 0.08);
      color: var(--ink);
      font: inherit;
      cursor: pointer;
      transition: transform 120ms ease, background 120ms ease;
    }}

    .button:hover {{
      transform: translateY(-1px);
      background: rgba(31, 42, 46, 0.14);
    }}

    .canvas-body {{
      flex: 1;
      overflow: auto;
      position: relative;
      background:
        linear-gradient(rgba(31, 42, 46, 0.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(31, 42, 46, 0.05) 1px, transparent 1px);
      background-size: 24px 24px;
      border-radius: 0 0 18px 18px;
    }}

    .svg-shell {{
      transform-origin: top left;
      transition: transform 120ms ease;
      width: fit-content;
      height: fit-content;
    }}

    svg {{
      display: block;
      overflow: visible;
    }}

    .group-box {{
      fill: rgba(255, 255, 255, 0.72);
      stroke: rgba(31, 42, 46, 0.09);
      stroke-dasharray: 6 6;
    }}

    .group-label {{
      font-size: 14px;
      font-weight: 700;
      fill: var(--muted);
    }}

    .edge {{
      fill: none;
      stroke: var(--edge);
      stroke-width: 2;
      pointer-events: none;
      transition: opacity 120ms ease, stroke 120ms ease, stroke-width 120ms ease;
    }}

    .edge.highlight {{
      stroke: rgba(31, 42, 46, 0.82);
      stroke-width: 2.8;
    }}

    .edge.dim {{
      opacity: 0.08;
    }}

    .node rect {{
      rx: 16;
      ry: 16;
      stroke-width: 2;
      transition: transform 120ms ease, opacity 120ms ease, stroke 120ms ease;
    }}

    .node:hover rect {{
      transform: translateY(-1px);
    }}

    .node text {{
      pointer-events: none;
    }}

    .node .label {{
      font-size: 14px;
      font-weight: 700;
      fill: #102025;
    }}

    .node .meta {{
      font-size: 11px;
      fill: rgba(16, 32, 37, 0.72);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}

    .node.dim {{
      opacity: 0.18;
    }}

    .node.selected rect {{
      stroke: #102025;
      stroke-width: 3;
    }}

    .node.highlight rect {{
      stroke-width: 2.4;
    }}

    .details-card {{
      margin-top: 14px;
      padding: 14px;
      background: rgba(31, 42, 46, 0.04);
      border-radius: 14px;
    }}

    .details-card h3 {{
      margin: 0;
      font-size: 1rem;
    }}

    .details-card code {{
      display: block;
      margin-top: 10px;
      padding: 10px;
      border-radius: 12px;
      background: rgba(16, 32, 37, 0.08);
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 0.85rem;
      word-break: break-word;
    }}

    .list {{
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }}

    .list-item {{
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.78);
      border: 1px solid rgba(31, 42, 46, 0.08);
    }}

    .hint {{
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.55;
    }}

    a {{
      color: #0b6d74;
    }}

    @media (max-width: 1440px) {{
      .shell {{
        grid-template-columns: 280px minmax(640px, 1fr) 320px;
      }}
    }}

    @media (max-width: 1180px) {{
      .shell {{
        grid-template-columns: 1fr;
      }}
      .canvas {{
        min-height: 68vh;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="panel sidebar">
      <h2>Project Map</h2>
      <p>Click a file to inspect what it uses, what points back to it, and where it lives in the repo.</p>
      <div class="section">
        <input id="search" class="search" type="search" placeholder="Search path, file, or description" />
      </div>
      <div class="section">
        <h2>Categories</h2>
        <div id="categoryFilters" class="filter-list"></div>
      </div>
      <div class="section">
        <h2>Relations</h2>
        <div id="relationFilters" class="filter-list"></div>
      </div>
      <div class="section stats" id="stats"></div>
    </aside>

    <section class="panel canvas">
      <div class="canvas-header">
        <div>
          <h1>{payload["meta"]["title"]}</h1>
          <p>{payload["meta"]["repo_root"]}</p>
        </div>
        <div class="toolbar">
          <button type="button" class="button" id="zoomOut">-</button>
          <button type="button" class="button" id="zoomReset">100%</button>
          <button type="button" class="button" id="zoomIn">+</button>
          <button type="button" class="button" id="clearSelection">Clear</button>
        </div>
      </div>
      <div class="canvas-body" id="canvasBody">
        <div class="svg-shell" id="svgShell">
          <svg id="mapSvg" width="{payload["meta"]["canvas"]["width"]}" height="{payload["meta"]["canvas"]["height"]}"></svg>
        </div>
      </div>
    </section>

    <aside class="panel details" id="details"></aside>
  </div>

  <script>
    const DATA = {data_json};
    const colorFor = (category) => `var(--${{category}})`;
    const nodesById = Object.fromEntries(DATA.nodes.map((node) => [node.id, node]));
    const outgoing = new Map();
    const incoming = new Map();
    const state = {{
      search: "",
      zoom: 1,
      selected: null,
      categories: new Set(DATA.meta.categories.map((item) => item.id)),
      relations: new Set(DATA.meta.relations.map((item) => item.id)),
    }};

    for (const node of DATA.nodes) {{
      outgoing.set(node.id, []);
      incoming.set(node.id, []);
    }}

    for (const edge of DATA.edges) {{
      outgoing.get(edge.source).push(edge);
      incoming.get(edge.target).push(edge);
    }}

    const svg = document.getElementById("mapSvg");
    const svgShell = document.getElementById("svgShell");
    const details = document.getElementById("details");
    const stats = document.getElementById("stats");
    const searchInput = document.getElementById("search");

    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }}

    function updateZoom() {{
      svgShell.style.transform = `scale(${{state.zoom}})`;
      document.getElementById("zoomReset").textContent = `${{Math.round(state.zoom * 100)}}%`;
    }}

    function buildFilters() {{
      const categoryTarget = document.getElementById("categoryFilters");
      categoryTarget.innerHTML = DATA.meta.categories.map((item) => `
        <label class="filter-item">
          <input type="checkbox" data-kind="category" value="${{item.id}}" checked />
          <span class="color-chip" style="background:${{colorFor(item.id)}}"></span>
          <span>${{item.label}}</span>
        </label>
      `).join("");

      const relationTarget = document.getElementById("relationFilters");
      relationTarget.innerHTML = DATA.meta.relations.map((item) => `
        <label class="filter-item">
          <input type="checkbox" data-kind="relation" value="${{item.id}}" checked />
          <span>${{item.label}}</span>
        </label>
      `).join("");

      for (const input of document.querySelectorAll("input[data-kind='category']")) {{
        input.addEventListener("change", (event) => {{
          const target = event.currentTarget;
          if (target.checked) {{
            state.categories.add(target.value);
          }} else {{
            state.categories.delete(target.value);
          }}
          render();
        }});
      }}

      for (const input of document.querySelectorAll("input[data-kind='relation']")) {{
        input.addEventListener("change", (event) => {{
          const target = event.currentTarget;
          if (target.checked) {{
            state.relations.add(target.value);
          }} else {{
            state.relations.delete(target.value);
          }}
          render();
        }});
      }}
    }}

    function nodeMatchesSearch(node) {{
      if (!state.search) {{
        return true;
      }}
      const haystack = `${{node.rel_path}} ${{node.label}} ${{node.description}}`.toLowerCase();
      return haystack.includes(state.search);
    }}

    function getVisibleNodeIds() {{
      return new Set(
        DATA.nodes
          .filter((node) => state.categories.has(node.category))
          .filter(nodeMatchesSearch)
          .map((node) => node.id)
      );
    }}

    function selectedNeighborhood() {{
      if (!state.selected) {{
        return null;
      }}
      const neighbors = new Set([state.selected]);
      for (const edge of outgoing.get(state.selected) || []) {{
        neighbors.add(edge.target);
      }}
      for (const edge of incoming.get(state.selected) || []) {{
        neighbors.add(edge.source);
      }}
      return neighbors;
    }}

    function renderStats(visibleNodes, visibleEdges) {{
      stats.innerHTML = `
        <div class="stat"><strong>${{visibleNodes.length}}</strong>Visible nodes</div>
        <div class="stat"><strong>${{visibleEdges.length}}</strong>Visible links</div>
        <div class="stat"><strong>${{DATA.meta.node_count}}</strong>Total nodes</div>
        <div class="stat"><strong>${{DATA.meta.edge_count}}</strong>Total links</div>
      `;
    }}

    function renderDetails() {{
      if (!state.selected || !nodesById[state.selected]) {{
        details.innerHTML = `
          <h2>Details</h2>
          <p class="hint">Select a node to see its role, location, and direct dependencies.</p>
          <div class="details-card">
            <h3>What this map shows</h3>
            <p class="hint">Imports are Python module links. Reads and writes come from detected file-path usage. References come from docs, templates, config, or other text files that mention another file or folder.</p>
          </div>
        `;
        return;
      }}

      const node = nodesById[state.selected];
      const outgoingList = (outgoing.get(node.id) || []).map((edge) => {{
        const target = nodesById[edge.target];
        return `<div class="list-item"><strong>${{edge.relation_label}}</strong><br>${{escapeHtml(target.rel_path)}}</div>`;
      }}).join("") || `<div class="list-item">No outgoing links in the current analysis.</div>`;

      const incomingList = (incoming.get(node.id) || []).map((edge) => {{
        const source = nodesById[edge.source];
        return `<div class="list-item"><strong>${{edge.relation_label}}</strong><br>${{escapeHtml(source.rel_path)}}</div>`;
      }}).join("") || `<div class="list-item">No incoming links in the current analysis.</div>`;

      details.innerHTML = `
        <h2>${{escapeHtml(node.label)}}</h2>
        <p>${{escapeHtml(node.description)}}</p>
        <div class="details-card">
          <h3>Path</h3>
          <code>${{escapeHtml(node.rel_path)}}</code>
          <p class="hint">${{escapeHtml(node.abs_path)}}</p>
          <p class="hint">Category: ${{escapeHtml(node.category_label)}} | Kind: ${{escapeHtml(node.kind)}}${{node.file_count ? ` | Items: ${{node.file_count}}` : ""}}</p>
          <p><a href="${{node.file_url}}">Open file or folder</a></p>
        </div>
        <div class="section">
          <h2>Affects</h2>
          <div class="list">${{outgoingList}}</div>
        </div>
        <div class="section">
          <h2>Affected By</h2>
          <div class="list">${{incomingList}}</div>
        </div>
      `;
    }}

    function render() {{
      const visibleNodeIds = getVisibleNodeIds();
      const neighborhood = selectedNeighborhood();
      const visibleNodes = DATA.nodes.filter((node) => visibleNodeIds.has(node.id));
      const visibleEdges = DATA.edges.filter((edge) => (
        visibleNodeIds.has(edge.source)
        && visibleNodeIds.has(edge.target)
        && state.relations.has(edge.relation)
      ));

      renderStats(visibleNodes, visibleEdges);

      const groupMarkup = DATA.meta.groups
        .filter((group) => visibleNodes.some((node) => node.category === group.id))
        .map((group) => `
          <g>
            <rect class="group-box" x="${{group.x}}" y="${{group.y}}" width="${{group.width}}" height="${{group.height}}"></rect>
            <text class="group-label" x="${{group.x + 14}}" y="${{group.y - 10}}">${{escapeHtml(group.label)}}</text>
          </g>
        `).join("");

      const edgeMarkup = visibleEdges.map((edge) => {{
        const dim = neighborhood && !(neighborhood.has(edge.source) && neighborhood.has(edge.target));
        const highlight = neighborhood && edge.source === state.selected || edge.target === state.selected;
        const classes = ["edge"];
        if (dim) classes.push("dim");
        if (highlight) classes.push("highlight");
        return `<path class="${{classes.join(" ")}}" d="${{edge.path}}"></path>`;
      }}).join("");

      const nodeMarkup = visibleNodes.map((node) => {{
        const selected = state.selected === node.id;
        const highlight = neighborhood && neighborhood.has(node.id) && !selected;
        const dim = neighborhood && !neighborhood.has(node.id);
        const classes = ["node"];
        if (selected) classes.push("selected");
        if (highlight) classes.push("highlight");
        if (dim) classes.push("dim");
        const fill = colorFor(node.category);
        const meta = node.category_label.toUpperCase();
        const label = escapeHtml(node.label);
        return `
          <g class="${{classes.join(" ")}}" data-node-id="${{node.id}}" transform="translate(${{node.x}},${{node.y}})">
            <rect width="${{node.width}}" height="${{node.height}}" fill="${{fill}}" fill-opacity="0.12" stroke="${{fill}}"></rect>
            <text class="label" x="14" y="24">${{label}}</text>
            <text class="meta" x="14" y="42">${{meta}}</text>
          </g>
        `;
      }}).join("");

      svg.innerHTML = `<g>${{groupMarkup}}${{edgeMarkup}}${{nodeMarkup}}</g>`;

      for (const element of svg.querySelectorAll("[data-node-id]")) {{
        element.addEventListener("click", () => {{
          const nodeId = element.getAttribute("data-node-id");
          state.selected = state.selected === nodeId ? null : nodeId;
          render();
        }});
      }}

      renderDetails();
    }}

    buildFilters();
    updateZoom();
    renderDetails();
    render();

    searchInput.addEventListener("input", (event) => {{
      state.search = event.currentTarget.value.trim().toLowerCase();
      render();
    }});

    document.getElementById("zoomIn").addEventListener("click", () => {{
      state.zoom = Math.min(2.2, state.zoom + 0.1);
      updateZoom();
    }});
    document.getElementById("zoomOut").addEventListener("click", () => {{
      state.zoom = Math.max(0.6, state.zoom - 0.1);
      updateZoom();
    }});
    document.getElementById("zoomReset").addEventListener("click", () => {{
      state.zoom = 1;
      updateZoom();
    }});
    document.getElementById("clearSelection").addEventListener("click", () => {{
      state.selected = null;
      render();
    }});
  </script>
</body>
</html>
"""


def build_project_map(repo_root: Path | None = None) -> dict[str, Any]:
    project_root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    return ProjectMapBuilder(project_root).build()


def write_project_map(output_path: Path, repo_root: Path | None = None) -> Path:
    payload = build_project_map(repo_root=repo_root)
    html = render_html(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an interactive project architecture map.")
    parser.add_argument(
        "--output",
        default="docs/project_map.html",
        help="Output HTML path relative to the repository root.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    output_path = (repo_root / args.output).resolve()
    write_project_map(output_path=output_path, repo_root=repo_root)
    print(f"Wrote interactive project map to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
