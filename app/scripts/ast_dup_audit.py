#!/usr/bin/env python3

# venv/bin/python -m app.scripts.ast_dup_audit --root app
# venv/bin/python -m app.scripts.ast_dup_audit --root app --json > /tmp/dup_audit_$(date +%Y%m%d_%H%M%S).json
# venv/bin/python -m app.scripts.ast_dup_audit --root app --similarity-threshold 0.90 --max-similar-pairs 200
# venv/bin/python -m app.scripts.ast_dup_audit --root app --only-names first_csv_token,runtime_profile_default,env_int,print_json,now_ms,now_ts,utcnow_naive,utcnow_db,compact,proxies_enabled,sentiment_score,hash_embed

from __future__ import annotations

"""
AST-based duplicate function audit for Python modules.

What it does:
- Scans functions in `app/**/*.py` (top-level + methods + nested by default).
- Reports exact clones (same AST hash).
- Reports shape clones (same structure with renamed identifiers/constants).
- Reports same-name groups.
- Reports high-similarity logic pairs even with different names.

Why it exists:
- Make duplication checks reproducible and CI-friendly.
- Catch "same behavior, different naming" before it spreads.
"""

import argparse
import ast
import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


DEFAULT_EXCLUDED_NAMES = {
    "main",
    "parse_args",
    "build_parser",
}


@dataclass
class FunctionRef:
    module: str
    file: str
    qualname: str
    name: str
    kind: str
    lineno: int
    end_lineno: int
    node_count: int
    hash: str
    shape_hash: str
    features: Dict[str, int]

    def as_row(self) -> dict:
        return {
            "module": self.module,
            "file": self.file,
            "qualname": self.qualname,
            "name": self.name,
            "kind": self.kind,
            "lineno": self.lineno,
            "end_lineno": self.end_lineno,
            "node_count": self.node_count,
            "hash": self.hash,
            "shape_hash": self.shape_hash,
        }


def _module_name(root: Path, py_file: Path) -> str:
    return ".".join(py_file.relative_to(root).with_suffix("").parts)


