"""Mechanical pass of a data-model audit: parse every object and emit CANDIDATE findings.

Nothing this script prints is a verdict. Each candidate names a check id from
references/checklist.md, the file and line it points at, and what to verify. The model
reading the output re-reads the code and confirms or drops each one. A check that cannot
be decided from the text is reported as "not_checkable", never as a pass.

Inputs (any mix):
  - .sql files or directories of them: plain DDL scripts, Databricks notebook exports
    ("-- COMMAND ----------" cells, "-- MAGIC" markdown), or dbt compiled models
    (target/compiled/**.sql, one SELECT per file, named after the file)
  - --claims claims.json: documented joins the model asserts, extracted from its docs by the
    auditor: [{"fact": .., "fact_col": .., "dim": .., "dim_col": .., "dim_grain": [..],
    "where": "file:line"}]. Each is checked against the columns the SQL outputs.

    uv run --with sqlglot python audit_sql.py models/ --claims claims.json -o candidates.json
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import sqlglot
    from sqlglot import exp
except ImportError:  # pragma: no cover
    sys.exit("needs sqlglot: uv run --with sqlglot python audit_sql.py ...")

CREATE_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?(MATERIALIZED\s+VIEW|VIEW|TABLE)"
    r"\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\"\w.]+)", re.I)
CLONE_RE = re.compile(r"\b(?:DEEP|SHALLOW)\s+CLONE\s+([`\"\w.]+)", re.I)
KEYISH = re.compile(r"(_id|_key|_code|_number|_no|_num|^id|^key)$", re.I)
TABLEISH = re.compile(r"\b([a-z]\w*\.[a-z]\w*(?:\.[a-z]\w*)?|[a-z]\w*__\w+)\b", re.I)


def arg(node, name):
    """node.args[name], allowing for sqlglot versions that renamed it name_ (from -> from_)."""
    return node.args.get(name) or node.args.get(name + "_")


def norm(name: str) -> str:
    return name.replace("`", "").replace('"', "").lower()


def short(name: str) -> str:
    return norm(name).split(".")[-1]


# ---------------------------------------------------------------- reading the files

def clean_notebook(text: str) -> tuple[str, str]:
    """(sql with markdown blanked out, the markdown) for a Databricks notebook export.
    Lines keep their positions so line numbers stay true."""
    sql, md = [], []
    for line in text.splitlines():
        if line.lstrip().startswith("-- MAGIC") or line.startswith("-- Databricks notebook source") \
                or line.startswith("-- COMMAND"):
            md.append(line)
            sql.append("")
        else:
            sql.append(line)
    return "\n".join(sql), "\n".join(md)


def split_statements(text: str) -> list[tuple[int, str]]:
    """[(start offset, statement)] split on semicolons outside quotes and comments."""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            j = text.find(c, i + 1)
            i = n if j < 0 else j + 1
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == ";":
            out.append((start, text[start:i]))
            start = i + 1
        i += 1
    if text[start:].strip():
        out.append((start, text[start:]))
    return out


def model_file(path: str) -> str:
    """For dbt compiled SQL (target/compiled/<project>/models/x.sql), the model the engineer opens.
    Line numbers still refer to the compiled file."""
    m = re.match(r"(.*?)/target/(?:compiled|run)/[^/]+/(.*)", path.replace("\\", "/"))
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


class Obj:
    def __init__(self, name, kind, file, line, stmt, offset, full_text):
        self.name, self.kind, self.file, self.line = name, kind, file, line
        self.stmt, self.offset, self.text = stmt, offset, full_text
        self.tree = None
        self.columns: list[str] = []      # output column names, "*" if a star hides them
        self.column_exprs: dict = {}
        self.sources: set[str] = set()    # full names read, CTEs excluded
        self.parse_error = ""

    def line_of(self, needle: str) -> int:
        """Line of the first occurrence of needle inside this statement, else the statement's line."""
        code = re.sub(r"--[^\n]*", lambda m: " " * len(m.group(0)), self.stmt)  # skip comments, keep offsets
        k = code.lower().find(needle.lower())
        if k < 0:
            k = self.stmt.lower().find(needle.lower())
        return line_at(self.text, self.offset + k) if k >= 0 else self.line

    def where(self, needle: str = "") -> str:
        return f"{self.file}:{self.line_of(needle) if needle else self.line}"


