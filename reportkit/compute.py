import re
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

D = Decimal


def d(x):
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def q(value: Decimal, places: int, rounding=ROUND_HALF_UP) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=rounding)


def incoming_by_relation(G, target, relation):
    if target not in G:
        return []
    out = []
    for u, v, data in G.in_edges(target, data=True):
        if data.get("relation") == relation:
            out.append(u)
    return sorted(out)


def out_target_by_relation(G, source, relation):
    if source not in G:
        return None
    for u, v, data in G.out_edges(source, data=True):
        if data.get("relation") == relation:
            return v
    return None


def position_ids(G):
    return sorted(n for n, attr in G.nodes(data=True) if attr.get("type") == "Position")


def sum_positions(G) -> Decimal:
    total = Decimal("0")
    for pid in position_ids(G):
        total += G.nodes[pid]["market_value"]
    return total


def exposure_for_asset_class(G, ac_name: str):
    ac_id = f"AssetClass:{ac_name}"
    total = Decimal("0")
    positions = []
    for pid in incoming_by_relation(G, ac_id, "BELONGS_TO"):
        if G.nodes[pid].get("type") == "Position":
            total += G.nodes[pid]["market_value"]
            positions.append(pid)
    return total, sorted(positions)


def chunk_citation(G, chunk_id: str):
    if not chunk_id:
        return {"source_doc": None, "page": None, "chunk_id": None, "passage_summary": ""}
    node_id = f"Chunk:{chunk_id}"
    if node_id in G.nodes:
        n = G.nodes[node_id]
        return {
            "source_doc": n.get("source_doc"),
            "page": n.get("page"),
            "chunk_id": n.get("chunk_id"),
            "passage_summary": n.get("passage_summary", ""),
        }
    return {
        "source_doc": None,
        "page": None,
        "chunk_id": chunk_id,
        "passage_summary": "",
    }


def method_citation(cfg, rule_id):
    for rule in cfg.get("method_rules", []):
        if rule.get("id") == rule_id:
            return rule.get("citation")
    return None


def format_source(graph_path: str, citations):
    parts = []
    for c in citations:
        if not c:
            continue
        src = c.get("source_doc") or "unknown"
        page = f" p.{c['page']}" if c.get("page") else ""
        chunk = f" {c['chunk_id']}" if c.get("chunk_id") else ""
        parts.append(f"{src}{page}{chunk}".strip())
    return f"{graph_path} → " + "; ".join(parts)


def status_bound(value: Decimal, minv, maxv, tol: Decimal) -> str:
    if minv is not None and value < (minv - tol):
        return "BREACH"
    if maxv is not None and value > (maxv + tol):
        return "BREACH"
    if maxv is not None and abs(value - maxv) <= tol:
        return "AT LIMIT"
    return "OK"


def pct_fmt(x: Decimal) -> str:
    return f"{format(x.normalize(), 'f')}%"


def limit_display(minv, maxv, unit: str, status: str, value: Decimal) -> str:
    if unit == "%":
        if minv is not None and maxv is not None:
            if status == "BREACH" and value < minv:
                return f"min {pct_fmt(minv)}"
            if status == "BREACH" and value > maxv:
                return f"max {pct_fmt(maxv)}"
            return f"{pct_fmt(minv)}–{pct_fmt(maxv)}"
        if minv is not None:
            return f"min {pct_fmt(minv)}"
        if maxv is not None:
            return f"max {pct_fmt(maxv)}"

    if unit == "yrs":
        if minv is not None and maxv is not None:
            if status == "BREACH" and value < minv:
                return f"min {q(minv, 1)} yrs"
            if status == "BREACH" and value > maxv:
                return f"max {q(maxv, 1)} yrs"
            return f"{q(minv, 1)}–{q(maxv, 1)} yrs"
        if minv is not None:
            return f"min {q(minv, 1)} yrs"
        if maxv is not None:
            return f"max {q(maxv, 1)} yrs"

    if unit == "SGD/bp":
        if maxv is not None:
            return f"max {int(maxv):,}"

    return ""


