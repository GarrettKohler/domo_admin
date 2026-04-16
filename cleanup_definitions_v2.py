#!/usr/bin/env python3
"""
cleanup_definitions_v2.py — Second-pass fixes for remaining quality issues:
1. Fix remaining boolean flag style
2. Expand all remaining short definitions (<10 char body)
3. Expand name-restating definitions more aggressively
4. Ensure trailing periods are consistent (no trailing periods — match majority)
"""

import csv, re
from collections import Counter

CSV = "column_definitions.csv"
PREFIX_RE = re.compile(r'^(\[[^\]]+\]\s*)')

# ── Manual expansions for all 68 short definitions ──────────────────────────
# Format: column_name → new full definition (including prefix)
MANUAL_EXPANSIONS = {
    # SF Site__c OMS fields
    'Average Daily Imp - Programmatic - 13+': '[SF: Site__c] Average daily programmatic impressions for the 13+ demographic, used in OMS planning',
    'Average Daily Imp - Programmatic - 18+': '[SF: Site__c] Average daily programmatic impressions for the 18+ demographic, used in OMS planning',
    'Average Daily Impressions - 13+': '[SF: Site__c] Average daily total impressions for the 13+ demographic, used in OMS planning',
    'Average Daily Impressions - 18+': '[SF: Site__c] Average daily total impressions for the 18+ demographic, used in OMS planning',
    'TDLinx Annual Sales Volume': '[SF: Site__c] Annual sales volume from Nielsen TDLinx, used in OMS planning',
    'TDLinx Weekly Sales Volume': '[SF: Site__c] Weekly sales volume from Nielsen TDLinx, used in OMS planning',

    # SF User fields
    'Address': '[SF: User] Mailing or business address for the Salesforce user',
    'address': '[SF: User] Mailing or business address for the Salesforce user',
    'IsActive': '[SF: User] Whether the Salesforce user account is currently active',
    'is_active': '[SF: User] Whether the Salesforce user account is currently active',

    # SF Opportunity fields
    'Tag_s__c': '[SF: Opportunity] Tags or labels applied to this opportunity for categorization',
    'Next Step': '[SF: Opportunity] Next action step planned for advancing this opportunity',
    'Opp #': '[SF: Opportunity] Opportunity number or sequential identifier',
    'Opp Stage': '[SF: Opportunity] Current sales pipeline stage of this opportunity',

    # Jira fields
    'Test plan': '[Jira] Test plan associated with this issue, describing validation steps',
    'Resolved': '[Jira] Date or timestamp when this issue was resolved',
    'Vendor': '[Jira] External vendor associated with this issue or request',
    'issueId': '[Jira] Unique numeric identifier for this Jira issue',
    'timeSpent': '[Jira] Total time spent working on this issue (human-readable format)',
    'started': '[Jira] Timestamp when work on this issue was started',
    'orderable': '[Jira] Whether this field can be used for ordering search results',
    'navigable': '[Jira] Whether this field is visible in the issue navigator',
    'Pronouns': '[Jira] Preferred pronouns for the Jira user',
    'Parent': '[Jira] Parent issue key for this sub-task or child issue',
    'Franchise': '[Jira] Franchise or brand associated with this issue',
    'Products': '[Jira] Product(s) related to this issue or request',
    'Goals': '[Jira] Strategic goals or objectives associated with this issue',
    'Insights': '[Jira] Key insights or findings related to this issue',
    'Tentpole': '[Jira] Tentpole event or major campaign associated with this issue',
    'Team_1': '[Jira] Primary team assignment for this issue',

    # GBase fields
    'address.city': '[GBase] City name from the site address document',
    'address.zip': '[GBase] ZIP code from the site address document',

    # SF Site/Location fields
    'GTVID__c': '[SF: Site/Location] GSTV unique site identifier (GTVID) stored in Salesforce',
    'County__c': '[SF: Site/Location] County name where the site is located',
    'DMA_Rank__c': '[SF: Site/Location] DMA market size rank for the site location',
    'EV_Site__c': '[SF: Site/Location] Whether this is an electric vehicle charging site',
    'Fuel_Site__c': '[SF: Site/Location] Whether this is a fueling site',
    'ID_Brand__c': '[SF: Site/Location] Brand identifier for the site',
    'ID_Gbase__c': '[SF: Site/Location] GBase system identifier for the site',
    'ID_GVR__c': '[SF: Site/Location] GVR (Gilbarco Veeder-Root) hardware identifier for the site',
    'ID_TDLinx__c': '[SF: Site/Location] Nielsen TDLinx identifier for the site',
    'Latitude__c': '[SF: Site/Location] Geographic latitude coordinate for the site',
    'Longitude__c': '[SF: Site/Location] Geographic longitude coordinate for the site',
    'My_Site__c': '[SF: Site/Location] Whether the current user owns or manages this site',
    'NFC_Type__c': '[SF: Site/Location] Near-field communication (NFC) hardware type at the site',
    'No_Email__c': '[SF: Site/Location] Whether this site contact should not receive emails',
    'Location__c': '[SF: Site/Location] Location reference or lookup field for the site',
    'Venue__c': '[SF: Site/Location] Venue reference or lookup field for the site',
    'Sellable__c': '[SF: Site/Location] Whether this site is currently sellable for advertising',
    'Month__c': '[SF: Site/Location] Month value associated with the site record',

    # SF RPA Submission fields
    'Retailer__c': '[SF: RPA Submission] Retailer associated with this RPA submission',
    'Site__c': '[SF: RPA Submission] Site reference for this RPA submission',
    'Revision__c': '[SF: RPA Submission] Revision number or version of this RPA submission',
    'Daypart__c': '[SF: RPA Submission] Daypart scheduling window for this RPA submission',
    'Details__c': '[SF: RPA Submission] Free-text details describing this RPA submission',
    'AssetID__c': '[SF: RPA Submission] Creative asset identifier linked to this RPA submission',
    'Length__c': '[SF: RPA Submission] Duration length (in seconds) of the RPA creative',
    'Primer__c': '[SF: RPA Submission] Primer creative associated with this RPA submission',
    'Music__c': '[SF: RPA Submission] Music track or audio selection for this RPA creative',

    # SF DMA demographic fields
    'm_16+': '[SF: DMA__c] Male population aged 16 and older in this DMA',
    'm_18+': '[SF: DMA__c] Male population aged 18 and older in this DMA',
    'm_21+': '[SF: DMA__c] Male population aged 21 and older in this DMA',
    'm_55+': '[SF: DMA__c] Male population aged 55 and older in this DMA',

    # Other fields
    'comment': 'Free-text comment or note associated with this record',
    'Total Fee': 'Total fee amount in USD charged for this item or service',
    'Ad Specs': 'Advertising specifications (format, dimensions, file requirements) for the creative',

    # Boolean fix
    'Has_NVIs_Partial_Month__c': '[SF: Site/Location] Whether this site has NVI data for only a partial month',
}

