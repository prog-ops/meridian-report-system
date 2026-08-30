import argparse
import hashlib
import json
import os
import sys

import yaml

from .audit import AuditLog
from .graph import GraphBuilder
from .compute import compute_all
from .narrative import build_narrative, firewall_check
from .reconcile import load_expected, reconcile_figures, traceability_check
from .report import write_report


def sha256_file(path: str) -> str:
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)

    return h.hexdigest()


def write_json(path: str, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def write_text(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
        f.write("\n")


def resolve_input(primary, fallback, audit, kind):
    if primary and os.path.exists(primary):
        return primary

    if fallback and os.path.exists(fallback):
        audit.record(
            "FALLBACK_INPUT_USED",
            "main",
            {
                "kind": kind,
                "primary": primary,
                "fallback": fallback,
            },
        )
        return fallback

    raise FileNotFoundError(f"Missing input for {kind}: {primary}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    outdir = cfg.get("output_dir", "output")
    os.makedirs(outdir, exist_ok=True)

    audit = AuditLog(cfg.get("audit_db", os.path.join(outdir, "audit.db")))

    audit.record(
        "CONFIG_LOADED",
        "main",
        {
            "config_path": args.config,
            "config_sha256": sha256_file(args.config),
            "firm_id": cfg["firm_id"],
        },
    )

    holdings_path = resolve_input(
        cfg["inputs"]["holdings"],
        cfg["inputs"].get("fallback_holdings"),
        audit,
        "holdings",
    )

    answer_key_path = cfg["inputs"].get("answer_key")
    fallback_answer_key = cfg["inputs"].get("fallback_answer_key")

    builder = GraphBuilder(
        cfg["inputs"]["guidelines_rules"],
        holdings_path,
        audit,
        asset_class_mapping=cfg.get("asset_class_mapping"),
    )

    G = builder.build()

    figures = compute_all(G, cfg, holdings_path)

    figures_path = os.path.join(outdir, "figures.json")
    write_json(figures_path, figures)

    audit.record(
        "FIGURES_COMPUTED",
        "compute",
        {
            "count": len(figures),
            "figures_sha256": sha256_file(figures_path),
        },
    )

    report_path = os.path.join(outdir, f"{cfg['firm_id']}_report.xlsx")
    write_report(figures, report_path)

    audit.record(
        "REPORT_EXPORTED",
        "report",
        {
            "path": report_path,
        },
    )

    expected = load_expected(answer_key_path, fallback_answer_key)
    recon = reconcile_figures(figures, expected)

    write_json(os.path.join(outdir, "reconciliation.json"), recon)

    audit.record(
        "RECONCILIATION_COMPLETED",
        "reconcile",
        {
            "overall_pass": recon["overall_pass"],
        },
    )

    trace = traceability_check(figures, G)

    write_json(os.path.join(outdir, "traceability_check.json"), trace)

    audit.record(
        "TRACEABILITY_CHECK",
        "trace",
        {
            "passed": trace["passed"],
            "issues": len(trace["issues"]),
        },
    )

    narrative = build_narrative(figures, cfg)
    firewall = firewall_check(narrative, figures)

    write_text(os.path.join(outdir, "narrative.txt"), narrative)
    write_json(os.path.join(outdir, "narrative_firewall.json"), firewall)

    audit.record(
        "NARRATIVE_FIREWALL",
        "narrative",
        {
            "passed": firewall["passed"],
        },
    )

    print(f"firm_id={cfg['firm_id']}")
    print(f"reconciliation_pass={recon['overall_pass']}")
    print(f"traceability_pass={trace['passed']}")
    print(f"narrative_firewall_pass={firewall['passed']}")
    print(f"report={report_path}")

    if not (
        recon["overall_pass"]
        and trace["passed"]
        and firewall["passed"]
    ):
        sys.exit(2)


if __name__ == "__main__":
    main()