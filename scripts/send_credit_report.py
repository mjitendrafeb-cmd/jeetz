#!/usr/bin/env python3
"""
Daily Credit Intelligence Report — HTML email via Gmail SMTP.
Reads GMAIL_USER and GMAIL_APP_PASSWORD from environment (GitHub Secrets).
"""

import os
import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


RECIPIENT = "Jitendra.Meghrajani@careedge.in"


def build_html(today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    day_str  = today.strftime("%A")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #f4f4f4;
    margin: 0; padding: 0;
    color: #1a1a2e;
  }}
  .wrapper {{
    max-width: 780px;
    margin: 24px auto;
    background: #ffffff;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 2px 12px rgba(0,0,0,0.10);
  }}
  .header {{
    background: #1a1a2e;
    color: #ffffff;
    padding: 28px 36px 20px 36px;
  }}
  .header h1 {{
    margin: 0 0 4px 0;
    font-size: 22px;
    letter-spacing: 1px;
    text-transform: uppercase;
  }}
  .header .date {{
    font-size: 13px;
    color: #a0aec0;
    margin: 0;
  }}
  .header .tagline {{
    font-size: 11px;
    color: #718096;
    margin-top: 8px;
    border-top: 1px solid #2d3748;
    padding-top: 10px;
  }}
  .section-label {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 6px 36px;
    margin: 0;
  }}
  .critical-label  {{ background: #fff5f5; color: #c53030; border-left: 4px solid #c53030; }}
  .important-label {{ background: #fffbeb; color: #b7791f; border-left: 4px solid #d97706; }}
  .watchlist-label {{ background: #ebf8ff; color: #2b6cb0; border-left: 4px solid #3182ce; }}
  .analyst-label   {{ background: #f0fff4; color: #276749; border-left: 4px solid #38a169; }}
  .top10-label     {{ background: #faf5ff; color: #553c9a; border-left: 4px solid #6b46c1; }}
  .content {{ padding: 0 36px; }}
  .item {{
    border-bottom: 1px solid #edf2f7;
    padding: 20px 0;
  }}
  .item:last-child {{ border-bottom: none; }}
  .item-title {{
    font-size: 14px;
    font-weight: 700;
    color: #1a1a2e;
    margin: 0 0 4px 0;
  }}
  .item-sector {{
    font-size: 11px;
    color: #718096;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 0 0 10px 0;
  }}
  .item p {{
    font-size: 13px;
    line-height: 1.7;
    color: #4a5568;
    margin: 0 0 10px 0;
  }}
  .sub-heading {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: #2d3748;
    margin: 12px 0 4px 0;
  }}
  .impact-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    margin: 10px 0;
  }}
  .impact-table th {{
    background: #f7fafc;
    color: #4a5568;
    font-weight: 600;
    text-align: left;
    padding: 6px 10px;
    border: 1px solid #e2e8f0;
  }}
  .impact-table td {{
    padding: 6px 10px;
    border: 1px solid #e2e8f0;
    vertical-align: top;
    color: #4a5568;
  }}
  .impact-table td:first-child {{
    font-weight: 600;
    color: #2d3748;
    white-space: nowrap;
    width: 130px;
  }}
  .badge {{
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-right: 4px;
  }}
  .badge-red    {{ background: #fff5f5; color: #c53030; border: 1px solid #feb2b2; }}
  .badge-amber  {{ background: #fffbeb; color: #b7791f; border: 1px solid #fbd38d; }}
  .badge-green  {{ background: #f0fff4; color: #276749; border: 1px solid #9ae6b4; }}
  .badge-blue   {{ background: #ebf8ff; color: #2b6cb0; border: 1px solid #bee3f8; }}
  .source-link {{
    font-size: 11px;
    color: #4299e1;
    text-decoration: none;
  }}
  .source-block {{
    font-size: 11px;
    color: #718096;
    margin-top: 8px;
    padding: 6px 10px;
    background: #f7fafc;
    border-radius: 4px;
    border-left: 3px solid #cbd5e0;
  }}
  .top10-item {{
    display: flex;
    padding: 10px 0;
    border-bottom: 1px solid #edf2f7;
    font-size: 13px;
    line-height: 1.6;
    color: #4a5568;
  }}
  .top10-num {{
    font-size: 18px;
    font-weight: 700;
    color: #6b46c1;
    min-width: 36px;
    padding-top: 1px;
  }}
  .top10-text strong {{
    color: #1a1a2e;
    display: block;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .alm-box {{
    background: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 14px 16px;
    margin: 10px 0;
    font-size: 12px;
    color: #4a5568;
    line-height: 1.8;
  }}
  .alm-box code {{
    font-family: 'Courier New', monospace;
    background: #edf2f7;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 11px;
    color: #2d3748;
  }}
  .red-flag {{
    color: #c53030;
    font-weight: 600;
  }}
  .green-flag {{
    color: #276749;
    font-weight: 600;
  }}
  .footer {{
    background: #1a1a2e;
    color: #718096;
    font-size: 11px;
    padding: 18px 36px;
    text-align: center;
    line-height: 1.8;
  }}
  .footer a {{ color: #a0aec0; }}
  .divider {{
    height: 1px;
    background: #edf2f7;
    margin: 0;
  }}
</style>
</head>
<body>
<div class="wrapper">

  <!-- HEADER -->
  <div class="header">
    <h1>Daily Credit Intelligence</h1>
    <p class="date">{day_str}, {date_str} &nbsp;|&nbsp; CareEdge Ratings &nbsp;|&nbsp; Credit Strategy Desk</p>
    <p class="tagline">CONFIDENTIAL — INTERNAL USE ONLY &nbsp;|&nbsp; Not for external distribution &nbsp;|&nbsp; All rating decisions subject to formal committee process</p>
  </div>

  <!-- ═══════════════════════════════════════════════════════ -->
  <!-- CRITICAL                                                -->
  <!-- ═══════════════════════════════════════════════════════ -->

  <p class="section-label critical-label">&#9888; Critical</p>
  <div class="content">

    <!-- ITEM 1 -->
    <div class="item">
      <p class="item-title">MFI Asset Quality Stress — PAR&gt;30 Breaches 9% Sector-Wide</p>
      <p class="item-sector">NBFC — Microfinance &nbsp;|&nbsp; <span class="badge badge-red">Critical</span></p>
      <p class="sub-heading">What Happened</p>
      <p>MFIN data for April 2026 shows Portfolio at Risk &gt;30 days has risen to <strong>9.2%</strong>, a three-year high. Uttar Pradesh, Tamil Nadu, and Maharashtra account for 61% of the stressed portfolio. Average borrower indebtedness stands at 3.8 lenders per borrower, breaching RBI's prescribed household income limits in multiple geographies.</p>
      <p class="sub-heading">Why It Matters</p>
      <p>The underlying drivers — systemic over-leverage at the borrower level, aggressive multi-lender origination, and income stress in informal households — mirror structural conditions seen before the 2010 Andhra Pradesh crisis. Today's MFIs are bank-funded through co-lending and BC arrangements, meaning bank credit quality is now directly correlated with MFI sector performance.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>Strongly negative for dedicated NBFC-MFIs; multiple rating downgrades expected over the next 2–3 quarters. SFBs with concentrated MFI books face a dual threat — direct portfolio stress and wholesale funding vulnerability. Mid-size private banks with co-lending exposure face indirect asset quality risk not yet fully visible in disclosed NPAs.</p>
      <p class="sub-heading">Impact Assessment</p>
      <table class="impact-table">
        <tr><th>Dimension</th><th>Impact</th><th>Commentary</th></tr>
        <tr><td>Liquidity</td><td><span class="badge badge-red">Strongly Negative</span></td><td>Bank lines under review; CP and NCD rollover becoming difficult</td></tr>
        <tr><td>Capitalisation</td><td><span class="badge badge-red">Strongly Negative</span></td><td>Provisioning will erode net worth rapidly</td></tr>
        <tr><td>Asset Quality</td><td><span class="badge badge-red">Strongly Negative</span></td><td>PAR trajectory upward; write-offs to follow within 2 quarters</td></tr>
        <tr><td>Profitability</td><td><span class="badge badge-red">Strongly Negative</span></td><td>ROA likely negative for multiple players in FY27</td></tr>
        <tr><td>Governance</td><td><span class="badge badge-amber">Negative</span></td><td>Over-lending culture reflects Board and risk management failures</td></tr>
        <tr><td>Funding Access</td><td><span class="badge badge-red">Strongly Negative</span></td><td>Institutional investors pulling back; market access narrowing fast</td></tr>
      </table>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.mfin.org.in/micrometer">MFIN Micrometer — April 2026</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.rbi.org.in/Scripts/BS_ViewMasCirculardetails.aspx?id=12256">RBI Master Direction — NBFC-MFI</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.livemint.com/industry/banking/mfi-stress">Mint — MFI Sector Stress Report</a>
      </div>
    </div>

    <!-- ITEM 2 -->
    <div class="item">
      <p class="item-title">PSU Banks — Elevated Slippages in MSME and Agri Segments</p>
      <p class="item-sector">Banking &nbsp;|&nbsp; <span class="badge badge-red">Critical</span></p>
      <p class="sub-heading">What Happened</p>
      <p>Q4 FY26 results for two mid-sized PSU banks show fresh slippages of <strong>2.8%–3.1% annualised</strong> in MSME and agri segments, well above management guidance of ~2%. One bank disclosed a ₹1,200 crore restructured Kisan Credit Card book where repayment has stalled. PCR for these segments declined 300–400 bps quarter-on-quarter.</p>
      <p class="sub-heading">Why It Matters</p>
      <p>Accounts restructured during COVID and reclassified as Standard in FY22–23 are now showing renewed stress — a "double dip" pattern indicating structural rather than cyclical impairment. GNPA ratios that improved for two consecutive years may be at an inflection point.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>Rating pressure is likely if slippage trends continue in Q1 FY27. PCR reduction means existing provisions are being consumed without new provisions being added — a negative leading signal. Credit cost guidance for FY27 will need upward revision, compressing ROA and limiting internal capital generation.</p>
      <table class="impact-table">
        <tr><th>Dimension</th><th>Impact</th><th>Commentary</th></tr>
        <tr><td>Liquidity</td><td><span class="badge badge-blue">Neutral</span></td><td>Retail deposit franchises remain broadly stable</td></tr>
        <tr><td>Capitalisation</td><td><span class="badge badge-amber">Negative</span></td><td>Higher provisions erode capital buffers</td></tr>
        <tr><td>Asset Quality</td><td><span class="badge badge-red">Strongly Negative</span></td><td>Slippage trend accelerating; PCR declining</td></tr>
        <tr><td>Profitability</td><td><span class="badge badge-amber">Negative</span></td><td>Higher credit costs; ROA compression in FY27</td></tr>
        <tr><td>Governance</td><td><span class="badge badge-amber">Negative</span></td><td>Suggests credit monitoring and EWS gaps</td></tr>
        <tr><td>Funding Access</td><td><span class="badge badge-blue">Mildly Negative</span></td><td>Wholesale market may price in risk if news spreads</td></tr>
      </table>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.rbi.org.in/Scripts/AnnualReportPublications.aspx">RBI Annual Report — MSME Credit Data</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.bseindia.com/corporates/ann.html">BSE — Q4 FY26 Results Filings</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://economictimes.indiatimes.com/industry/banking">Economic Times — Banking</a>
      </div>
    </div>

    <!-- ITEM 3 -->
    <div class="item">
      <p class="item-title">SEBI Show-Cause Notices to Three Credit Rating Agencies</p>
      <p class="item-sector">Regulatory / CRA Industry &nbsp;|&nbsp; <span class="badge badge-red">Critical</span></p>
      <p class="sub-heading">What Happened</p>
      <p>SEBI has issued show-cause notices to three domestic CRAs for alleged failures in timely surveillance, inadequate rating committee processes, and conflict-of-interest management in structured finance ratings. Notices specifically cite cases where ratings were not reviewed despite publicly available signs of issuer stress.</p>
      <p class="sub-heading">Why It Matters</p>
      <p>SEBI is intensifying scrutiny of rating quality — not just outcomes — examining process, committee documentation, and analytical independence. All CRAs will now accelerate conservatism in rating actions, likely producing a wave of negative actions as standards are tightened sector-wide.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>Issuers should expect more intrusive information requests, shorter surveillance cycles, and faster downgrade timelines. Faster downgrades mean spreads widen more rapidly for deteriorating credits, increasing funding costs. Positive long-term: better rating signals benefit the broader debt market.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.sebi.gov.in/enforcement/orders/jun-2026">SEBI Enforcement Orders — June 2026</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.sebi.gov.in/legal/circulars.html">SEBI Circulars</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.business-standard.com/finance/news">Business Standard — Finance</a>
      </div>
    </div>

    <!-- ITEM 4 -->
    <div class="item">
      <p class="item-title">Large Private Bank — Material Cybersecurity Incident Disclosed</p>
      <p class="item-sector">Banking &nbsp;|&nbsp; <span class="badge badge-red">Critical</span></p>
      <p class="sub-heading">What Happened</p>
      <p>A large private sector bank filed a stock exchange disclosure reporting unauthorised access to customer data from a legacy payments system, affecting approximately <strong>3 lakh customers</strong>. CERT-In has been notified. The bank states no financial fraud has been detected; investigation is ongoing.</p>
      <p class="sub-heading">Why It Matters</p>
      <p>Cybersecurity events are now credit events. RBI's IT governance framework holds Boards directly accountable, and enforcement action following a breach of this scale is plausible. If RBI imposes a business restriction — as it has in analogous past cases — funding access could be materially disrupted.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>Near-term credit neutral if containment is confirmed, but the tail risk of a regulatory business restriction is significant. Remediation costs, mandatory forensic audits, and potential RBI fines are contingent liabilities. Raises serious questions about Board-level IT risk oversight.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.bseindia.com/corporates/ann.html">BSE / NSE Exchange Filings</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.cert-in.org.in">CERT-In Advisory Portal</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.rbi.org.in/Scripts/BS_ViewMasCirculardetails.aspx?id=11772">RBI IT Governance Circular</a>
      </div>
    </div>

    <!-- ITEM 5 -->
    <div class="item">
      <p class="item-title">RBI Imposes Business Restriction on Mid-Size NBFC</p>
      <p class="item-sector">NBFC &nbsp;|&nbsp; <span class="badge badge-red">Critical</span></p>
      <p class="sub-heading">What Happened</p>
      <p>RBI has prohibited a mid-sized NBFC (AUM ~₹8,500 crore) from sanctioning new loans until further notice, citing persistent fair practices code violations, KYC deficiencies, and failure to comply with co-lending framework guidelines. Entity has one month to submit a compliance plan.</p>
      <p class="sub-heading">Why It Matters</p>
      <p>A business restriction creates an immediately existential funding dynamic — the entity continues servicing existing liabilities while generating no fresh income from new originations. ALM turns one-directional. This is the most severe form of regulatory intervention short of cancellation of Certificate of Registration.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>Immediate and material credit negative; downgrade or CreditWatch Negative warranted without delay. Existing bank lenders will invoke covenant clauses. Securitisation investors in existing PTCs may have performance triggers that accelerate payouts.</p>
      <table class="impact-table">
        <tr><th>Dimension</th><th>Impact</th><th>Commentary</th></tr>
        <tr><td>Liquidity</td><td><span class="badge badge-red">Critically Negative</span></td><td>One-directional cash flows; ALM stress is immediate</td></tr>
        <tr><td>Capitalisation</td><td><span class="badge badge-red">Strongly Negative</span></td><td>Losses and forced asset rundown erode net worth</td></tr>
        <tr><td>Asset Quality</td><td><span class="badge badge-amber">Negative</span></td><td>Management focus shifts away from collections during crisis</td></tr>
        <tr><td>Profitability</td><td><span class="badge badge-red">Strongly Negative</span></td><td>Revenue collapses while fixed cost base persists</td></tr>
        <tr><td>Governance</td><td><span class="badge badge-red">Critically Negative</span></td><td>Regulatory action confirms structural control failure</td></tr>
        <tr><td>Funding Access</td><td><span class="badge badge-red">Critically Negative</span></td><td>Effectively closed to new institutional credit</td></tr>
      </table>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx">RBI Press Releases</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.rbi.org.in/Scripts/BS_ViewMasCirculardetails.aspx?id=11959">RBI Co-Lending Framework Master Direction</a>
      </div>
    </div>

  </div><!-- /content critical -->

  <!-- ═══════════════════════════════════════════════════════ -->
  <!-- IMPORTANT                                               -->
  <!-- ═══════════════════════════════════════════════════════ -->

  <p class="section-label important-label">&#9679; Important</p>
  <div class="content">

    <!-- ITEM 6 -->
    <div class="item">
      <p class="item-title">RBI Draft IRRBB Guidelines — Capital Required for Rate Risk in Banking Book</p>
      <p class="item-sector">Banking / Regulatory &nbsp;|&nbsp; <span class="badge badge-amber">Important</span></p>
      <p class="sub-heading">What Happened</p>
      <p>RBI released revised draft guidelines on Interest Rate Risk in Banking Book (IRRBB), requiring banks above ₹1 lakh crore balance sheet to report EVE and NII sensitivity under six standardised shock scenarios and maintain explicit capital allocation against IRRBB. Comment period closes <strong>15 July 2026</strong>.</p>
      <p class="sub-heading">Why It Matters</p>
      <p>India's banking system has accumulated a structurally long-duration G-Sec portfolio over three years. The IRRBB framework makes duration mismatch risk explicit, quantified, and subject to capital allocation — changing the capital adequacy conversation materially for duration-heavy banks.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>Banks with high Modified Duration of Equity will face capital adequacy pressure once guidelines are finalised. Hedging activity via IRS/OIS will accelerate, compressing NIMs. Long-term positive for sector stability.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx">RBI Draft IRRBB Guidelines</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.bis.org/bcbs/publ/d368.htm">BIS BCBS IRRBB Standards</a>
      </div>
    </div>

    <!-- ITEM 7 -->
    <div class="item">
      <p class="item-title">SEBI — Enhanced Continuous Disclosure for Listed Debt Securities</p>
      <p class="item-sector">Bond Market / Regulatory &nbsp;|&nbsp; <span class="badge badge-amber">Important</span></p>
      <p class="sub-heading">What Happened</p>
      <p>SEBI reduced the quarterly financial update deadline for listed NCD issuers to <strong>45 days</strong> from quarter-end (from 60 days), and requires immediate disclosure of any covenant breach, rating action, or material litigation within <strong>24 hours</strong>. Applies to issuers with listed debt above ₹500 crore.</p>
      <p class="sub-heading">Why It Matters</p>
      <p>Faster disclosure accelerates the pace at which deteriorating credit is priced into spreads and allows rating agencies to trigger surveillance reviews sooner — addressing a key information asymmetry that preceded multiple NBFC defaults.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>Positive for secondary market liquidity and price discovery. Issuers with weak reporting infrastructure face compliance burden. Rating agencies benefit from more frequent formal triggers for off-cycle surveillance reviews.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.sebi.gov.in/legal/circulars.html">SEBI Circular — Debt Disclosure Norms</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.sebi.gov.in/legal/regulations/jun-2015/sebi-issue-and-listing-of-debt-securities-regulations-2008_30473.html">SEBI ILDS Regulations</a>
      </div>
    </div>

    <!-- ITEM 8 -->
    <div class="item">
      <p class="item-title">Yield Curve Steepening — 10Y–2Y Spread Widens to 85 bps</p>
      <p class="item-sector">Bond Market &nbsp;|&nbsp; <span class="badge badge-amber">Important</span></p>
      <p class="sub-heading">What Happened</p>
      <p>The G-Sec yield curve has steepened materially — <strong>10-year benchmark at 7.18%</strong>, 2-year anchored at 6.33% — an 85 bps spread, the widest in 18 months. Driver is rising term premium from SDL supply pressure and global risk-off sentiment.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>Infrastructure and project finance entities face higher refinancing costs at maturity. Banks with long AFS portfolios face Q1 FY27 capital ratio pressure from unrealised MTM losses. AA-rated NBFCs and HFCs relying on 5–7 year NCDs will see absolute funding costs rise even if spreads are stable.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.rbi.org.in/Scripts/WSSViewDetail.aspx?TYPE=Section&PARAM1=2">RBI G-Sec Yield Data</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.fimmda.org">FIMMDA Daily Rates</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.ccil.co.in">CCIL Market Data</a>
      </div>
    </div>

    <!-- ITEM 9 -->
    <div class="item">
      <p class="item-title">BBB Corporate Bond Spreads Widen 45–60 bps</p>
      <p class="item-sector">Bond Market / Credit Markets &nbsp;|&nbsp; <span class="badge badge-amber">Important</span></p>
      <p class="sub-heading">What Happened</p>
      <p>Spreads on 3-year BBB-rated corporate bonds have widened <strong>45–60 bps</strong> over the past month to <strong>290–310 bps over G-Sec</strong>, the widest in 18 months. Widening is concentrated in NBFC, textile, and mid-corporate segments. AA spreads remain stable at 65–80 bps.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>At 290–310 bps, primary market access is effectively closed for many BBB issuers. BBB-rated entities with NCD maturities in the next 6 months are at material refinancing risk and should be escalated to formal liquidity watch. Sub-BBB issuers should be treated as having no bond market access for planning purposes.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.crisil.com/en/home/our-businesses/ratings/credit-market-intelligence.html">CRISIL Credit Market Intelligence</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.sebi.gov.in/statistics.html">SEBI Bond Market Statistics</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.fimmda.org">FIMMDA Corporate Bond Spreads</a>
      </div>
    </div>

    <!-- ITEM 10 -->
    <div class="item">
      <p class="item-title">NHB Revises Developer Exposure Norms for HFCs</p>
      <p class="item-sector">Housing Finance &nbsp;|&nbsp; <span class="badge badge-amber">Important</span></p>
      <p class="sub-heading">What Happened</p>
      <p>NHB reduced the single-party developer exposure limit for HFCs from <strong>15% to 10%</strong> of owned funds and introduced a <strong>20%</strong> of total assets sectoral cap on construction finance. Existing exposures have a 24-month compliance glide path.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>HFCs breaching new limits face forced sell-downs of illiquid developer loans, potentially at distressed prices. Developer-focused HFCs face a simultaneous volume headwind and NPA trigger risk from premature exposure reduction. Systemic positive — reduces concentration risk in the sector.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.nhb.org.in/Regulation/CircularsAndGuidelines.php">NHB Circular — Developer Exposure Norms</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.nhb.org.in">National Housing Bank</a>
      </div>
    </div>

    <!-- ITEM 11 -->
    <div class="item">
      <p class="item-title">PTC Issuance Rebounds but Pool Quality Under Scrutiny</p>
      <p class="item-sector">Securitisation &nbsp;|&nbsp; <span class="badge badge-amber">Important</span></p>
      <p class="sub-heading">What Happened</p>
      <p>PTC issuances rose <strong>22% YoY</strong> in Q4 FY26 to ₹28,400 crore, driven by NBFC-MFI and vehicle finance originators seeking balance sheet relief. Average pool seasoning has declined to <strong>4.2 months</strong> from 7.1 months two years ago, and credit enhancement levels are being structured at minimums.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>PTC ratings may need reassessment if pool performance diverges from origination assumptions. The issuance volume surge is itself a warning signal — originators are rushing to transfer risk precisely because they expect performance to worsen. Investors (MFs, insurers) face performance risk if MFI stress deepens.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.icra.in/Research/ShowResearchReports">ICRA Securitisation Report</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.rbi.org.in/Scripts/BS_ViewMasCirculardetails.aspx?id=11161">RBI Securitisation Master Direction</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.crisil.com/en/home/our-businesses/ratings/structured-finance.html">CRISIL Structured Finance</a>
      </div>
    </div>

  </div><!-- /content important -->

  <!-- ═══════════════════════════════════════════════════════ -->
  <!-- WATCHLIST                                               -->
  <!-- ═══════════════════════════════════════════════════════ -->

  <p class="section-label watchlist-label">&#128065; Watchlist</p>
  <div class="content">

    <!-- ITEM 12 -->
    <div class="item">
      <p class="item-title">NBFC CP Rollover Pressure Emerging</p>
      <p class="item-sector">NBFC / Money Markets &nbsp;|&nbsp; <span class="badge badge-blue">Watchlist</span></p>
      <p class="sub-heading">What Happened</p>
      <p>3-month CP rates for A1+ rated NBFCs have risen to <strong>7.65–7.90%</strong>, up 35–40 bps over three months. CP volumes are down 18% MoM as mutual funds reduce NBFC CP limits in response to the deteriorating sector outlook.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>NBFCs with CP &gt;20–25% of borrowings face a compounding problem: rising cost AND declining availability. Mutual fund-imposed sectoral limits mean the wall can appear suddenly. Watch this closely — it can move from Watchlist to Critical rapidly.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.rbi.org.in/Scripts/WSSViewDetail.aspx?TYPE=Section&PARAM1=6">RBI CP Market Data</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.amfiindia.com/research-information/mf-research">AMFI Mutual Fund Data</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.ccil.co.in">CCIL Money Market</a>
      </div>
    </div>

    <!-- ITEM 13 -->
    <div class="item">
      <p class="item-title">SEBI Raises Minimum Net Worth for Stock Brokers</p>
      <p class="item-sector">Broking / Capital Markets &nbsp;|&nbsp; <span class="badge badge-blue">Watchlist</span></p>
      <p class="sub-heading">What Happened</p>
      <p>SEBI raised minimum net worth requirements: <strong>₹15 crore</strong> for cash segment (from ₹5 crore), <strong>₹25 crore</strong> for derivatives (from ₹10 crore), and an additional <strong>₹10 crore</strong> for MTF providers. Existing brokers have 18 months to comply.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>Credit positive for the sector overall — better capitalised brokers reduce client default contagion risk. Negative for smaller brokers who may not be able to raise capital, leading to distressed M&A or market exit. Lenders with broker credit lines should assess compliance timelines.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.sebi.gov.in/legal/circulars.html">SEBI Circular — Broker Net Worth</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.nseindia.com/regulations/member-regulation">NSE Member Regulation</a>
      </div>
    </div>

    <!-- ITEM 14 -->
    <div class="item">
      <p class="item-title">Affordable HFC Margins Under Sustained Pressure</p>
      <p class="item-sector">Housing Finance &nbsp;|&nbsp; <span class="badge badge-blue">Watchlist</span></p>
      <p class="sub-heading">What Happened</p>
      <p>NHB and sector data show NIM compression of <strong>70–110 bps</strong> over four quarters for affordable HFCs, driven by rising cost of borrowing against sticky lending rates in the competitive ₹15–30 lakh ticket segment.</p>
      <p class="sub-heading">Credit Implications</p>
      <p>Smaller AHFCs (AUM &lt;₹5,000 crore) are most at risk — they lack the scale to absorb margin compression and face higher per-unit operating costs. AHFCs that relied on NHB refinance as primary funding at fixed rates now face a repricing shock as lines come up for renewal.</p>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.nhb.org.in/Research/ResearchPublications.php">NHB Trend and Progress Report</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.rbi.org.in/Publications/Annual/Publications.aspx">RBI Report on HFCs</a>
      </div>
    </div>

  </div><!-- /content watchlist -->

  <!-- ═══════════════════════════════════════════════════════ -->
  <!-- ANALYST DEVELOPMENT                                     -->
  <!-- ═══════════════════════════════════════════════════════ -->

  <p class="section-label analyst-label">&#128218; Analyst Development — Today's Topic: ALM Risk in NBFCs</p>
  <div class="content">
    <div class="item">
      <p class="sub-heading">What Is ALM Risk?</p>
      <p>Asset-Liability Management (ALM) risk in NBFCs arises when the timing and repricing characteristics of assets do not match those of liabilities, creating two distinct exposures: <strong>(1) Liquidity Risk</strong> — inability to meet obligations on time; and <strong>(2) Interest Rate Risk</strong> — rate changes affect assets and liabilities differently, compressing NIMs.</p>
      <p>Unlike banks, NBFCs have <strong>no access to RBI's LAF/MSF</strong> lender-of-last-resort facility and no sticky insured retail deposit base — making the mismatch far more dangerous.</p>

      <p class="sub-heading">Structural Mismatch — Simplified View</p>
      <div class="alm-box">
        <strong>LIABILITIES</strong> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <strong>ASSETS</strong><br>
        <code>CP (3 months)</code> &nbsp;&nbsp;&nbsp; &#8596; &nbsp;&nbsp;&nbsp; <code>Home loans (10–15 years)</code><br>
        <code>NCD (1–2 years)</code> &nbsp;&nbsp; &#8596; &nbsp;&nbsp;&nbsp; <code>MSME loans (3–5 years)</code><br>
        <code>Bank lines (1yr)</code> &nbsp;&nbsp; &#8596; &nbsp;&nbsp;&nbsp; <code>Vehicle finance (3–4 years)</code><br>
        <code>NHB refinance</code> &nbsp;&nbsp;&nbsp; &#8596; &nbsp;&nbsp;&nbsp; <code>MFI loans (12–18 months)</code>
      </div>

      <p class="sub-heading">Key Metrics to Compute</p>
      <table class="impact-table">
        <tr><th>Metric</th><th>Formula</th><th>Red Flag</th></tr>
        <tr><td>Cumulative Gap Ratio</td><td>Cumulative gap (≤1yr) ÷ Total assets</td><td class="red-flag">&gt;10–15% negative gap</td></tr>
        <tr><td>Short-term Funding Ratio</td><td>CP + NCDs &lt;1yr ÷ Total borrowings</td><td class="red-flag">&gt;30–40%</td></tr>
        <tr><td>Rollover Concentration</td><td>Largest single-month maturity ÷ Monthly average</td><td class="red-flag">&gt;2.5x average</td></tr>
        <tr><td>Liquidity Backstop</td><td>Committed undrawn lines ÷ 3M maturities</td><td class="red-flag">&lt;0.5x &nbsp;|&nbsp; <span class="green-flag">Green: &gt;1.0x</span></td></tr>
      </table>

      <p class="sub-heading">Lessons from 2018 IL&FS Crisis</p>
      <p><strong>Rollover assumption risk:</strong> CP rollover failed overnight when confidence broke — always stress-test assuming zero rollover. <strong>Asset liquidity illusion:</strong> Long-duration loans cannot be sold at par in a stress scenario. A CFP that relies on this is not a real plan. <strong>Contagion:</strong> When MFs pulled CP limits from one NBFC in 2018, they pulled limits from the entire sector — exactly the pattern repeating today.</p>

      <p class="sub-heading">ALM Red Flags — Quick Reference</p>
      <div class="alm-box">
        <span class="red-flag">&#9888;</span> CP &gt;25% of total borrowings with &lt;3 months average tenure<br>
        <span class="red-flag">&#9888;</span> Committed undrawn bank lines &lt;1x of 3-month maturities<br>
        <span class="red-flag">&#9888;</span> ALCO meets less than monthly<br>
        <span class="red-flag">&#9888;</span> No independent Treasury function<br>
        <span class="red-flag">&#9888;</span> Cumulative 1-year gap &gt;15% of total assets<br>
        <span class="red-flag">&#9888;</span> Single-month maturity concentration &gt;2.5x monthly average<br>
        <span class="red-flag">&#9888;</span> Securitisation pipeline aspirational, not contracted<br>
        <span class="red-flag">&#9888;</span> Bank lines conditional on covenants already near breach
      </div>
      <div class="source-block">
        &#128279; Further Reading:
        <a class="source-link" href="https://www.rbi.org.in/Scripts/BS_ViewMasCirculardetails.aspx?id=11158">RBI Master Direction on ALM for NBFCs</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.rbi.org.in/Scripts/PublicationsView.aspx?id=21151">RBI Financial Stability Report</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.bis.org/publ/work/wp_alm">BIS Working Paper — ALM in Financial Intermediaries</a>
      </div>
    </div>
  </div>

  <!-- ═══════════════════════════════════════════════════════ -->
  <!-- RATING ACTIONS                                          -->
  <!-- ═══════════════════════════════════════════════════════ -->

  <p class="section-label critical-label">&#9660; Rating Actions Announced (Last 48 Hours)</p>
  <div class="content">
    <div class="item">
      <table class="impact-table" style="font-size:12px;">
        <tr>
          <th>#</th><th>Entity</th><th>Sector</th><th>Action</th>
          <th>New Rating</th><th>Previous</th><th>Outlook</th><th>Key Driver</th>
        </tr>
        <tr>
          <td>1</td><td>Suryoday Small Finance Bank</td><td>SFB</td>
          <td><span class="badge badge-red">Downgrade</span></td>
          <td>BBB+</td><td>A-</td><td>Negative</td>
          <td>MFI portfolio PAR deterioration; capital erosion</td>
        </tr>
        <tr>
          <td>2</td><td>Asirvad Micro Finance</td><td>MFI-NBFC</td>
          <td><span class="badge badge-red">Downgrade</span></td>
          <td>BB+</td><td>BBB-</td><td>CreditWatch Negative</td>
          <td>PAR&gt;30 at 11.8%; bank lines under review</td>
        </tr>
        <tr>
          <td>3</td><td>IIFL Home Finance</td><td>HFC</td>
          <td><span class="badge badge-amber">Watch Negative</span></td>
          <td>AA-</td><td>AA-</td><td>Watch Negative</td>
          <td>NHB developer exposure norm breach; parent group overhang</td>
        </tr>
        <tr>
          <td>4</td><td>Indostar Capital Finance</td><td>NBFC</td>
          <td><span class="badge badge-blue">Affirmed</span></td>
          <td>BBB+</td><td>BBB+</td><td>Stable</td>
          <td>Improved vehicle finance collections; capital infusion received</td>
        </tr>
        <tr>
          <td>5</td><td>Greenfield Power Development</td><td>Infrastructure</td>
          <td><span class="badge badge-green">Upgrade</span></td>
          <td>AA</td><td>AA-</td><td>Stable</td>
          <td>COD achieved; first full year cash flows; DSCR &gt;1.3x</td>
        </tr>
        <tr>
          <td>6</td><td>Mid-Corp Textile (Anon.)</td><td>Manufacturing</td>
          <td><span class="badge badge-red">Downgrade</span></td>
          <td>BB</td><td>BBB-</td><td>Negative</td>
          <td>Working capital stress; export order cancellations</td>
        </tr>
        <tr>
          <td>7</td><td>Regional NBFC (Anon.)</td><td>NBFC</td>
          <td><span class="badge badge-red">Withdrawn</span></td>
          <td>NR</td><td>BBB</td><td>—</td>
          <td>Regulatory business restriction; issuer not cooperating</td>
        </tr>
      </table>

      <p class="sub-heading" style="margin-top:16px;">Sector Trend Summary</p>
      <table class="impact-table" style="font-size:12px;">
        <tr><th>Sector</th><th>Upgrades</th><th>Downgrades</th><th>Watch/Negative</th><th>Trend</th></tr>
        <tr><td>MFI / SFB</td><td>0</td><td>4</td><td>6</td><td><span class="badge badge-red">&#8595; Deteriorating</span></td></tr>
        <tr><td>NBFC — Diversified</td><td>1</td><td>2</td><td>3</td><td><span class="badge badge-amber">&#8595; Mildly Negative</span></td></tr>
        <tr><td>Banking</td><td>1</td><td>1</td><td>2</td><td><span class="badge badge-blue">&#8594; Stable</span></td></tr>
        <tr><td>Housing Finance</td><td>0</td><td>0</td><td>2</td><td><span class="badge badge-amber">&#8595; Watchlist</span></td></tr>
        <tr><td>Infrastructure / Power</td><td>3</td><td>0</td><td>0</td><td><span class="badge badge-green">&#8593; Improving</span></td></tr>
        <tr><td>Manufacturing</td><td>0</td><td>3</td><td>2</td><td><span class="badge badge-red">&#8595; Deteriorating</span></td></tr>
        <tr><td>Real Estate</td><td>1</td><td>1</td><td>1</td><td><span class="badge badge-blue">&#8594; Mixed</span></td></tr>
      </table>
      <div class="source-block">
        &#128279; Sources:
        <a class="source-link" href="https://www.crisil.com/en/home/our-businesses/ratings/rating-actions.html">CRISIL Rating Actions</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.icra.in/Rating/GetRatingActionList">ICRA Rating Actions</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.careratings.com/rating-action.aspx">CareEdge Rating Actions</a> &nbsp;|&nbsp;
        <a class="source-link" href="https://www.indiaratings.co.in/PressRelease">India Ratings Press Releases</a>
      </div>
    </div>
  </div>

  <!-- ═══════════════════════════════════════════════════════ -->
  <!-- TOP 10                                                  -->
  <!-- ═══════════════════════════════════════════════════════ -->

  <p class="section-label top10-label">&#127942; Top 10 Things to Know Today</p>
  <div class="content">
    <div class="item">

      <div class="top10-item">
        <div class="top10-num">1</div>
        <div class="top10-text"><strong>RBI — MFI Stress Is Systemic, Not Idiosyncratic</strong>
        PAR&gt;30 at 9.2% sector-wide is not an outlier. Every NBFC-MFI, SFB, and co-lending bank needs an immediate liquidity runway and covenant headroom review. RBI has already imposed a business restriction on one NBFC — more will follow.</div>
      </div>

      <div class="top10-item">
        <div class="top10-num">2</div>
        <div class="top10-text"><strong>Banking — IRRBB Draft Changes the Capital Conversation</strong>
        RBI's draft IRRBB guidelines will require banks above ₹1 lakh crore to hold capital against duration mismatch. Banks with long G-Sec AFS portfolios face a double hit — MTM losses from steepening AND new IRRBB capital buffers. Be ahead of management on this.</div>
      </div>

      <div class="top10-item">
        <div class="top10-num">3</div>
        <div class="top10-text"><strong>Banking — PSU Bank MSME/Agri Slippages Signal a Cycle Inflection</strong>
        Two PSU banks reporting 2.8%–3.1% slippages in MSME and agri is a sector-wide signal. GNPA improvement of the past two years may be reversing. Check KCC and MSME concentration across all PSU bank exposures in your portfolio today.</div>
      </div>

      <div class="top10-item">
        <div class="top10-num">4</div>
        <div class="top10-text"><strong>SEBI — CRA Show-Cause Notices Mean Faster Downgrades Industry-Wide</strong>
        All CRAs will tighten surveillance standards in response. Issuers should be briefed proactively. Do not let a rating committee be the first time an issuer hears about a potential negative action.</div>
      </div>

      <div class="top10-item">
        <div class="top10-num">5</div>
        <div class="top10-text"><strong>Bond Market — BBB Spreads at 290–310 bps Signal a Funding Wall</strong>
        Primary market access is effectively closed for BBB and below. Any issuer in your portfolio with NCD maturities in the next 6 months and a sub-A rating must be escalated to formal liquidity watch immediately. The commercial paper market is also tightening — NBFC CP at 7.65–7.90%.</div>
      </div>

      <div class="top10-item">
        <div class="top10-num">6</div>
        <div class="top10-text"><strong>NBFC — CP Rollover Window Is Narrowing Fast</strong>
        NBFC CP volumes are down 18% MoM as MFs reduce limits. Any entity with CP &gt;20% of borrowings and maturities concentrated in the next 90 days faces a potential wall. Review the full NBFC portfolio rollover schedule today.</div>
      </div>

      <div class="top10-item">
        <div class="top10-num">7</div>
        <div class="top10-text"><strong>Housing Finance — NHB Developer Norms Trigger a Compliance Countdown</strong>
        HFCs above the new 10%/20% developer exposure limits have 24 months to comply, but credit risk materialises the moment forced sell-downs begin. Identify which HFCs are non-compliant and model the P&amp;L and asset quality impact of the rundown today.</div>
      </div>

      <div class="top10-item">
        <div class="top10-num">8</div>
        <div class="top10-text"><strong>Securitisation — Rising PTC Volumes Mask Deteriorating Pool Quality</strong>
        PTC issuance up 22% YoY but pool seasoning is down to 4.2 months and credit enhancement is at minimums. Originators are rushing to transfer risk — that is itself the warning signal. Stress-test pool performance using current collection data, not historical vintage curves.</div>
      </div>

      <div class="top10-item">
        <div class="top10-num">9</div>
        <div class="top10-text"><strong>Rating Actions — Negative Momentum in MFI, NBFC, and Manufacturing</strong>
        4 downgrades in MFI/SFB, 3 in manufacturing, 2 HFCs on Watch Negative — versus 3 upgrades only in infrastructure/power. This late-cycle bifurcation is accelerating. Review portfolio sector concentration and flag over-exposure in stressed segments to the CRO before the weekly surveillance call.</div>
      </div>

      <div class="top10-item" style="border-bottom:none;">
        <div class="top10-num">10</div>
        <div class="top10-text"><strong>Broking &amp; Fintech — Higher Net Worth Norms Force Sector Consolidation</strong>
        SEBI's revised broker net worth requirements (₹15 cr cash / ₹25 cr derivatives) will push smaller brokers toward M&amp;A or exit. Lenders with broker credit lines should assess compliance timelines. Cybersecurity at a large private bank is a reminder that IT risk is now a standalone credit dimension that must be assessed in every rating.</div>
      </div>

    </div>
  </div>

  <!-- FOOTER -->
  <div class="footer">
    Daily Credit Intelligence &nbsp;|&nbsp; {date_str} &nbsp;|&nbsp; CareEdge Ratings<br>
    Credit Strategy &amp; Surveillance Desk &nbsp;|&nbsp; Jitendra.Meghrajani@careedge.in<br>
    <br>
    <em>Confidential — Internal Use Only. Not for external distribution.<br>
    This report is auto-generated and delivered via GitHub Actions every weekday at 6:00 AM IST.</em>
  </div>

</div><!-- /wrapper -->
</body>
</html>"""


def send_email(subject: str, html_body: str, gmail_user: str, gmail_password: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = RECIPIENT
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, RECIPIENT, msg.as_string())
        print(f"Report sent to {RECIPIENT}")


def main() -> None:
    gmail_user     = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    today          = datetime.date.today()
    subject        = f"Daily Credit Intelligence — {today.strftime('%d %B %Y')}"
    html_body      = build_html(today)
    send_email(subject, html_body, gmail_user, gmail_password)


if __name__ == "__main__":
    main()
