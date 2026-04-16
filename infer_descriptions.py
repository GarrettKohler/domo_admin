#!/usr/bin/env python3
"""
infer_descriptions.py — Infer descriptions for datasets and dataflows
that don't have one, based on naming patterns, domain classification,
schema content, and lineage context.

Outputs: dataset_descriptions.csv, dataflow_descriptions.csv
"""

import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone

import analytics

CACHE_FILE = ".cache/latest.json"
DS_OUTPUT = "dataset_descriptions.csv"
DF_OUTPUT = "dataflow_descriptions.csv"


# ── Pattern-based description rules for datasets ───────────────────────────
# (name_regex, description_template)
# Templates can use {name} for the cleaned dataset name
DS_RULES = [
    # Programmatic revenue
    (r'(?i)programmatic.*revenue.*full\s*granularity.*live',
     'Live programmatic advertising revenue at full granularity (site/day/SSP level), refreshed continuously'),
    (r'(?i)programmatic.*revenue.*full\s*granularity',
     'Programmatic advertising revenue at full granularity (site/day/SSP level)'),
    (r'(?i)programmatic.*(?:ssp|exchange)\s*revenue.*daily.*(?:site|venue)',
     'Daily programmatic exchange revenue broken down by site/venue'),
    (r'(?i)programmatic.*(?:ssp|exchange)\s*revenue',
     'Programmatic exchange revenue from SSP partners'),
    (r'(?i)(?:vistar|px).*(?:ssp|exchange)\s*revenue.*full\s*granularity',
     'Vistar SSP exchange revenue at full granularity'),
    (r'(?i)vistar.*flexible\s*revenue.*full\s*granularity',
     'Vistar flexible (managed) revenue at full granularity'),
    (r'(?i)vistar.*revenue',
     'Revenue data from Vistar programmatic advertising platform'),
    (r'(?i)(?:ytd|year.to.date).*(?:px|exchange)\s*revenue',
     'Year-to-date programmatic exchange revenue'),

    # Revenue general
    (r'(?i)revenue.*allocation',
     'Revenue allocation data mapping campaign revenue to time periods and dimensions'),
    (r'(?i)sell\s*through\s*calculation',
     'Sell-through waterfall calculations combining scheduling, revenue, and avails data'),

    # Campaign validated impressions
    (r'(?i)campaign\s*validated\s*impressions.*base\s*data',
     'Base dataset for campaign-level validated impression counts, used for billing and reporting'),
    (r'(?i)campaign\s*validated\s*impressions.*fy\d+\s*and\s*beyond',
     'Campaign validated impressions for the current and future fiscal years'),
    (r'(?i)campaign\s*validated\s*impressions.*historic',
     'Historical campaign validated impressions (archived fiscal years)'),
    (r'(?i)campaign\s*validated\s*impressions',
     'Campaign-level validated impression counts for ad delivery verification'),

    # Network validated impressions (NVI)
    (r'(?i)network\s*validated\s*impressions.*base\s*data.*fiscal',
     'Base dataset for network-level validated impressions with fiscal calendar mapping'),
    (r'(?i)network\s*validated\s*impressions.*base\s*data',
     'Base dataset for network-level validated impression counts'),
    (r'(?i)network\s*validated\s*impressions',
     'Network-level validated impression (NVI) counts for audience measurement'),

    # Transactions
    (r'(?i)unvalidated\s*transactions.*hourly.*(?:assembler|filterable)',
     'Hourly unvalidated transaction data, structured for filtering and analysis'),
    (r'(?i)unvalidated\s*transactions.*daily.*(?:gbase|upload)',
     'Daily unvalidated transaction data uploaded from GBase'),
    (r'(?i)unvalidated\s*transactions',
     'Raw unvalidated fuel transaction data before QA processing'),
    (r'(?i)(?:daily\s*)?transaction.*monitoring',
     'Transaction volume monitoring data for operational alerts'),
    (r'(?i)transaction.*comparison.*retailer',
     'Transaction data compared against retailer-reported figures for reconciliation'),

    # Site plays
    (r'(?i)site\s*plays?\s*by\s*hour',
     'Hourly ad play counts by site, used for impression validation and diagnostics'),
    (r'(?i)site\s*plays?\s*(?:and|&)\s*leases?',
     'Combined site play counts and lease/contract data for revenue reconciliation'),

    # Site status
    (r'(?i)site\s*status\s*history.*(?:month|ending)',
     'Monthly snapshots of site operational status changes over time'),
    (r'(?i)site\s*status\s*history.*per\s*day',
     'Daily site operational status history for granular status tracking'),
    (r'(?i)site\s*status\s*history',
     'Historical record of site operational status changes'),

    # Proof of Play (POP)
    (r'(?i)(?:denormalize|flatten).*proof\s*of\s*play',
     'Flattened Proof of Play records for ad delivery verification'),
    (r'(?i)proof\s*of\s*play.*(?:base|raw)',
     'Base Proof of Play data capturing ad play confirmations'),
    (r'(?i)(?:dxp|dx\s*promote?).*proof\s*of\s*play',
     'DXPromote Proof of Play data for retailer-promoted content verification'),

    # Traffic instructions
    (r'(?i)traffic\s*instruction',
     'Traffic instruction data defining scheduled ad content, timing, and placement rules'),

    # Vistar venue/avails
    (r'(?i)vistar\s*venue\s*avail',
     'Available programmatic ad inventory by Vistar venue, before sell-through deductions'),
    (r'(?i)programmatic\s*venue\s*avail',
     'Programmatic ad inventory availability by venue'),
    (r'(?i)vistar.*diagnostic.*(?:insight|daily)',
     'Daily diagnostic data from Vistar for monitoring programmatic ad delivery health'),

    # Pluto / combined revenue+diagnostics
    (r'(?i)pluto.*revenue.*diagnostic',
     'Combined programmatic revenue and diagnostic metrics (Pluto reporting framework)'),

    # Master station list / site data
    (r'(?i)master\s*station\s*list',
     'Master list of all GSTV gas station sites with location and operational attributes'),
    (r'(?i)active\s*site\s*list',
     'Current list of active GSTV sites with key site attributes'),
    (r'(?i)(?:sites?|station).*base\s*data',
     'Base site/station dataset containing core site attributes and identifiers'),

    # RPA (Retailer Promoted Advertising)
    (r'(?i)rpa\s*conversion.*vistar',
     'Converts RPA scheduling data to Vistar-compatible format for programmatic delivery'),
    (r'(?i)rpa\s*(?:management|submission)',
     'RPA (Retailer Promoted Advertising) submission and management data'),
    (r'(?i)(?:active\s*)?sites?\s*with\s*rpa',
     'Sites currently running RPA (Retailer Promoted Advertising) creatives'),

    # Odyssey / Krypton projects
    (r'(?i)odyssey.*programmatic.*period\s*comparison',
     'Odyssey 2.0 programmatic revenue with period-over-period comparison metrics'),
    (r'(?i)odyssey',
     'Data supporting the Odyssey platform initiative'),
    (r'(?i)(?:project\s*)?krypton',
     'Data supporting the Project Krypton analytics initiative'),

    # DomoStats / Governance
    (r'(?i)domostats|domo.*governance|gstv.*governance',
     'Domo platform governance and usage statistics for instance monitoring'),
    (r'(?i)domo.*activity\s*log',
     'Domo user activity log for tracking platform usage and audit events'),
    (r'(?i)domo.*user\s*metrics',
     'Domo user engagement metrics (page views, card views, login activity)'),
    (r'(?i)domo.*credit',
     'Domo credit consumption tracking for cost management'),

    # Campaign / IO data
    (r'(?i)campaign\s*(?:summary|overview).*all\s*time',
     'All-time campaign performance summary with aggregated delivery metrics'),
    (r'(?i)campaign\s*(?:delivery|tracking)',
     'Campaign delivery tracking data for monitoring ad execution against plan'),
    (r'(?i)campaign\s*impact',
     'Campaign impact analysis measuring advertising effectiveness'),

    # NOC / monitoring
    (r'(?i)noc\s*(?:outreach|status)',
     'Network Operations Center outreach and status tracking for site maintenance'),
    (r'(?i)network\s*(?:health|dashboard)',
     'Network health monitoring dashboard data'),

    # Salesforce extracts
    (r'(?i)salesforce.*(?:extract|export|dump)',
     'Data extracted from Salesforce CRM for reporting and analysis'),
    (r'(?i)(?:booked|pipeline).*(?:history|snapshot)',
     'Historical snapshots of booked revenue and sales pipeline from Salesforce'),
    (r'(?i)(?:io|insertion\s*order).*(?:list|data)',
     'Insertion order data from the ad sales workflow'),

    # Comscore
    (r'(?i)comscore.*transaction',
     'Comscore-measured transaction data for audience and sales attribution'),

    # DMA / geographic
    (r'(?i)dma.*(?:rank|market|data)',
     'Designated Market Area (DMA) reference data with rankings and attributes'),

    # ── Wave 2: Additional patterns ──

    # All GSTV - Ad Serving / Flexible / SSP / Diagnostic patterns
    (r'(?i)all\s*gstv.*ad\s*serving.*flexible.*(?:full\s*)?granularity',
     'Consolidated flexible (managed) ad serving data at full granularity across all GSTV networks'),
    (r'(?i)all\s*gstv.*ad\s*serving.*flexible',
     'Consolidated flexible (managed) ad serving data across all GSTV networks'),
    (r'(?i)all\s*gstv.*(?:ssp|exchange)\s*revenue.*(?:full\s*)?granularity',
     'Consolidated SSP exchange revenue at full granularity across all GSTV networks'),
    (r'(?i)all\s*gstv.*flexible\s*revenue.*(?:full\s*)?granularity',
     'Consolidated flexible (managed) revenue at full granularity across all GSTV networks'),
    (r'(?i)all\s*gstv.*diagnostic.*(?:insight|daily)',
     'Consolidated diagnostic insights data across all GSTV networks'),
    (r'(?i)all\s*gstv',
     'Consolidated data across all GSTV networks'),

    # Ad Ops patterns
    (r'(?i)ad\s*ops.*(?:campaign|launch)\s*monitor',
     'Ad Operations campaign launch monitoring for delivery tracking'),
    (r'(?i)ad\s*ops.*site.*(?:pop|health|score)',
     'Ad Operations site health/POP scoring for operational monitoring'),
    (r'(?i)ad\s*ops.*(?:conservative|hispanic|qsr)',
     'Ad Operations targeting segment data for campaign planning'),
    (r'(?i)ad\s*ops',
     'Ad Operations data for campaign and site management'),

    # Activity log
    (r'(?i)activity\s*log.*(?:creation|execution|view|download)',
     'Domo activity log tracking object-level usage events'),

    # Admin / ontology
    (r'(?i)admin.*(?:dataset|ontology|import|viewflow)',
     'Administrative metadata about Domo datasets and dataflow relationships'),

    # Analysis / check / diagnostic
    (r'(?i)^analysis\s*-',
     'One-off analytical dataset for investigation or reporting'),
    (r'(?i)^check(?:\s|:)',
     'Data quality validation check dataset'),
    (r'(?i)^diagnostics?\s*-',
     'Diagnostic data for investigating system or data issues'),

    # Accounts / Advertisers / Agencies (Salesforce)
    (r'(?i)^accounts?\s*(?:-\s*buying|\s*history)?$',
     'Salesforce account records for advertiser and agency management'),
    (r'(?i)^advertiser(?:s|\s*names)',
     'Advertiser reference data from the ad sales system'),
    (r'(?i)^agenc(?:y|ies)',
     'Agency reference data from the ad sales system'),

    # Broadsign
    (r'(?i)broadsign.*revenue',
     'Revenue data from the Broadsign programmatic exchange'),
    (r'(?i)broadsign',
     'Data from the Broadsign digital signage platform'),

    # Circle K / Casey's / retailer-specific
    (r'(?i)circle\s*k',
     'Data specific to the Circle K retailer network'),
    (r'(?i)casey',
     'Data specific to the Casey\'s retailer network'),
    (r'(?i)speedway',
     'Data specific to the Speedway retailer network'),
    (r'(?i)kwik\s*trip',
     'Data specific to the Kwik Trip retailer network'),
    (r'(?i)brookshire',
     'Data specific to the Brookshire Brothers retailer network'),
    (r'(?i)clark\s*oil',
     'Data specific to the Clark Oil Company retailer network'),

    # Clawback
    (r'(?i)clawback',
     'Revenue clawback calculation data for billing adjustments'),

    # CPM / floor pricing
    (r'(?i)cpm\s*floor',
     'CPM floor pricing data for programmatic bid management'),

    # Creative / plays
    (r'(?i)creative.*(?:site|play)',
     'Creative-to-site play mapping data'),

    # DMA reference
    (r'(?i)dma.*(?:gtvid|creation|sandbox|status)',
     'DMA-to-site mapping data for geographic targeting'),
    (r'(?i)^dmas?\s',
     'Designated Market Area (DMA) reference data'),

    # Direct / Flex revenue
    (r'(?i)direct\s*(?:flex|to\s*retailer)',
     'Direct and flexible advertising revenue data by retailer'),

    # Dover / Wayne / Gilbarco network-specific
    (r'(?i)dover.*(?:network|site|pop|transaction)',
     'Data specific to the Dover network'),
    (r'(?i)wayne.*(?:iotv|network|site)',
     'Data specific to the Wayne IOTV network'),
    (r'(?i)gilbarco.*(?:ics|notification|transaction|advertisement)',
     'Data from the Gilbarco ICS network'),

    # Engineering / assembler / dev
    (r'(?i)assembler',
     'Data assembler pipeline output for transaction aggregation'),
    (r'(?i)engineering.*(?:prod|support)',
     'Engineering production support data'),

    # EDA / exchange inventory
    (r'(?i)eda.*exchange\s*inventory',
     'Exploratory data analysis of programmatic exchange inventory'),

    # Example / demo / sandbox
    (r'(?i)^example\s',
     'Example/sample dataset for training or demonstration purposes'),
    (r'(?i)^demo\s*-\s*sandbox',
     'Sandbox demonstration dataset for testing'),

    # FPIV / rebrands / deployment
    (r'(?i)fpiv|rebrand',
     'Site hardware deployment or rebranding project tracking data'),

    # Health score / report
    (r'(?i)(?:average\s*)?health\s*score',
     'Calculated site health score based on operational metrics'),
    (r'(?i)weekly\s*(?:health\s*)?report',
     'Weekly operational health report data'),
    (r'(?i)weekly\s*report',
     'Weekly report data for operational review'),

    # IOTV
    (r'(?i)iotv.*(?:status|report|site)',
     'IOTV (Internet of Things Video) device status and site data'),

    # Insertion orders / IO
    (r'(?i)(?:^|\s)io\s*(?:list|data|revenue)',
     'Insertion order data from the ad sales workflow'),

    # Managed service
    (r'(?i)managed\s*service',
     'Managed service advertising data for direct-sold retailer campaigns'),

    # POP scoring / active sites
    (r'(?i)active\s*sites?\s*no\s*pop',
     'Active sites without Proof of Play data for operational investigation'),
    (r'(?i)active\s*site\s*count',
     'Active site counts by network, program, or date for trend analysis'),

    # Salesforce generic
    (r'(?i)salesforce.*(?:site|input|writeback)',
     'Salesforce integration data for site or account syncing'),

    # Scheduler / availability
    (r'(?i)(?:future\s*)?availab',
     'Ad inventory availability data for scheduling and planning'),

    # 4/5 digit sites
    (r'(?i)^\d+\s*digit\s*sites?',
     'Site subset filtered by GTVID digit count for legacy analysis'),

    # Uploads / CSV files
    (r'(?i)\.csv$',
     'Uploaded CSV data file'),
    (r'(?i)\.xlsx?$',
     'Uploaded Excel spreadsheet data'),

    # Generic patterns (must be last)
    (r'(?i)\[?(?:test|dev|temp|dnu)\]?',
     None),  # Skip test/temp — will need manual review
    (r'(?i)(?:^|\s)(?:copy|clone)\s+(?:of\s+)?',
     None),  # Skip copies
    (r'(?i)(?:view\s+of|copy\s+of)\s+(.+)',
     None),  # View/copy — handled in function
]

