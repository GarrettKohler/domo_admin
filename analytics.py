"""Analytical functions that derive lineage, domain, and staleness insights."""

import re
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain classification rules (order matters — first match wins)
# ---------------------------------------------------------------------------
DOMAIN_RULES = [
    # (pattern, domain_label, workspace)
    #
    # ORDER MATTERS — first match wins. Rules are sequenced so that:
    # 1. Cleanup candidates are caught first (test/temp/dev)
    # 2. Governance and data quality monitoring are caught before domain-specific
    #    keywords like "transactions" pull monitoring datasets into the wrong bucket
    # 3. Narrow overrides (clawback→Revenue, TDLinx→Sites, DXP→Sites) run before
    #    the broader domain they'd otherwise fall into (POP, Transactions, etc.)
    # 4. Managed Services catches remaining retailer names AFTER functional domains
    #    have already claimed retailer-specific transactions, POP, etc.

    # --- 1. Test / Temp / Archive (cleanup candidates) ---
    (r"(?i)\btest\b|\btemp\b|\bdev\b|sandbox|\bcopy\b|\bold\b|\bdnu\b|deprecated|archive|\bflag.?for.?deletion", "Test / Temp / Archive", "Cleanup Candidate"),

    # --- 2. Monitoring & Governance ---
    (r"(?i)domostats|domo.*(system|admin|governance)|observability|\bgovernan", "Monitoring & Governance", "Data Engineering"),
    (r"(?i)\bpmar\b|\bdata.?quality\b|\bdata.?check\b|check.?ratio", "Monitoring & Governance", "Data Engineering"),

    # --- 3. Traffic Instructions (standalone workspace) ---
    (r"(?i)traffic.?instruction", "Traffic Instructions", "Ad Operations"),

    # --- 4. RPA (standalone workspace, before managed services) ---
    (r"(?i)\brpa\b|rotation|play.?assignment", "RPA", "Ad Operations"),

    # --- 5. Early overrides — route to correct workspace before broader rules claim them ---
    # Clawback → Revenue & Monetization (not Proof of Play)
    (r"(?i)\bclawback", "Revenue & Monetization", "Finance"),
    # Revenue Share, rent payments, retailer campaign revenue → Revenue
    (r"(?i)\brevenue.?share|rev.?share|rent.?payment|retailer.?campaign|contribution.?ratio", "Revenue & Monetization", "Finance"),
    # DXP / DXPromote → Sites & Locations (not Proof of Play)
    (r"(?i)\bdxp\b|dxpromote|dover.*dxp", "Sites & Locations", "Network Operations"),
    # TDLinx → Sites & Locations (not Transactions)
    (r"(?i)\btdlinx", "Sites & Locations", "Data Engineering"),
    # Comscore → Impressions (partner data)
    (r"(?i)\bcomscore", "Impressions", "Data & Analytics"),

    # --- 6. Proof of Play ---
    (r"(?i)\bics\b|applause|gilbarco.*ics|\bterminal\b|pop.*(by|data|stat|report|daily|hourly)|proof.?of.?play", "Proof of Play", "Network Operations"),

    # --- 7. Impressions (NVI / CVI) ---
    (r"(?i)\bnvi\b|\bcvi\b|validated.?impression|impression.*hour|impression.*multiplier|hourly.*impression", "Impressions", "Data & Analytics"),

    # --- 8. Transactions ---
    (r"(?i)\btransaction|fuel.?sales", "Transactions", "Data & Analytics"),

    # --- 9. Salesforce / CRM ---
    (r"(?i)\bsalesforce|sf.*(opp|account|contact)|opp.?io.?rev", "Salesforce / CRM", "Sales"),

    # --- 10. Revenue & Monetization (remaining revenue datasets) ---
    (r"(?i)\brevenue|rev.?pjct|pluto|cpm.?floor|monetiz|invoice", "Revenue & Monetization", "Finance"),

    # --- 11. Sites & Locations ---
    (r"(?i)\bmaster.?station|site.*list|gbase|mongo.*site|sites.*base|site.*status|site.*config", "Sites & Locations", "Data Engineering"),
    (r"(?i)market.?plan|dma.*gtvid|\bcstore|c-store|convenience", "Sites & Locations", "Data Engineering"),
    (r"(?i)\bnoc\b|full.?status.?report|enterprise.*iotv|iotv.*status|site.?offline|jupiter|dispenser", "Sites & Locations", "Network Operations"),

    # --- 12. Programmatic Operations (diagnostics, avails, auction, bid, inventory) ---
    (r"(?i)\bvistar.*(diagnos|avail|fill)|auction|bid.*cpm|sell.?through", "Programmatic Operations", "Programmatic"),
    (r"(?i)place.?exchange.*(inventory|pmp|pacing)|magnite.*(site|list)|hivestack.*(site|screen)|broadsign.*(site|list)", "Programmatic Operations", "Programmatic"),

    # --- 13. Programmatic (remaining — revenue, SSP, exchange → revenue subsection) ---
    (r"(?i)\bvistar\b|programmatic|place.?exchange|px.?revenue|magnite|hivestack|broadsign|ssp\b|spot.*lease|ad.*lease|venue.*avail", "Programmatic", "Programmatic"),

    # --- 14. Campaigns & Delivery ---
    (r"(?i)\bad.?ops|campaign.?delivery|campaign.?impact|campaign.?track|io.?list|io.?number|campaign", "Campaigns & Delivery", "Ad Operations"),

    # --- 15. Site Analytics / ML ---
    (r"(?i)\bsite.*metric|site.*scor|platinum|lookalike|classification|hackathon", "Site Analytics", "Data & Analytics"),

    # --- 16. General monitoring (catch remaining monitoring/alerting datasets) ---
    (r"(?i)\bmonitor|alert|troubleshoot|diagnostics", "Monitoring & Governance", "Data Engineering"),

    # --- 17. Managed Services (remaining retailer names not caught above) ---
    (r"(?i)\bmanaged.?service", "Managed Services", "Ad Operations"),
    (r"(?i)\bcasey|speedway|circle.?k|kwik|wawa|pilot|sheetz|marathon|tesoro|holiday.?station", "Managed Services", "Ad Operations"),

    # --- 18. Advertiser-specific → Campaigns ---
    (r"(?i)\bstate.?farm|\bdiscover\b|fairlife", "Campaigns & Delivery", "Ad Operations"),

    # --- 19. Catch-up patterns (reduce unclassified) ---
    # Internal tools
    (r"(?i)\bodyssey|\bkrypton", "Engineering", "Engineering"),
    # Remaining impressions not caught by NVI/CVI rules
    (r"(?i)\bimpression|imps\b|avg.*imp", "Impressions", "Data & Analytics"),
    # Revenue / Finance terms not caught above
    (r"(?i)\bbudget|\bforecast|\bfinance\b|\bmargin|\bprofit|\bcost\b|\bspend\b|\bgross\b", "Revenue & Monetization", "Finance"),
    # Additional retailer brand names → Managed Services
    (r"(?i)\bbp\b|\bshell\b|\bchevron|\bexxon|\bcumberland|\b7.?eleven|\blov(?:e|s)|\bmurphy|sunoco|phillips|valero|arco|citgo", "Managed Services", "Ad Operations"),
    # Scheduling / calendar
    (r"(?i)\bschedul|\bcalendar\b|\btimeline\b", "Campaigns & Delivery", "Ad Operations"),
    # Ad inventory / avails
    (r"(?i)\bavail|\bfill.?rate|\bdemand\b|\bsupply\b", "Programmatic", "Programmatic"),
    # Rates / pricing
    (r"(?i)\bratecard|rate.?card|\bpricing\b", "Revenue & Monetization", "Finance"),
    # Network health / connectivity
    (r"(?i)\bnetwork.*health|\buptime|\bconnectiv|\bheartbeat|\blatency", "Monitoring & Governance", "Data Engineering"),
    # Content / creative assets
    (r"(?i)\bcreative\b|\bcontent.?mgmt|\basset.?mgmt|\bmedia.?plan", "Campaigns & Delivery", "Ad Operations"),
    # Audience / targeting / segmentation
    (r"(?i)\baudience|\btarget(?:ing)?\b|\bsegment\b|\bdemograph", "Site Analytics", "Data & Analytics"),
    # Weather data
    (r"(?i)\bweather|\btemp(?:erature)?.*(?:high|low|avg)", "Site Analytics", "Data & Analytics"),
    # Geographic / maps
    (r"(?i)\bgeojson|\bpolygon|\bgeofence", "Sites & Locations", "Data Engineering"),
    # ETL / dataflow artifacts
    (r"(?i)\bdataflow\b|\betl\b|\bpipeline\b|\bstaging\b", "Engineering", "Engineering"),
    # Analysis projects
    (r"(?i)\banalysis\b|^Analysis\s*-", "Site Analytics", "Data & Analytics"),

    # --- 20. Engineering (remaining) ---
    (r"(?i)\bjira|engineer|sprint|worklog|agile", "Engineering", "Engineering"),
]

