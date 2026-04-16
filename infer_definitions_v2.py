#!/usr/bin/env python3
"""Second-pass definition inference for remaining undefined columns.

Targets: OOH Frame/Format fields, ALL_CAPS system fields, compound
impression/revenue/transaction metrics, and remaining interpretable names.
"""

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFINITIONS_CSV = BASE_DIR / "column_definitions.csv"
CACHE_PATH = BASE_DIR / ".cache" / "latest.json"

RULES = []

def rule(pattern, flags=re.IGNORECASE):
    def decorator(func):
        RULES.append((re.compile(pattern, flags), func))
        return func
    return decorator


# =====================================================================
# OOH / Programmatic partner fields (Frame.*, Format.*, FrameLocation.*)
# =====================================================================

@rule(r"^Frame\.(ConstructionDate|ConstructionType|FaceCount|FacingDirection|HasAudio|Illumination|IsRotating|MotionType|OutOfChargeDate|SourceSystem|Type|MediaOwnerReference)$")
def _(m):
    labels = {
        "ConstructionDate": "construction date",
        "ConstructionType": "construction type (e.g., permanent, temporary)",
        "FaceCount": "number of faces on the display unit",
        "FacingDirection": "compass direction the display faces",
        "HasAudio": "whether the frame supports audio playback",
        "Illumination": "illumination type (e.g., backlit, ambient, none)",
        "IsRotating": "whether the display is a rotating/scrolling unit",
        "MotionType": "motion capability (e.g., static, video, full motion)",
        "OutOfChargeDate": "date the frame goes out of service",
        "SourceSystem": "source system that provided the frame data",
        "Type": "frame type classification",
        "MediaOwnerReference": "media owner's reference ID for the frame",
    }
    return f"[Programmatic] OOH frame {labels.get(m.group(1), m.group(1).lower())}"

@rule(r"^FrameDimension\.(Height|Width|Orientation|PixelHeight|PixelWidth|SurfaceArea|Unit)$")
def _(m):
    labels = {
        "Height": "physical height", "Width": "physical width",
        "Orientation": "orientation (landscape or portrait)",
        "PixelHeight": "pixel height resolution", "PixelWidth": "pixel width resolution",
        "SurfaceArea": "total surface area", "Unit": "unit of measurement for dimensions",
    }
    return f"[Programmatic] OOH frame {labels.get(m.group(1), m.group(1).lower())}"

@rule(r"^FrameLocation\.(AdministrativeRegion\d|CountryCode|Latitude|Longitude|Location|PanelName|PostalCode|TVRegion)$")
def _(m):
    labels = {
        "AdministrativeRegion1": "state/province",
        "AdministrativeRegion2": "county/district",
        "AdministrativeRegion3": "city/municipality",
        "CountryCode": "ISO country code",
        "Latitude": "latitude coordinate",
        "Longitude": "longitude coordinate",
        "Location": "location description",
        "PanelName": "panel display name",
        "PostalCode": "postal/ZIP code",
        "TVRegion": "television market region",
    }
    return f"[Programmatic] OOH frame location {labels.get(m.group(1), m.group(1).lower())}"

@rule(r"^FrameMetaData\.(.+)$")
def _(m):
    return f"[Programmatic] OOH frame metadata - {m.group(1).replace('_', ' ').lower()}"

@rule(r"^Format\.(Description|Id|Name|SourceSystem|Type)$")
def _(m):
    return f"[Programmatic] OOH ad format {m.group(1).lower()}"

@rule(r"^FormatGroup\.(Description|Id|Name|SourceSystem)$")
def _(m):
    return f"[Programmatic] OOH format group {m.group(1).lower()}"

# =====================================================================
# Traffic Instructions / RPA ALL_CAPS fields
# =====================================================================

@rule(r"^ADJACENCY_POSITION$")
def _(m):
    return "Position of the ad relative to adjacent content in the traffic instruction"

@rule(r"^ADJACENT_LINE_ITEM_ID$")
def _(m):
    return "Identifier of the adjacent line item in the traffic instruction"

@rule(r"^ADVERTISING_CATGORY$")
def _(m):
    return "Advertising category classification (note: field name has typo for 'category')"

@rule(r"^ASSET_ROTATION$")
def _(m):
    return "Rotation sequence assignment for the creative asset"

@rule(r"^CONTRACT_NUMBER$")
def _(m):
    return "Contract number associated with the insertion order or agreement"