# ── Pattern-based description rules for dataflows ──────────────────────────
DF_RULES = [
    # ETL / flatten / denormalize
    (r'(?i)flatten\s*ti',
     'Flattens traffic instruction data from nested format into a denormalized table'),
    (r'(?i)denormalize.*proof\s*of\s*play',
     'Denormalizes Proof of Play records into a flat structure for reporting'),
    (r'(?i)flatten.*(?:pop|proof)',
     'Flattens Proof of Play records into a flat structure for reporting'),

    # RPA conversion
    (r'(?i)rpa\s*conversion.*vistar.*(?:managed|service)',
     'Converts managed service RPA schedules to Vistar-compatible format'),
    (r'(?i)rpa\s*conversion.*vistar.*(?:\d\s*slot|\d\s*line)',
     'Converts RPA data to Vistar multi-slot scheduling format'),
    (r'(?i)rpa\s*conversion',
     'Converts RPA scheduling data between internal and Vistar formats'),

    # Transaction processing
    (r'(?i)(?:daily\s*)?transaction.*monitoring.*(?:all|network)',
     'Aggregates transaction monitoring data across all networks for daily tracking'),
    (r'(?i)transaction.*(?:gilbarco|wayne|dover|speedway)',
     'Processes transaction data for the specified network'),
    (r'(?i)transaction.*hourly.*(?:week|aggregate)',
     'Aggregates hourly transaction data to weekly totals'),
    (r'(?i)transaction.*comparison',
     'Compares transaction volumes across sources for data quality validation'),

    # Site data joins
    (r'(?i)(?:join|enrich|merge).*(?:nvi|impression).*site',
     'Joins NVI/impression data to site attributes for enriched reporting'),
    (r'(?i)(?:join|enrich|merge).*site\s*data',
     'Enriches data by joining to the site master dataset'),

    # Sell through
    (r'(?i)sell\s*through',
     'Calculates sell-through rates combining avails, scheduling, and revenue data'),

    # Traffic instructions
    (r'(?i)(?:etl|sql).*traffic\s*instruction',
     'ETL pipeline processing traffic instruction data from Vistar BI'),
    (r'(?i)traffic\s*instruction.*(?:play|collapse)',
     'Processes traffic instructions and matches to play records'),

    # Campaign / impressions
    (r'(?i)campaign.*validated\s*impression',
     'Processes and validates campaign impression data for billing accuracy'),
    (r'(?i)campaign.*(?:delivery|tracking)',
     'Tracks campaign delivery progress against contracted commitments'),

    # Vistar / programmatic
    (r'(?i)vistar.*(?:diagnostic|insight)',
     'Processes Vistar diagnostic data for programmatic health monitoring'),
    (r'(?i)vistar.*(?:venue|avail)',
     'Processes Vistar venue availability data for sell-through analysis'),
    (r'(?i)(?:patch|backfill).*vistar',
     'Patches or backfills historical Vistar data'),

    # Monitoring / governance
    (r'(?i)monitoring.*(?:site|network)',
     'Monitoring pipeline tracking site/network operational health'),
    (r'(?i)monitoring.*(?:snowflake|transaction)',
     'Monitors data pipeline health from Snowflake transaction feeds'),
    (r'(?i)(?:domo|gstv).*gov',
     'Domo governance dataflow for instance monitoring and credit tracking'),

    # Revenue
    (r'(?i)revenue.*(?:allocation|report)',
     'Processes revenue data for allocation and reporting'),
    (r'(?i)(?:programmatic|exchange).*revenue',
     'Aggregates programmatic exchange revenue data'),

    # Ad serving / scheduling
    (r'(?i)ad\s*(?:serving|ops)',
     'Ad operations pipeline for scheduling and delivery tracking'),
    (r'(?i)(?:current|future)\s*advertisement',
     'Processes current and upcoming advertisement scheduling data'),

    # Speedway / retailer-specific
    (r'(?i)speedway',
     'Processes data specific to the Speedway retailer network'),
    (r'(?i)casey',
     'Processes data specific to the Casey\'s retailer network'),

    # DFS / NOC
    (r'(?i)dfs\s*(?:weekly|report)',
     'Generates weekly DFS (Distributed Field Services) reporting data'),
    (r'(?i)noc\s*(?:agenda|report)',
     'Generates Network Operations Center reporting data'),

    # Site status
    (r'(?i)site\s*status',
     'Processes site operational status data for tracking and reporting'),

    # ── Wave 2: Additional dataflow patterns ──

    # Network-specific
    (r'(?i)(?:dover|gilbarco|wayne).*transaction',
     'Processes transaction data for the specified retail network'),
    (r'(?i)circle\s*k',
     'Processes data for the Circle K retailer network'),
    (r'(?i)kwik\s*trip',
     'Processes data for the Kwik Trip retailer network'),

    # NVI / impression pipelines
    (r'(?i)(?:nvi|network\s*validated\s*impression)',
     'Processes network validated impression (NVI) calculations'),
    (r'(?i)impression.*(?:calc|valid|process)',
     'Processes and validates ad impression data'),

    # Clawback / billing
    (r'(?i)clawback',
     'Calculates revenue clawback adjustments for billing'),
    (r'(?i)(?:invoice|billing)',
     'Processes billing and invoice data'),

    # Salesforce
    (r'(?i)salesforce',
     'Processes Salesforce CRM data for integration with Domo reporting'),

    # POP pipeline
    (r'(?i)(?:pop|proof\s*of\s*play)',
     'Processes Proof of Play data for ad delivery verification'),

    # Venue / avails
    (r'(?i)avail',
     'Calculates ad inventory availability for scheduling and sell-through'),

    # Admin / governance
    (r'(?i)admin|ontology|governance',
     'Administrative/governance dataflow for platform management'),

    # Health / alert / data quality
    (r'(?i)(?:health|alert|data\s*quality)',
     'Data quality monitoring and alerting pipeline'),

    # Creative / scheduling
    (r'(?i)creative|scheduling',
     'Processes creative content scheduling data'),

    # Revenue share / commission
    (r'(?i)revenue\s*share|commission',
     'Calculates revenue share or commission allocations'),

    # Patch / backfill
    (r'(?i)patch|backfill|historical',
     'Patches or backfills historical data for completeness'),

    # Join / enrich / merge
    (r'(?i)(?:^|\s)(?:join|enrich|merge|combine|append)',
     'Combines multiple data sources through joining or appending'),

    # Aggregate / rollup / summary
    (r'(?i)(?:aggregate|rollup|summary|consolidat)',
     'Aggregates or summarizes data for reporting'),

    # Filter / subset
    (r'(?i)(?:filter|subset|segment)',
     'Filters or segments data for a specific use case'),

    # Generic ETL (must be last)
    (r'(?i)^(?:df|etl|sql)\s*\d+',
     None),  # Numbered dataflows — too generic, skip
    (r'(?i)^new\s*etl\s*transform$',
     None),  # Generic unnamed ETL
]


