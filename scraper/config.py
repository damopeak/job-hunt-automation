import json
import os
from dotenv import load_dotenv

load_dotenv()

# Seniority terms used for scoring (not search queries)
SENIORITY_TERMS = [
    "junior", "graduate", "grad", "entry level", "entry-level", "associate",
    "internship", "intern", "placement", "off cycle", "off-cycle",
    # Implicit entry-level signals — added 11 Aug 2026 after "Analyst"
    # (deverellsmith, property development finance) was missed: the ad never
    # says "junior"/"graduate" anywhere, it signals entry-level via "No
    # professional qualification required" / "not necessary to be chartered
    # or working towards ACA, ACCA or CIMA" instead, so seniority_match was
    # false and the rating got capped at 5 despite strong CV/sector alignment.
    # Deliberately narrow — bare "training provided" was considered and
    # rejected as too generic (plenty of senior roles offer training too);
    # these phrases specifically disclaim needing prior experience/quals,
    # which senior postings essentially never say.
    "no professional qualification required", "no qualification required",
    "no experience required", "no experience necessary",
    # "Analyst I" — added 11 Aug 2026 after "Finance Analyst I (Sales)"
    # (Global Payments) was missed. Large corporates commonly use a numbered
    # title-ladder (Analyst I/II/III, Senior Analyst, ...) where "I" denotes
    # the entry rung — a reliable, narrow signal distinct from any other
    # meaning of the word "analyst".
    "analyst i",
    # "Educated to degree level" — added 11 Aug 2026 after "Analyst, Market
    # Regulation" (ICE) was missed: no seniority word, no explicit years-of-
    # experience requirement anywhere in the posting, just this phrase. Safe
    # to treat as an entry-level signal because any posting that ALSO states
    # an explicit years-experience or prior-role requirement is already
    # hard-excluded earlier in rater.rate() before seniority scoring runs —
    # this only affects postings that already cleared every other
    # experience-requirement gate.
    "educated to degree level", "educated to graduate level",
]

# Search queries = seniority + sector combos
# "associate" removed 28 Jul 2026 — user: remove all associate roles entirely
# (rater.py now also hard-excludes any title containing "Associate").
SENIORITY_SEARCH = ["junior", "graduate", "entry level"]
SECTOR_SEARCH = [
    "marketplace", "ecommerce", "SDR", "BDR",
    "growth",
    # Tech/AI-focused SDR/BDR — added 15 Aug 2026, user re-enabled SDR/BDR
    # roles (paused 10 Aug 2026) and explicitly asked for tech/AI sector
    # coverage specifically, not just generic SDR/BDR.
    "SaaS SDR", "SaaS BDR", "tech SDR", "tech BDR", "AI SDR", "AI BDR",
    "software SDR", "software BDR",
    # Marketplace partner/seller manager
    "seller manager", "partner manager",
    # Pricing / revenue management
    "pricing analyst", "revenue management",
    # RevOps
    "revenue operations", "revops",
    # Amazon-focused agency account management
    "account manager", "amazon account manager",
    # Trading assistant — "buying assistant" removed 28 Jul 2026 (user: too
    # many low-value results, "clogging space")
    "trading assistant",
    # Bare "operations" — added 11 Aug 2026 after "Graduate Operations
    # Executive" (HIVED) was missed. Already heavily weighted in rater.py's
    # TARGET_TITLES/STRONG_TITLE_SECTORS for scoring, but only compound forms
    # ("revenue operations", "revops") were ever actually searched for — bare
    # "operations" itself was never a search query.
    "operations",
    # Accounting / audit
    "audit", "accounting",
    # Generic graduate scheme titles
    "management trainee", "trainee",
    # Consulting / strategy — already scored highly by rater.py but was
    # never actually searched for anywhere (real gap found 26 Jul 2026)
    "consulting", "consultant", "strategy consultant", "management consulting",
]