@rule(r"^LINE_ITEMS_NAME$")
def _(m):
    return "Name of the campaign line item"

@rule(r"^LEASED_ADS_COUNT$")
def _(m):
    return "Number of programmatic ad spots leased for the time period"

@rule(r"^REVENUE_SOURCE$")
def _(m):
    return "Source category of the revenue (e.g., direct, programmatic, exchange)"

# =====================================================================
# ICS / Gilbarco system fields
# =====================================================================

@rule(r"^ADDITIONAL_INFORMATION$")
def _(m):
    return "Supplementary information from the ICS notification or system event"

@rule(r"^AVG_SCREENS$")
def _(m):
    return "Average number of screens reporting at the site"

@rule(r"^MAX_SCREENS$")
def _(m):
    return "Maximum number of screens observed at the site"

@rule(r"^MIN_SCREENS$")
def _(m):
    return "Minimum number of screens observed at the site"

@rule(r"^INSERT_TIME$")
def _(m):
    return "Timestamp when the record was inserted into the database"

@rule(r"^INSERT_TIME_GILBARCO_ICS_NOTIFICATIONS$")
def _(m):
    return "Timestamp when the Gilbarco ICS notification was inserted"

@rule(r"^ID_REF_IN_PLAYLIST_UPDATES$")
def _(m):
    return "Reference ID linking to the playlist update record"

@rule(r"^FILE_LAST_MODIFIED$")
def _(m):
    return "Timestamp when the source file was last modified"

@rule(r"^METADATA_FILENAME$")
def _(m):
    return "Filename from the source data metadata"

@rule(r"^METADATA_NOTES$")
def _(m):
    return "Notes from the source data metadata"

# =====================================================================
# Location / Site fields
# =====================================================================

@rule(r"^LOCATION_NO$")
def _(m):
    return "Location number identifier"

@rule(r"^LOCATION_TELEPHONE_NO$")
def _(m):
    return "Telephone number for the location"

@rule(r"^LOCATION_ZIP_CODE$")
def _(m):
    return "ZIP code for the location"

@rule(r"^CITY_NAME$")
def _(m):
    return "Name of the city"

@rule(r"^CSTORE_BRAND$")
def _(m):
    return "Convenience store brand name associated with the site"

@rule(r"^LANE_LABEL$")
def _(m):
    return "Label identifying the fuel dispenser lane"

@rule(r"^LANE_ORDER$")
def _(m):
    return "Sort order of the dispenser lane at the site"

# =====================================================================
# Database schema metadata (ALL_CAPS identity/interval fields)
# =====================================================================

@rule(r"^(IDENTITY_CYCLE|IDENTITY_GENERATION|IDENTITY_INCREMENT|IDENTITY_MAXIMUM|IDENTITY_MINIMUM|IDENTITY_ORDERED|IDENTITY_START|IS_IDENTITY|IS_NULLABLE|IS_SELF_REFERENCING|INTERVAL_PRECISION|INTERVAL_TYPE|MAXIMUM_CARDINALITY|NUMERIC_PRECISION|NUMERIC_PRECISION_RADIX|NUMERIC_SCALE|SCOPE_CATALOG|SCOPE_NAME|SCOPE_SCHEMA|TABLE_CATALOG|TABLE_NAME|TABLE_SCHEMA|UDT_CATALOG|UDT_NAME|UDT_SCHEMA)$")
def _(m):
    labels = {
        "IDENTITY_CYCLE": "Whether the identity column cycles when max is reached",
        "IDENTITY_GENERATION": "How identity values are generated (ALWAYS or BY DEFAULT)",
        "IDENTITY_INCREMENT": "Increment value for the identity column",
        "IDENTITY_MAXIMUM": "Maximum value for the identity column",
        "IDENTITY_MINIMUM": "Minimum value for the identity column",
        "IDENTITY_ORDERED": "Whether identity values are guaranteed to be ordered",
        "IDENTITY_START": "Starting value for the identity column",
        "IS_IDENTITY": "Whether the column is an identity column",
        "IS_NULLABLE": "Whether the column allows NULL values",
        "IS_SELF_REFERENCING": "Whether the column is self-referencing",
        "INTERVAL_PRECISION": "Precision of the interval data type",
        "INTERVAL_TYPE": "Type of interval (e.g., DAY TO SECOND)",
        "MAXIMUM_CARDINALITY": "Maximum cardinality for array types",
        "NUMERIC_PRECISION": "Numeric precision (total number of digits)",
        "NUMERIC_PRECISION_RADIX": "Radix (base) of the numeric precision",
        "NUMERIC_SCALE": "Number of digits to the right of the decimal point",
        "SCOPE_CATALOG": "Catalog of the referenced scope",
        "SCOPE_NAME": "Name of the referenced scope",
        "SCOPE_SCHEMA": "Schema of the referenced scope",
        "TABLE_CATALOG": "Catalog containing the table",
        "TABLE_NAME": "Name of the table the column belongs to",
        "TABLE_SCHEMA": "Schema containing the table",
        "UDT_CATALOG": "Catalog of the user-defined type",
        "UDT_NAME": "Name of the user-defined type",
        "UDT_SCHEMA": "Schema of the user-defined type",
    }
    return f"[Schema metadata] {labels.get(m.group(1), m.group(1))}"

