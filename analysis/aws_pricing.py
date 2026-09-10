#!/usr/bin/env python3
"""Pull on-demand prices for the study's candidate resources into a dated snapshot.

Cost figures in this repo are claims like any other, so they get the same treatment:
a script that regenerates them from the source, an immutable dated snapshot, and no
hand-typed numbers in any README. See CLAUDE.md, "Provenance or it didn't happen."

The Pricing API only serves from a few regions and prices are keyed by a human
location string, not a region code - both facts are hard-coded below rather than
discovered, because they change on AWS's schedule and a silent fallback would
produce a wrong table rather than an error.

Usage:
    python3 analysis/aws_pricing.py                  # write a snapshot + print table
    python3 analysis/aws_pricing.py --dry-run        # print only

Credentials come from the environment. The repo's own IAM user lives in .env:
    set -a; . ./.env; set +a
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

# The study's region. Pricing API keys on this string, not on "ap-southeast-1".
REGION = "ap-southeast-1"
LOCATION = "Asia Pacific (Singapore)"
# The Pricing API is not available in every region; us-east-1 always serves it.
PRICING_ENDPOINT_REGION = "us-east-1"

REPO = pathlib.Path(__file__).resolve().parent.parent

# Instance arms. The `d` variants carry NVMe instance store; their storeless
# siblings are here so the premium is computed rather than asserted.
INSTANCE_TYPES = [
    "t4g.small",
    "m7g.large", "m7gd.large",
    "c7g.large", "c7gd.large",
    "r7g.large", "r7gd.large",
]


def aws(service: str, *args: str) -> Any:
    """Run an AWS CLI command and parse its JSON. Fails loudly."""
    cmd = ["aws", service, *args, "--output", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])} failed:\n{proc.stderr.strip()}")
    return json.loads(proc.stdout or "null")


def get_products(service_code: str, filters: dict[str, str], limit: int = 100) -> list[dict]:
    """Fetch every price-list document matching the filters, already parsed.

    Paginates. A service code like AmazonECS returns far more than one page, and
    silently taking only the first is how a cost table ends up missing the exact
    line item it was built to find.
    """
    flags = [f"Type=TERM_MATCH,Field={k},Value={v}" for k, v in filters.items()]
    docs: list[dict] = []
    token: str | None = None
    while True:
        page_args = ["--next-token", token] if token else []
        raw = aws(
            "pricing", "get-products",
            "--region", PRICING_ENDPOINT_REGION,
            "--service-code", service_code,
            "--max-results", str(limit),
            "--filters", *flags,
            *page_args,
        ) or {}
        docs.extend(json.loads(d) for d in raw.get("PriceList", []))
        token = raw.get("NextToken")
        if not token:
            return docs


def check_location(doc: dict) -> str:
    """Return the product's location, refusing anything outside the study's region.

    The API filter should already guarantee this. Checking anyway is the point: a
    silently mis-filtered price is indistinguishable from a correct one once it is
    in a table, and a cost table that cannot prove its own region is not provenance.
    """
    loc = doc["product"]["attributes"].get("location")
    if loc != LOCATION:
        raise RuntimeError(
            f"price document for location {loc!r}, expected {LOCATION!r} - "
            f"sku {doc['product'].get('sku')}"
        )
    return loc


def on_demand_dimensions(doc: dict) -> list[tuple[float, str, str]]:
    """Extract (price, unit, description) for every on-demand dimension of a product.

    A product can carry several dimensions (e.g. storage and throughput priced
    separately), so this returns all of them rather than guessing which one matters.
    """
    out = []
    for term in doc.get("terms", {}).get("OnDemand", {}).values():
        for dim in term.get("priceDimensions", {}).values():
            usd = dim.get("pricePerUnit", {}).get("USD")
            if usd is None:
                continue
            price = float(usd)
            out.append((price, dim.get("unit", ""), dim.get("description", "")))
    return out


def cheapest(doc: dict) -> tuple[float, str, str] | None:
    """The single non-zero dimension of a product, or None if it is all free tier."""
    dims = [d for d in on_demand_dimensions(doc) if d[0] > 0]
    return min(dims, key=lambda d: d[0]) if dims else None


def price_ec2_instances() -> dict[str, dict]:
    """On-demand Linux hourly rates, plus the instance-store spec from the EC2 API."""
    out: dict[str, dict] = {}
    for itype in INSTANCE_TYPES:
        docs = get_products("AmazonEC2", {
            "instanceType": itype,
            "location": LOCATION,
            "operatingSystem": "Linux",
            "tenancy": "Shared",
            "preInstalledSw": "NA",
            "capacitystatus": "Used",
            "licenseModel": "No License required",
        })
        if not docs:
            out[itype] = {"error": "no price returned"}
            continue
        # Several SKUs can match; the on-demand hourly rate is identical across them.
        for doc in docs:
            check_location(doc)
        dim = cheapest(docs[0])
        attrs = docs[0]["product"]["attributes"]
        out[itype] = {
            "usd_per_hour": dim[0] if dim else None,
            "location": attrs.get("location"),
            "usagetype": attrs.get("usagetype"),
            "vcpu": attrs.get("vcpu"),
            "memory": attrs.get("memory"),
            "storage": attrs.get("storage"),
            "network": attrs.get("networkPerformance"),
        }
    return out


def price_storage() -> dict[str, list[dict]]:
    """Storage tiers. These have multiple priced dimensions, so all are kept."""
    queries = {
        # EFS: standard storage, and the elastic-throughput read/write charges.
        "efs": ("AmazonEFS", {"location": LOCATION}),
        # FSx covers OpenZFS, Lustre and ONTAP under one service code; the
        # fileSystemType attribute separates them.
        "fsx": ("AmazonFSx", {"location": LOCATION}),
    }
    out: dict[str, list[dict]] = {}
    for name, (code, filters) in queries.items():
        rows = []
        for doc in get_products(code, filters, limit=100):
            check_location(doc)
            dim = cheapest(doc)
            if not dim:
                continue
            a = doc["product"]["attributes"]
            rows.append({
                "usd": dim[0],
                "unit": dim[1],
                "description": dim[2],
                "location": a.get("location"),
                "usagetype": a.get("usagetype"),
                "family": doc["product"].get("productFamily"),
                "type": a.get("fileSystemType") or a.get("storageClass") or a.get("usagetype"),
                "deployment": a.get("deploymentOption"),
            })
        rows.sort(key=lambda r: (str(r["type"]), r["usd"]))
        out[name] = rows
    return out


def price_fargate() -> list[dict]:
    """Fargate vCPU-hour and GB-hour rates.

    The ECS service code also carries ECS Managed Instances and ECS Anywhere rates,
    which are a different product entirely - hence the usagetype filter rather than
    taking whatever the service code returns.
    """
    rows = []
    for doc in get_products("AmazonECS", {"location": LOCATION}):
        check_location(doc)
        a = doc["product"]["attributes"]
        usage = a.get("usagetype", "")
        if "Fargate" not in usage:
            continue
        for price, unit, desc in on_demand_dimensions(doc):
            if price <= 0:
                continue
            rows.append({
                "usd": price, "unit": unit, "description": desc,
                "usagetype": usage, "cputype": a.get("cputype"),
                "location": a.get("location"),
            })
    rows.sort(key=lambda r: (r["usagetype"], r["usd"]))
    return rows


def price_vpc_endpoint() -> list[dict]:
    """Interface endpoints are per-hour per-AZ and are E1's dominant line item."""
    rows = []
    for doc in get_products("AmazonVPC", {"location": LOCATION, "productFamily": "VpcEndpoint"}):
        check_location(doc)
        a = doc["product"]["attributes"]
        usage = a.get("usagetype", "")
        for price, unit, desc in on_demand_dimensions(doc):
            # Keep only the per-hour ENI charge. The same family also prices data
            # processing per GB, which is a usage charge, not a standing cost.
            if price > 0 and unit.lower().startswith("hr"):
                rows.append({
                    "usd": price, "unit": unit, "description": desc,
                    "usagetype": usage, "endpoint_type": a.get("endpointType"),
                    "location": a.get("location"),
                })
    rows.sort(key=lambda r: r["usd"])
    return rows