# Sectors added 27 Jul 2026 — finance/IB/PE/AM/WM titles use "associate" to
# mean a senior (3-6+ yrs) role, not entry-level, so these are combined with a
# restricted seniority set (no "associate") rather than the full SENIORITY_SEARCH.
SENIORITY_SEARCH_NO_ASSOCIATE = ["junior", "graduate", "entry level"]
SECTOR_SEARCH_NO_ASSOCIATE = [
    "finance", "retail", "procurement", "supply chain",
    "product analyst", "data analyst",
    "investment banking", "private equity", "asset management", "wealth management",
    # Regulatory/compliance/risk — added 11 Aug 2026 after "Junior Regulatory
    # Change Analyst" (Vanguard) was flagged as missed; user confirmed this is
    # a genuinely wanted target sector going forward, not a one-off.
    "regulatory", "regulation", "compliance", "risk analyst", "risk management",
    # Credit — added 17 Sep 2026 after "Graduate Credit Analyst" was flagged as
    # missed. "credit" was already in rater.py's CV_KEYWORDS (scored fine)
    # but had never actually been a search term, same scored-but-never-
    # searched pattern as real estate/regulatory below.
    "credit", "credit analyst", "credit risk",
    # Real estate/property — added 11 Aug 2026 after "Analyst" (deverellsmith,
    # property development finance — appraisals/valuations/investment) was
    # flagged as missed. "real estate" was already in rater.py's CV_KEYWORDS
    # (scored fine) but had never actually been a search term, so nothing
    # ever surfaced it to be scored in the first place.
    "real estate", "property",
    # Bare "analyst" — added 11 Aug 2026, user: "i love analyst roles in
    # general". The deverellsmith job's title was literally just "Analyst"
    # with no sector/seniority qualifier, so it couldn't match any existing
    # combo query. EXCLUDED_TITLE_KEYWORDS + MIN_RATING still filter out the
    # irrelevant analyst roles (quant, BI, market research, insights, etc.
    # are already excluded by title).
    "analyst",
]

SEARCH_KEYWORDS = [f"{s} {sec}" for s in SENIORITY_SEARCH for sec in SECTOR_SEARCH]
SEARCH_KEYWORDS += [f"{s} {sec}" for s in SENIORITY_SEARCH_NO_ASSOCIATE for sec in SECTOR_SEARCH_NO_ASSOCIATE]
# Note: several combos here (e.g. "junior consultant", "graduate trading
# assistant") are already generated by the comprehensions above since their
# sector is in SECTOR_SEARCH/SECTOR_SEARCH_NO_ASSOCIATE — only genuinely
# additional phrasings are kept here (11 redundant entries removed 11 Aug
# 2026, found wasting a full scrape pass each on an already-covered combo).
SEARCH_KEYWORDS += [
    "graduate scheme",
    "graduate programme",
    "graduate program",
    "graduate commercial",
    "junior commercial",
    "junior commercial analyst",
    "graduate commercial analyst",
    "graduate marketplace manager",
    "junior revenue management analyst",
    "graduate revenue management analyst",
    "graduate revenue operations analyst",
    "junior revops analyst",
    "graduate revops analyst",
    "graduate ecommerce account manager",
    "junior marketplace account manager",
    "ACA graduate scheme",
    "ACCA graduate scheme",
    "graduate audit scheme",
    "graduate accounting programme",
    "strategy analyst graduate",
]

# Internship / off-cycle searches
INTERNSHIP_SECTORS = ["ecommerce", "commercial", "marketplace", "business development", "operations", "growth"]
SEARCH_KEYWORDS += [f"internship {sec}" for sec in INTERNSHIP_SECTORS]
SEARCH_KEYWORDS += [f"graduate internship {sec}" for sec in INTERNSHIP_SECTORS]
SEARCH_KEYWORDS += ["off cycle internship", "off-cycle internship", "spring internship 2025", "summer internship 2025 graduate", "industrial placement ecommerce", "industrial placement commercial"]

# Summer internship searches for the finance/retail/procurement/analyst sectors
# added 27 Jul 2026. Deliberately NOT "spring week"/"spring insight" — those
# programmes require being a current university student, which a candidate
# who has already graduated no longer is.
SEARCH_KEYWORDS += [f"summer internship {sec}" for sec in SECTOR_SEARCH_NO_ASSOCIATE]

# Company exclusion list — skip regardless of role
EXCLUDED_COMPANIES = [
    "pareto",
]