# =====================================================================
# Schedule / MTH fields
# =====================================================================

@rule(r"^MTH_(END_TIME|SCHEDULE_DATE|WANTED)$")
def _(m):
    labels = {
        "END_TIME": "End time for the monthly schedule period",
        "SCHEDULE_DATE": "Scheduled date for the monthly period",
        "WANTED": "Requested/desired value for the monthly schedule",
    }
    return labels.get(m.group(1), f"Monthly schedule {m.group(1).lower()}")

@rule(r"^HOUR_OF_WEEK$")
def _(m):
    return "Hour number within the week (0-167)"

@rule(r"^DISTINCT_DAYS$")
def _(m):
    return "Count of distinct days in the time period"

# =====================================================================
# Impression metrics
# =====================================================================

@rule(r"^Daily (?:Average )?Impressions?\s*(?:-\s*(.+))?$", re.IGNORECASE)
def _(m):
    qualifier = f" ({m.group(1).strip()})" if m.group(1) else ""
    return f"Average daily impression count{qualifier}"

@rule(r"^Daily NVIs$")
def _(m):
    return "Daily Network Validated Impression (NVI) count"

@rule(r"^(.+?)\s+Contributed?\s+Impressions$")
def _(m):
    return f"Impression count contributed by {m.group(1).strip()}"

@rule(r"^(.+?)\s+Contribution\s+Ratio$")
def _(m):
    return f"Ratio of impressions contributed by {m.group(1).strip()} to total impressions"

@rule(r"^(.+?)\s+Site\s+Ratio$")
def _(m):
    return f"Site count ratio for {m.group(1).strip()} relative to total"

@rule(r"^Impression\s+(.+)$", re.IGNORECASE)
def _(m):
    return f"Impression {m.group(1).strip().lower()}"

@rule(r"^Flexible\s+(Impressions|Revenue|Spots)$")
def _(m):
    return f"Programmatic flexible (non-deal, non-exchange) {m.group(1).strip().lower()}"

@rule(r"^Geopath Weekly 18\+ Impressions$")
def _(m):
    return "Geopath-certified weekly impressions for adults 18+"

@rule(r"^Hours Reporting NVIs$")
def _(m):
    return "Number of hours with reported Network Validated Impressions"

@rule(r"^Circulation \(Daily Impressions\)$")
def _(m):
    return "Daily circulation count expressed as impression equivalents"

@rule(r"^Average (?:Daily |Monthly )?Impressions$")
def _(m):
    return "Average impression count for the time period"

@rule(r"^First NVI(?:\s+as\s+(.+))?$")
def _(m):
    suffix = f" as {m.group(1).strip()}" if m.group(1) else ""
    return f"Date of the first Network Validated Impression{suffix}"

@rule(r"^(.+?)\s+NVIs?$")
def _(m):
    prefix = m.group(1).strip()
    if prefix.lower() in ("daily", "monthly", "weekly", "february -", "average daily"):
        return f"{prefix} Network Validated Impression count"
    return None

@rule(r"^Impression Source\s*-\s*(.+)$")
def _(m):
    return f"Primary source methodology for impressions ({m.group(1).strip()})"

# =====================================================================
# Revenue metrics
# =====================================================================

@rule(r"^(.+?)\s+Revenue(?:\s+Share)?\s+Payment$")
def _(m):
    return f"Revenue share payment amount for {m.group(1).strip()}"

@rule(r"^(.+?)\s+Revenue$")
def _(m):
    source = m.group(1).strip()
    if source.lower() in ("direct", "flexible", "exchange", "deal"):
        return f"Programmatic {source.lower()} revenue"
    return f"Revenue from {source}"