def dbt_materialisations(files: list[Path]) -> dict:
    """{compiled file: VIEW | TABLE | ...} from the manifest beside target/compiled, when there is one."""
    out, seen = {}, set()
    for f in files:
        target = next((d for d in f.resolve().parents
                       if (d / "manifest.json").exists() and (d / "compiled").is_dir()), None)
        if target is None or target in seen:
            continue
        seen.add(target)
        manifest = target / "manifest.json"
        for node in json.loads(manifest.read_text()).get("nodes", {}).values():
            if node.get("resource_type") != "model":
                continue
            mat = (node.get("config", {}).get("materialized") or "model").upper()
            rel = f"compiled/{node['package_name']}/{node['original_file_path']}"
            out[str((target / rel).resolve())] = {"INCREMENTAL": "TABLE", "EPHEMERAL": "EPHEMERAL"}.get(mat, mat)
    return out


def read_objects(paths: list[Path], dialect: str) -> tuple[list[Obj], list[dict]]:
    objs, unparsed = [], []
    files = []
    for p in paths:
        files += sorted(p.rglob("*.sql")) if p.is_dir() else [p]
    # dbt compiles generic tests under models/<path>/<schema>.yml/ and singular tests under tests/
    files = [f for f in files if not any(part.endswith((".yml", ".yaml")) for part in f.parts)]
    files = [f for f in files if not re.search(r"/target/(?:compiled|run)/[^/]+/tests/", str(f).replace("\\", "/"))]
    materialized = dbt_materialisations(files)
    for f in files:
        raw = f.read_text(encoding="utf-8", errors="replace")
        text, _ = clean_notebook(raw) if "-- COMMAND ----------" in raw or "-- MAGIC" in raw else (raw, "")
        stmts = [(o, s) for o, s in split_statements(text) if s.strip()]
        creates = [(o, s, CREATE_RE.search(s)) for o, s in stmts]
        if not any(m for _, _, m in creates):
            # a dbt compiled model: the file is one SELECT, named after the file
            body = text.strip().rstrip(";")
            if body:
                first = len(text) - len(text.lstrip())
                objs.append(Obj(f.stem, materialized.get(str(f.resolve()), "model"), str(f), line_at(text, first),
                                body, first, text))
            continue
        for off, s, m in creates:
            if not m:
                if re.search(r"\b(SELECT|INSERT|MERGE|UPDATE|DELETE)\b", s, re.I):
                    lead = len(s) - len(s.lstrip())
                    unparsed.append({"file": str(f), "line": line_at(text, off + lead),
                                     "note": "statement is not a CREATE; not modelled (" + s.strip().split()[0] + ")"})
                continue
            lead = len(s) - len(s.lstrip())
            objs.append(Obj(norm(m.group(2)), m.group(1).upper(), str(f), line_at(text, off + m.start()), s,
                            off, text))
    for o in objs:
        analyse(o, dialect)
        if o.parse_error:
            unparsed.append({"file": o.file, "line": o.line, "note": f"{o.name}: {o.parse_error}"})
    return objs, unparsed


# ---------------------------------------------------------------- analysing one object

def outer_select(tree):
    """The query that defines the object's output columns."""
    if isinstance(tree, exp.Create):
        tree = tree.expression
    while isinstance(tree, exp.Subquery):
        tree = tree.this
    return tree


def projections(select) -> tuple[list[str], dict]:
    cols, exprs = [], {}
    for p in select.expressions:
        if isinstance(p, exp.Star) or (isinstance(p, exp.Column) and isinstance(p.this, exp.Star)):
            cols.append("*")
            continue
        name = p.alias_or_name
        cols.append(name.lower() if name else "?")
        exprs[(name or "?").lower()] = p.unalias() if isinstance(p, exp.Alias) else p
    return cols, exprs


def branches(q) -> list:
    if isinstance(q, (exp.Union, exp.Intersect, exp.Except)):
        return branches(q.left) + branches(q.right)
    while isinstance(q, exp.Subquery):
        q = q.this
    return [q]