def format_utilization(ratio, cfg):
    if ratio is None:
        return "n/a"

    fmt = cfg["calculation"]["utilization"]["format"]
    if fmt == "percent_1dp":
        return f"{q(ratio * Decimal('100'), 1)}%"

    if fmt == "truncated_bps":
        bps = (ratio * Decimal("10000")).to_integral_value(rounding=ROUND_DOWN)
        return f"{int(bps)} bps"

    raise ValueError(f"Unknown utilization format: {fmt}")


def allocation_utilization(value: Decimal, minv, maxv, status: str, cfg):
    below_min = minv is not None and value < minv
    if below_min and cfg["calculation"]["utilization"].get("below_min_allocation_utilization") is None:
        return None

    if maxv is not None and maxv > 0:
        return value / maxv
    if minv is not None and minv > 0:
        return value / minv
    return None


def make_figure(
    figure_id,
    section,
    metric,
    value_str,
    limit_str,
    utilization_str,
    status,
    graph_path,
    citations,
    raw_value=None,
):
    citations = [c for c in citations if c]
    return {
        "figure": figure_id,
        "section": section,
        "metric": metric,
        "value": value_str,
        "limit": limit_str,
        "utilization": utilization_str,
        "status": status,
        "raw_value": None if raw_value is None else str(raw_value),
        "graph_path": graph_path,
        "citation": citations[0] if citations else {},
        "citations": citations,
        "source": format_source(graph_path, citations),
    }


