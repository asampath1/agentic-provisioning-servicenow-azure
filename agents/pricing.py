"""Monthly cost estimates from the Azure retail price list (policy: docs/request-policy.md, "Cost estimate").

Default: the dated snapshot in synthetic-data/data/prices.json (repeatable). ``Prices.live()`` asks the public Azure
Retail Prices API (no login) for the current Central India prices and falls back to the snapshot per item.
"""
from __future__ import annotations

import json
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[1] / "synthetic-data/data/prices.json"
API = "https://prices.azure.com/api/retail/prices"
HOURS = 730
STORAGE_GB = 100


class Prices:
    def __init__(self, data: dict, source: str):
        self.d, self.source = data, source

    @classmethod
    def snapshot(cls) -> "Prices":
        d = json.loads(SNAPSHOT.read_text())
        return cls(d, d.get("_source", "snapshot"))

    @classmethod
    def live(cls, timeout: int = 20) -> "Prices":
        import requests

        d = json.loads(SNAPSHOT.read_text())
        region = d["region"]
        got = 0
        for size in list(d["vm_hourly"]):
            flt = (f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}' and armSkuName eq '{size}' "
                   f"and priceType eq 'Consumption'")
            try:
                items = requests.get(API, params={"$filter": flt}, timeout=timeout).json().get("Items", [])
            except (requests.RequestException, ValueError):
                continue
            linux = [i["retailPrice"] for i in items if i["productName"].startswith("Virtual Machines")
                     and "Windows" not in i["productName"] and "Spot" not in i["skuName"]
                     and "Low Priority" not in i["skuName"]]
            if linux:
                d["vm_hourly"][size] = min(linux)
                got += 1
        return cls(d, f"Azure Retail Prices API, live ({got} of {len(d['vm_hourly'])} VM prices; rest from snapshot)")

    def vm_monthly(self, size: str) -> float | None:
        hourly = self.d["vm_hourly"].get(size)
        if hourly is None:
            return None
        return round(hourly * HOURS + sum(self.d["os_disk_monthly"].values()), 2)

    def storage_monthly(self, sku: str) -> float | None:
        per_gb = self.d["blob_hot_gb_month"].get(sku)
        return None if per_gb is None else round(per_gb * STORAGE_GB, 2)
