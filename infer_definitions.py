#!/usr/bin/env python3
"""Infer column definitions from column names using pattern matching.

Scans undefined columns and applies a large set of naming-pattern rules to
generate reasonable definitions automatically.  Saves results back into
column_definitions.csv with status='inferred'.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFINITIONS_CSV = BASE_DIR / "column_definitions.csv"
CACHE_PATH = BASE_DIR / ".cache" / "latest.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _title(s: str) -> str:
    """Lowercase a string for embedding in a definition."""
    return s.strip()


def _year_range(yy1: str, yy2: str) -> str:
    """Convert '22/23' or '22','23' to '2022 and 2023'."""
    y1 = int(yy1) + 2000 if int(yy1) < 100 else int(yy1)
    y2 = int(yy2) + 2000 if int(yy2) < 100 else int(yy2)
    return f"{y1} and {y2}"


def _month_name(mm: str) -> str:
    months = {
        "01": "January", "02": "February", "03": "March", "04": "April",
        "05": "May", "06": "June", "07": "July", "08": "August",
        "09": "September", "10": "October", "11": "November", "12": "December",
    }
    return months.get(mm, mm)


def _month_from_name(name: str) -> str:
    """Extract month from name like 'January', 'February', etc."""
    return name.strip()


def _format_hour_range(h1: str, h2: str) -> str:
    """Format '10/11' or '10','11' as '10:00-11:00'."""
    return f"{int(h1):02d}:00-{int(h2):02d}:00"


def _clean_jira_suffix(field_path: str) -> str:
    """Convert 'Time to first response_completedCycles_breachTime_epochMillis' to readable."""
    parts = field_path.split("_")
    readable = " ".join(parts)
    return readable


def _gender_label(code: str) -> str:
    return "Female" if code.upper() == "F" else "Male" if code.upper() == "M" else code


def _age_range(lo: str, hi: str) -> str:
    if hi == "":
        return f"{lo}+"
    return f"{lo}-{hi}"


# ---------------------------------------------------------------------------
# Pattern rules — each returns (definition, status) or None
# ---------------------------------------------------------------------------

RULES = []

def rule(pattern, flags=re.IGNORECASE):
    """Decorator to register an inference rule."""
    def decorator(func):
        RULES.append((re.compile(pattern, flags), func))
        return func
    return decorator


# ---- Year-Month Transactions ----
@rule(r"^(\d{4})-(\d{2})\s*-\s*Trans(?:actions|cations)?\s*$")
def _(m):
    return f"Transaction count for {_month_name(m.group(2))} {m.group(1)}"

@rule(r"^(\d{4})\s*-\s*Transactions$")
def _(m):
    return f"Total transaction count for the year {m.group(1)}"

@rule(r"^(\d{4})\.Average Daily Transactions$")
def _(m):
    return f"Average daily transaction count for the year {m.group(1)}"

# ---- Year - Days - Status ----
@rule(r"^(\d{4})\s*-\s*Days\s*-\s*(.+)$")
def _(m):
    return f"Number of days the site was in '{m.group(2).strip()}' status during {m.group(1)}"

# ---- Active Days - Year ----
@rule(r"^Active Days\s*-\s*(\d{4})$")
def _(m):
    return f"Number of days the site was active during {m.group(1)}"

@rule(r"^Other Status Days\s*-\s*(\d{4})$")
def _(m):
    return f"Number of days the site was in a non-standard status during {m.group(1)}"

# ---- Transactions - Year ----
@rule(r"^Transactions\s*-\s*(\d{4})$")
def _(m):
    return f"Total transaction count for the year {m.group(1)}"

# ---- Delta columns ----
@rule(r"^Delta\s*\(#\)\s*-\s*(\d{2})/(\d{2})$")
def _(m):
    return f"Year-over-year change (absolute count) between {_year_range(m.group(1), m.group(2))}"

@rule(r"^Delta\s*\(%\)\s*-\s*(\d{2})/(\d{2})$")
def _(m):
    return f"Year-over-year change (percentage) between {_year_range(m.group(1), m.group(2))}"

@rule(r"^Delta\s*-\s*(\d{2})/(\d{2})\s*\(#\)$")
def _(m):
    return f"Year-over-year change (absolute count) between {_year_range(m.group(1), m.group(2))}"

@rule(r"^Delta\s*-\s*(\d{2})/(\d{2})\s*\(%\)$")
def _(m):
    return f"Year-over-year change (percentage) between {_year_range(m.group(1), m.group(2))}"

@rule(r"^Delta Bucketing\s*-\s*(\d{2})/(\d{2})$")
def _(m):
    return f"Categorical bucket for the year-over-year change between {_year_range(m.group(1), m.group(2))}"

@rule(r"^Network Change\s*-\s*(\d{2})/(\d{2})$")
def _(m):
    return f"Whether the site changed networks between {_year_range(m.group(1), m.group(2))}"

# ---- 2 Year / 4 Year Delta ----
@rule(r"^(\d)\s*Year\s*-\s*Delta\s*-\s*(.+?)\s*\((#)\)$")
def _(m):
    return f"{m.group(1)}-year change in {m.group(2).strip()} (absolute count)"

@rule(r"^(\d)\s*Year\s*-\s*Delta\s*-\s*(.+?)\s*\((%)\)$")
def _(m):
    return f"{m.group(1)}-year change in {m.group(2).strip()} (percentage)"

# ---- Comparison columns ----
@rule(r"^Comparison\s*-\s*(\d)\s*Year\s*-\s*(.+)$")
def _(m):
    return f"{m.group(1)}-year comparison value for {m.group(2).strip()}"

# ---- DMA Demographics (DMA.F_18_24, DMA.M_25_34, etc.) ----
@rule(r"^DMA\.([FM])_(\d+)_(\d+)$")
def _(m):
    return f"DMA-level {_gender_label(m.group(1))} population aged {m.group(2)}-{m.group(3)}"

@rule(r"^DMA\.([FM])_(\d+)\+?$")
def _(m):
    return f"DMA-level {_gender_label(m.group(1))} population aged {m.group(2)} and older"

@rule(r"^DMA\.DMA Code$")
def _(m):
    return "Nielsen Designated Market Area (DMA) numeric code"

# ---- Day-of-week hourly columns (Tuesday 10/11) ----
@rule(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{2})/(\d{2})$")
def _(m):
    return f"Hourly metric for {m.group(1)} between {_format_hour_range(m.group(2), m.group(3))}"

@rule(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$")
def _(m):
    days = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"}
    return f"Metric value for {days.get(m.group(1), m.group(1))}"

# ---- Open Hour N ----
@rule(r"^Open Hour\s+(\d+)$")
def _(m):
    return f"Whether the site is open during hour {m.group(1)}:00-{int(m.group(1))+1}:00"

@rule(r"^(\d+)\s+Hours?$")
def _(m):
    return f"Metric value at {m.group(1)} hour(s) after the reference point"

# ---- Hourly transaction columns ----
@rule(r"^Daily Transactions\s*-\s*(\d+)$")
def _(m):
    return f"Daily transaction count for hour {m.group(1)}:00"

# ---- Numbered columns (just digits) ----
@rule(r"^(\d{1,2})$")
def _(m):
    return f"Metric value for hour or period {m.group(1)}"

# ---- # (count) columns ----
@rule(r"^#\s*(?:of\s+)?(.+)$")
def _(m):
    return f"Count of {m.group(1).strip().lower()}"

@rule(r"^#\s*Days$")
def _(m):
    return "Number of days"

# ---- % columns ----
@rule(r"^%\s+(.+)$")
def _(m):
    return f"Percentage of {m.group(1).strip().lower()}"

# ---- Count of X ----
@rule(r"^Count\s+(?:of\s+)?(?:distinct\s+)?(.+)$", re.IGNORECASE)
def _(m):
    return f"Count of {m.group(1).strip()}"

# ---- Total X ----
@rule(r"^Total\s+(.+)$")
def _(m):
    subject = m.group(1).strip()
    if subject.lower() in ("", "1"):
        return None
    return f"Total {subject.lower()}"

# ---- Average X ----
@rule(r"^(?:Avg|Average)\s+(.+)$", re.IGNORECASE)
def _(m):
    return f"Average {m.group(1).strip().lower()}"

# ---- Number of X ----
@rule(r"^Number\s+of\s+(.+)$", re.IGNORECASE)
def _(m):
    return f"Number of {m.group(1).strip().lower()}"

# ---- Days Since X ----
@rule(r"^Days\s+Since\s+(.+)$", re.IGNORECASE)
def _(m):
    return f"Number of days since {m.group(1).strip().lower()}"

@rule(r"^Days\s+(?:With|Of)\s+(.+)$", re.IGNORECASE)
def _(m):
    return f"Number of days with {m.group(1).strip().lower()}"

@rule(r"^Days\s+(Active|Flagged|Migrated|Run|Online|Reporting|Not Reporting|In)(?:\s+(.+))?$", re.IGNORECASE)
def _(m):
    suffix = m.group(2).strip() if m.group(2) else ""
    return f"Number of days {m.group(1).strip().lower()}{' ' + suffix if suffix else ''}"

@rule(r"^Days\s+In\s+(.+)$", re.IGNORECASE)
def _(m):
    return f"Number of days in {m.group(1).strip().lower()}"

@rule(r"^Days\s*Ago$", re.IGNORECASE)
def _(m):
    return "Number of days ago relative to the current date"

# ---- BLANK_COL_XX ----
@rule(r"^BLANK_COL_\d+$")
def _(m):
    return "[N/A] Unused placeholder column"

# ---- Column0, Column11, etc. ----
@rule(r"^Column\d+$")
def _(m):
    return "[N/A] Auto-generated placeholder column from data import"

# ---- Jira user property fields ----
@rule(r"^(Assignee|Creator|Contributors|Approvers|Reporter|Change managers|Business Owner)_(accountId)$", re.IGNORECASE)
def _(m):
    return f"[Jira] Atlassian account ID of the {m.group(1).lower()}"

@rule(r"^(Assignee|Creator|Contributors|Approvers|Reporter|Change managers|Business Owner)_(accountType)$", re.IGNORECASE)
def _(m):
    return f"[Jira] Account type (e.g., atlassian, customer) of the {m.group(1).lower()}"

@rule(r"^(Assignee|Creator|Contributors|Approvers|Reporter|Change managers|Business Owner)_(active)$", re.IGNORECASE)
def _(m):
    return f"[Jira] Whether the {m.group(1).lower()}'s account is currently active"

@rule(r"^(Assignee|Creator|Contributors|Approvers|Reporter|Change managers|Business Owner)_(displayName)$", re.IGNORECASE)
def _(m):
    return f"[Jira] Display name of the {m.group(1).lower()}"

@rule(r"^(Assignee|Creator|Contributors|Approvers|Reporter|Change managers|Business Owner)_(emailAddress)$", re.IGNORECASE)
def _(m):
    return f"[Jira] Email address of the {m.group(1).lower()}"

@rule(r"^(Assignee|Creator|Contributors|Approvers|Reporter|Change managers|Business Owner)_(timeZone)$", re.IGNORECASE)
def _(m):
    return f"[Jira] Time zone setting of the {m.group(1).lower()}"

@rule(r"^(Assignee|Creator|Contributors|Approvers|Reporter|Change managers|Business Owner)_(self)$", re.IGNORECASE)
def _(m):
    return f"[Jira] API self-link URL for the {m.group(1).lower()}"

# ---- Jira generic _id, _self, _value patterns ----
@rule(r"^(.+)_id$")
def _(m):
    field = m.group(1).strip()
    if len(field) < 3 or field.startswith("BLANK") or field[0].isdigit():
        return None
    return f"[Jira] Internal identifier for the {field} field"

@rule(r"^(.+)_self$")
def _(m):
    field = m.group(1).strip()
    if len(field) < 3:
        return None
    return f"[Jira] API self-link URL for the {field} field"

@rule(r"^(.+)_value$")
def _(m):
    field = m.group(1).strip()
    if len(field) < 3:
        return None
    return f"[Jira] Display value of the {field} field"

# ---- Jira SLA fields ----
@rule(r"^(Time to .+?)_(completedCycles|ongoingCycle)_(.+)$")
def _(m):
    sla_name = m.group(1)
    cycle_type = "completed cycle" if "completed" in m.group(2) else "ongoing cycle"
    subfield = m.group(3).replace("_", " ")
    return f"[Jira] {sla_name} SLA - {cycle_type} {subfield}"

@rule(r"^(Time to .+?)_(errorMessage|i18nErrorMessage_i18nKey|id|name)$")
def _(m):
    sla_name = m.group(1)
    subfield = m.group(2).replace("_", " ")
    return f"[Jira] {sla_name} SLA metadata ({subfield})"

@rule(r"^(Time to .+?)_(.+)$")
def _(m):
    sla_name = m.group(1)
    subfield = m.group(2).replace("_", " ").replace("links ", "")
    return f"[Jira] {sla_name} SLA {subfield}"

# ---- Jira Approvals fields ----
@rule(r"^Approvals_(.+)$")
def _(m):
    return f"[Jira] Approval workflow {m.group(1).replace('_', ' ')}"

# ---- Jira Organizations fields ----
@rule(r"^Organizations_(.+)$")
def _(m):
    return f"[Jira] Organization {m.group(1).replace('_', ' ')}"

# ---- Jira Components fields ----
@rule(r"^Components_(description|id|name|self)$")
def _(m):
    return f"[Jira] Component {m.group(1)}"

# ---- Jira Affects versions fields ----
@rule(r"^Affects versions_(archived|description|id|name|released|self)$")
def _(m):
    return f"[Jira] Affected software version {m.group(1)}"

# ---- DomoStats Dataset_ fields ----
@rule(r"^Dataset_(.+)$")
def _(m):
    field = m.group(1).replace("_", " ")
    return f"[DomoStats] Dataset {field.lower()}"

@rule(r"^DS_DomoStats_DataSets\.(.+)$")
def _(m):
    return f"[DomoStats] Dataset {m.group(1).lower()} from the DomoStats DataSets connector"

# ---- BillingAddress fields ----
@rule(r"^BillingAddress\.(.+)$")
def _(m):
    field = m.group(1)
    labels = {
        "city": "city", "country": "country", "geocodeAccuracy": "geocoding accuracy level",
        "latitude": "latitude coordinate", "longitude": "longitude coordinate",
        "postalCode": "postal/ZIP code", "state": "state or province", "street": "street address",
    }
    return f"[SF] Billing address {labels.get(field, field.lower())}"

# ---- Enterprise location fields ----
@rule(r"^Enterprise\.(.+)$")
def _(m):
    field = m.group(1)
    labels = {"City": "city", "State": "state", "Street": "street address"}
    return f"Enterprise location {labels.get(field, field.lower())}"

# ---- Environment fields ----
@rule(r"^Environment\.(Description|Id|Name|SourceSystem)$")
def _(m):
    return f"Display environment {m.group(1).lower()}"

# ---- OPP/IO fields ----
@rule(r"^OPP/IO\.(.+)$")
def _(m):
    field = m.group(1).strip()
    return f"[SF: Opportunity] {field} from the Opportunity/Insertion Order record"

@rule(r"^OPP/IO\s+(.+)$")
def _(m):
    return f"Opportunity/Insertion Order {m.group(1).strip().lower()}"

# ---- Achieved columns ----
@rule(r"^Achieved\s*\((\$|%)\)\s*-\s*(.+)$")
def _(m):
    unit = "dollar amount" if m.group(1) == "$" else "percentage"
    period = m.group(2).strip()
    return f"Sales achievement {unit} for {period}"

# ---- DMA Revenue / Impressions metrics ----
@rule(r"^DMA\s+(.+)$", re.IGNORECASE)
def _(m):
    return f"DMA-level {m.group(1).strip().lower()}"

@rule(r"^CBSA[_ ](.+)$")
def _(m):
    field = m.group(1).strip()
    labels = {"EMP": "employment count", "POP": "population count", "WRK": "worker count", "Name": "name", "Population": "population"}
    return f"Core-Based Statistical Area (CBSA) {labels.get(field, field.lower())}"

# ---- Monthly name columns (April 2024, etc.) ----
@rule(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$")
def _(m):
    return f"Metric value for {m.group(1)} {m.group(2)}"

@rule(r"^(Apr|Aug|Dec|Feb|Jan|Jul|Jun|Mar|May|Nov|Oct|Sep)\s+(\d{4})$")
def _(m):
    return f"Metric value for {m.group(1)} {m.group(2)}"

# ---- Exchange / Deal revenue columns ----
@rule(r"^(Exchange|Deal)\s+(Revenue|Impressions|Spots)(?:\s*-\s*(.+))?$", re.IGNORECASE)
def _(m):
    type_ = m.group(1)
    metric = m.group(2).lower()
    qualifier = f" ({m.group(3).strip()})" if m.group(3) else ""
    return f"Programmatic {type_.lower()} {metric}{qualifier}"

@rule(r"^(Exchange|Deal)\s+(Rev|Revenue|Impressions|Spots)_(\d+)([dw])k?_avg$")
def _(m):
    type_ = m.group(1)
    metric = "revenue" if "Rev" in m.group(2) else m.group(2).lower()
    period = m.group(3)
    unit = "day" if m.group(4) == "d" else "week"
    return f"Programmatic {type_.lower()} {metric} ({period}-{unit} rolling average)"

# ---- _30d_avg / _4wk_avg suffixed columns ----
@rule(r"^(.+?)_(\d+)(d|wk)_avg$")
def _(m):
    base = m.group(1).replace("_", " ").strip()
    period = m.group(2)
    unit = "day" if m.group(3) == "d" else "week"
    return f"{base} ({period}-{unit} rolling average)"

# ---- Casey's / retailer-specific ----
@rule(r"^Casey'?s?\s+(.+)$")
def _(m):
    return f"Casey's-specific {m.group(1).strip().lower()}"

@rule(r"^Circle K\s+(.+)$")
def _(m):
    return f"Circle K-specific {m.group(1).strip().lower()}"

@rule(r"^Dover DXPromote\s+(.+)$")
def _(m):
    return f"Dover DXPromote {m.group(1).strip().lower()}"

@rule(r"^Direct to Retailer\s+(.+)$")
def _(m):
    return f"Direct-to-retailer {m.group(1).strip().lower()}"

# ---- Nth position columns (First, Second, ... for campaign line items) ----
@rule(r"^(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh|Twelfth)$")
def _(m):
    return f"Value or identifier for the {m.group(1).lower()} item in the sequence"

@rule(r"^(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|Eleventh|Twelfth)(CTR|Clicks|Delivered IMPs?)$")
def _(m):
    metrics = {"CTR": "click-through rate", "Clicks": "click count", "Delivered IMPs": "delivered impressions", "Delivered IMP": "delivered impressions"}
    return f"{metrics.get(m.group(2), m.group(2))} for the {m.group(1).lower()} line item in the campaign"

@rule(r"^Total(CTR|Clicks|Delivered\s*IMPs?)$")
def _(m):
    metrics = {"CTR": "click-through rate", "Clicks": "click count", "DeliveredIMPs": "delivered impressions", "Delivered IMPs": "delivered impressions"}
    val = m.group(1).strip()
    return f"Total {metrics.get(val, val.lower())} across all line items"

# ---- Base / Comp programmatic columns ----
@rule(r"^(Base|Comp)\s*-\s*(.+)$")
def _(m):
    period = "base (current)" if m.group(1) == "Base" else "comparison (prior)"
    metric = m.group(2).strip()
    return f"{metric} for the {period} period"

@rule(r"^(Base|Comp)\s+(.+)$")
def _(m):
    period = "base (current)" if m.group(1) == "Base" else "comparison (prior)"
    metric = m.group(2).strip()
    return f"{metric} for the {period} period"

# ---- DATABASE METADATA columns ----
@rule(r"^(CHARACTER_MAXIMUM_LENGTH|CHARACTER_OCTET_LENGTH|CHARACTER_SET_CATALOG|CHARACTER_SET_NAME|CHARACTER_SET_SCHEMA|COLLATION_CATALOG|COLLATION_NAME|COLLATION_SCHEMA|COLUMN_DEFAULT|COLUMN_NAME|DATA_TYPE|DATA_TYPE_ALIAS|DATETIME_PRECISION|DOMAIN_CATALOG|DOMAIN_NAME|DOMAIN_SCHEMA|ORDINAL_POSITION|DTD_IDENTIFIER)$")
def _(m):
    labels = {
        "CHARACTER_MAXIMUM_LENGTH": "Maximum character length of the column",
        "CHARACTER_OCTET_LENGTH": "Maximum length in bytes of the column",
        "CHARACTER_SET_CATALOG": "Character set catalog for the column",
        "CHARACTER_SET_NAME": "Character set name for the column",
        "CHARACTER_SET_SCHEMA": "Character set schema for the column",
        "COLLATION_CATALOG": "Collation catalog for the column",
        "COLLATION_NAME": "Collation name for the column",
        "COLLATION_SCHEMA": "Collation schema for the column",
        "COLUMN_DEFAULT": "Default value defined for the column",
        "COLUMN_NAME": "Name of the database column",
        "DATA_TYPE": "Data type of the column",
        "DATA_TYPE_ALIAS": "Alias for the column data type",
        "DATETIME_PRECISION": "Fractional seconds precision for datetime columns",
        "DOMAIN_CATALOG": "Domain catalog the column belongs to",
        "DOMAIN_NAME": "Domain name the column is constrained by",
        "DOMAIN_SCHEMA": "Schema of the domain the column belongs to",
        "ORDINAL_POSITION": "Position of the column within its table",
        "DTD_IDENTIFIER": "Data type descriptor identifier",
    }
    return f"[Schema metadata] {labels.get(m.group(1), m.group(1))}"

# ---- Owner property fields ----
@rule(r"^Owner_(DisplayName|EmployeeID|EmployeeNumber|Locale|Location|ProfilePictureURL)$")
def _(m):
    labels = {
        "DisplayName": "display name", "EmployeeID": "employee ID",
        "EmployeeNumber": "employee number", "Locale": "locale setting",
        "Location": "office location", "ProfilePictureURL": "profile picture URL",
    }
    return f"Dataset owner's {labels.get(m.group(1), m.group(1).lower())}"

# ---- Programmatic fields ----
@rule(r"^PD\s+(.+)$")
def _(m):
    return f"Programmatic direct {m.group(1).strip().lower()}"

@rule(r"^PMP\s+(.+)$")
def _(m):
    return f"Private marketplace (PMP) {m.group(1).strip().lower()}"

# ---- CC (Credit Card / Gilbarco) fields ----
@rule(r"^CC\s+(City|State|ZIP|Zip Code|Phone|Days Since Last Sync|Dispenser Types|Server Version)$")
def _(m):
    return f"[Gilbarco CC] Credit card terminal {m.group(1).strip().lower()}"

# ---- Avg_Daily patterns ----
@rule(r"^Avg_Daily_(Imps|Transactions)_(.+?)_(\d{4})_(\d{4})$")
def _(m):
    metric = "impressions" if "Imp" in m.group(1) else "transactions"
    period = m.group(2).replace("_", " ")
    return f"Average daily {metric} for {period} period ({m.group(3)}-{m.group(4)})"

# ---- 4 Week / rolling columns ----
@rule(r"^4\s*Week\s+(.+)$")
def _(m):
    return f"4-week rolling {m.group(1).strip().lower()}"

# ---- Impressions range columns (13-17 Impressions, etc.) ----
@rule(r"^(\d+)\s*(?:-\s*(\d+))?\s+Impressions.*$")
def _(m):
    if m.group(2):
        return f"Impression count for the {m.group(1)}-{m.group(2)} age/hour range"
    return f"Impression count for the {m.group(1)}+ age/hour range"

# ---- Day lag columns ----
@rule(r"^(\d+)_Day_Lag_(Leases|Plays)$")
def _(m):
    return f"Programmatic {m.group(2).lower()} reported with a {m.group(1)}-day lag"

# ---- N Days Ago ----
@rule(r"^(\d+)\s+Days?\s+Ago.*$")
def _(m):
    return f"Metric value from {m.group(1)} day(s) ago"

# ---- Delivered Impressions variants ----
@rule(r"^Delivered Impressions\s*-\s*(.+)$")
def _(m):
    return f"Delivered impressions calculated using {m.group(1).strip().lower()} methodology"

# ---- Delta - named metrics ----
@rule(r"^Delta\s*-\s*(.+?)\s*\(([#%])\)$")
def _(m):
    unit = "absolute count" if m.group(2) == "#" else "percentage"
    return f"Change in {m.group(1).strip().lower()} ({unit})"

@rule(r"^Delta\s*-\s*(.+)$")
def _(m):
    return f"Change in {m.group(1).strip().lower()}"

@rule(r"^Delta\s*\(([#%])\)$")
def _(m):
    unit = "absolute count" if m.group(1) == "#" else "percentage"
    return f"Period-over-period change ({unit})"

@rule(r"^Delta$")
def _(m):
    return "Period-over-period change"

# ---- Concat / concatenated fields ----
@rule(r"^Concat(?:enated?)?\s+(.+)$", re.IGNORECASE)
def _(m):
    return f"Concatenated key combining {m.group(1).strip()}"

# ---- Simple well-known fields ----
@rule(r"^(Email Address|Email - Personal|Company email address)$", re.IGNORECASE)
def _(m):
    return "Email address"

@rule(r"^(Currency|Currency Code)$", re.IGNORECASE)
def _(m):
    return "Currency code (e.g., USD, CAD)"

@rule(r"^Time Spent$", re.IGNORECASE)
def _(m):
    return "[Jira] Total time spent on the issue"

@rule(r"^Time Logged$", re.IGNORECASE)
def _(m):
    return "[Jira] Time logged against the issue"

@rule(r"^Original estimate$", re.IGNORECASE)
def _(m):
    return "[Jira] Original time estimate for the issue"

@rule(r"^Epic Color$", re.IGNORECASE)
def _(m):
    return "[Jira] Color assigned to the epic for visual identification"

@rule(r"^Epic Link$", re.IGNORECASE)
def _(m):
    return "[Jira] Link to the parent epic this issue belongs to"

@rule(r"^(Sprint|Sprints)$", re.IGNORECASE)
def _(m):
    return "[Jira] Sprint(s) the issue is assigned to"

@rule(r"^Checklist (.+)$")
def _(m):
    return f"[Jira] Checklist {m.group(1).strip().lower()}"

@rule(r"^(Assignee|Approvers|Contributors|Reporter|Creator)$")
def _(m):
    return f"[Jira] {m.group(1)} of the issue"

@rule(r"^(Background|Design|Development|Escalation|Entitlement)$")
def _(m):
    return f"[Jira] {m.group(1)} field on the issue"

@rule(r"^(Aggregate .+)$")
def _(m):
    return f"[Jira] {m.group(1)} across all sub-tasks"

@rule(r"^Delivery progress$", re.IGNORECASE)
def _(m):
    return "[Jira] Progress percentage toward delivery completion"

@rule(r"^(Open|Closed|Total)\s+forms$", re.IGNORECASE)
def _(m):
    return f"[Jira] Number of {m.group(1).lower()} ProForma forms on the issue"

# ---- Advertising/Campaign fields ----
@rule(r"^Advertiser\s+(.+)$", re.IGNORECASE)
def _(m):
    return f"Advertiser {m.group(1).strip().lower()}"

@rule(r"^Buying Agency\s*-?\s*(.+)$", re.IGNORECASE)
def _(m):
    return f"Buying agency {m.group(1).strip().lower()}"

@rule(r"^Campaign\s+(.+)$", re.IGNORECASE)
def _(m):
    return f"Campaign {m.group(1).strip().lower()}"

@rule(r"^Ad\s+(.+)$", re.IGNORECASE)
def _(m):
    subject = m.group(1).strip()
    if subject.lower() in ("requests", "specs", "play length (seconds)"):
        return f"Ad {subject.lower()}"
    return None

# ---- Site/location descriptive fields ----
@rule(r"^(.+)\s*-\s*Uppercase$", re.IGNORECASE)
def _(m):
    return f"{m.group(1).strip()} converted to uppercase for matching"

@rule(r"^(City|Address|Street)\s+\d+$", re.IGNORECASE)
def _(m):
    return f"Alternate {m.group(1).strip().lower()} field"

# ---- Boolean / flag columns ----
@rule(r"^(.+)\?$")
def _(m):
    subject = m.group(1).strip()
    if len(subject) < 3:
        return None
    return f"Boolean flag indicating whether {subject.lower()}"

# ---- Screeen count columns ----
@rule(r"^(\d+)'?\s*\\n\s*Screen\s*\\n\s*Count$", re.IGNORECASE)
def _(m):
    return f"Count of {m.group(1)}-foot screens at the site"

# ---- Programmatic UPPER columns ----
@rule(r"^AUDIENCE_IMPRESSIONS$")
def _(m):
    return "Audience-based impression count for programmatic campaigns"

@rule(r"^AVAILABLEIMPS|AvailableImps$")
def _(m):
    return "Available programmatic impressions for the time period"

@rule(r"^AvailableSOV$")
def _(m):
    return "Available share of voice for programmatic allocation"

@rule(r"^BUYING_PLATFORM$")
def _(m):
    return "Programmatic buying platform (e.g., Vistar, PlaceExchange)"

@rule(r"^DURATION_S$")
def _(m):
    return "Duration in seconds"

@rule(r"^DAILY_TRANSACTIONS$")
def _(m):
    return "Daily transaction count"

@rule(r"^(BATCH_ID|CUSTOMER_BATCH_ID_)$")
def _(m):
    return "Batch processing identifier"

@rule(r"^CUSTOMER_BATCH_LAST_RUN_$")
def _(m):
    return "Timestamp of the last batch processing run"

@rule(r"^CUSTOM_AUDIENCE_EXTRA_COST$")
def _(m):
    return "Additional cost for custom audience targeting in programmatic campaigns"

@rule(r"^(PLAY_COUNT|Total_Plays|Total Plays)$")
def _(m):
    return "Total number of ad plays"

@rule(r"^(PLAYS_FULL_SCREEN|PLAYS_PARTIAL_SCREEN)$")
def _(m):
    mode = "full-screen" if "FULL" in m.group(1) else "partial-screen"
    return f"Number of ad plays displayed in {mode} mode"

@rule(r"^PLAYLISTS$")
def _(m):
    return "Playlist identifiers assigned to the screen"

@rule(r"^PLAYLISTUPDATETIME$")
def _(m):
    return "Timestamp when the playlist was last updated"

@rule(r"^DEPLOYREQUESTID$")
def _(m):
    return "Deployment request identifier"

@rule(r"^DEVICE$")
def _(m):
    return "Device identifier or type"

@rule(r"^(DOMO_INSTANCE)$")
def _(m):
    return "[DomoStats] Domo instance identifier"

@rule(r"^DAY_OF_WEEK$")
def _(m):
    return "Day of the week (e.g., Monday=1 through Sunday=7)"

@rule(r"^DOW_(NAME|NUM)$")
def _(m):
    if m.group(1) == "NAME":
        return "Day of the week name (e.g., Monday, Tuesday)"
    return "Day of the week number"

@rule(r"^DOVER_ID$")
def _(m):
    return "Dover/Wayne equipment identifier"

# ---- Owner fields in Salesforce context ----
@rule(r"^(?:New|Old)\s+Owner\s*-\s*(.+)$")
def _(m):
    return f"Ownership change tracking - {m.group(1).strip().lower()}"

@rule(r"^Owner\s*-\s*(Sales Division|Territory)$")
def _(m):
    return f"Account owner's {m.group(1).strip().lower()}"

@rule(r"^Owner ID\.(Sales Division|Territory)$")
def _(m):
    return f"Account owner's {m.group(1).strip().lower()} from the owner lookup"

# ---- Add Constants / Add Formula fields ----
@rule(r"^Add Constants?\.(.+)$")
def _(m):
    return f"Constant value column for {m.group(1).strip()}"

@rule(r"^Add Formula \d+\.(.+)$")
def _(m):
    return f"Calculated formula column for {m.group(1).strip()}"

# ---- Misc well-known fields ----
@rule(r"^Dwell Time$")
def _(m):
    return "Average time a consumer spends at the fuel dispenser"

@rule(r"^Action Required$")
def _(m):
    return "Description of the action required"

@rule(r"^Additional (?:Details|Info.*)$")
def _(m):
    return "Additional details or notes"

@rule(r"^Clawback$")
def _(m):
    return "Revenue clawback amount or flag"

@rule(r"^Classification$")
def _(m):
    return "Classification category"

@rule(r"^Capacity$")
def _(m):
    return "Capacity value (e.g., number of screens or ad slots)"

@rule(r"^Discount$")
def _(m):
    return "Discount amount or percentage applied"

@rule(r"^Credits$")
def _(m):
    return "Credit amount applied to the account or transaction"

@rule(r"^Difference$")
def _(m):
    return "Calculated difference between two values"

@rule(r"^Duplicate\??$")
def _(m):
    return "Flag indicating whether this record is a duplicate"

@rule(r"^Override$")
def _(m):
    return "Manual override value or flag"

@rule(r"^Tracking$")
def _(m):
    return "Tracking identifier or status"

@rule(r"^Organization$")
def _(m):
    return "Organization or company name"

@rule(r"^Distributor$")
def _(m):
    return "Fuel or equipment distributor name"

@rule(r"^Compass$")
def _(m):
    return "Compass directional indicator for the site"

@rule(r"^Date Updated$")
def _(m):
    return "Date when the record was last updated"

@rule(r"^Date\s*\(Week\)$")
def _(m):
    return "Date truncated to the start of the week"

@rule(r"^Date by month$|^DATE by month$")
def _(m):
    return "Date truncated to the first of the month"

@rule(r"^Date Number$")
def _(m):
    return "Numeric representation of the date"

@rule(r"^Day Of Year$")
def _(m):
    return "Day number within the year (1-366)"

@rule(r"^Day of (?:the )?Month$")
def _(m):
    return "Day number within the month (1-31)"

@rule(r"^End of Month$")
def _(m):
    return "Last day of the month for the given date"

@rule(r"^(Created On|CreatedOn)$")
def _(m):
    return "Date/time when the record was created"

@rule(r"^CreatedBy$")
def _(m):
    return "User who created the record"

@rule(r"^Date/Time Generated$")
def _(m):
    return "Timestamp when the report or data was generated"

@rule(r"^DateofReport$")
def _(m):
    return "Date the report was generated"

@rule(r"^(CVI|NVI)\s*\((.+)\)$")
def _(m):
    type_ = "Certified Validated Impression" if m.group(1) == "CVI" else "Network Validated Impression"
    return f"{type_} with criteria: {m.group(2).strip()}"


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def load_definitions():
    rows = []
    with open(DEFINITIONS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
    return rows, fieldnames


def infer_definition(col_name: str) -> str | None:
    """Try each rule in order; return first match or None."""
    for pattern, func in RULES:
        m = pattern.match(col_name) if not (pattern.flags & re.IGNORECASE and pattern.pattern.startswith("^")) else pattern.match(col_name)
        if not m:
            m = pattern.match(col_name)
        if m:
            result = func(m)
            if result:
                # Auto-capitalize first letter (after any prefix)
                if result[0] == "[":
                    # Has prefix like [Jira] — capitalize after the prefix
                    bracket_end = result.index("]") + 1
                    rest = result[bracket_end:].lstrip()
                    if rest and rest[0].islower():
                        rest = rest[0].upper() + rest[1:]
                    result = result[:bracket_end] + " " + rest
                elif result[0].islower():
                    result = result[0].upper() + result[1:]
                # Remove trailing period
                result = result.rstrip(".")
                return result
    return None


def main():
    rows, fieldnames = load_definitions()

    # Also load schema to know which datasets each column appears in
    with open(CACHE_PATH) as f:
        cache = json.load(f)
    schemas = cache.get("schemas", [])

    # Build column -> dataset mapping
    col_datasets = defaultdict(set)
    for s in schemas:
        col_datasets[s["column_name"]].add(s["dataset_name"])

    inferred_count = 0
    skipped = []
    updated_rows = []

    for row in rows:
        defn = row.get("definition", "").strip()
        if defn:
            updated_rows.append(row)
            continue

        col_name = row["column_name"]
        new_def = infer_definition(col_name)

        if new_def:
            row["definition"] = new_def
            row["status"] = "inferred"
            inferred_count += 1
        else:
            skipped.append(col_name)

        updated_rows.append(row)

    # Write back
    with open(DEFINITIONS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)

    print(f"Inferred {inferred_count} new definitions")
    print(f"Still undefined: {len(skipped)}")

    # Show sample of what couldn't be inferred
    if skipped:
        print(f"\nSample of remaining undefined ({min(50, len(skipped))} of {len(skipped)}):")
        for name in sorted(set(skipped))[:50]:
            ds_sample = sorted(col_datasets.get(name, set()))[:2]
            ds_str = f"  [{', '.join(ds_sample)}]" if ds_sample else ""
            print(f"  {name}{ds_str}")


if __name__ == "__main__":
    main()