def compute_all(G, cfg, holdings_path):
    figures = []
    nav = sum_positions(G)
    if nav <= 0:
        raise ValueError("NAV is zero or negative; cannot compute percentages.")

    tol = Decimal(str(cfg["calculation"]["status"]["at_limit_tolerance"]))
    pct_places = int(cfg["calculation"]["rounding"]["percent_value"])
    dur_places = int(cfg["calculation"]["rounding"]["duration"])
    dv01_places = int(cfg["calculation"]["rounding"]["dv01"])

    holdings_citation = {
        "source_doc": holdings_path,
        "page": None,
        "chunk_id": "holdings_snapshot",
        "passage_summary": "Period-end holdings snapshot",
    }

    # Allocation
    for ac_name in cfg["allocation_order"]:
        ac_id = f"AssetClass:{ac_name}"
        node = G.nodes.get(ac_id, {})
        total, _ = exposure_for_asset_class(G, ac_name)
        value = total / nav * Decimal("100")

        minv = d(node.get("limit_min"))
        maxv = d(node.get("limit_max"))
        chunk = node.get("chunk")

        status = status_bound(value, minv, maxv, tol)
        util_ratio = allocation_utilization(value, minv, maxv, status, cfg)
        util_str = format_utilization(util_ratio, cfg)
        limit_str = limit_display(minv, maxv, "%", status, value)
        value_str = f"{q(value, pct_places)}%"

        graph_path = (
            f"(Position)-[:BELONGS_TO]->({ac_id})"
            f"-[:HAS_LIMIT]->(Limit:allocation:{ac_name})"
        )
        citations = [chunk_citation(G, chunk), holdings_citation]

        figures.append(
            make_figure(
                f"allocation_{slugify(ac_name)}",
                "Allocation",
                ac_name,
                value_str,
                limit_str,
                util_str,
                status,
                graph_path,
                citations,
                raw_value=value,
            )
        )

    # Aggregate non-IG exposure
    agg_name = "Aggregate non-IG exposure"
    agg_id = f"Aggregate:{agg_name}"
    agg_node = G.nodes[agg_id]
    agg_max = d(agg_node["limit_max"])

    total_non_ig = Decimal("0")
    counted_positions = set()
    contributors = []

    for ac_id in incoming_by_relation(G, agg_id, "CONTRIBUTES_TO"):
        ac_node = G.nodes[ac_id]
        acn = ac_node["name"]
        expo, pos_ids = exposure_for_asset_class(G, acn)
        total_non_ig += expo
        counted_positions.update(pos_ids)
        contributors.append(acn)

    contributors = sorted(contributors)

    extra_paths = []
    fallen_positions = []
    include_fallen = bool(cfg["calculation"]["non_ig"].get("include_fallen_angels", False))

    if include_fallen:
        for pid in position_ids(G):
            if pid in counted_positions:
                continue
            rating_id = out_target_by_relation(G, pid, "HAS_RATING")
            if rating_id and G.nodes[rating_id].get("below_ig"):
                mv = G.nodes[pid]["market_value"]
                total_non_ig += mv
                counted_positions.add(pid)
                fallen_positions.append(pid)
                extra_paths.append(
                    f"({pid})-[:HAS_RATING]->({rating_id})"
                    f"-[:MEMBER_OF]->(RiskClass:non_investment_grade)"
                )

    agg_value = total_non_ig / nav * Decimal("100")
    agg_status = status_bound(agg_value, None, agg_max, tol)
    agg_util_ratio = agg_value / agg_max if agg_max else None
    agg_util = format_utilization(agg_util_ratio, cfg)
    agg_limit = limit_display(None, agg_max, "%", agg_status, agg_value)

    if len(contributors) == 1:
        base_path = f"(AssetClass:{contributors[0]})-[:CONTRIBUTES_TO]->({agg_id})"
    elif len(contributors) == 2:
        base_path = (
            f"(AssetClass:{contributors[0]})-[:CONTRIBUTES_TO]->({agg_id})"
            f"<-[:CONTRIBUTES_TO]-(AssetClass:{contributors[1]})"
        )
    else:
        base_path = " + ".join(
            f"(AssetClass:{c})-[:CONTRIBUTES_TO]->({agg_id})" for c in contributors
        )

    agg_path = base_path
    if extra_paths:
        agg_path = base_path + " + " + " + ".join(sorted(extra_paths))

    agg_citations = [chunk_citation(G, agg_node.get("chunk")), holdings_citation]
    if include_fallen and fallen_positions:
        fallen_cite = method_citation(cfg, "fallen_angels_in_non_ig") or {
            "source_doc": "firm_B_brief.md",
            "page": 1,
            "chunk_id": "firm_b_rule_fallen_angels",
            "passage_summary": "Aggregate non-IG exposure includes fallen angels",
        }
        agg_citations.append(fallen_cite)

    figures.append(
        make_figure(
            "aggregate_non_ig_exposure",
            "Aggregate",
            agg_name,
            f"{q(agg_value, pct_places)}%",
            agg_limit,
            agg_util,
            agg_status,
            agg_path,
            agg_citations,
            raw_value=agg_value,
        )
    )

    # Largest single corporate issuer
    conc_single_id = "ConcentrationLimit:Largest single corporate issuer"
    single_max = d(G.nodes[conc_single_id]["limit_max"])
    single_chunk = G.nodes[conc_single_id].get("chunk")

    exclude_types = set(cfg["calculation"]["single_issuer"].get("exclude_issuer_types", []))
    exclude_names = set(cfg["calculation"]["single_issuer"].get("exclude_issuers", []))

    issuer_sums = {}
    for pid in position_ids(G):
        issuer_id = out_target_by_relation(G, pid, "ISSUED_BY")
        if not issuer_id:
            continue
        issuer = G.nodes[issuer_id]
        if issuer.get("issuer_type") in exclude_types:
            continue
        if issuer.get("name") in exclude_names:
            continue

        key = issuer.get("name")
        issuer_sums[key] = issuer_sums.get(key, Decimal("0")) + G.nodes[pid]["market_value"]

    if issuer_sums:
        top_issuer, top_mv = sorted(issuer_sums.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    else:
        top_issuer, top_mv = "None", Decimal("0")

    single_value = top_mv / nav * Decimal("100")
    single_status = status_bound(single_value, None, single_max, tol)
    single_util = format_utilization(single_value / single_max if single_max else None, cfg)
    single_limit = limit_display(None, single_max, "%", single_status, single_value)

    single_path = f"(Position)-[:ISSUED_BY]->(Issuer:{top_issuer})"
    single_citations = [chunk_citation(G, single_chunk), holdings_citation]

    figures.append(
        make_figure(
            "largest_single_corporate_issuer",
            "Concentration",
            "Largest single corporate issuer",
            f"{q(single_value, pct_places)}%",
            single_limit,
            single_util,
            single_status,
            single_path,
            single_citations,
            raw_value=single_value,
        )
    )

    # Largest GRE issuer
    conc_gre_id = "ConcentrationLimit:Largest GRE issuer"
    gre_max = d(G.nodes[conc_gre_id]["limit_max"])
    gre_chunk = G.nodes[conc_gre_id].get("chunk")
    gre_level = cfg["calculation"]["gre_concentration"]["level"]

    gre_sums = {}
    gre_children = {}

    for pid in position_ids(G):
        issuer_id = out_target_by_relation(G, pid, "ISSUED_BY")
        if not issuer_id:
            continue
        issuer = G.nodes[issuer_id]
        if issuer.get("issuer_type") != "GRE":
            continue

        if gre_level == "parent":
            parent_id = out_target_by_relation(G, issuer_id, "ROLLS_UP_TO")
            if parent_id:
                key = G.nodes[parent_id].get("name", issuer.get("parent_issuer") or issuer.get("name"))
            else:
                key = issuer.get("parent_issuer") or issuer.get("name")
            gre_children.setdefault(key, set()).add(issuer.get("name"))
        else:
            key = issuer.get("name")
            gre_children.setdefault(key, set()).add(key)

        gre_sums[key] = gre_sums.get(key, Decimal("0")) + G.nodes[pid]["market_value"]

    if gre_sums:
        top_gre, top_gre_mv = sorted(gre_sums.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    else:
        top_gre, top_gre_mv = "None", Decimal("0")

    gre_value = top_gre_mv / nav * Decimal("100")
    gre_status = status_bound(gre_value, None, gre_max, tol)
    gre_util = format_utilization(gre_value / gre_max if gre_max else None, cfg)
    gre_limit = limit_display(None, gre_max, "%", gre_status, gre_value)

    if gre_level == "parent":
        gre_path = " + ".join(
            f"(Issuer:{child})-[:ROLLS_UP_TO]->(Issuer:{top_gre})"
            for child in sorted(gre_children.get(top_gre, []))
        )
    else:
        gre_path = f"(Issuer:{top_gre})"

    gre_citations = [chunk_citation(G, gre_chunk), holdings_citation]
    if gre_level == "parent":
        gre_method = method_citation(cfg, "gre_parent_concentration") or {
            "source_doc": "firm_B_brief.md",
            "page": 1,
            "chunk_id": "firm_b_rule_gre_parent",
            "passage_summary": "GRE concentration is measured at parent issuer",
        }
        gre_citations.append(gre_method)

    figures.append(
        make_figure(
            "largest_gre_issuer",
            "Concentration",
            "Largest GRE issuer",
            f"{q(gre_value, pct_places)}%",
            gre_limit,
            gre_util,
            gre_status,
            gre_path,
            gre_citations,
            raw_value=gre_value,
        )
    )

    # Liquid assets ratio
    liq_name = "Liquid assets ratio"
    liq_id = f"LiquidityMetric:{liq_name}"
    liq_node = G.nodes[liq_id]
    liq_min = d(liq_node["limit_min"])
    liq_chunk = liq_node.get("chunk")

    liq_total = Decimal("0")
    liq_components = []
    for ac_id in incoming_by_relation(G, liq_id, "COMPONENT_OF"):
        ac_name = G.nodes[ac_id]["name"]
        expo, _ = exposure_for_asset_class(G, ac_name)
        liq_total += expo
        liq_components.append(ac_name)

    liq_value = liq_total / nav * Decimal("100")
    liq_status = status_bound(liq_value, liq_min, None, tol)
    liq_util = format_utilization(liq_value / liq_min if liq_min else None, cfg)
    liq_limit = limit_display(liq_min, None, "%", liq_status, liq_value)

    liq_path = " + ".join(
        f"(AssetClass:{c})-[:COMPONENT_OF]->({liq_id})" for c in sorted(liq_components)
    )
    liq_citations = [chunk_citation(G, liq_chunk), holdings_citation]

    figures.append(
        make_figure(
            "liquid_assets_ratio",
            "Liquidity",
            liq_name,
            f"{q(liq_value, pct_places)}%",
            liq_limit,
            liq_util,
            liq_status,
            liq_path,
            liq_citations,
            raw_value=liq_value,
        )
    )

    # Market risk base: total market-value * duration
    total_mv_duration = Decimal("0")
    for pid in position_ids(G):
        node = G.nodes[pid]
        total_mv_duration += node["market_value"] * node["modified_duration"]

    # Portfolio modified duration
    dur_name = "Portfolio modified duration"
    dur_rm_id = f"RiskMetric:{dur_name}"
    dur_node = G.nodes[dur_rm_id]
    dur_min = d(dur_node.get("limit_min"))
    dur_max = d(dur_node.get("limit_max"))
    dur_chunk = dur_node.get("chunk")

    duration_value = total_mv_duration / nav
    duration_status = status_bound(duration_value, dur_min, dur_max, tol)
    duration_limit = limit_display(dur_min, dur_max, "yrs", duration_status, duration_value)
    duration_value_str = f"{q(duration_value, dur_places)} yrs"

    duration_path = (
        "(Position)-[:PART_OF]->(Portfolio:Meridian Fixed Income Fund)"
        "-[:MEASURED_BY]->(RiskMetric:Portfolio modified duration)"
        "-[:HAS_LIMIT]->(Limit:risk:Portfolio modified duration)"
    )
    duration_citations = [chunk_citation(G, dur_chunk), holdings_citation]

    figures.append(
        make_figure(
            "portfolio_modified_duration",
            "Market risk",
            dur_name,
            duration_value_str,
            duration_limit,
            "n/a",
            duration_status,
            duration_path,
            duration_citations,
            raw_value=duration_value,
        )
    )

    # Portfolio DV01
    dv01_name = "Portfolio DV01"
    dv01_rm_id = f"RiskMetric:{dv01_name}"
    dv01_node = G.nodes[dv01_rm_id]
    dv01_max = d(dv01_node.get("limit_max"))
    dv01_chunk = dv01_node.get("chunk")

    dv01_value = total_mv_duration / Decimal("10000")
    dv01_status = status_bound(dv01_value, None, dv01_max, tol)
    dv01_util = format_utilization(dv01_value / dv01_max if dv01_max else None, cfg)
    dv01_limit = limit_display(None, dv01_max, "SGD/bp", dv01_status, dv01_value)
    dv01_value_str = f"SGD {int(q(dv01_value, dv01_places)):,} / bp"

    dv01_path = (
        "(Position)-[:PART_OF]->(Portfolio:Meridian Fixed Income Fund)"
        "-[:MEASURED_BY]->(RiskMetric:Portfolio DV01)"
        "-[:HAS_LIMIT]->(Limit:risk:Portfolio DV01)"
    )
    dv01_citations = [chunk_citation(G, dv01_chunk), holdings_citation]

    figures.append(
        make_figure(
            "portfolio_dv01",
            "Market risk",
            dv01_name,
            dv01_value_str,
            dv01_limit,
            dv01_util,
            dv01_status,
            dv01_path,
            dv01_citations,
            raw_value=dv01_value,
        )
    )

    return figures