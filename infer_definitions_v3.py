#!/usr/bin/env python3
"""Third-pass definition inference — mop up remaining interpretable columns."""

import csv
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFINITIONS_CSV = BASE_DIR / "column_definitions.csv"

RULES = []

def rule(pattern, flags=re.IGNORECASE):
    def decorator(func):
        RULES.append((re.compile(pattern, flags), func))
        return func
    return decorator

# =====================================================================
# Placeholder / auto-generated columns
# =====================================================================

@rule(r"^_COLUMN_\d+$")
def _(m):
    return "[N/A] Auto-generated placeholder column from data import"

@rule(r"^__createdBy__$")
def _(m):
    return "[DomoStats] Internal field tracking who created the record"

# =====================================================================
# Jira Linked Issues nested fields
# =====================================================================

@rule(r"^Linked Issues_(inwardIssue|outwardIssue)_fields_(.+)$")
def _(m):
    direction = "inward (blocked by)" if "inward" in m.group(1) else "outward (blocks)"
    field_path = m.group(2).replace("_", " > ")
    return f"[Jira] Linked issue ({direction}) - {field_path}"

@rule(r"^Linked Issues_(inwardIssue|outwardIssue)_(.+)$")
def _(m):
    direction = "inward" if "inward" in m.group(1) else "outward"
    field = m.group(2).replace("_", " ")
    return f"[Jira] Linked issue ({direction}) {field}"

@rule(r"^Linked Issues_(.+)$")
def _(m):
    return f"[Jira] Issue link {m.group(1).replace('_', ' ')}"

# =====================================================================
# Plays by day of week
# =====================================================================

@rule(r"^Plays\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)$")
def _(m):
    return f"Play count for {m.group(1)}"

@rule(r"^Plays\s*[-_]\s*(Previous Day|Yesterday|2 Days Prior|2_Days_Prior)$")
def _(m):
    period = m.group(1).replace("_", " ").lower()
    return f"Play count from {period}"

@rule(r"^Played Hour$")
def _(m):
    return "Hour during which the ad was played"

@rule(r"^Played \(str\)$")
def _(m):
    return "Whether the ad was played (string/boolean representation)"

# =====================================================================
# Prev Days Ago lookback fields
# =====================================================================

@rule(r"^Prev Days Ago\.(.+)$")
def _(m):
    return f"Previous day's value for {m.group(1).strip()}"

# =====================================================================
# Owner tracking / change fields
# =====================================================================

@rule(r"^(Planning Agency|Advertiser|Buying Agency)\s*-\s*(New|Old)\s+Owner\s*-\s*(.+)$")
def _(m):
    return f"{m.group(1)} ownership change - {m.group(2).lower()} owner's {m.group(3).strip().lower()}"

@rule(r"^(Planning Agency|Advertiser|Buying Agency)\s+Change$")
def _(m):
    return f"Whether the {m.group(1).lower()} changed from the prior period"

# =====================================================================
# Site launch tracking
# =====================================================================

@rule(r"^Site\s+(\d+)\s*-\s*Launched$")
def _(m):
    return f"Launch date for site #{m.group(1)} in the deployment sequence"

@rule(r"^Site Account #$")
def _(m):
    return "Account number associated with the site"

@rule(r"^Site Active in ICS$")
def _(m):
    return "Whether the site is active in the Gilbarco ICS system"

@rule(r"^Site\s*-\s*GTVID$")
def _(m):
    return "GSTV site identifier (GTVID)"

# =====================================================================
# Miscellaneous interpretable names
# =====================================================================

@rule(r"^Activity Date Week Number$")
def _(m):
    return "Week number of the year for the activity date"

@rule(r"^AE (Monthly|Total) Split Amount \(Weighted\)$")
def _(m):
    return f"Account Executive weighted {m.group(1).lower()} revenue split amount"

@rule(r"^ASO Additional Info$")
def _(m):
    return "Additional information for the Authorized Service Organization"

@rule(r"^(Advertisers|Seller|Sellers?\(s\))$")
def _(m):
    return f"{m.group(0).strip()} associated with the record"

@rule(r"^Affects versions$")
def _(m):
    return "[Jira] Software versions affected by the issue"