@rule(r"^Revenue\s*-\s*(.+?)(?:_(Q\d|max|min|avg))?$")
def _(m):
    channel = m.group(1).strip()
    suffix = f" ({m.group(2)})" if m.group(2) else ""
    return f"Revenue from {channel.lower()}{suffix}"

@rule(r"^Raw (.+)$")
def _(m):
    return f"Unprocessed/raw {m.group(1).strip().lower()}"

@rule(r"^Previously Reported (.+)$")
def _(m):
    return f"Previously reported {m.group(1).strip().lower()} (prior period value)"

@rule(r"^Rev Share Grouping$")
def _(m):
    return "Grouping category for revenue share calculations"

@rule(r"^OWNER_(EXCHANGE_FEE|INTERNATIONAL_FEE|NET_REVENUE)$")
def _(m):
    labels = {
        "EXCHANGE_FEE": "Exchange fee charged to the media owner",
        "INTERNATIONAL_FEE": "International transaction fee charged to the media owner",
        "NET_REVENUE": "Net revenue after fees for the media owner",
    }
    return f"[Programmatic] {labels.get(m.group(1), m.group(1))}"

@rule(r"^MEASUREMENT_EXTRA_COST$")
def _(m):
    return "[Programmatic] Additional cost for measurement/verification services"

@rule(r"^CUSTOM_AUDIENCE_EXTRA_COST$")
def _(m):
    return "[Programmatic] Additional cost for custom audience targeting"

# =====================================================================
# Site / Status fields
# =====================================================================

@rule(r"^(Awaiting Installation|Awaiting Reactivation|Deactivated|Active|Cancelled|Contract Signed)\s+Sites$")
def _(m):
    return f"Count of sites in '{m.group(1)}' status"

@rule(r"^Activated Year$")
def _(m):
    return "Year the site was activated"

@rule(r"^Active (?:Days|Months|Locations)(?:\s+in\s+(.+))?$", re.IGNORECASE)
def _(m):
    suffix = f" during {m.group(1).strip()}" if m.group(1) else ""
    return f"Number of active days/months/locations{suffix}"

@rule(r"^Active Purchased Impressions$")
def _(m):
    return "Purchased impressions for currently active campaigns"

@rule(r"^Total Active (.+)$")
def _(m):
    return f"Total count of active {m.group(1).strip().lower()}"

@rule(r"^DXP\s+(.+)$")
def _(m):
    return f"Dover DXPromote {m.group(1).strip().lower()}"

@rule(r"^ATV Screens Playing$")
def _(m):
    return "Number of ATV (at-the-venue) screens currently playing content"

@rule(r"^(Operational|Out of Service|Total)\s+Screens$")
def _(m):
    return f"Count of {m.group(1).lower()} screens at the site"

@rule(r"^Number Screens (.+)$")
def _(m):
    return f"Number of screens {m.group(1).strip().lower()}"

@rule(r"^Total Screens (.+)$")
def _(m):
    return f"Total screens {m.group(1).strip().lower()}"

@rule(r"^Device With POP$")
def _(m):
    return "Whether the device has reported Proof of Play"

@rule(r"^Ever Reported POP.*$")
def _(m):
    return "Whether the site has ever reported Proof of Play data"

@rule(r"^Date POP Last Reported$")
def _(m):
    return "Most recent date Proof of Play was reported for this site"

@rule(r"^Days Reporting PoP$")
def _(m):
    return "Number of days with Proof of Play data reported"

@rule(r"^Days of POP.+$")
def _(m):
    return "Number of days with Proof of Play data in the specified period"

@rule(r"^Days Reporting NVI$")
def _(m):
    return "Number of days with Network Validated Impression data reported"

@rule(r"^Days Reporting Transactions$")
def _(m):
    return "Number of days with transaction data reported"

@rule(r"^Days Not Reporting Transactions$")
def _(m):
    return "Number of days without transaction data"

@rule(r"^Days of Transactions.+$")
def _(m):
    return "Number of days with transaction data in the specified period"

@rule(r"^Days of NVI.+$")
def _(m):
    return "Number of days with NVI data in the specified period"

@rule(r"^Days With Programmatic$")
def _(m):
    return "Number of days with programmatic ad activity"

@rule(r"^Days Online \(%\)$")
def _(m):
    return "Percentage of days the site was online"

@rule(r"^DaysOffline$")
def _(m):
    return "Count of days the site was offline"