def instance_store_specs() -> dict[str, dict]:
    """Instance-store geometry straight from the EC2 API, not from the docs."""
    data = aws(
        "ec2", "describe-instance-types",
        "--region", REGION,
        "--instance-types", *INSTANCE_TYPES,
    )
    out = {}
    for it in data.get("InstanceTypes", []):
        si = it.get("InstanceStorageInfo") or {}
        out[it["InstanceType"]] = {
            "total_gb": si.get("TotalSizeInGB"),
            "nvme": si.get("NvmeSupport"),
            "disks": [
                {"count": d.get("Count"), "size_gb": d.get("SizeInGB"), "type": d.get("Type")}
                for d in si.get("Disks", [])
            ],
            "encrypted_at_rest": si.get("EncryptionSupport"),
        }
    return out


def render_instance_table(instances: dict, stores: dict) -> str:
    lines = [
        "| Instance | vCPU | Memory | Instance store | $/hr | Premium over storeless |",
        "|---|--:|--:|---|--:|--:|",
    ]
    for itype in INSTANCE_TYPES:
        p = instances.get(itype, {})
        rate = p.get("usd_per_hour")
        store = stores.get(itype, {})
        disks = store.get("disks") or []
        store_txt = (
            f"{disks[0]['count']} x {disks[0]['size_gb']} GB {disks[0]['type'].upper()}"
            if disks else "—"
        )
        premium = "—"
        if itype.split(".")[0].endswith("d"):
            base = itype.replace("gd.", "g.")
            base_rate = instances.get(base, {}).get("usd_per_hour")
            if base_rate and rate:
                premium = f"+{(rate / base_rate - 1) * 100:.1f}%"
        lines.append(
            f"| `{itype}` | {p.get('vcpu', '?')} | {p.get('memory', '?')} | {store_txt} | "
            f"{('$%.4f' % rate) if rate else '?'} | {premium} |"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print without writing a snapshot")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    snapshot: dict[str, Any] = {
        "snapshot_utc": now.isoformat(),
        "region": REGION,
        "location": LOCATION,
        "note": "On-demand list prices. No savings plans, no reserved capacity, no free tier.",
    }

    print(f"Pricing snapshot {now:%Y-%m-%d} for {LOCATION}\n", file=sys.stderr)
    snapshot["ec2_instances"] = price_ec2_instances()
    snapshot["instance_store"] = instance_store_specs()
    snapshot["vpc_endpoint"] = price_vpc_endpoint()
    snapshot["fargate"] = price_fargate()
    snapshot["storage"] = price_storage()

    table = render_instance_table(snapshot["ec2_instances"], snapshot["instance_store"])
    print(table)

    if args.dry_run:
        return 0

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                         capture_output=True, text=True).stdout.strip() or "nogit"
    run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{sha}"
    snapshot["run_id"] = run_id
    out_dir = REPO / "results" / "pricing" / run_id
    if out_dir.exists():
        print(f"\nrefusing to overwrite existing snapshot {out_dir}", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True)
    (out_dir / "pricing.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    (out_dir / "instances.md").write_text(table + "\n")
    print(f"\nwrote {out_dir.relative_to(REPO)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