# Job title exclusion list — skip before rating
EXCLUDED_TITLE_KEYWORDS = [
    # Tech/engineering roles
    "software engineer", "software developer", "web developer", "app developer",
    "mobile developer", "ios developer", "android developer",
    "front end", "frontend", "backend", "back end", "full stack", "fullstack",
    "devops", "dev ops", "site reliability", "cloud engineer", "platform engineer",
    "data engineer", "data scientist", "data science", "machine learning",
    "ml engineer", "ai engineer", "nlp engineer", "deep learning",
    "python developer", "java developer", ".net developer", "react developer",
    "systems engineer", "systems architect", "network engineer", "infrastructure engineer",
    "security engineer", "cybersecurity", "penetration", "qa engineer",
    "test engineer", "automation engineer", "embedded engineer",
    "firmware", "hardware engineer", "robotics",
    # Analytics/data roles not relevant — "data analyst" removed 27 Jul 2026,
    # now a target sector in its own right (config.SECTOR_SEARCH_NO_ASSOCIATE)
    "business intelligence", "bi analyst", "bi developer",
    "analytics engineer", "quantitative analyst", "quant analyst",
    "marketing analyst", "research analyst", "insight analyst",
    "mmm analyst", "econometri", "statistician",
    # Senior/leadership
    "senior", "lead ", "head of", "director", "vp ", "vice president",
    "principal", "chief ", "cto", "cfo", "coo", "ceo",
    "partner", "associate director",
    # Other irrelevant
    "solicitor", "lawyer", "legal",
    "nurse", "doctor", "engineer technician", "electrician", "plumber",
    "warehouse operative", "driver", "delivery", "logistics coordinator",
    "it support", "helpdesk", "service desk", "tech support",
    # Roles consistently rejected by user
    "merchandiser",
    "it project",
    "market research",
    "insights analyst",
    # Quant roles — user not interested
    "quantitative analyst", "quantitative researcher", "quantitative trader",
    "quant analyst", "quant trader", "quant researcher", "quant developer",
    # Language-specific roles
    "german", "dutch speaker", "french speaker", "spanish speaker",
    "dutch speaking", "french speaking", "german speaking", "spanish speaking",
    "language speaker",
    # Jewellery & watches industry
    "jewellery", "jewelry", "jeweller", "jeweler",
    "watches", "watchmaker", "horology", "gemstone", "gems",
    # Footwear & apparel industry
    "footwear", "apparel", "fashion buyer", "fashion assistant",
    "clothing", "garment", "textile", "womenswear", "menswear",
    "sportswear", "outerwear", "knitwear", "footwear buyer",
]

# Minimum rating to send to Airtable
MIN_RATING = 7

# Target job titles for role match scoring
TARGET_TITLES = [
    "marketplace", "ecommerce", "e-commerce", "amazon",
    "commercial", "sdr", "bdr", "sales development",
    "business development", "category",
    "operations", "pricing", "growth",
    "executive",
    "seller manager", "partner manager", "account manager",
    "revenue management", "revenue operations", "revops",
    "trading", "audit", "accounting",
]

# Candidate profile — loaded from profile.json (your real, git-ignored file)
# or, if that doesn't exist, the fictional profile.example.json shipped with
# the repo. Nothing personal is hardcoded in the code itself.
_HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_PATH = os.getenv(
    "PROFILE_PATH",
    os.path.join(_HERE, "profile.json")
    if os.path.exists(os.path.join(_HERE, "profile.json"))
    else os.path.join(_HERE, "profile.example.json"),
)


def _load_profile(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


PROFILE = _load_profile(PROFILE_PATH)


def _build_profile_text(p: dict) -> str:
    """Renders the profile as the plain-text block the AI qualification check
    is prompted with."""
    lines = [
        f"Name: {p['name']}",
        f"Degree: {p['degree']}",
        f"Location: {p['location']}",
        f"Target salary: £{p['target_salary']:,}+ per year",
        f"Preferred location: {p['preferred_location_note']}",
        "",
        "Experience:",
    ]
    lines += [f"- {e}" for e in p.get("experience", [])]
    lines += [
        "",
        "Skills: " + ", ".join(p.get("skills", [])) + ".",
        "",
        "Best fit roles: " + ", ".join(p.get("best_fit_roles", [])) + ".",
    ]
    return "\n".join(lines)


CANDIDATE_PROFILE = _build_profile_text(PROFILE)

# Airtable
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN", "")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME", "Jobs")