@rule(r"^All Time Status-?\s*(.+)$")
def _(m):
    return f"Historical status tracking by {m.group(1).strip()}"

@rule(r"^Lat\s*Lon$")
def _(m):
    return "Combined latitude and longitude coordinates"

@rule(r"^Latency$")
def _(m):
    return "Network or system latency measurement"

@rule(r"^Latest_Billing$")
def _(m):
    return "Most recent billing date or amount"

@rule(r"^Latitude\s*\d*$")
def _(m):
    return "Latitude coordinate"

@rule(r"^(Letter|Letter Summary)$")
def _(m):
    return "Correspondence letter or summary"

@rule(r"^Life Cycle$")
def _(m):
    return "Lifecycle stage of the asset or record"

@rule(r"^Line Item[_\s]*\d*$")
def _(m):
    return "Campaign line item identifier"

@rule(r"^Link [Tt]o (.+)$")
def _(m):
    return f"URL or reference link to {m.group(1).strip().lower()}"

@rule(r"^(Sentiment|Severity|Service|Service Category|Ship Mode|Shape_Area|Shape_Length)$")
def _(m):
    labels = {
        "Sentiment": "Sentiment analysis result",
        "Severity": "Severity level classification",
        "Service": "Service type or name",
        "Service Category": "Service category classification",
        "Ship Mode": "Shipping mode for the order",
        "Shape_Area": "Geographic shape area from GIS data",
        "Shape_Length": "Geographic shape perimeter length from GIS data",
    }
    return labels.get(m.group(1), m.group(1))

@rule(r"^Shell$")
def _(m):
    return "Shell Oil branded site flag"

@rule(r"^Short Description$")
def _(m):
    return "Brief description of the record"

@rule(r"^Simple Category$")
def _(m):
    return "Simplified category classification"

@rule(r"^Simplified Phone$")
def _(m):
    return "Phone number in simplified/normalized format"

@rule(r"^Post code$")
def _(m):
    return "Postal/ZIP code"

@rule(r"^Post Survey Ready\?.*$")
def _(m):
    return "Whether the site is ready for post-installation survey"

@rule(r"^Potential Dependencies$")
def _(m):
    return "[Jira] Potential dependencies for the issue"

@rule(r"^Pred vs Actual$")
def _(m):
    return "Comparison of predicted vs actual values"

@rule(r"^Previous Market Plan$")
def _(m):
    return "Market plan from the previous period"

@rule(r"^Serial Group$")
def _(m):
    return "Serial number group for device classification"

@rule(r"^(Sent to Media Support|Confirmed\?|Create AssetID|Set-up Requirement\(s\))$")
def _(m):
    return f"Workflow status: {m.group(0).strip().lower()}"

@rule(r"^(Costs|Number)$")
def _(m):
    return f"{m.group(1)} value"

@rule(r"^(1st|2nd|3rd)\s+(.+)$")
def _(m):
    ordinal = m.group(1)
    rest = m.group(2).strip()
    return f"{ordinal} {rest.lower()}"

@rule(r"^14\+\s*Day NVI GTVID$")
def _(m):
    return "GTVID for sites with 14+ consecutive days of NVI reporting"

@rule(r"^(\d+)\+?\s+Impressions\s*\d*$")
def _(m):
    return f"Impression count for the {m.group(1)}+ demographic or time segment"

@rule(r"^2023 DMA Rank$")
def _(m):
    return "DMA rank based on 2023 data"

@rule(r"^Exp Daily Spend\s*$")
def _(m):
    return "Expected daily spend amount"

@rule(r"^Last Sync\s*-\s*(.+)$")
def _(m):
    return f"Timestamp of the last data sync with {m.group(1).strip()}"

@rule(r"^(AssetID|Asset)$")
def _(m):
    return "Creative asset identifier"

@rule(r"^Asset (Daypart Start|Daypart Stop|List|Rotation)$")
def _(m):
    return f"Creative asset {m.group(1).strip().lower()}"

@rule(r"^Assigned Slot$")
def _(m):
    return "Assigned time slot for the ad play"

@rule(r"^Associations$")
def _(m):
    return "Associated records or relationships"