# =====================================================================
# Programmatic operations
# =====================================================================

@rule(r"^Available\s+(Supply|Space|Time)\s*(?:-\s*(.+))?$")
def _(m):
    qualifier = f" ({m.group(2).strip()})" if m.group(2) else ""
    return f"Available programmatic {m.group(1).strip().lower()}{qualifier}"

@rule(r"^Default (Share Of Voice|Spot Duration)$")
def _(m):
    return f"Default {m.group(1).strip().lower()} configured for the venue"

@rule(r"^(Deal|Exchange|Flexible)\s+(Spots|Impressions|Revenue)_(\d+)(d|wk)_avg$")
def _(m):
    unit = "day" if m.group(4) == "d" else "week"
    return f"Programmatic {m.group(1).lower()} {m.group(2).lower()} ({m.group(3)}-{unit} rolling average)"

# =====================================================================
# FP6 / Device fields
# =====================================================================

@rule(r"^FP6-Device-Detail.*\.(.+)$")
def _(m):
    return f"FlexPay 6 device detail - {m.group(1).replace('_', ' ')}"

# =====================================================================
# Jira / ITSM additional fields
# =====================================================================

@rule(r"^Acceptance Criteria$")
def _(m):
    return "[Jira] Conditions that must be met for the story/issue to be considered complete"

@rule(r"^Accessibility needs$")
def _(m):
    return "[Jira] Accessibility requirements for the issue"

@rule(r"^(Affected hardware|Affected services|Other hardware)$")
def _(m):
    return f"[Jira] {m.group(1)} impacted by the incident or change request"

@rule(r"^(Change reason|Change risk|Change type|Change managers|Cancellation Policy).*$")
def _(m):
    return f"[Jira] {m.group(0).split('_')[0]} for the change request"

@rule(r"^(Backout plan|Business Impact|Business Value)$")
def _(m):
    return f"[Jira] {m.group(1)} documentation for the change request"

@rule(r"^(Operational categorization|Operational categorization_.+)$")
def _(m):
    if "_" in m.group(1):
        suffix = m.group(1).split("_", 1)[1]
        return f"[Jira] Operational categorization {suffix}"
    return "[Jira] Operational categorization of the service request"

@rule(r"^(Atlas project key|Atlassian project)$")
def _(m):
    return f"[Jira] {m.group(1)} identifier"

@rule(r"^Definition of Done.*$")
def _(m):
    return "[Jira] Definition of Done criteria or metadata"

@rule(r"^(Epic Status|Benefits Owner Assigned and Benefits Agreed).*$")
def _(m):
    base = m.group(1)
    full = m.group(0)
    if "_" in full:
        suffix = full.rsplit("_", 1)[1]
        return f"[Jira] {base} field {suffix}"
    return f"[Jira] {base} field"

# =====================================================================
# Salesforce / CRM additional fields
# =====================================================================

@rule(r"^Account Owner$")
def _(m):
    return "[SF] Name of the Salesforce account owner"

@rule(r"^Opp (?:Stage|Lost Description|Lost Reason|#).*$")
def _(m):
    return f"[SF: Opportunity] {m.group(0)}"

@rule(r"^OpportunityId$")
def _(m):
    return "[SF: Opportunity] Salesforce Opportunity record ID"

@rule(r"^CampaignName$")
def _(m):
    return "Name of the advertising campaign"

@rule(r"^Campaigns$")
def _(m):
    return "Campaign names or count associated with the record"

@rule(r"^ClientName$")
def _(m):
    return "Name of the client or advertiser"

@rule(r"^CustomerSegment$")
def _(m):
    return "Customer segmentation classification"

@rule(r"^CustomerState$")
def _(m):
    return "State/province of the customer"

# =====================================================================
# Misc interpretable fields
# =====================================================================

@rule(r"^(.+)\s+\(formatted\)$")
def _(m):
    return f"{m.group(1).strip()} with display formatting applied"

@rule(r"^Concat Site\s*\+\s*(.+)$")
def _(m):
    return f"Concatenated key of site ID and {m.group(1).strip().lower()}"

@rule(r"^(Dispenser|Equipment)\s+(Count|Fee|Types?).*$")
def _(m):
    return f"{m.group(1)} {m.group(2).lower()} at the site"

@rule(r"^(Content|Creative)\s+(Height|Width|Partner|Restritions|Attributes|Management System.*).*$")
def _(m):
    val = m.group(0).strip()
    return f"Ad creative or content {val.lower()}"