def cols_of(q, cte_cols: dict):
    """Output column names of a query branch, resolving SELECT * FROM <cte> when the CTE lists
    its columns. None when they cannot be known from the text."""
    while isinstance(q, exp.Subquery):
        q = q.this
    if isinstance(q, (exp.Union, exp.Intersect, exp.Except)):
        return cols_of(q.left, cte_cols)
    if not isinstance(q, exp.Select):
        return None
    cols = projections(q)[0]
    if cols == ["*"] and not arg(q, "joins"):
        src = arg(q, "from")
        t = src.this if src else None
        if isinstance(t, exp.Table):
            if not t.db and norm(t.name) in cte_cols:
                return cte_cols[norm(t.name)]
            return OBJECT_COLS.get(norm(".".join(p for p in (t.catalog, t.db, t.name) if p))) \
                or OBJECT_COLS.get(norm(t.name))
        return None
    return None if "*" in cols else cols


OBJECT_COLS: dict = {}  # name -> output columns of every object in the inputs, for SELECT * across objects


def resolve_star_columns(objs: list) -> None:
    """Give objects that end in SELECT * (dbt's `select * from final`) their real columns, by
    following their own CTEs and the other objects they read. Repeats until nothing changes."""
    for _ in range(len(objs) + 1):
        changed = False
        for o in objs:
            if o.columns and "*" not in o.columns:
                OBJECT_COLS[o.name] = OBJECT_COLS[short(o.name)] = o.columns
        for o in objs:
            if not o.tree or (o.columns and "*" not in o.columns):
                continue
            ctes = {}
            for c in o.tree.find_all(exp.CTE):
                ctes[norm(c.alias)] = cols_of(c.this, ctes)
            q = outer_select(o.tree)
            cols = cols_of(q, ctes) if q is not None else None
            if cols:
                o.columns, changed = cols, True
        if not changed:
            return


def set_check(o, label, needle, bs, cte_cols, add) -> None:
    if len(bs) < 2:
        return
    lists = [cols_of(b, cte_cols) for b in bs]
    if any(c is None for c in lists):
        add("SET-01", o, needle, f"{label}set operation over {len(bs)} branches with SELECT * whose columns are "
            "not visible here; columns line up by position, so compare each source's column ORDER",
            status="not_checkable")
        return
    ref = lists[0]
    for k, cols in enumerate(lists[1:], 2):
        if len(cols) != len(ref):
            add("SET-02", o, needle, f"{label}branch {k} has {len(cols)} columns, branch 1 has {len(ref)}")
        else:
            # a rename or an unaliased literal is harmless; a name that sits at a different position is not
            pos = {c: i for i, c in enumerate(cols) if c != "?"}
            moved = [f"{r} <- {cols[i]}" for i, r in enumerate(ref) if r != "?" and r in pos and pos[r] != i]
            if moved:
                kind = "SET-01" if any(isinstance(b, exp.Select) and projections(b)[0] == ["*"] for b in bs) \
                    else "SET-02"
                add(kind, o, needle, f"{label}branch {k} has the same columns in a different order, lined up by "
                    "position: " + ", ".join(moved[:6]) + (" ..." if len(moved) > 6 else ""))


def analyse(o: Obj, dialect: str) -> None:
    clone = CLONE_RE.search(o.stmt)
    if clone:
        o.sources = {norm(clone.group(1))}
        o.columns = ["*"]
        return
    try:
        o.tree = sqlglot.parse_one(o.stmt, read=dialect)
    except Exception as e:  # noqa: BLE001 - any parser failure is reported, not fatal
        o.parse_error = str(e).splitlines()[0][:160]
        return
    q = outer_select(o.tree)
    if q is None:
        o.parse_error = "no query body"
        return
    first = branches(q)[0]
    if isinstance(first, exp.Select):
        o.columns, o.column_exprs = projections(first)
    ctes = {norm(c.alias) for c in o.tree.find_all(exp.CTE)}
    for t in o.tree.find_all(exp.Table):
        if not t.name or isinstance(t.parent, exp.Create) and t.parent.this is t:
            continue
        full = norm(".".join(p for p in (t.catalog, t.db, t.name) if p))
        if full and full not in ctes and full != o.name and not o.name.endswith("." + full):
            o.sources.add(full)
    o.sources -= {o.name}


# ---------------------------------------------------------------- the checks