def infer_dataset_description(ds: dict, domain: str, dept: str, lineage_info: dict) -> str | None:
    """Try to infer a description for a dataset."""
    name = ds.get('dataset_name', '').strip()

    # Try pattern rules
    for pattern, template in DS_RULES:
        if re.search(pattern, name):
            if template is None:
                return None  # Explicitly skip
            return template

    # If it's a "View of X" or "Copy of X", reference the source
    m = re.match(r'(?i)(?:view\s+of|copy\s+of)\s+(.+)', name)
    if m:
        source = m.group(1).strip()
        return f'Derived view/copy of "{source}"'

    # Use domain classification for generic inference
    domain_descriptions = {
        'Impressions': 'Impression measurement data for ad delivery tracking',
        'Transactions': 'Fuel transaction data for site activity monitoring',
        'Revenue': 'Revenue data for financial reporting and analysis',
        'Sites & Locations': 'Site and location reference data',
        'Programmatic': 'Programmatic advertising data',
        'Campaigns': 'Campaign scheduling and delivery data',
        'Proof of Play': 'Proof of Play ad delivery verification data',
        'Monitoring & Governance': 'Operational monitoring and data governance metrics',
        'Site Analytics': 'Site-level analytics and performance data',
    }

    if domain in domain_descriptions:
        return domain_descriptions[domain]

    return None