@rule(r"^(Aspect Ratio|Animation|Audio.*|Digital\?)$")
def _(m):
    return f"Media specification: {m.group(0).strip().lower()}"

@rule(r"^Contract\s+(.+)$")
def _(m):
    return f"Contract {m.group(1).strip().lower()}"

@rule(r"^Current\s+(.+)$")
def _(m):
    val = m.group(1).strip()
    if val in ("Fuel Brand", "GTV#", "MP?", "Network", "Store Brand"):
        return f"Current {val.lower()} for the site"
    return None

@rule(r"^Brand\s*-?\s*(C-Store|Fuel|Credit Card)\s*(.*)$")
def _(m):
    qualifier = f" {m.group(2).strip()}" if m.group(2).strip() else ""
    return f"{m.group(1)} brand{qualifier} associated with the site"

@rule(r"^Branded Cstore$")
def _(m):
    return "Whether the site has a branded convenience store"

@rule(r"^Ad Play Length \(seconds\)$")
def _(m):
    return "Duration of the ad play in seconds"

@rule(r"^Ad Requests$")
def _(m):
    return "Number of programmatic ad requests sent"

@rule(r"^Ad Specs$")
def _(m):
    return "Creative specifications for the ad placement"

@rule(r"^Acutal Avg Daily Spend$")
def _(m):
    return "Actual average daily spend (note: field name has typo for 'actual')"

@rule(r"^Avg Imp (.+)$")
def _(m):
    return f"Average impressions - {m.group(1).strip()}"

@rule(r"^Category\.(.+)$")
def _(m):
    return f"Category {m.group(1).strip().lower()} from the category lookup"

@rule(r"^Filter Rows\.(.+)$")
def _(m):
    return f"Filter criteria value for {m.group(1).strip()}"

@rule(r"^Coupon File$")
def _(m):
    return "Coupon file name or reference"

@rule(r"^Cross Street Description$")
def _(m):
    return "Description of the cross street or intersection near the site"

@rule(r"^(Abbr|BU|CAB|CSA|OID|DBA)$")
def _(m):
    labels = {
        "Abbr": "Abbreviation (e.g., state abbreviation)",
        "BU": "Business unit identifier",
        "CAB": "Cable/CBSA area classification",
        "CSA": "Combined Statistical Area code",
        "OID": "Object identifier",
        "DBA": "Doing Business As name",
    }
    return labels.get(m.group(1), m.group(1))

@rule(r"^CSA_Name$")
def _(m):
    return "Combined Statistical Area name"

@rule(r"^BLKGRPCE$")
def _(m):
    return "Census block group code"

@rule(r"^COUNTYFP$")
def _(m):
    return "County FIPS code"

@rule(r"^(TotEmp|TotPop|CountHU)$")
def _(m):
    labels = {"TotEmp": "Total employment count", "TotPop": "Total population count", "CountHU": "Count of housing units"}
    return labels.get(m.group(1), m.group(1))

@rule(r"^Ac_(Land|Total|Unpr|Water)$")
def _(m):
    labels = {"Land": "Land area in acres", "Total": "Total area in acres", "Unpr": "Unprotected area in acres", "Water": "Water area in acres"}
    return f"[Census] {labels.get(m.group(1), m.group(1))}"

@rule(r"^Only Include Hardware Type Column\.(Network|Program)$")
def _(m):
    return f"Hardware type filter column for {m.group(1).lower()}"

@rule(r"^(Evergreen|Non Evergreen)\s+Plays$")
def _(m):
    return f"{m.group(1)} content play count"

@rule(r"^(PIPPlays|PLAY_COUNT)$")
def _(m):
    return "Total play count"

@rule(r"^(DailyCount|DailyTransactions|Number of Transactions|Transaction Entries)$")
def _(m):
    return "Daily transaction count"

@rule(r"^Transaction Source$")
def _(m):
    return "Source system or method that recorded the transaction"

@rule(r"^Transactions\s*-\s*(.+)$")
def _(m):
    val = m.group(1).strip()
    if val.startswith("ID"):
        return f"Transaction record ID ({val})"
    return f"Transaction count for {val}"

@rule(r"^Transactions Per Site$")
def _(m):
    return "Average transaction count per site"

@rule(r"^Transactions Difference$")
def _(m):
    return "Difference in transaction counts between two periods"