# Below this length a scraped/API-returned Description is probably a
# truncated teaser (e.g. Adzuna's API, confirmed 10 Aug 2026) rather than the
# full posting — worth re-fetching from the job's own URL before rating.
# Shared between main.py (live scrape path) and retrate_airtable.py (backlog
# refresh path) so the two don't drift apart.
#
# Raised 480 -> 520 on 12 Aug 2026 — Adzuna's API truncates its description
# field at EXACTLY 500 chars (confirmed by direct inspection), which sat just
# above the old 480 threshold, so the "too short, re-fetch it" check never
# actually fired for the vast majority of Adzuna jobs even though 500 chars
# is always a mid-sentence cutoff, never the real posting. The re-fetch
# mechanism itself works fine once triggered (recovers 2,000-9,000+ chars in
# most cases) — this was purely a threshold gap, not a fetch-logic bug. User
# report: "every adzuna role is getting flagged" (AI Uncertain, from the
# qualification check having only a truncated snippet to judge from).
MIN_USABLE_DESCRIPTION_CHARS = 520

# API keys (optional — scrapers skip if blank)
REED_API_KEY = os.getenv("REED_API_KEY", "")
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# LinkedIn uses an unauthenticated, rate-limited endpoint — kept to a small,
# high-signal subset of SEARCH_KEYWORDS rather than the full list, to keep
# request volume low enough to avoid getting blocked.
#
# Bare-title additions (no "junior"/"graduate" prefix) added 11 Aug 2026 —
# "E-Commerce Operations Analyst" (Tradition, posted 1h before found by the
# user) was invisible under every graduate/junior-prefixed ecommerce query,
# even across all 6 result pages, but ranked #3 for the literal phrase
# "ecommerce operations analyst" — LinkedIn's own relevance ranking buries a
# title with no seniority word behind tighter 2-word-query matches, so a
# graduate/junior-only keyword set structurally can't reach titles phrased
# this way regardless of how often the scraper runs.
LINKEDIN_KEYWORDS = [
    "graduate ecommerce", "graduate marketplace", "graduate commercial",
    "junior ecommerce", "junior commercial", "graduate scheme", "graduate programme",
    "junior SDR", "junior BDR",
    # Tech/AI SDR/BDR — added 15 Aug 2026, see SECTOR_SEARCH comment above.
    "SaaS SDR", "AI SDR", "tech SDR", "SaaS BDR", "AI BDR",
    "graduate pricing analyst", "junior account manager",
    "graduate audit scheme", "graduate management trainee",
    "graduate consulting", "junior consultant",
    "graduate investment banking", "graduate private equity",
    "graduate asset management", "graduate finance", "graduate data analyst",
    "ecommerce operations analyst", "ecommerce analyst", "marketplace analyst",
    "commercial analyst",
    # Regulatory/compliance/risk — added 11 Aug 2026 alongside the
    # SECTOR_SEARCH_NO_ASSOCIATE addition; bare-title forms included from the
    # start given the Tradition lesson above.
    "graduate regulatory", "junior compliance", "regulatory analyst",
    "compliance analyst", "risk analyst", "market regulation analyst",
    # Real estate/property + bare analyst — added 11 Aug 2026 after the
    # deverellsmith "Analyst" (property development finance) miss. Bare
    # "graduate analyst"/"junior analyst" catches generic-titled postings the
    # way "ecommerce operations analyst" needed a bare-title query above.
    "real estate analyst", "property analyst", "graduate analyst",
    "junior analyst",
    # Bare "operations" — added 11 Aug 2026 after "Graduate Operations
    # Executive" (HIVED) was missed, see SECTOR_SEARCH comment above.
    "graduate operations", "junior operations", "operations executive",
    # Credit — added 17 Sep 2026, see SECTOR_SEARCH_NO_ASSOCIATE comment above.
    "graduate credit analyst", "credit analyst", "credit risk analyst",
]

RUN_INTERVAL_HOURS = float(os.getenv("RUN_INTERVAL_HOURS", "3"))