def candidates(objs: list[Obj], claims: list[dict], args) -> list[dict]:
    out = []
    by_short = {short(o.name): o for o in objs}

    def add(check, o, needle, detail, status="candidate", evidence=(), **kw):
        """evidence: tokens that must appear within a few lines of `where` (scripts/verify_findings.py)."""
        tokens = [t for t in ([needle] if needle else []) + list(evidence) if t]
        out.append({"check": check, "object": o.name if o else "", "where": o.where(needle) if o else kw.pop("where", ""),
                    "model_file": model_file(o.file) if o else "", "detail": detail, "status": status,
                    "evidence": tokens, **kw})

    resolve_star_columns(objs)
    for o in objs:
        if o.columns and "*" not in o.columns:
            OBJECT_COLS[o.name] = OBJECT_COLS[short(o.name)] = o.columns
    in_lists = defaultdict(list)
    for o in objs:
        if not o.tree:
            continue
        q = outer_select(o.tree)
        bs = branches(q) if q is not None else []

        # SET-01 / SET-02: set operations line columns up by position, not by name
        cte_cols = {}
        for c in o.tree.find_all(exp.CTE):  # in order, so a CTE can resolve through an earlier one
            cte_cols[norm(c.alias)] = cols_of(c.this, cte_cols)
        for label, needle, q_ in [("", "union", q)] + [(f"CTE {c.alias}: ", c.alias, c.this)
                                                       for c in o.tree.find_all(exp.CTE)]:
            set_check(o, label, needle, branches(q_) if q_ is not None else [], cte_cols, add)

        # KEY-03: a key-like output column that is a NULL or constant literal
        for name, e in o.column_exprs.items():
            core = e.this if isinstance(e, exp.Cast) else e
            if KEYISH.search(name) and isinstance(core, (exp.Null, exp.Literal)):
                add("KEY-03", o, name, evidence=["null" if isinstance(core, exp.Null) else ""], detail=f"output column {name} is a {'NULL' if isinstance(core, exp.Null) else 'constant'} "
                    "literal; any join on it never matches (or always matches)")

        # LAYER-04: wrapper-only object
        frm = arg(q, "from") if isinstance(q, exp.Select) else None
        over_table = frm is not None and isinstance(frm.this, exp.Table) and not list(o.tree.find_all(exp.CTE))
        if over_table and o.columns == ["*"] and len(o.sources) == 1 and not arg(q, "joins") \
                and not arg(q, "where") and not arg(q, "group"):
            src = next(iter(o.sources))
            if re.search(args.source_aligned, f"{o.file} {o.name}", re.I):
                # by design in a source-aligned layer; a duplicate only when it re-exposes another estate's object
                add("LAYER-04", o, "", f"source-aligned wrapper over {src}", status="info", evidence=[short(src)])
            else:
                add("LAYER-04", o, "", f"only re-exposes {src}: no filter, join or logic", evidence=[short(src)])

        # FACT-03: a fact built by joining another fact
        if re.search(args.fact_pattern, short(o.name), re.I):
            others = sorted(s_ for s_ in o.sources if re.search(args.fact_pattern, short(s_), re.I))
            if len(others) > 1 or (others and arg(q, "joins") if isinstance(q, exp.Select) else False):
                add("FACT-03", o, short(others[0]), f"fact reads other facts {[short(x) for x in others]}: "
                    "fact-to-fact joins usually fan out or mix grain")

        # GOV-02: hard-coded literal lists
        for node in o.tree.find_all(exp.In):
            vals = node.expressions
            if len(vals) >= args.in_list and all(isinstance(v, exp.Literal) for v in vals):
                key = tuple(sorted(v.this for v in vals))
                in_lists[key].append(o)
                add("GOV-02", o, vals[0].sql(), f"IN list of {len(vals)} literals on {node.this.sql()[:60]}")

        # GOV-01: restricted or confidential sources
        for s in sorted(o.sources):
            if re.search(args.restricted, s, re.I):
                add("GOV-01", o, s.split(".")[-1], f"reads {s}")

        # DOC-03: a comment inside the object names a table the SQL does not read
        comments = re.findall(r"--([^\n]*)", o.stmt)
        named = {m.lower() for c in comments for m in TABLEISH.findall(c)}
        read = {short(s) for s in o.sources} | {s for s in o.sources}
        for t in sorted(named):
            if "__" in t and short(t) not in read and t not in read and short(t) not in by_short:
                add("DOC-03", o, t, f"a comment names {t}, which this object does not read")

    # GOV-02 rolled up: the same list repeated across objects
    for key, os_ in in_lists.items():
        if len(os_) > 1:
            out.append({"check": "GOV-02", "object": ", ".join(sorted({x.name for x in os_})), "where": os_[0].where(),
                        "detail": f"the same {len(key)}-value list appears in {len(os_)} objects: belongs in one "
                                  "config table", "status": "candidate"})

    # LAYER-06: long chains of views with no materialised step
    views = {short(o.name): o for o in objs if o.kind == "VIEW"}  # dbt "model" = materialisation unknown
    depth = {}

    def chain(n, seen=()):
        if n in depth:
            return depth[n]
        if n in seen or n not in views:
            return 0
        d = 1 + max([chain(short(s), seen + (n,)) for s in views[n].sources] or [0])
        depth[n] = d
        return d
    for n, o in views.items():
        if chain(n) > args.view_depth:
            add("LAYER-06", o, "", f"{chain(n)} views deep with no table in between")

    # Claims: documented joins checked against what the SQL outputs
    for c in claims:
        sides = [("fact", c.get("fact"), c.get("fact_col")), ("dim", c.get("dim"), c.get("dim_col"))]
        problems, unknown = [], []
        for role, obj, col in sides:
            o = by_short.get(short(obj or ""))
            if not o or not col:
                unknown.append(f"{role} {obj} not defined in the inputs" if not o else f"{role} column missing")
            elif "*" in o.columns:
                unknown.append(f"{role} {obj} outputs SELECT *, columns not visible")
            elif norm(col) not in o.columns:
                problems.append(f"{role} {obj} does not output {col}")
            elif role == "fact":
                e = o.column_exprs.get(norm(col))
                core = e.this if isinstance(e, exp.Cast) else e
                if isinstance(core, exp.Null):
                    problems.append(f"fact {obj}.{col} is NULL in the SQL")
        grain = [norm(g) for g in c.get("dim_grain") or []]
        if len(grain) > 1 and c.get("dim_col") and norm(c["dim_col"]) in grain:
            problems.append(f"dim grain is {grain}; the join uses {c['dim_col']} alone")
        o = by_short.get(short(c.get("fact") or ""))
        base = {"check": "KEY-04", "object": f"{c.get('fact')} -> {c.get('dim')}", "where": c.get("where", ""),
                "code": o.where() if o else ""}
        if problems:
            out.append({**base, "check": "KEY-02" if "grain" in problems[-1] else "KEY-04",
                        "detail": "; ".join(problems), "status": "candidate"})
        elif unknown:
            out.append({**base, "detail": "; ".join(unknown), "status": "not_checkable"})
    return out


