from datetime import datetime

from openpyxl import Workbook


def write_report(figures, path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"

    ws.append(
        [
            "Section",
            "Metric",
            "Value",
            "Limit",
            "Utilization",
            "Status",
            "Source (graph path → doc/page)",
        ]
    )

    for f in figures:
        ws.append(
            [
                f["section"],
                f["metric"],
                f["value"],
                f["limit"],
                f["utilization"],
                f["status"],
                f["source"],
            ]
        )

    # Fixed metadata to keep generated file more deterministic.
    wb.properties.created = datetime(2024, 1, 1)
    wb.properties.modified = datetime(2024, 1, 1)

    wb.save(path)