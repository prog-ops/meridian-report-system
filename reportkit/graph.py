import csv
import hashlib
import json
from decimal import Decimal

import networkx as nx
import yaml

from .ratings import is_below_ig, IG_RATINGS


def _ser(v):
    """
    Serialize graph attribute values for deterministic hashing.
    """
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (set, tuple)):
        return list(v)
    return v


def canonical_graph_hash(G: nx.MultiDiGraph) -> str:
    """
    Produce a deterministic hash of the whole graph.
    This is used in the audit log to prove which exact graph was used.
    """
    nodes = []
    for n in sorted(G.nodes()):
        d = G.nodes[n]
        nodes.append({"id": n, **{k: _ser(v) for k, v in d.items()}})

    edges = []
    edge_list = sorted(
        G.edges(keys=True, data=True),
        key=lambda x: (str(x[0]), str(x[1]), x[3].get("relation", ""), x[2])
    )

    for u, v, k, d in edge_list:
        edges.append(
            {
                "u": u,
                "v": v,
                "key": k,
                **{kk: _ser(vv) for kk, vv in d.items()},
            }
        )

    payload = json.dumps(
        {"nodes": nodes, "edges": edges},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class GraphBuilder:
    """
    Builds one knowledge graph from:
    - guideline rules / chunks / limits
    - holdings snapshot

    Every Position, Issuer, Rating, AssetClass, Limit, RiskMetric, etc.
    becomes a graph node with explicit relationships.
    """

    def __init__(
        self,
        rules_path: str,
        holdings_path: str,
        audit,
        asset_class_mapping=None,
    ):
        self.rules_path = rules_path
        self.holdings_path = holdings_path
        self.audit = audit
        self.asset_class_mapping = asset_class_mapping or {}
        self.G = nx.MultiDiGraph()

        with open(rules_path, "r", encoding="utf-8") as f:
            self.rules = yaml.safe_load(f)

    def build(self) -> nx.MultiDiGraph:
        self._add_chunks()
        self._add_portfolio_root()
        self._add_asset_classes()
        self._add_aggregates()
        self._add_concentration_limits()
        self._add_liquidity()
        self._add_risk_metrics()
        self._add_holdings()

        graph_hash = canonical_graph_hash(self.G)

        self.audit.record(
            "GRAPH_CONSTRUCTED",
            "graph_builder",
            {
                "rules_path": self.rules_path,
                "holdings_path": self.holdings_path,
                "node_count": self.G.number_of_nodes(),
                "edge_count": self.G.number_of_edges(),
                "graph_hash": graph_hash,
            },
        )

        return self.G

    def _add_node(self, node_id: str, node_type: str, **attrs):
        if node_id not in self.G:
            self.G.add_node(node_id, type=node_type, **attrs)
        else:
            self.G.nodes[node_id].update(attrs)
        return node_id

    def _add_edge(self, src: str, dst: str, relation: str, **attrs):
        attrs["relation"] = relation
        self.G.add_edge(src, dst, **attrs)

    def _add_chunks(self):
        docs = sorted({c["source_doc"] for c in self.rules.get("chunks", [])})

        for doc in docs:
            self._add_node(f"Document:{doc}", "Document", name=doc)

        for c in self.rules.get("chunks", []):
            chunk_id = f"Chunk:{c['chunk_id']}"

            self._add_node(
                chunk_id,
                "Chunk",
                chunk_id=c["chunk_id"],
                source_doc=c["source_doc"],
                page=c.get("page"),
                passage_summary=c.get("passage_summary", ""),
                extraction_confidence=1.0,
            )

            self._add_edge(
                f"Document:{c['source_doc']}",
                chunk_id,
                "HAS_CHUNK",
            )

    def _add_portfolio_root(self):
        self._add_node(
            "Portfolio:Meridian Fixed Income Fund",
            "Portfolio",
            name="Meridian Fixed Income Fund",
        )

    def _add_asset_classes(self):
        for idx, ac in enumerate(self.rules.get("asset_classes", []), start=1):
            name = ac["name"]
            chunk = ac["chunk"]

            minv = None if ac.get("limit_min") is None else Decimal(str(ac["limit_min"]))
            maxv = None if ac.get("limit_max") is None else Decimal(str(ac["limit_max"]))

            ac_id = f"AssetClass:{name}"
            limit_id = f"Limit:allocation:{name}"

            self._add_node(
                ac_id,
                "AssetClass",
                name=name,
                limit_min=minv,
                limit_max=maxv,
                chunk=chunk,
                order=idx,
            )

            self._add_node(
                limit_id,
                "Limit",
                scope="allocation",
                unit="%",
                limit_min=minv,
                limit_max=maxv,
            )

            self._add_edge(ac_id, limit_id, "HAS_LIMIT")
            self._add_edge(ac_id, f"Chunk:{chunk}", "HAS_PROVENANCE")
            self._add_edge(limit_id, f"Chunk:{chunk}", "HAS_PROVENANCE")

    def _add_aggregates(self):
        for agg in self.rules.get("aggregates", []):
            name = agg["name"]
            chunk = agg["chunk"]
            maxv = Decimal(str(agg["limit_max"]))

            agg_id = f"Aggregate:{name}"
            limit_id = f"Limit:aggregate:{name}"

            self._add_node(
                agg_id,
                "AggregateMetric",
                name=name,
                limit_max=maxv,
                chunk=chunk,
            )

            self._add_node(
                limit_id,
                "Limit",
                scope="aggregate",
                unit="%",
                limit_max=maxv,
            )

            self._add_edge(agg_id, limit_id, "HAS_LIMIT")
            self._add_edge(agg_id, f"Chunk:{chunk}", "HAS_PROVENANCE")
            self._add_edge(limit_id, f"Chunk:{chunk}", "HAS_PROVENANCE")

            for contributor in agg.get("contributors", []):
                self._add_edge(
                    f"AssetClass:{contributor}",
                    agg_id,
                    "CONTRIBUTES_TO",
                )

    def _add_concentration_limits(self):
        for cl in self.rules.get("concentration_limits", []):
            name = cl["name"]
            chunk = cl["chunk"]
            maxv = Decimal(str(cl["limit_max"]))

            conc_id = f"ConcentrationLimit:{name}"
            limit_id = f"Limit:concentration:{name}"

            self._add_node(
                conc_id,
                "ConcentrationLimit",
                name=name,
                limit_max=maxv,
                chunk=chunk,
            )

            self._add_node(
                limit_id,
                "Limit",
                scope="concentration",
                unit="%",
                limit_max=maxv,
            )

            self._add_edge(conc_id, limit_id, "HAS_LIMIT")
            self._add_edge(conc_id, f"Chunk:{chunk}", "HAS_PROVENANCE")
            self._add_edge(limit_id, f"Chunk:{chunk}", "HAS_PROVENANCE")

    def _add_liquidity(self):
        liq = self.rules.get("liquidity")
        if not liq:
            return

        name = liq["name"]
        chunk = liq["chunk"]
        minv = Decimal(str(liq["limit_min"]))

        liq_id = f"LiquidityMetric:{name}"
        limit_id = f"Limit:liquidity:{name}"

        self._add_node(
            liq_id,
            "LiquidityMetric",
            name=name,
            limit_min=minv,
            chunk=chunk,
        )

        self._add_node(
            limit_id,
            "Limit",
            scope="liquidity",
            unit="%",
            limit_min=minv,
        )

        self._add_edge(liq_id, limit_id, "HAS_LIMIT")
        self._add_edge(liq_id, f"Chunk:{chunk}", "HAS_PROVENANCE")
        self._add_edge(limit_id, f"Chunk:{chunk}", "HAS_PROVENANCE")

        for component in liq.get("components", []):
            self._add_edge(
                f"AssetClass:{component}",
                liq_id,
                "COMPONENT_OF",
            )

    def _add_risk_metrics(self):
        portfolio_id = "Portfolio:Meridian Fixed Income Fund"

        for rm in self.rules.get("risk_metrics", []):
            name = rm["name"]
            chunk = rm["chunk"]

            minv = None if rm.get("limit_min") is None else Decimal(str(rm["limit_min"]))
            maxv = None if rm.get("limit_max") is None else Decimal(str(rm["limit_max"]))

            rm_id = f"RiskMetric:{name}"
            limit_id = f"Limit:risk:{name}"
            action_id = f"BreachAction:{name}"
            owner_id = f"Owner:{rm['owner']}"

            self._add_node(
                rm_id,
                "RiskMetric",
                name=name,
                unit=rm.get("unit"),
                limit_min=minv,
                limit_max=maxv,
                chunk=chunk,
            )

            self._add_node(
                limit_id,
                "Limit",
                scope="risk",
                unit=rm.get("unit"),
                limit_min=minv,
                limit_max=maxv,
            )

            self._add_node(
                action_id,
                "BreachAction",
                name=name,
                action=rm.get("breach_action"),
            )

            self._add_node(
                owner_id,
                "Owner",
                name=rm["owner"],
            )

            self._add_edge(rm_id, limit_id, "HAS_LIMIT")
            self._add_edge(rm_id, action_id, "HAS_BREACH_ACTION")
            self._add_edge(action_id, owner_id, "OWNED_BY")

            self._add_edge(rm_id, f"Chunk:{chunk}", "HAS_PROVENANCE")
            self._add_edge(limit_id, f"Chunk:{chunk}", "HAS_PROVENANCE")
            self._add_edge(action_id, f"Chunk:{chunk}", "HAS_PROVENANCE")

            self._add_edge(portfolio_id, rm_id, "MEASURED_BY")

    def _add_holdings(self):
        """
        Ingest sample_holdings.csv into the graph.

        Expected CSV columns:
        - instrument_id
        - instrument_name
        - asset_class
        - issuer_name
        - issuer_type
        - parent_issuer
        - credit_rating
        - downgraded_from
        - market_value_sgd
        - modified_duration
        """
        doc_id = f"Document:{self.holdings_path}"
        chunk_id = "Chunk:holdings_snapshot"

        self._add_node(doc_id, "Document", name=self.holdings_path)

        self._add_node(
            chunk_id,
            "Chunk",
            chunk_id="holdings_snapshot",
            source_doc=self.holdings_path,
            page=None,
            passage_summary="Period-end holdings snapshot",
            extraction_confidence=1.0,
        )

        self._add_edge(doc_id, chunk_id, "HAS_CHUNK")

        self._add_node(
            "RiskClass:non_investment_grade",
            "RiskClass",
            name="non_investment_grade",
            definition="Current credit rating below investment grade",
        )

        self._add_edge(
            "RiskClass:non_investment_grade",
            "Chunk:chunk_sec3_2_fallen_angel",
            "HAS_PROVENANCE",
        )

        mapping = self.asset_class_mapping or {}

        with open(self.holdings_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row_num, row in enumerate(reader, start=2):
                instrument_id = row["instrument_id"].strip()
                instrument_name = row["instrument_name"].strip()

                asset_class_raw = row["asset_class"].strip()
                asset_class = mapping.get(asset_class_raw, asset_class_raw)

                issuer_name = row["issuer_name"].strip()
                issuer_type = row.get("issuer_type", "").strip()
                parent_issuer = row.get("parent_issuer", "").strip()
                credit_rating = row.get("credit_rating", "").strip()
                downgraded_from = row.get("downgraded_from", "").strip()

                market_value = Decimal(row["market_value_sgd"].strip())
                modified_duration = Decimal(
                    (row.get("modified_duration") or "0").strip() or "0"
                )

                fallen_angel = bool(
                    credit_rating
                    and downgraded_from
                    and is_below_ig(credit_rating)
                    and downgraded_from in IG_RATINGS
                )

                pos_id = f"Position:{instrument_id}"

                self._add_node(
                    pos_id,
                    "Position",
                    instrument_id=instrument_id,
                    instrument_name=instrument_name,
                    asset_class=asset_class,
                    issuer=issuer_name,
                    issuer_type=issuer_type,
                    parent_issuer=parent_issuer,
                    credit_rating=credit_rating,
                    downgraded_from=downgraded_from,
                    market_value=market_value,
                    modified_duration=modified_duration,
                    fallen_angel=fallen_angel,
                    source_doc=self.holdings_path,
                    row=row_num,
                    extraction_confidence=1.0,
                )

                self._add_edge(
                    pos_id,
                    chunk_id,
                    "HAS_PROVENANCE",
                    row=row_num,
                    extraction_confidence=1.0,
                )

                self._add_edge(
                    pos_id,
                    "Portfolio:Meridian Fixed Income Fund",
                    "PART_OF",
                )

                ac_id = f"AssetClass:{asset_class}"

                if ac_id not in self.G:
                    self._add_node(
                        ac_id,
                        "AssetClass",
                        name=asset_class,
                        unresolved=True,
                    )

                    self.audit.record(
                        "UNRESOLVED_ENTITY",
                        "graph_builder",
                        {
                            "entity": ac_id,
                            "reason": "asset class not present in guideline graph",
                            "row": row_num,
                        },
                    )

                self._add_edge(
                    pos_id,
                    ac_id,
                    "BELONGS_TO",
                    row=row_num,
                    extraction_confidence=1.0,
                )

                issuer_id = f"Issuer:{issuer_name}"

                if issuer_id not in self.G:
                    self._add_node(
                        issuer_id,
                        "Issuer",
                        name=issuer_name,
                        issuer_type=issuer_type,
                        parent_issuer=parent_issuer,
                    )
                else:
                    self.G.nodes[issuer_id].update(
                        issuer_type=issuer_type,
                        parent_issuer=parent_issuer,
                    )

                self._add_edge(
                    pos_id,
                    issuer_id,
                    "ISSUED_BY",
                    row=row_num,
                    extraction_confidence=1.0,
                )

                if parent_issuer and parent_issuer != issuer_name:
                    parent_id = f"Issuer:{parent_issuer}"

                    if parent_id not in self.G:
                        self._add_node(
                            parent_id,
                            "Issuer",
                            name=parent_issuer,
                            issuer_type="ParentGroup",
                        )

                    self._add_edge(
                        issuer_id,
                        parent_id,
                        "ROLLS_UP_TO",
                    )

                if credit_rating:
                    rating_id = f"Rating:{credit_rating}"
                    below_ig = is_below_ig(credit_rating)

                    if rating_id not in self.G:
                        self._add_node(
                            rating_id,
                            "Rating",
                            rating=credit_rating,
                            below_ig=below_ig,
                        )

                    self._add_edge(pos_id, rating_id, "HAS_RATING")

                    if below_ig:
                        self._add_edge(
                            rating_id,
                            "RiskClass:non_investment_grade",
                            "MEMBER_OF",
                        )

                if downgraded_from:
                    dg_id = f"Rating:{downgraded_from}"

                    if dg_id not in self.G:
                        self._add_node(
                            dg_id,
                            "Rating",
                            rating=downgraded_from,
                            below_ig=is_below_ig(downgraded_from),
                        )

                    self._add_edge(pos_id, dg_id, "DOWNGRADED_FROM")