# Staleness tiers
STALENESS_TIERS = [
    (7, "Active"),
    (30, "Stale"),
    (90, "Very Stale"),
    (365, "Dormant"),
    (999999, "Abandoned"),
]


def _parse_timestamp(ts: str) -> datetime | None:
    """Parse a Domo API timestamp string to datetime."""
    if not ts:
        return None
    try:
        # Handle various formats
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(str(ts), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        # Try ISO format as fallback
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _get_staleness(days_old: int | None) -> str:
    """Return staleness tier label."""
    if days_old is None:
        return "Unknown"
    for threshold, label in STALENESS_TIERS:
        if days_old <= threshold:
            return label
    return "Abandoned"


def _classify_domain(name: str) -> tuple[str, str]:
    """Classify a dataset name into (domain, department)."""
    for pattern, domain, dept in DOMAIN_RULES:
        if re.search(pattern, name):
            return domain, dept
    return "Other / Unclassified", "Unknown"


def build_dataset_lineage_analysis(
    datasets: list[dict[str, Any]],
    lineage: list[dict[str, Any]],
    dataflows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the Dataset Lineage Analysis tab.

    For each dataset, compute:
    - How many dataflows use it as input (feeds_dataflow_count)
    - How many dataflows produce it as output (fed_by_dataflow_count)
    - Role: Source, Sink, Pass-through, Orphan
    - Downstream reach (total datasets reachable via output chains)
    - Domain classification
    - Staleness tier
    """
    now = datetime.now(timezone.utc)

    # Build lineage lookup
    ds_feeds = defaultdict(set)       # dataset_id -> set of dataflow_ids it feeds
    ds_fed_by = defaultdict(set)      # dataset_id -> set of dataflow_ids that produce it
    df_inputs = defaultdict(set)      # dataflow_id -> set of input dataset_ids
    df_outputs = defaultdict(set)     # dataflow_id -> set of output dataset_ids

    for rec in lineage:
        ds_id = rec.get("dataset_id", "")
        df_id = rec.get("dataflow_id", "")
        direction = rec.get("direction", "")
        if not ds_id or not df_id:
            continue
        if direction == "Input":
            ds_feeds[ds_id].add(df_id)
            df_inputs[df_id].add(ds_id)
        elif direction == "Output":
            ds_fed_by[ds_id].add(df_id)
            df_outputs[df_id].add(ds_id)

    # Compute downstream reach via BFS
    def _downstream_reach(start_ds_id: str) -> int:
        """Count total unique datasets reachable downstream."""
        visited = set()
        queue = [start_ds_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            # Find dataflows this dataset feeds
            for df_id in ds_feeds.get(current, set()):
                # Find outputs of those dataflows
                for out_ds in df_outputs.get(df_id, set()):
                    if out_ds not in visited:
                        queue.append(out_ds)
        return len(visited) - 1  # exclude self

    # Build dataset lookup
    ds_lookup = {ds.get("dataset_id", ""): ds for ds in datasets}

    # Build dataflow names for listing
    df_name_lookup = {}
    for rec in lineage:
        df_id = rec.get("dataflow_id", "")
        df_name = rec.get("dataflow_name", "")
        if df_id and df_name:
            df_name_lookup[df_id] = df_name

    records = []
    for ds in datasets:
        ds_id = ds.get("dataset_id", "")
        ds_name = ds.get("dataset_name", "")

        feeds_count = len(ds_feeds.get(ds_id, set()))
        fed_by_count = len(ds_fed_by.get(ds_id, set()))

        # Determine role
        if feeds_count > 0 and fed_by_count > 0:
            role = "Pass-through"
        elif feeds_count > 0:
            role = "Source"
        elif fed_by_count > 0:
            role = "Sink"
        else:
            role = "Orphan"

        # Downstream reach (only compute for datasets that feed something)
        downstream = _downstream_reach(ds_id) if feeds_count > 0 else 0

        # Staleness
        data_current = _parse_timestamp(ds.get("data_current_at", ""))
        days_old = (now - data_current).days if data_current else None
        staleness = _get_staleness(days_old)

        # Domain
        domain, department = _classify_domain(ds_name)

        # List of dataflow names this feeds (up to 5)
        feed_names = sorted(df_name_lookup.get(df_id, df_id) for df_id in list(ds_feeds.get(ds_id, set()))[:5])

        records.append({
            "dataset_id": ds_id,
            "dataset_name": ds_name,
            "role": role,
            "feeds_dataflow_count": feeds_count,
            "fed_by_dataflow_count": fed_by_count,
            "downstream_reach": downstream,
            "domain": domain,
            "department": department,
            "staleness": staleness,
            "days_since_update": days_old if days_old is not None else "",
            "row_count": ds.get("row_count", 0),
            "owner_name": ds.get("owner_name", ""),
            "feeds_dataflows": " | ".join(feed_names),
        })

    # Sort: Sources first, then by downstream_reach descending
    role_order = {"Source": 0, "Pass-through": 1, "Sink": 2, "Orphan": 3}
    records.sort(key=lambda r: (role_order.get(r["role"], 9), -r["downstream_reach"], r["dataset_name"].lower()))

    logger.info("Built lineage analysis for %d datasets", len(records))
    return records


def build_cleanup_candidates(
    datasets: list[dict[str, Any]],
    lineage: list[dict[str, Any]],
    dataflows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the Cleanup Candidates tab.

    Flags datasets and dataflows that are candidates for deletion/archival.
    """
    now = datetime.now(timezone.utc)

    # Build lineage sets
    ds_in_lineage = set()
    for rec in lineage:
        ds_id = rec.get("dataset_id", "")
        if ds_id:
            ds_in_lineage.add(ds_id)

    df_in_lineage = set()
    for rec in lineage:
        df_id = rec.get("dataflow_id", "")
        if df_id:
            df_in_lineage.add(df_id)

    records = []

    # --- Dataset candidates ---
    for ds in datasets:
        ds_id = ds.get("dataset_id", "")
        ds_name = ds.get("dataset_name", "")
        data_current = _parse_timestamp(ds.get("data_current_at", ""))
        days_old = (now - data_current).days if data_current else None
        staleness = _get_staleness(days_old)
        has_lineage = ds_id in ds_in_lineage
        domain, department = _classify_domain(ds_name)
        row_count = ds.get("row_count", 0) or 0

        # Determine recommendation
        if staleness in ("Abandoned",) and not has_lineage:
            recommendation = "Delete"
            priority = 1
        elif staleness in ("Dormant",) and not has_lineage:
            recommendation = "Delete"
            priority = 2
        elif staleness in ("Very Stale",) and not has_lineage:
            recommendation = "Review for Deletion"
            priority = 3
        elif staleness in ("Abandoned",) and has_lineage:
            recommendation = "Review — Stale but Connected"
            priority = 4
        elif staleness in ("Dormant",) and has_lineage:
            recommendation = "Review — Dormant but Connected"
            priority = 5
        elif domain == "Test / Temp / Archive":
            recommendation = "Review — Test/Temp Dataset"
            priority = 6
        else:
            continue  # Skip healthy datasets

        records.append({
            "type": "Dataset",
            "id": ds_id,
            "name": ds_name,
            "domain": domain,
            "department": department,
            "staleness": staleness,
            "days_since_update": days_old if days_old is not None else "",
            "has_lineage": "Yes" if has_lineage else "No",
            "row_count": row_count,
            "owner_name": ds.get("owner_name", ""),
            "recommendation": recommendation,
            "priority": priority,
        })

    # --- Dataflow candidates ---
    for df in dataflows:
        df_id = str(df.get("dataflow_id", ""))
        df_name = df.get("dataflow_name", "")
        last_exec = _parse_timestamp(df.get("last_execution_date", ""))
        days_since_exec = (now - last_exec).days if last_exec else None
        staleness = _get_staleness(days_since_exec)
        has_lineage = df_id in df_in_lineage
        domain, department = _classify_domain(df_name)

        if staleness in ("Abandoned",):
            recommendation = "Disable/Delete — Not Executing"
            priority = 2
        elif staleness in ("Dormant",):
            recommendation = "Review — Dormant Dataflow"
            priority = 4
        elif staleness in ("Very Stale",):
            recommendation = "Review — Very Stale Dataflow"
            priority = 5
        else:
            continue

        records.append({
            "type": "Dataflow",
            "id": df_id,
            "name": df_name,
            "domain": domain,
            "department": department,
            "staleness": staleness,
            "days_since_update": days_since_exec if days_since_exec is not None else "",
            "has_lineage": "Yes" if has_lineage else "No",
            "row_count": "",
            "owner_name": df.get("owner_name", ""),
            "recommendation": recommendation,
            "priority": priority,
        })

    # Sort by priority, then staleness days descending
    records.sort(key=lambda r: (
        r["priority"],
        -(r["days_since_update"] if isinstance(r["days_since_update"], (int, float)) else 0),
    ))

    logger.info("Identified %d cleanup candidates", len(records))
    return records


def build_domain_map(
    datasets: list[dict[str, Any]],
    lineage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the Domain Map tab.

    Each dataset gets classified into a domain/department with health metrics.
    """
    now = datetime.now(timezone.utc)

    # Build lineage sets
    ds_feeds = defaultdict(set)
    ds_fed_by = defaultdict(set)
    for rec in lineage:
        ds_id = rec.get("dataset_id", "")
        df_id = rec.get("dataflow_id", "")
        direction = rec.get("direction", "")
        if direction == "Input":
            ds_feeds[ds_id].add(df_id)
        elif direction == "Output":
            ds_fed_by[ds_id].add(df_id)

    records = []
    for ds in datasets:
        ds_id = ds.get("dataset_id", "")
        ds_name = ds.get("dataset_name", "")
        data_current = _parse_timestamp(ds.get("data_current_at", ""))
        days_old = (now - data_current).days if data_current else None
        staleness = _get_staleness(days_old)
        domain, department = _classify_domain(ds_name)

        feeds_count = len(ds_feeds.get(ds_id, set()))
        fed_by_count = len(ds_fed_by.get(ds_id, set()))

        if feeds_count > 0 and fed_by_count > 0:
            role = "Pass-through"
        elif feeds_count > 0:
            role = "Source"
        elif fed_by_count > 0:
            role = "Sink"
        else:
            role = "Orphan"

        records.append({
            "domain": domain,
            "department": department,
            "dataset_name": ds_name,
            "dataset_id": ds_id,
            "role": role,
            "staleness": staleness,
            "days_since_update": days_old if days_old is not None else "",
            "row_count": ds.get("row_count", 0),
            "column_count": ds.get("column_count", 0),
            "owner_name": ds.get("owner_name", ""),
            "feeds_dataflow_count": feeds_count,
            "fed_by_dataflow_count": fed_by_count,
        })

    # Sort by domain, then staleness, then name
    records.sort(key=lambda r: (r["domain"].lower(), r["dataset_name"].lower()))

    logger.info("Built domain map for %d datasets", len(records))
    return records