# ── Name-restating expansion rules ──────────────────────────────────────────
# For definitions that just restate the column name, provide better text
# Pattern: (column_name_regex, new_definition_template)
NAME_RESTATE_FIXES = [
    # Jira nested object fields that restate like "Assignee account ID"
    (re.compile(r'^(Reporter|Assignee|Creator)\s+(Account\s+ID|Display\s+Name|Email\s+Address|Active|Time\s+Zone|Locale)', re.I),
     lambda m: f'[Jira] {m.group(1)}\'s {m.group(2).lower()} in the Jira user profile'),

    # Generic "X Name" that restates
    (re.compile(r'^(\w+)\s+Name$'),
     lambda m: f'Display name of the {m.group(1).lower()}'),
]


def main():
    with open(CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    stats = Counter()

    for i, row in enumerate(rows):
        defn = row['definition']
        if not defn or not defn.strip():
            continue

        col = row['column_name']

        # Apply manual expansions
        if col in MANUAL_EXPANSIONS:
            new_defn = MANUAL_EXPANSIONS[col]
            if new_defn != defn:
                rows[i]['definition'] = new_defn
                stats['manual_expanded'] += 1
                continue

        # Fix remaining name-restating patterns
        m = PREFIX_RE.match(defn)
        prefix = m.group(1) if m else ''
        body = defn[m.end():].strip() if m else defn.strip()

        # Check if body essentially restates column name
        col_clean = re.sub(r'[_\-\.]', ' ', col).strip()
        body_clean = re.sub(r'[_\-\.]', ' ', body).strip()

        if body_clean.lower() == col_clean.lower() or \
           body_clean.lower() == re.sub(r'([a-z])([A-Z])', r'\1 \2', col).lower():
            # Try rule-based fix
            for pat, fixer in NAME_RESTATE_FIXES:
                m2 = pat.match(col)
                if m2:
                    rows[i]['definition'] = fixer(m2)
                    stats['name_restate_fixed'] += 1
                    break

    # Write
    with open(CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"V2 CLEANUP SUMMARY")
    print(f"{'='*50}")
    for cat, count in stats.most_common():
        print(f"  {cat:30s}: {count:>5d}")
    print(f"  {'TOTAL':30s}: {sum(stats.values()):>5d}")

    # Quick remaining-short check
    with open(CSV, newline='', encoding='utf-8') as f:
        rows2 = list(csv.DictReader(f))

    short_remaining = 0
    for r in rows2:
        d = r['definition']
        if not d.strip(): continue
        m = PREFIX_RE.match(d)
        body = d[m.end():] if m else d
        if len(body.strip()) < 10:
            short_remaining += 1

    print(f"\n  Remaining short definitions: {short_remaining}")


if __name__ == '__main__':
    main()
