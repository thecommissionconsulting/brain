"""The mechanical pass finds every planted defect in the fixture and nothing on the distractors."""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
FIXTURE = SKILL.parents[1] / "evals" / "data-model-audit-roastery" / "fixtures"


def audit(*paths, claims=None, extra=()):
    cmd = [sys.executable, str(SKILL / "scripts" / "audit_sql.py"), *map(str, paths), *extra]
    if claims:
        cmd += ["--claims", str(claims)]
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)


def found(result):
    return {(c["check"], c["object"].split(".")[-1], c["status"]) for c in result["candidates"]}


def test_every_planted_defect_is_found():
    got = found(audit(FIXTURE / "model.sql", claims=FIXTURE / "claims.json"))
    expected = {
        ("LAYER-04", "order_lines", "candidate"),
        ("GOV-01", "dim_employee", "candidate"),
        ("GOV-02", "dim_store", "candidate"),
        ("KEY-03", "fact_sales", "candidate"),
        ("DOC-03", "fact_sales", "candidate"),
        ("SET-01", "fact_roasts", "candidate"),
        ("KEY-04", "fact_sales -> dim_store", "candidate"),
        ("KEY-04", "fact_sales -> dim_customer", "candidate"),
        ("KEY-02", "fact_roasts -> dim_shift", "candidate"),
    }
    assert expected <= got, expected - got


def test_no_finding_on_distractors():
    r = audit(FIXTURE / "model.sql", claims=FIXTURE / "claims.json")
    flagged = {c["object"].split(".")[-1] for c in r["candidates"]}
    assert "src_open_orders" not in flagged          # SELECT * with a filter is not a wrapper
    assert "fact_movements" not in flagged           # explicit union, same order
    assert not any("notes" in c["detail"] for c in r["candidates"])     # NULL, but not a key
    assert not any("channel" in c["detail"] for c in r["candidates"])   # short IN list
    assert not any("dim_date" in c["object"] for c in r["candidates"])  # documented join holds


def test_set_check_names_the_swapped_columns():
    r = audit(FIXTURE / "model.sql")
    (c,) = [c for c in r["candidates"] if c["check"] == "SET-01" and c["status"] == "candidate"]
    assert "kg <- kind" in c["detail"] and c["where"].endswith(":57")
    (u,) = [c for c in r["candidates"] if c["check"] == "SET-01" and c["status"] == "not_checkable"]
    assert u["object"].endswith("fact_all_batches")


def test_unresolvable_star_union_is_not_checkable_not_a_pass(tmp_path):
    sql = tmp_path / "m.sql"
    sql.write_text("CREATE VIEW v AS SELECT * FROM a.b.one UNION ALL SELECT * FROM a.b.two;")
    (c,) = audit(sql)["candidates"]
    assert (c["check"], c["status"]) == ("SET-01", "not_checkable")


def test_claim_against_star_output_is_not_checkable(tmp_path):
    sql = tmp_path / "m.sql"
    sql.write_text("CREATE VIEW f AS SELECT * FROM a.b.t;\nCREATE VIEW d AS SELECT k FROM a.b.d;")
    claims = tmp_path / "c.json"
    claims.write_text(json.dumps([{"fact": "f", "fact_col": "k", "dim": "d", "dim_col": "k", "where": "doc:1"}]))
    r = audit(sql, claims=claims)
    assert [c["status"] for c in r["candidates"] if c["check"] == "KEY-04"] == ["not_checkable"]


def test_dbt_compiled_models_are_one_object_per_file(tmp_path):
    (tmp_path / "fct_orders.sql").write_text("select o.order_id, cast(null as int) as customer_key\nfrom raw.orders o\n")
    r = audit(tmp_path)
    assert r["inventory"]["objects"][0]["name"] == "fct_orders"
    assert ("KEY-03", "fct_orders", "candidate") in found(r)


def test_notebook_markdown_is_ignored_and_lines_stay_true(tmp_path):
    nb = tmp_path / "nb.sql"
    nb.write_text("-- Databricks notebook source\n-- MAGIC %md\n-- MAGIC # Title\n\n-- COMMAND ----------\n\n"
                  "CREATE VIEW x.y.v AS SELECT * FROM x.y.t;\n")
    r = audit(nb)
    assert r["inventory"]["objects"][0]["where"].endswith(":7")


def test_fact_to_fact_join_is_flagged():
    assert ("FACT-03", "fact_sales_per_kg", "candidate") in found(audit(FIXTURE / "model.sql"))


def test_dbt_final_cte_and_raw_layer_are_not_wrappers(tmp_path):
    marts = tmp_path / "target" / "compiled" / "shop" / "models" / "marts"
    raw = tmp_path / "target" / "compiled" / "shop" / "models" / "raw"
    marts.mkdir(parents=True)
    raw.mkdir(parents=True)
    (marts / "dim_store.sql").write_text("with final as (select id from db.s.stores where live)\nselect * from final\n")
    (raw / "raw_pos_orders.sql").write_text("select * from landing.pos.orders\n")
    r = audit(tmp_path)
    assert not [c for c in r["candidates"] if c["check"] == "LAYER-04" and c["status"] != "info"]
    assert r["inventory"]["objects"][0]["name"] in ("dim_store", "raw_pos_orders")


def test_compiled_sql_maps_back_to_the_model_file(tmp_path):
    d = tmp_path / "proj" / "target" / "compiled" / "shop" / "models" / "marts"
    d.mkdir(parents=True)
    (d / "fct_orders.sql").write_text("select cast(null as int) as customer_key from db.s.orders\n")
    (c,) = [c for c in audit(tmp_path / "proj")["candidates"] if c["check"] == "KEY-03"]
    assert c["model_file"].endswith("proj/models/marts/fct_orders.sql")


def verify(findings, tmp_path):
    import subprocess as sp
    p = tmp_path / "f.json"
    p.write_text(json.dumps(findings))
    return sp.run([sys.executable, str(SKILL / "scripts" / "verify_findings.py"), str(p), "--root", str(FIXTURE)],
                  capture_output=True, text=True)


def test_verify_accepts_a_true_citation_and_rejects_false_ones(tmp_path):
    good = {"id": "F1", "check": "KEY-03", "verdict": "CONFIRMED", "where": "model.sql:42",
            "evidence": ["customer_id", "null"], "candidate_status": "candidate"}
    assert verify([good], tmp_path).returncode == 0
    wrong_line = {**good, "where": "model.sql:12"}
    no_tokens = {**good, "evidence": []}
    promoted = {**good, "candidate_status": "not_checkable"}
    other_side = {**good, "also": [{"where": "claims.json:2", "evidence": ["store_key_that_is_not_there"]}]}
    for bad in (wrong_line, no_tokens, promoted, other_side):
        assert verify([bad], tmp_path).returncode == 1, bad


def test_source_aligned_wrapper_is_info_not_a_candidate(tmp_path):
    sql = tmp_path / "m.sql"
    sql.write_text("CREATE VIEW sbx.eng.f1_src_orders AS SELECT * FROM prod.std.orders;")
    (c,) = audit(sql)["candidates"]
    assert (c["check"], c["status"]) == ("LAYER-04", "info")