def inventory(objs: list[Obj]) -> dict:
    created = {short(o.name) for o in objs}
    external = sorted({s for o in objs for s in o.sources if short(s) not in created})
    return {
        "objects": [{"name": o.name, "kind": o.kind, "where": o.where(), "columns": o.columns[:200],
                     "sources": sorted(o.sources)} for o in objs],
        "external_sources": external,
        "counts": {"objects": len(objs), "external_sources": len(external),
                   "by_kind": {k: sum(1 for o in objs if o.kind == k) for k in sorted({o.kind for o in objs})}},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--claims", type=Path, help="documented joins to check, JSON")
    ap.add_argument("--dialect", default="databricks")
    ap.add_argument("--restricted", default=r"restricted|confidential|_pii|sensitive",
                    help="regex for source names that need access control")
    ap.add_argument("--in-list", type=int, default=5, help="flag IN lists with at least this many literals")
    ap.add_argument("--view-depth", type=int, default=5, help="flag view chains deeper than this")
    ap.add_argument("--source-aligned", default=r"(^|[/_.])(raw|src|stg|staging|bronze|landing)[/_.]",
                    help="regex on path or name: objects in these layers may be plain SELECT * wrappers")
    ap.add_argument("--fact-pattern", default=r"^(fact|fct)_|_(fact|fct)$", help="regex for fact object names")
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()

    objs, unparsed = read_objects(args.paths, args.dialect)
    claims = json.loads(args.claims.read_text()) if args.claims else []
    result = {"inventory": inventory(objs), "candidates": candidates(objs, claims, args), "unparsed": unparsed}
    by_check = defaultdict(int)
    for c in result["candidates"]:
        by_check[f"{c['check']} ({c['status']})"] += 1
    result["summary"] = {**result["inventory"]["counts"], "candidates": dict(sorted(by_check.items())),
                         "unparsed": len(unparsed)}
    text = json.dumps(result, indent=1)
    if args.out:
        args.out.write_text(text)
        print(json.dumps(result["summary"], indent=1))
    else:
        print(text)


if __name__ == "__main__":
    main()