@rule(r"^Transacted \(str\)$")
def _(m):
    return "Whether the site had transactions (string/boolean representation)"

@rule(r"^Transactions\*$")
def _(m):
    return "Adjusted or modified transaction count"

@rule(r"^(\*)\s*(Network|Transactions)$")
def _(m):
    return f"Adjusted/modified {m.group(2).lower()} value"

@rule(r"^Total Hourly Transactions$")
def _(m):
    return "Total transaction count for the hour"

@rule(r"^Comp Daily Transactions$")
def _(m):
    return "Daily transaction count for the comparison (prior) period"

@rule(r"^(?:AVG|Avg)\s+Daily Transactions$", re.IGNORECASE)
def _(m):
    return "Average daily transaction count"

@rule(r"^(.+?)\s+Store Number$")
def _(m):
    return f"{m.group(1).strip()} retailer store number"

@rule(r"^Data (Availability|Partner|Validated\?)$")
def _(m):
    labels = {"Availability": "Data availability status or date", "Partner": "Data partner providing the information", "Validated?": "Whether the data has been validated"}
    return labels.get(m.group(1), f"Data {m.group(1).lower()}")

@rule(r"^Dataset (Link|Owner)$")
def _(m):
    return f"[DomoStats] {m.group(0)}"

@rule(r"^Download Email$")
def _(m):
    return "Email address for download notifications"

@rule(r"^(Call Duration|Call Object Identifier|Call Result)$")
def _(m):
    return f"[SF] Salesforce activity {m.group(1).lower()}"

@rule(r"^(Employee location|Office .+)$")
def _(m):
    return f"Employee or office {m.group(0).strip().lower()}"

@rule(r"^(.+?)\s+(\d{4})\s*$")
def _(m):
    metric = m.group(1).strip()
    year = m.group(2)
    # Only match if the metric part is meaningful
    if len(metric) > 3 and not metric[0].isdigit():
        return f"{metric} for the year {year}"
    return None

@rule(r"^Domo Campaign Delivery Process\s*-\s*(.+)$")
def _(m):
    return f"Domo campaign delivery process {m.group(1).strip().lower()}"

@rule(r"^(Dollars|Operating Fee|Equipment Fee|Total Fee|Total Equipment Fee|Total Operating Fee)\s*$")
def _(m):
    return f"{m.group(1).strip()} amount"

@rule(r"^(Normal|Custom)$")
def _(m):
    return f"Boolean flag or category indicator for {m.group(1).lower()}"

# =====================================================================
# Catch-all for readable compound names
# =====================================================================

@rule(r"^(Affiliate Inventory)$")
def _(m):
    return "Affiliate partner inventory count or flag"

@rule(r"^Alarm History Summary$")
def _(m):
    return "Summary of alarm history events for the site or device"

@rule(r"^Alert Key$")
def _(m):
    return "Unique key identifying the alert or monitoring event"

@rule(r"^(Allowed Language|Accepted FileTypes|Accepted Material)$")
def _(m):
    return f"{m.group(1)} for the partner or placement"

@rule(r"^(Allows Extensions\?|Create Recurring Series of Tasks)$")
def _(m):
    return f"Configuration flag: {m.group(0).lower()}"

@rule(r"^(Changed Field|New Value|Old Value)$")
def _(m):
    return f"Field change audit - {m.group(1).lower()}"

@rule(r"^Any Brand Change$")
def _(m):
    return "Whether the site experienced any brand change"

@rule(r"^(After Activation|After ICS Activation)$")
def _(m):
    return f"Status or metric measured {m.group(1).lower()}"

@rule(r"^Agent (Launched|Product)$")
def _(m):
    return f"Field service agent {m.group(1).lower()}"

@rule(r"^(Bad|OK)\s+Terminal Hours$")
def _(m):
    return f"Hours the terminal was in {m.group(1).lower()} status"

@rule(r"^Total Terminal Hours$")
def _(m):
    return "Total hours the terminal was monitored"

@rule(r"^CK\s+(.+)$")
def _(m):
    return f"Circle K {m.group(1).strip().lower()}"

@rule(r"^Chevron Texaco$")
def _(m):
    return "Chevron Texaco branded site flag"

@rule(r"^Olipop$")
def _(m):
    return "Olipop brand campaign or targeting flag"

@rule(r"^Omnia$")
def _(m):
    return "Omnia device or platform identifier"

@rule(r"^Oracle Site #$")
def _(m):
    return "Oracle system site number"