@rule(r"^Attending$")
def _(m):
    return "Whether the person is attending"

@rule(r"^Attendees/Titles$")
def _(m):
    return "List of attendees and their titles"

@rule(r"^AutoOwn[012p]+$")
def _(m):
    return "Auto-ownership assignment flag or tier"

@rule(r"^Background Image Filename$")
def _(m):
    return "Filename of the background image asset"

@rule(r"^Base \(ID - Gbase\)$")
def _(m):
    return "GBase ID for the base (current) period site"

@rule(r"^Comparison \(ID - Gbase\)$")
def _(m):
    return "GBase ID for the comparison (prior) period site"

@rule(r"^Comparison Key$")
def _(m):
    return "Key used to match base and comparison period records"

@rule(r"^Comp ID - Gbase$")
def _(m):
    return "GBase ID for the comparison (prior) period site"

@rule(r"^(Calculation Timestamp|Time Stamp)$")
def _(m):
    return "Timestamp when the calculation or record was generated"

@rule(r"^Open Day$")
def _(m):
    return "Day of the week the site is open"

@rule(r"^Open Hours$")
def _(m):
    return "Total hours the site is open per day"

@rule(r"^Operating (Hour|Hours|Week)$")
def _(m):
    return f"Operating {m.group(1).lower()} for the site"

@rule(r"^Operational Times$")
def _(m):
    return "Operational time windows for the site"

@rule(r"^(Approver groups|Approver groups_.+)$")
def _(m):
    if "_" in m.group(0):
        suffix = m.group(0).split("_", 1)[1]
        return f"[Jira] Approver group {suffix}"
    return "[Jira] Approval group(s) assigned to the request"

@rule(r"^(CStore Brand Change|Any Brand Change)$")
def _(m):
    return "Whether the convenience store brand changed"

@rule(r"^(DB-APCH-PHP)$")
def _(m):
    return "Database approach/PHP configuration identifier"

@rule(r"^(Conversion|Category) (.+)$")
def _(m):
    return f"{m.group(1)} {m.group(2).strip().lower()}"

@rule(r"^(COUNT|Count)\(.+\)$")
def _(m):
    return f"Aggregated count calculation: {m.group(0)}"

@rule(r"^(Customer|Opp|OPP)\s+#$")
def _(m):
    return f"{m.group(1)} reference number"

@rule(r"^(Datatype|Data Type)$")
def _(m):
    return "Data type of the field or column"

@rule(r"^(COMMENT|Connection|Date Provided to GSTV RS|Date GSTV Set up|Date IGVR Finished|Date IGVR Sent|Date Surveyed)$")
def _(m):
    labels = {
        "COMMENT": "Comment or note on the record",
        "Connection": "Network connection type or status",
        "Date Provided to GSTV RS": "Date provided to GSTV Retailer Services",
        "Date GSTV Set up": "Date GSTV completed setup",
        "Date IGVR Finished": "Date IGVR process completed",
        "Date IGVR Sent": "Date IGVR was sent",
        "Date Surveyed": "Date the site survey was completed",
    }
    return labels.get(m.group(1), m.group(1))

@rule(r"^(Black Buffalo INCLUDE)$")
def _(m):
    return "Whether to include the site for Black Buffalo campaign targeting"

@rule(r"^(Checklist Text|Checklist Text \(view-only\))$")
def _(m):
    return "[Jira] Checklist text content"

@rule(r"^(Original|Error|Change)\s+(.+)$")
def _(m):
    return f"{m.group(1)} {m.group(2).strip().lower()}"

@rule(r"^(Non-Audited|Non DXP)\s+(.+)$")
def _(m):
    return f"{m.group(1)} {m.group(2).strip().lower()}"

@rule(r"^(Inherited|Invenco|IOTV1)\s+(.+)$")
def _(m):
    return f"{m.group(1)} {m.group(2).strip().lower()}"

@rule(r"^(Kwik Trip|Marathon|Speedway|Wawa|Pilot|Sheetz|Holiday)\s+(.+)$")
def _(m):
    return f"{m.group(1)}-specific {m.group(2).strip().lower()}"

@rule(r"^LastGetTaskTimestamp$")
def _(m):
    return "Timestamp of the last task retrieval"