def _hash_payload(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _hash_node(node: ast.AST) -> str:
    payload = ast.dump(node, annotate_fields=True, include_attributes=False)
    return _hash_payload(payload)


class _ShapeNormalizer(ast.NodeTransformer):
    """
    Normalizes AST to compare function *shape*:
    - strips function/variable/arg/import names
    - strips literal values while preserving literal type
    """

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = "__fn__"
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.name = "__fn__"
        return self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = "__arg__"
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> ast.AST:
        node.id = "__id__"
        return self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        node.attr = "__attr__"
        return self.generic_visit(node)

    def visit_alias(self, node: ast.alias) -> ast.AST:
        node.name = "__import__"
        if node.asname:
            node.asname = "__as__"
        return node

    def visit_keyword(self, node: ast.keyword) -> ast.AST:
        if node.arg:
            node.arg = "__kw__"
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        value = node.value
        if value is None:
            marker = "__none__"
        elif isinstance(value, bool):
            marker = "__bool__"
        elif isinstance(value, int):
            marker = 0
        elif isinstance(value, float):
            marker = 0.0
        elif isinstance(value, str):
            marker = "__str__"
        elif isinstance(value, bytes):
            marker = b"__bytes__"
        else:
            marker = f"__{type(value).__name__.lower()}__"
        node.value = marker
        return node


def _shape_hash(node: ast.AST) -> str:
    cloned = copy.deepcopy(node)
    normalized = _ShapeNormalizer().visit(cloned)
    ast.fix_missing_locations(normalized)
    return _hash_node(normalized)


def _feature_counter(node: ast.AST) -> Dict[str, int]:
    feats: Counter[str] = Counter()
    for sub in ast.walk(node):
        feats[f"N:{type(sub).__name__}"] += 1

        if isinstance(sub, ast.Constant):
            feats[f"K:{type(sub.value).__name__}"] += 1
        elif isinstance(sub, ast.BinOp):
            feats[f"OP:{type(sub.op).__name__}"] += 1
        elif isinstance(sub, ast.UnaryOp):
            feats[f"OP:{type(sub.op).__name__}"] += 1
        elif isinstance(sub, ast.BoolOp):
            feats[f"OP:{type(sub.op).__name__}"] += 1
        elif isinstance(sub, ast.Compare):
            for op in sub.ops:
                feats[f"OP:{type(op).__name__}"] += 1
        elif isinstance(sub, ast.Call):
            feats["CALL:any"] += 1
        elif isinstance(sub, ast.comprehension):
            feats["COMP:any"] += 1
    return dict(feats)


def _iter_py_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


class _FunctionCollector(ast.NodeVisitor):
    def __init__(self, *, module: str, file: str, include_methods: bool, include_nested: bool):
        self.module = module
        self.file = file
        self.include_methods = include_methods
        self.include_nested = include_nested
        self.class_stack: List[str] = []
        self.func_stack: List[str] = []
        self.items: List[FunctionRef] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self.func_stack:
            kind = "nested"
        elif self.class_stack:
            kind = "method"
        else:
            kind = "function"

        should_include = True
        if kind == "method" and not self.include_methods:
            should_include = False
        if kind == "nested" and not self.include_nested:
            should_include = False

        if should_include:
            parts: List[str] = []
            if self.class_stack:
                parts.extend(self.class_stack)
            if self.func_stack:
                parts.extend(self.func_stack)
            parts.append(node.name)
            qualname = ".".join(parts)

            node_count = sum(1 for _ in ast.walk(node))
            self.items.append(
                FunctionRef(
                    module=self.module,
                    file=self.file,
                    qualname=qualname,
                    name=node.name,
                    kind=kind,
                    lineno=int(getattr(node, "lineno", 0) or 0),
                    end_lineno=int(getattr(node, "end_lineno", 0) or 0),
                    node_count=node_count,
                    hash=_hash_node(node),
                    shape_hash=_shape_hash(node),
                    features=_feature_counter(node),
                )
            )

        self.func_stack.append(node.name)
        self.generic_visit(node)
        self.func_stack.pop()


def collect_functions(root: Path, *, include_methods: bool, include_nested: bool) -> List[FunctionRef]:
    out: List[FunctionRef] = []
    for py_file in _iter_py_files(root):
        module = _module_name(root.parent, py_file)
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        collector = _FunctionCollector(
            module=module,
            file=str(py_file),
            include_methods=include_methods,
            include_nested=include_nested,
        )
        collector.visit(tree)
        out.extend(collector.items)
    return out


def _group_by_field(
    funcs: Sequence[FunctionRef],
    *,
    field: str,
    min_size: int,
) -> List[dict]:
    by_key: Dict[str, List[FunctionRef]] = defaultdict(list)
    for fn in funcs:
        by_key[str(getattr(fn, field))].append(fn)

    groups: List[dict] = []
    for key, refs in by_key.items():
        if len(refs) < min_size:
            continue
        rows = [r.as_row() for r in sorted(refs, key=lambda x: (x.qualname, x.module, x.lineno))]
        groups.append(
            {
                "key": key,
                "count": len(refs),
                "names": sorted({r.name for r in refs}),
                "kinds": sorted({r.kind for r in refs}),
                "items": rows,
            }
        )
    groups.sort(key=lambda g: g["count"], reverse=True)
    return groups


def _group_by_name(funcs: Sequence[FunctionRef], min_size: int) -> List[dict]:
    by_name: Dict[str, List[FunctionRef]] = defaultdict(list)
    for fn in funcs:
        by_name[fn.name].append(fn)

    groups: List[dict] = []
    for name, refs in by_name.items():
        if len(refs) < min_size:
            continue
        by_hash: Dict[str, List[FunctionRef]] = defaultdict(list)
        for r in refs:
            by_hash[r.hash].append(r)

        hash_groups = [
            {
                "hash": h,
                "count": len(items),
                "items": [i.as_row() for i in sorted(items, key=lambda x: (x.module, x.lineno))],
            }
            for h, items in by_hash.items()
        ]
        hash_groups.sort(key=lambda g: g["count"], reverse=True)
        groups.append(
            {
                "name": name,
                "count": len(refs),
                "distinct_implementations": len(by_hash),
                "exact_clone": len(by_hash) == 1,
                "hash_groups": hash_groups,
            }
        )
    groups.sort(key=lambda g: g["count"], reverse=True)
    return groups


def _counter_cosine(a: Dict[str, int], b: Dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(float(a[k]) * float(b[k]) for k in common)
    norm_a = math.sqrt(sum(float(v) * float(v) for v in a.values()))
    norm_b = math.sqrt(sum(float(v) * float(v) for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _find_similar_logic_pairs(
    funcs: Sequence[FunctionRef],
    *,
    similarity_threshold: float,
    min_nodes: int,
    max_pairs: int,
) -> List[dict]:
    out: List[dict] = []
    n = len(funcs)
    if n < 2:
        return out

    for i in range(n - 1):
        left = funcs[i]
        if left.node_count < min_nodes:
            continue
        for j in range(i + 1, n):
            right = funcs[j]
            if right.node_count < min_nodes:
                continue
            if left.hash == right.hash:
                continue
            if left.shape_hash == right.shape_hash:
                continue

            ratio = float(min(left.node_count, right.node_count)) / float(max(left.node_count, right.node_count))
            if ratio < 0.55:
                continue

            score = _counter_cosine(left.features, right.features)
            if score < similarity_threshold:
                continue

            out.append(
                {
                    "score": round(score, 6),
                    "same_name": left.name == right.name,
                    "left": left.as_row(),
                    "right": right.as_row(),
                }
            )

    out.sort(
        key=lambda row: (
            float(row["score"]),
            int(row["left"]["node_count"]) + int(row["right"]["node_count"]),
        ),
        reverse=True,
    )
    return out[: max(1, max_pairs)]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AST duplicate function audit.")
    p.add_argument("--root", default="app", help="Root directory to scan (default: app).")
    p.add_argument("--min-group-size", type=int, default=2, help="Minimum members per group (default: 2).")
    p.add_argument("--limit", type=int, default=120, help="Max groups shown in text mode (default: 120).")
    p.add_argument(
        "--only-names",
        default="",
        help="Comma-separated function names to focus (example: _now_ms,_compact).",
    )
    p.add_argument(
        "--exclude-names",
        default=",".join(sorted(DEFAULT_EXCLUDED_NAMES)),
        help=(
            "Comma-separated function names to exclude "
            "(default: main,parse_args,build_parser)."
        ),
    )
    p.add_argument("--no-methods", action="store_true", help="Ignore class methods.")
    p.add_argument("--no-nested", action="store_true", help="Ignore nested functions.")
    p.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.92,
        help="Cosine threshold for similar-logic pair reporting (default: 0.92).",
    )
    p.add_argument(
        "--min-similarity-nodes",
        type=int,
        default=12,
        help="Ignore tiny functions below this AST node count for similarity checks (default: 12).",
    )
    p.add_argument(
        "--max-similar-pairs",
        type=int,
        default=120,
        help="Maximum similar-logic pairs to keep (default: 120).",
    )
    p.add_argument("--skip-similarity", action="store_true", help="Skip pairwise similar-logic detection.")
    p.add_argument("--json", action="store_true", help="Emit JSON payload.")
    return p.parse_args()


def _print_text(payload: dict, *, limit: int) -> None:
    print(f"ROOT: {payload['root']}")
    print(f"TOTAL_FUNCTIONS: {payload['totals']['total_functions']}")
    print(f"TOTAL_TOP_LEVEL_FUNCTIONS: {payload['totals']['top_level_functions']}")
    print(f"TOTAL_METHODS: {payload['totals']['methods']}")
    print(f"TOTAL_NESTED_FUNCTIONS: {payload['totals']['nested_functions']}")
    print(f"EXACT_CLONE_GROUPS: {payload['totals']['exact_clone_groups']}")
    print(f"SHAPE_CLONE_GROUPS: {payload['totals']['shape_clone_groups']}")
    print(f"SAME_NAME_GROUPS: {payload['totals']['same_name_groups']}")
    print(f"SIMILAR_LOGIC_PAIRS: {payload['totals']['similar_logic_pairs']}")

    print("\n[Exact Clone Groups]")
    for g in payload["exact_clone_groups"][: max(1, limit)]:
        print(f"- hash={g['key'][:10]} count={g['count']} names={','.join(g['names'])}")
        for item in g["items"]:
            print(f"  - {item['module']}:{item['lineno']} {item['qualname']} ({item['kind']})")

    print("\n[Shape Clone Groups]")
    for g in payload["shape_clone_groups"][: max(1, limit)]:
        print(f"- shape={g['key'][:10]} count={g['count']} names={','.join(g['names'])}")
        for item in g["items"]:
            print(f"  - {item['module']}:{item['lineno']} {item['qualname']} ({item['kind']})")

    print("\n[Same-Name Groups]")
    for g in payload["same_name_groups"][: max(1, limit)]:
        flavor = "exact-clone" if g["exact_clone"] else "similar-name-different-body"
        print(
            f"- name={g['name']} count={g['count']} impls={g['distinct_implementations']} type={flavor}"
        )
        for hg in g["hash_groups"]:
            print(f"  - impl hash={hg['hash'][:10]} count={hg['count']}")
            for item in hg["items"]:
                print(f"    - {item['module']}:{item['lineno']} {item['qualname']}")

    print("\n[Similar-Logic Pairs]")
    for row in payload["similar_logic_pairs"][: max(1, limit)]:
        l = row["left"]
        r = row["right"]
        print(
            f"- score={row['score']:.3f} same_name={row['same_name']} "
            f"{l['module']}:{l['lineno']} {l['qualname']} <-> {r['module']}:{r['lineno']} {r['qualname']}"
        )


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Invalid --root directory: {root}")

    funcs = collect_functions(
        root,
        include_methods=not bool(args.no_methods),
        include_nested=not bool(args.no_nested),
    )

    only = {x.strip() for x in str(args.only_names or "").split(",") if x.strip()}
    excluded = {x.strip() for x in str(args.exclude_names or "").split(",") if x.strip()}
    if only:
        funcs = [f for f in funcs if f.name in only]
    elif excluded:
        funcs = [f for f in funcs if f.name not in excluded]

    exact_groups = _group_by_field(funcs, field="hash", min_size=max(2, int(args.min_group_size)))
    shape_groups = _group_by_field(funcs, field="shape_hash", min_size=max(2, int(args.min_group_size)))
    name_groups = _group_by_name(funcs, min_size=max(2, int(args.min_group_size)))
    similar_pairs = [] if args.skip_similarity else _find_similar_logic_pairs(
        funcs,
        similarity_threshold=max(0.0, min(1.0, float(args.similarity_threshold))),
        min_nodes=max(1, int(args.min_similarity_nodes)),
        max_pairs=max(1, int(args.max_similar_pairs)),
    )

    kind_counter = Counter(f.kind for f in funcs)
    payload = {
        "root": str(root),
        "filters": {
            "only_names": sorted(only),
            "excluded_names": sorted(excluded),
            "include_methods": not bool(args.no_methods),
            "include_nested": not bool(args.no_nested),
            "similarity_threshold": float(args.similarity_threshold),
            "min_similarity_nodes": int(args.min_similarity_nodes),
            "max_similar_pairs": int(args.max_similar_pairs),
            "skip_similarity": bool(args.skip_similarity),
        },
        "totals": {
            "total_functions": len(funcs),
            "top_level_functions": int(kind_counter.get("function", 0)),
            "methods": int(kind_counter.get("method", 0)),
            "nested_functions": int(kind_counter.get("nested", 0)),
            "exact_clone_groups": len(exact_groups),
            "shape_clone_groups": len(shape_groups),
            "same_name_groups": len(name_groups),
            "similar_logic_pairs": len(similar_pairs),
        },
        "exact_clone_groups": exact_groups,
        "shape_clone_groups": shape_groups,
        "same_name_groups": name_groups,
        "similar_logic_pairs": similar_pairs,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload, limit=max(1, int(args.limit)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