def infer_dataflow_description(df: dict, domain: str) -> str | None:
    """Try to infer a description for a dataflow."""
    name = df.get('dataflow_name', '').strip()

    for pattern, template in DF_RULES:
        if re.search(pattern, name):
            if template is None:
                return None
            return template

    # Copy of X
    m = re.match(r'(?i)(?:copy\s+of)\s+(.+)', name)
    if m:
        source = m.group(1).strip()
        return f'Copy of the "{source}" dataflow'

    return None


def main():
    with open(CACHE_FILE) as f:
        data = json.load(f)

    datasets = data['datasets']
    dataflows = data['dataflows']
    lineage = data['lineage']

    # Build lineage context
    ds_feeds = defaultdict(set)
    ds_produced_by = defaultdict(set)
    for rec in lineage:
        ds_id = rec.get('dataset_id', '')
        df_name = rec.get('dataflow_name', '').strip()
        direction = rec.get('direction', '')
        if direction == 'Input':
            ds_feeds[ds_id].add(df_name)
        elif direction == 'Output':
            ds_produced_by[ds_id].add(df_name)

    # ── Datasets ──
    ds_rows = []
    inferred_count = 0
    skipped_count = 0
    already_has = 0

    for ds in datasets:
        existing = ds.get('description', '').strip()
        ds_id = ds['dataset_id']
        name = ds.get('dataset_name', '').strip()
        domain, dept = analytics._classify_domain(name)

        if existing:
            already_has += 1
            ds_rows.append({
                'dataset_id': ds_id,
                'dataset_name': name,
                'existing_description': existing,
                'suggested_description': '',
                'source': 'existing',
                'owner': ds.get('owner_name', ''),
            })
            continue

        lineage_info = {
            'feeds': sorted(ds_feeds.get(ds_id, set())),
            'produced_by': sorted(ds_produced_by.get(ds_id, set())),
        }

        suggested = infer_dataset_description(ds, domain, dept, lineage_info)
        if suggested:
            inferred_count += 1
        else:
            skipped_count += 1

        ds_rows.append({
            'dataset_id': ds_id,
            'dataset_name': name,
            'existing_description': '',
            'suggested_description': suggested or '',
            'source': 'inferred' if suggested else '',
            'owner': ds.get('owner_name', ''),
        })

    with open(DS_OUTPUT, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['dataset_id', 'dataset_name', 'existing_description',
                                                'suggested_description', 'source', 'owner'])
        writer.writeheader()
        writer.writerows(ds_rows)

    print(f'DATASET DESCRIPTIONS')
    print(f'  Already have description: {already_has}')
    print(f'  Inferred:                 {inferred_count}')
    print(f'  Could not infer:          {skipped_count}')
    print(f'  Total:                    {len(ds_rows)}')
    print(f'  Coverage:                 {(already_has + inferred_count) / len(ds_rows) * 100:.1f}%')
    print(f'  Output: {DS_OUTPUT}')

    # ── Dataflows ──
    df_rows = []
    df_inferred = 0
    df_skipped = 0
    df_already = 0

    id_to_name = {}
    for d in datasets:
        if d.get('owner_name') and d.get('owner_id'):
            id_to_name[d['owner_id']] = d['owner_name']

    for df in dataflows:
        existing = df.get('description', '').strip()
        df_id = str(df.get('dataflow_id', ''))
        name = df.get('dataflow_name', '').strip()
        domain, dept = analytics._classify_domain(name)
        owner_id = df.get('owner_id')
        int_id = int(owner_id) if str(owner_id).isdigit() else owner_id
        owner = id_to_name.get(owner_id, id_to_name.get(int_id, ''))

        if existing:
            df_already += 1
            df_rows.append({
                'dataflow_id': df_id,
                'dataflow_name': name,
                'existing_description': existing,
                'suggested_description': '',
                'source': 'existing',
                'owner': owner,
            })
            continue

        suggested = infer_dataflow_description(df, domain)
        if suggested:
            df_inferred += 1
        else:
            df_skipped += 1

        df_rows.append({
            'dataflow_id': df_id,
            'dataflow_name': name,
            'existing_description': '',
            'suggested_description': suggested or '',
            'source': 'inferred' if suggested else '',
            'owner': owner,
        })

    with open(DF_OUTPUT, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['dataflow_id', 'dataflow_name', 'existing_description',
                                                'suggested_description', 'source', 'owner'])
        writer.writeheader()
        writer.writerows(df_rows)

    print(f'\nDATAFLOW DESCRIPTIONS')
    print(f'  Already have description: {df_already}')
    print(f'  Inferred:                 {df_inferred}')
    print(f'  Could not infer:          {df_skipped}')
    print(f'  Total:                    {len(df_rows)}')
    print(f'  Coverage:                 {(df_already + df_inferred) / len(df_rows) * 100:.1f}%')
    print(f'  Output: {DF_OUTPUT}')


if __name__ == '__main__':
    main()