@rule(r"^Outreach Retailer$")
def _(m):
    return "Retailer targeted for outreach communications"

@rule(r"^Cassandra Network$")
def _(m):
    return "Network classification from the Cassandra data source"

@rule(r"^(Business Usage|Ask Type|Conference Room|Confirmed\?|Data Type|DFS Category|DFS Conversion Responsibility\?|Deal Type/ Priority|Opp Stage).*$")
def _(m):
    base = m.group(1).strip()
    full = m.group(0).strip()
    if full.endswith(("_id", "_self", "_value")):
        suffix = full.rsplit("_", 1)[1]
        return f"[Jira/SF] {base} field {suffix} property"
    return f"{base} classification or category"

@rule(r"^(Dispatching status for .+)$")
def _(m):
    return f"Dispatch workflow status: {m.group(1)}"

@rule(r"^Display (Failure|Failures|Success)$")
def _(m):
    return f"Count of display {m.group(1).lower()} events"

@rule(r"^Duration Delta$")
def _(m):
    return "Difference between actual and expected play duration"

@rule(r"^(Enterprise to DXP Conversion)$")
def _(m):
    return "Whether the site converted from Enterprise to DXP platform"

@rule(r"^EventYear$")
def _(m):
    return "Year the event occurred"

@rule(r"^Events_ThreeDays$")
def _(m):
    return "Count of events in the last three days"

@rule(r"^(Distinct Network|Count .+|Approximate Count .+)$")
def _(m):
    return f"{m.group(0).strip()}"

@rule(r"^(Bucketing|Characteristic|Connection|Design reference|Environment|Outage Granularly|OrderPriority)$")
def _(m):
    return f"{m.group(1)} classification or value"

@rule(r"^(Ad Wall # of Screens|Canada Digital Walls|33 Degree Menu Boards|Car Wash Screen)$")
def _(m):
    return f"Site hardware configuration: {m.group(1).lower()}"

@rule(r"^(Only Playing 1 File)$")
def _(m):
    return "Flag indicating the device is only playing a single content file"

@rule(r"^(AdOps|Ad Ops)\s*-\s*(.+)$")
def _(m):
    return f"Ad Operations flag: {m.group(2).strip()}"

@rule(r"^(Added Value)\s*-\s*(Flight|Site)$")
def _(m):
    return f"Added value impressions or bonus at the {m.group(2).lower()} level"

@rule(r"^(Black Buffalo|Olipop)\s+(INCLUDE|EXCLUDE)$")
def _(m):
    return f"Whether to {m.group(2).lower()} the site for {m.group(1)} campaign targeting"

@rule(r"^(Advertiser|Campaign|Buying Agency)\s+Change$")
def _(m):
    return f"Whether the {m.group(1).lower()} changed from the prior period"

@rule(r"^(Advertiser Category|Advertising Category|Category Mapping|Category ID 18)$")
def _(m):
    return "Advertising category classification for the campaign"

@rule(r"^(All-Day Logic Alert|All_Day_Blocker)$")
def _(m):
    return "Flag for all-day scheduling logic or blocking condition"

@rule(r"^(Normalized Clock Issues)$")
def _(m):
    return "Count or flag for normalized clock synchronization issues"

@rule(r"^(Availability-Group)$")
def _(m):
    return "Availability grouping classification for the venue"

@rule(r"^(Buying Agent|Buying Agency)$")
def _(m):
    return f"Name of the {m.group(1).lower()}"

@rule(r"^(Concatenated_Info)$")
def _(m):
    return "Concatenated information field combining multiple attributes"

@rule(r"^(Checklist Content YAML|Checklist Template|Checklist Progress|Checklist Completed)$")
def _(m):
    return f"[Jira] {m.group(1)}"

# =====================================================================
# Main logic
# =====================================================================

def load_definitions():
    rows = []
    with open(DEFINITIONS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
    return rows, fieldnames


def infer(col_name):
    for pattern, func in RULES:
        m = pattern.match(col_name)
        if m:
            result = func(m)
            if result:
                # Capitalize and strip trailing period
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
    rows, fieldnames = load_definitions()
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

    print(f"Second pass: inferred {count} additional definitions")
    print(f"Still undefined: {still_undefined}")

    # Stats
    defined = sum(1 for r in rows if r.get("definition", "").strip())
    total = len(rows)
    print(f"Overall: {defined}/{total} defined ({defined/total*100:.1f}%)")


if __name__ == "__main__":
    main()