@rule(r"^(Address|Department|Approvals|Components)_\(customfield_\d+\)$")
def _(m):
    return f"[Jira] Custom field for {m.group(1).lower()}"

@rule(r"^(.+?)_\(customfield_\d+\)$")
def _(m):
    return f"[Jira] Custom field: {m.group(1).replace('_', ' ')}"

@rule(r"^(Direct Revenue)$")
def _(m):
    return "Revenue from direct (non-programmatic) ad sales"

@rule(r"^(Gilbarco ICS\s*-?\s*)(.+)$")
def _(m):
    return f"[Gilbarco ICS] {m.group(2).strip()}"

@rule(r"^(N/A Revenue)$")
def _(m):
    return "Revenue categorized as not applicable or unclassified"

@rule(r"^(Traffic Instructions)$")
def _(m):
    return "Traffic instruction document or reference"

@rule(r"^(Total Weeks|Total Hours|Total Duration|Total Play Duration|Total NVI Reported|Total Monthly Impressions.*)$")
def _(m):
    return m.group(0).strip()

@rule(r"^(Total Checks|Total_Checks)$")
def _(m):
    return "Total number of data quality checks performed"

@rule(r"^(Total_Uptime)$")
def _(m):
    return "Total uptime duration for the device"

@rule(r"^(Total Impacted|Total Sites In|Total Sites Remaining|Total Calculated|Total Hourly|Total Plan|TotalMPs).*$")
def _(m):
    return m.group(0).strip().replace("TotalMPs", "Total market plans")

@rule(r"^(Today|Yesterday|2 Days Ago)\s+Reported Plays\??$")
def _(m):
    return f"Whether the site reported plays {m.group(1).lower()}"

@rule(r"^Top 200 Retailer$")
def _(m):
    return "Whether the site belongs to a Top 200 retailer"

@rule(r"^Transaction Check.+$")
def _(m):
    return "Transaction data quality check result"

@rule(r"^Transtion Lookup$")
def _(m):
    return "Transition lookup reference (note: field name has typo for 'transition')"

@rule(r"^(Verified|Validated|Active|Inactive|Pending|Draft|Archived|Cancelled|Closed|Paused)$")
def _(m):
    return f"Status flag: {m.group(1).lower()}"

@rule(r"^(Average impressions_per_spot)$")
def _(m):
    return "Average impression count per ad spot"

@rule(r"^(Average display time latency \(seconds\))_(.+)$")
def _(m):
    return f"Average display time latency in seconds ({m.group(2).replace('_', ' ')})"

@rule(r"^(Avg Imp .+)$")
def _(m):
    return f"Average impressions - {m.group(0)[8:].strip()}"

@rule(r"^(DMA Rank).*$")
def _(m):
    return "DMA ranking metric"

@rule(r"^(DMA Impacted|DMA Average|DMA Revenue|Networks Impacted).*$")
def _(m):
    return m.group(0).strip()


# =====================================================================
# Main
# =====================================================================

def infer(col_name):
    for pattern, func in RULES:
        m = pattern.match(col_name)
        if m:
            result = func(m)
            if result:
                if result[0] == "[":
                    bracket_end = result.index("]") + 1
                    rest = result[bracket_end:].lstrip()
                    if rest and rest[0].islower():
                        rest = rest[0].upper() + rest[1:]
                    result = result[:bracket_end] + " " + rest
                elif result[0].islower():
                    result = result[0].upper() + result[1:]
                return result.rstrip(".")
    return None


def main():
    rows = []
    with open(DEFINITIONS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)

    count = 0
    still_undefined = 0
    for row in rows:
        if row.get("definition", "").strip():
            continue
        new_def = infer(row["column_name"])
        if new_def:
            row["definition"] = new_def
            row["status"] = "inferred"
            count += 1
        else:
            still_undefined += 1

    with open(DEFINITIONS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    defined = sum(1 for r in rows if r.get("definition", "").strip())
    total = len(rows)
    print(f"Third pass: inferred {count} additional definitions")
    print(f"Still undefined: {still_undefined}")
    print(f"Overall: {defined}/{total} defined ({defined/total*100:.1f}%)")


if __name__ == "__main__":
    main()
