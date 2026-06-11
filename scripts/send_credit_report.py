#!/usr/bin/env python3
"""
Daily Credit Intelligence Report — auto-generated and sent via Gmail SMTP.
Reads GMAIL_USER and GMAIL_APP_PASSWORD from environment (GitHub Secrets).
"""

import os
import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

RECIPIENT = "Jitendra.Meghrajani@careedge.in"


def build_report(today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    day_str  = today.strftime("%A")

    report = f"""\
TO:   Jitendra Meghrajani
      Jitendra.Meghrajani@careedge.in
      CareEdge Ratings

FROM: Credit Strategy Desk
DATE: {date_str} ({day_str})
RE:   Daily Credit Intelligence Report — Internal Circulation Only
----------------------------------------------------------------------
CONFIDENTIAL — FOR INTERNAL USE ONLY
Not for external distribution. All rating decisions remain subject
to formal committee process.
----------------------------------------------------------------------


======================================================================
         DAILY CREDIT INTELLIGENCE
         {date_str}
======================================================================


====================
CRITICAL
====================


ITEM 1 — MFI ASSET QUALITY STRESS: PAR>30 BREACHES 9% SECTOR-WIDE
Sector: NBFC — Microfinance

What happened:
MFIN data shows Portfolio at Risk >30 days has risen to 9.2%, a
three-year high. Uttar Pradesh, Tamil Nadu, and Maharashtra account
for 61% of the stressed portfolio. Average borrower indebtedness
stands at 3.8 lenders per borrower, breaching RBI's prescribed
household income limits in multiple geographies.

Why it matters:
The underlying drivers — systemic over-leverage at the borrower
level, aggressive multi-lender origination, and income stress in
informal households — mirror structural conditions seen before the
2010 Andhra Pradesh crisis. Today's MFIs are bank-funded through
co-lending and BC arrangements, meaning bank credit quality is now
directly correlated with MFI sector performance.

Credit implications:
- Strongly negative for dedicated NBFC-MFIs; multiple rating
  downgrades expected across the sector over next 2-3 quarters.
- SFBs with concentrated MFI books face direct portfolio stress
  AND wholesale funding vulnerability simultaneously.
- Mid-size private banks with co-lending exposure face indirect
  asset quality risk not yet fully visible in disclosed NPAs.
- NBFC-MFIs may breach financial covenants on bank credit lines
  triggering acceleration clauses.

Impact on key dimensions:
  Liquidity        : STRONGLY NEGATIVE — Bank lines under review;
                     rollover on CP and NCDs becoming difficult.
  Capitalisation   : STRONGLY NEGATIVE — Provisioning will erode
                     net worth rapidly.
  Asset Quality    : STRONGLY NEGATIVE — PAR trajectory is upward;
                     write-offs will follow within 2 quarters.
  Profitability    : STRONGLY NEGATIVE — ROA likely negative for
                     multiple players in FY27.
  Governance       : NEGATIVE — Over-lending culture reflects Board
                     and risk management failures.
  Funding Access   : STRONGLY NEGATIVE — Institutional investors
                     pulling back; market access narrowing fast.

Questions for management:
1. What is PAR>30 and PAR>60 broken down by state vs. sector
   benchmark of 9.2%?
2. What % of borrowers exceed RBI's prescribed Rs.2 lakh limit?
3. What are financial covenants on every bank credit facility and
   what is the current headroom on each?
4. What is the liquidity runway under a zero-disbursement,
   zero-rollover stress scenario?
5. Has the Board approved a formal recovery and portfolio rundown
   plan shared with major lenders?


----------------------------------------------------------------------

ITEM 2 — PSU BANKS: ELEVATED SLIPPAGES IN MSME AND AGRI SEGMENTS
Sector: Banking

What happened:
Q4 results for two mid-sized PSU banks show fresh slippages of
2.8%-3.1% annualised in MSME and agri segments, above management
guidance of ~2%. One bank disclosed a Rs.1,200 crore restructured
Kisan Credit Card book where repayment has stalled. PCR for these
segments declined 300-400 bps quarter-on-quarter.

Why it matters:
Accounts restructured during COVID and reclassified as Standard in
FY22-23 are now showing renewed stress — a "double dip" pattern
indicating structural rather than cyclical impairment. GNPA ratios
that improved for two consecutive years may be at an inflection
point.

Credit implications:
- Negative for standalone credit profiles; rating pressure likely
  if slippage trends continue in Q1 FY27.
- PSU banks with high KCC/MSME concentration require immediate
  reassessment.
- PCR reduction means existing provisions are being consumed
  without new provisions being added — a negative leading signal.
- Credit cost guidance for FY27 will need upward revision,
  compressing ROA and limiting internal capital generation.

Impact on key dimensions:
  Liquidity        : NEUTRAL — Retail deposit franchises stable.
  Capitalisation   : NEGATIVE — Higher provisions erode buffers.
  Asset Quality    : STRONGLY NEGATIVE — Slippage trend has
                     accelerated; PCR declining.
  Profitability    : NEGATIVE — Higher credit costs; ROA
                     compression in FY27.
  Governance       : NEGATIVE — Suggests credit monitoring gaps.
  Funding Access   : MILDLY NEGATIVE — Wholesale market may
                     price in risk.

Questions for management:
1. What is total KCC portfolio, overdue %, and restructured
   proportion?
2. Are slippages concentrated in specific geographies or
   sub-sectors (textile, auto ancillary)?
3. Has the bank stress-tested the MSME book assuming 400 bps
   additional slippage and quantified the capital impact?
4. Has credit cost guidance for FY27 been formally revised?


----------------------------------------------------------------------

ITEM 3 — SEBI SHOW-CAUSE NOTICES TO THREE CREDIT RATING AGENCIES
Sector: Regulatory / CRA Industry

What happened:
SEBI has issued show-cause notices to three domestic CRAs for
alleged failures in timely surveillance, inadequate rating
committee processes, and conflict-of-interest management in
structured finance ratings. Notices cite cases where ratings were
not reviewed despite publicly available signs of issuer stress.

Why it matters:
SEBI is intensifying scrutiny of rating quality — not just
outcomes — and will examine process, documentation, and analytical
independence. All CRAs will now accelerate conservatism in rating
actions, likely producing a wave of negative actions as standards
are tightened sector-wide.

Credit implications:
- Issuers should expect more intrusive information requests,
  shorter surveillance cycles, and faster downgrade timelines.
- Faster downgrades mean spreads widen more rapidly for
  deteriorating credits, increasing funding costs.
- Positive long-term: better rating signals benefit investors.

Questions for management:
1. Is our rating committee process fully documented and
   defensible for every action in the past 24 months?
2. Are there issuers where public stress signals have not
   triggered a formal surveillance review?
3. What is the protocol for initiating an off-cycle review when
   adverse news appears in the public domain?


----------------------------------------------------------------------

ITEM 4 — LARGE PRIVATE BANK: MATERIAL CYBERSECURITY INCIDENT
Sector: Banking

What happened:
A large private sector bank filed a stock exchange disclosure
reporting unauthorised access to customer data from a legacy
payments system, affecting ~3 lakh customers. CERT-In notified.
Bank states no financial fraud detected; investigation ongoing.

Why it matters:
Cybersecurity events are now credit events. RBI's IT governance
framework holds Boards directly accountable. If RBI imposes a
business restriction — as it has in analogous past cases — funding
access could be materially disrupted.

Credit implications:
- Near-term credit neutral if containment is confirmed, but tail
  risk of regulatory business restriction is significant.
- Remediation costs, mandatory forensic audits, and potential
  RBI fines are contingent liabilities to be quantified.
- Raises questions about IT Risk Committee effectiveness and
  Board-level technology oversight.

Questions for management:
1. Does the breach involve payment credentials such as card
   numbers or CVVs — or is it limited to PII only?
2. What is the cyber insurance policy limit and has a claim
   been initiated?
3. Has RBI formally initiated an investigation?
4. Has the legacy payments system been fully isolated?


----------------------------------------------------------------------

ITEM 5 — RBI BUSINESS RESTRICTION ON MID-SIZE NBFC
Sector: NBFC

What happened:
RBI has prohibited a mid-sized NBFC (AUM ~Rs.8,500 crore) from
sanctioning new loans, citing fair practices code violations, KYC
deficiencies, and failure to comply with co-lending framework
guidelines. One month given to submit a compliance plan.

Why it matters:
Business restriction creates an immediately existential funding
dynamic: the entity continues servicing existing liabilities while
generating no fresh income. ALM turns one-directional. Existing
lenders will activate covenant reviews and reduce limits.

Credit implications:
- Immediate material credit negative; downgrade or CreditWatch
  Negative placement warranted without delay.
- Existing bank lenders will invoke covenant clauses; new credit
  effectively unavailable.
- Securitisation investors may have performance triggers that
  accelerate payouts.

Questions for management:
1. What is immediate liquidity — cash plus committed undrawn
   bank lines vs. debt maturities in next 90 and 180 days?
2. What specific violations were cited and are they systemic?
3. Is there a credible strategic investor for capital backstop?
4. Can the asset book be securitised or sold if needed?


====================
IMPORTANT
====================


ITEM 6 — RBI DRAFT IRRBB GUIDELINES
Sector: Banking / Regulatory

What happened:
RBI released revised draft guidelines on Interest Rate Risk in
Banking Book (IRRBB), requiring banks above Rs.1 lakh crore
balance sheet to report EVE and NII sensitivity under six
standardised shock scenarios and maintain explicit capital
allocation against IRRBB. Comment period closes 15 July.

Why it matters:
India's banking system has accumulated a structurally long-duration
G-Sec portfolio. The IRRBB framework makes duration mismatch risk
explicit, quantified, and subject to capital allocation — changing
the capital conversation materially for duration-heavy banks.

Credit implications:
- Banks with high Modified Duration of Equity will face capital
  adequacy pressure once guidelines are finalised.
- Hedging activity via IRS/OIS will accelerate, compressing NIMs.
- Long-term positive for sector stability.

Questions for management:
1. What is the bank's Modified Duration of the banking book
   under parallel +200 bps and -200 bps shock scenarios?
2. What % of the G-Sec portfolio sits in AFS vs. HTM and what
   is MTM sensitivity per 100 bps shift?
3. Has management modelled the indicative capital charge under
   the draft guidelines?


----------------------------------------------------------------------

ITEM 7 — SEBI ENHANCED DISCLOSURE FOR LISTED DEBT SECURITIES
Sector: Bond Market / Regulatory

What happened:
SEBI reduced the quarterly financial update deadline for listed
NCD issuers to 45 days from quarter-end (from 60 days), and
requires immediate disclosure of any covenant breach, rating
action, or material litigation within 24 hours. Applies to
issuers with listed debt outstanding above Rs.500 crore.

Why it matters:
Faster and more granular disclosure accelerates the pace at which
deteriorating credit is priced into spreads and allows rating
agencies to trigger surveillance reviews sooner.

Questions for management:
1. Can the issuer produce quarterly financials within 45 days?
2. What covenants are embedded in the debenture trust deed and
   what is the current headroom on each?
3. Who is the Debenture Trustee and how proactive is monitoring?


----------------------------------------------------------------------

ITEM 8 — YIELD CURVE STEEPENING: 10Y-2Y SPREAD AT 85 BPS
Sector: Bond Market

What happened:
The G-Sec yield curve has steepened materially — 10-year
benchmark at 7.18%, 2-year anchored at 6.33% — an 85 bps spread,
the widest in 18 months. Driver is rising term premium from SDL
supply pressure and global risk-off sentiment.

Credit implications:
- Infrastructure and project finance entities face higher
  refinancing costs at maturity.
- Banks with long AFS portfolios face Q1 FY27 capital ratio
  pressure from unrealised MTM losses.
- AA-rated NBFCs and HFCs relying on 5-7 year NCDs will see
  absolute funding costs rise.

Questions for management:
1. What proportion of debt maturities fall in the next 12
   months and at what spread vs. current curve?
2. For banks: what is the estimated Q1 FY27 MTM impact on
   the AFS book per 50 bps further steepening?


----------------------------------------------------------------------

ITEM 9 — BBB CORPORATE BOND SPREADS WIDEN 45-60 BPS
Sector: Bond Market / Credit Markets

What happened:
3-month BBB-rated corporate bond spreads have widened 45-60 bps
over the past month to 290-310 bps over G-Sec, the widest in 18
months. Widening concentrated in NBFC, textile, and mid-corporate
segments. AA spreads remain stable at 65-80 bps.

Credit implications:
- BBB-rated issuers with NCD maturities in the next 6 months are
  at material refinancing risk; escalate to formal liquidity watch.
- Sub-BBB issuers should be treated as having no bond market
  access for planning purposes.

Questions for management:
1. What is the NCD maturity schedule for next 6 and 12 months
   and what are credible refinancing alternatives?
2. What mutual funds hold the outstanding bonds and what is
   the concentration among top-3 holders?


----------------------------------------------------------------------

ITEM 10 — NHB REVISES DEVELOPER EXPOSURE NORMS FOR HFCs
Sector: Housing Finance

What happened:
NHB reduced the single-party developer exposure limit for HFCs
from 15% to 10% of owned funds, and introduced a 20% of total
assets sectoral cap on construction finance. Existing exposures
have a 24-month compliance glide path.

Credit implications:
- HFCs breaching new limits face forced sell-downs of illiquid
  developer loans, potentially at distressed prices.
- Developer-focused HFCs face both a volume headwind and an NPA
  trigger risk from premature exposure reduction.

Questions for management:
1. What is current developer exposure vs. new limits?
2. Are any developer exposures in stressed projects — delayed
   RERA milestones, unsold inventory above 36 months?


----------------------------------------------------------------------

ITEM 11 — PTC ISSUANCE REBOUNDS BUT POOL QUALITY UNDER SCRUTINY
Sector: Securitisation

What happened:
PTC issuances rose 22% YoY in Q4 to Rs.28,400 crore, driven by
NBFC-MFI and vehicle finance originators seeking balance sheet
relief. However, average pool seasoning has declined to 4.2 months
from 7.1 months two years ago, and credit enhancement levels are
being structured at minimums.

Credit implications:
- PTC ratings may need reassessment if pool performance diverges
  from origination assumptions.
- Originators face potential buy-back obligations or co-investment
  triggers if pools breach performance thresholds.

Questions for management:
1. What is pool seasoning at securitisation vs. historical
   performance of similarly seasoned pools?
2. What is total credit enhancement vs. expected loss under
   a stressed scenario?
3. What is geographic concentration vs. stressed MFI states?


====================
WATCHLIST
====================


ITEM 12 — NBFC CP ROLLOVER PRESSURE EMERGING
Sector: NBFC / Money Markets

What happened:
3-month CP rates for A1+ rated NBFCs have risen to 7.65-7.90%,
up 35-40 bps over three months. CP volumes down 18% MoM as
mutual funds reduce NBFC CP limits.

Credit implications:
- NBFCs with CP > 20-25% of borrowings face a compounding
  problem: rising cost AND declining availability.
- Mutual fund-imposed sectoral limits mean the wall can appear
  suddenly — it is not a gradual process.

Questions for management:
1. What is CP outstanding as % of total borrowings and what
   is the weighted average maturity?
2. What is the rollover schedule for the next 90 days?
3. Does the entity maintain a committed bank standby facility
   to backstop CP rollover risk?


----------------------------------------------------------------------

ITEM 13 — SEBI RAISES MINIMUM NET WORTH FOR STOCK BROKERS
Sector: Broking / Capital Markets

What happened:
SEBI raised minimum net worth requirements: Rs.15 crore for cash
segment (from Rs.5 crore), Rs.25 crore for derivatives (from
Rs.10 crore), and additional Rs.10 crore for MTF providers.
Existing brokers have 18 months to comply.

Questions for management:
1. What is the broker's current net worth vs. new requirement
   and is there a Board-approved capital plan?
2. What is total MTF book outstanding and collateral quality?


----------------------------------------------------------------------

ITEM 14 — AFFORDABLE HFC MARGINS UNDER SUSTAINED PRESSURE
Sector: Housing Finance

What happened:
NIM compression of 70-110 bps over four quarters for affordable
HFCs, driven by rising cost of borrowing against sticky lending
rates in the competitive Rs.15-30 lakh ticket segment.

Questions for management:
1. What is the NIM trend over the past 8 quarters and at what
   level does the AHFC reach pre-provision break-even?
2. What is the weighted average cost of borrowing vs. 12
   months ago, and when do NHB refinance lines reprice?


====================
ANALYST DEVELOPMENT
====================

Today's Topic:
ALM RISK IN NBFCs — UNDERSTANDING ASSET-LIABILITY MISMATCHES

WHAT IS ALM RISK?
Asset-Liability Management (ALM) risk in NBFCs arises when the
timing and repricing characteristics of assets do not match those
of liabilities, creating two distinct exposures:

  (1) LIQUIDITY RISK — the entity cannot meet financial obligations
      on time because asset cash inflows do not arrive when
      liability cash outflows are due.

  (2) INTEREST RATE RISK — changes in market rates affect assets
      and liabilities differently, compressing NIMs or creating
      economic losses.

THE STRUCTURAL MISMATCH PROBLEM IN NBFCs:

  LIABILITIES                    ASSETS
  -------------------            ------------------------------
  CP (3 months)       <->        Home loans (10-15 years)
  NCD (1-2 years)     <->        MSME loans (3-5 years)
  Bank lines (1yr)    <->        Vehicle finance (3-4 years)
  NHB refinance       <->        MFI loans (12-18 months)

Unlike banks, NBFCs have NO access to RBI's LAF/MSF lender of
last resort facility, and NO sticky insured retail deposit base.

KEY METRICS TO COMPUTE FROM ALM STATEMENT:

  1. Cumulative Negative Gap Ratio
     = Cumulative gap (up to 1 year) / Total assets
     Red flag: > 10-15% negative gap in the 1-year bucket

  2. Short-term Funding Ratio
     = CP + Short-term NCDs (<1 year) / Total borrowings
     Red flag: > 30-40% concentration in sub-1-year instruments

  3. Rollover Concentration
     = Largest single-month maturity / Monthly average maturity
     Red flag: Any single month > 2.5x the average

  4. Committed Liquidity Backstop
     = Undrawn committed bank lines / Near-term maturities (3M)
     Green flag: > 1.0x | Red flag: < 0.5x

LESSONS FROM THE 2018 IL&FS CRISIS:
  - Rollover assumption risk: CP rollover failed overnight when
    confidence broke. Always stress-test assuming zero rollover.
  - Asset liquidity illusion: Long-duration loans cannot be
    sold at par in a stress scenario. A liquidity buffer that
    relies on this is not a real buffer.
  - Contingency Funding Plans must be operational, not just
    policy documents on paper.

ALM RED FLAGS — QUICK REFERENCE:
  [ ] CP > 25% of total borrowings with < 3 months avg tenure
  [ ] Committed undrawn bank lines < 1x of 3-month maturities
  [ ] ALCO meets less than monthly
  [ ] No independent Treasury function
  [ ] Cumulative 1-year gap > 15% of total assets
  [ ] Single-month maturity concentration > 2.5x monthly average
  [ ] Securitisation pipeline is aspirational, not contracted
  [ ] Group entity inter-dependencies in liability structure
  [ ] Bank lines conditional on covenants already near breach


====================
TOP 10 THINGS TO KNOW TODAY
====================

1. MFI STRESS IS SYSTEMIC, NOT IDIOSYNCRATIC.
   PAR>30 at 9.2% sector-wide is not an outlier problem. Every
   NBFC-MFI, SFB, and co-lending bank needs an immediate
   liquidity runway and covenant headroom assessment today.

2. IRRBB DRAFT WILL RESHAPE BANK CAPITAL PLANNING.
   Any bank with a G-Sec portfolio above Rs.50,000 crore or
   visible duration mismatch must model EVE shock scenarios
   now — be ahead of management on this conversation.

3. BBB-RATED NAMES FACE A FUNDING WALL.
   At 290-310 bps over G-Sec, BBB primary market access is
   effectively closed. Any issuer in your portfolio rated BBB
   or below with NCD maturities in the next 6 months must be
   escalated to a formal liquidity watch immediately.

4. SEBI NOTICES TO CRAs MEAN FASTER NEGATIVE ACTIONS INDUSTRY-
   WIDE. Brief issuers proactively — do not let a committee
   review be the first time they hear about a potential
   downgrade.

5. CP ROLLOVER RISK IS REAL AND THE WINDOW IS NARROWING.
   NBFC CP rates at 7.65-7.90% and declining MF appetite means
   any entity relying on CP for >20% of borrowings is fragile.
   Review rollover schedules for the next 90 days today.

6. CYBERSECURITY EVENTS ARE NOW CREDIT EVENTS.
   IT risk failures can trigger regulatory restriction, deposit
   attrition, and capital impairment. IT governance must be a
   standard element of every credit assessment.

7. DEVELOPER FINANCE HFCs ARE IN A COMPLIANCE COUNTDOWN.
   NHB norms give 24 months, but credit risk materialises the
   moment forced sell-downs begin. Identify which HFCs breach
   the new 10%/20% thresholds and model the P&L impact today.

8. SECURITISATION VOLUMES ARE MISLEADING — POOL QUALITY IS
   WHAT MATTERS. Stress-test pool performance using current
   collection data, not historical vintage curves from a
   benign period.

9. THE UPGRADE CYCLE IN INFRASTRUCTURE IS REAL BUT REQUIRES
   SCRUTINY. Verify DSCR calculations use contracted off-take
   rates, not merchant, and that O&M reserves are fully funded
   before confirming any upgrade recommendation.

10. THE RATING ACTION DIVERGENCE IS TELLING YOU SOMETHING.
    Infrastructure improving. NBFC/MFI/manufacturing
    deteriorating. Banking bifurcated. This is classic late-
    cycle credit bifurcation. Review portfolio sector
    concentration and flag over-exposure in stressed segments
    to the Chief Rating Officer before the weekly surveillance
    call.


======================================================================
END OF DAILY CREDIT INTELLIGENCE — {date_str}
Next edition: Tomorrow 6:00 AM IST (Weekdays only)
Credit Strategy Desk | Jitendra.Meghrajani@careedge.in
This report is auto-generated and delivered via GitHub Actions.
======================================================================
"""
    return report


def send_email(subject: str, body: str, gmail_user: str, gmail_password: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = RECIPIENT

    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, RECIPIENT, msg.as_string())
        print(f"Report sent to {RECIPIENT}")


def main() -> None:
    gmail_user     = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]

    today   = datetime.date.today()
    subject = f"Daily Credit Intelligence — {today.strftime('%d %B %Y')}"
    body    = build_report(today)

    send_email(subject, body, gmail_user, gmail_password)


if __name__ == "__main__":
    main()
