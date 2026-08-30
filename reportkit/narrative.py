import re


def build_narrative(figures, cfg):
    """
    Deterministic narrative layer.

    This deliberately avoids LLM-generated numbers.
    If an LLM is later plugged in, it must only rewrite narrative text
    and must still pass the firewall check.
    """
    lines = [
        "Narrative generated deterministically. No figures were produced by an LLM."
    ]

    breaches = [f for f in figures if f["status"] == "BREACH"]
    at_limit = [f for f in figures if f["status"] == "AT LIMIT"]

    if breaches:
        lines.append("Breaches requiring attention:")
        for f in breaches:
            lines.append(f"- {f['metric']} = {f['value']} against {f['limit']}")
    else:
        lines.append("No breaches detected.")

    if at_limit:
        lines.append("Positions at limit:")
        for f in at_limit:
            lines.append(f"- {f['metric']} = {f['value']} against {f['limit']}")

    return "\n".join(lines)


def _normalize_number(s: str) -> str:
    return s.replace(",", "").strip()


def _extract_numbers(text: str):
    return {_normalize_number(x) for x in re.findall(r"\d+(?:[.,]\d+)*", text)}


def firewall_check(narrative: str, figures):
    allowed = set()

    for f in figures:
        for field in ["value", "limit", "utilization", "raw_value"]:
            val = f.get(field)
            if val is None:
                continue
            allowed.update(_extract_numbers(str(val)))

    narrative_numbers = _extract_numbers(narrative)
    invalid = sorted(narrative_numbers - allowed)

    return {
        "passed": len(invalid) == 0,
        "narrative_numbers": sorted(narrative_numbers),
        "invalid_numbers": invalid,
    }