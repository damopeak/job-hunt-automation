import re
import config
from matching import compile_terms, any_match, count_matches

# Candidate-specific facts the rules below depend on are all read from the
# profile JSON (see config.PROFILE / profile.example.json) rather than
# hardcoded, so the same rater works for any candidate.
_PROFILE = config.PROFILE
_DEGREE_SUBJECT = _PROFILE.get("degree_subject", "economics").lower()
_HAS_MANUAL_LICENCE = bool(_PROFILE.get("has_manual_driving_licence", False))
_LANGUAGES_SPOKEN = {l.lower() for l in _PROFILE.get("languages_spoken", ["english"])}
_TARGET_SALARY = int(_PROFILE.get("target_salary", 25000))
_MIN_ACCEPTABLE_SALARY = int(_PROFILE.get("min_acceptable_salary", 20000))

# "buyer"/"buying" removed from CV_KEYWORDS/TARGET_TITLES/STRONG_TITLE_SECTORS
# on 28 Jul 2026 — user: too many low-value results in this category, "clogging
# space". Also removed from config.py search terms. ("account manager" was
# briefly removed too, then explicitly kept on user's follow-up.)
CV_KEYWORDS = [
    "marketplace", "ecommerce", "e-commerce", "amazon", "fba",
    "seller central", "listing", "wholesale", "distribution", "fmcg",
    "supplier", "sourcing", "category",
    "commercial", "pricing", "growth", "account manager",
    "business development", "sales development", "sdr", "bdr",
    "p&l", "inventory", "multichannel",
    "retail", "brand", "consumer goods",
    # Finance / IB / PE
    "private equity", "venture capital", "investment banking",
    "capital markets", "asset management", "wealth management", "hedge fund",
    "mergers", "acquisitions", "m&a", "due diligence",
    "financial modelling", "valuation", "lbo", "dcf", "finance", "financial",
    "trading", "markets", "equities", "fixed income",
    # Generalist corporate finance/FP&A — added 11 Aug 2026 after "Finance
    # Analyst I (Sales)" (Global Payments, budgeting/forecasting/variance
    # work) scored only "partial" CV alignment despite being a genuine
    # finance analyst role — the existing finance terms above lean heavily
    # toward IB/PE/consulting buzzwords and missed plain FP&A language.
    "budgeting", "forecasting", "financial planning", "fp&a",
    "variance analysis", "financial reporting", "financial analysis",
    "infrastructure", "real estate", "credit",
    "portfolio", "deal", "transactions", "actuarial", "insurance",
    "property",
    # Procurement / supply chain / product-data analyst — added 27 Jul 2026
    "procurement", "supply chain", "product analyst", "data analyst",
    # Data-analyst toolkit — added 11 Aug 2026, same fix as "Data Analyst"
    # (Haystack) above. "excel" is literally on the candidate's own CV
    # (config.CANDIDATE_PROFILE skills list); power bi/tableau/data
    # visualization are standard tools for the data-analyst sector this file
    # already targets.
    "excel", "power bi", "tableau", "data visualization",
    # Regulatory/compliance/risk — added 11 Aug 2026, user confirmed this is
    # a permanent target sector (Vanguard "Junior Regulatory Change Analyst"
    # miss; "add these sorts of roles, i love analyst roles in general").
    "regulatory", "regulation", "compliance", "risk management", "risk analyst",
    "financial crime", "aml", "kyc", "governance",
    # Consulting — deliberately NOT bare "consulting"/"consultant"/"strategy":
    # those single words also match unrelated roles (social media strategist,
    # recruitment/sales consultant, etc.) that have nothing to do with
    # management/strategy consulting. Found 28 Jul 2026 via "Social Media
    # Consulting Strategist" (VaynerMedia) scoring a false 10.
    "management consulting", "strategy consulting", "business consulting",
    "corporate strategy", "strategy analyst", "consulting analyst",
    "consulting graduate scheme", "advisory",
    "mckinsey", "bain", "bcg", "deloitte", "pwc", "kpmg", "ey", "accenture",
    # Marketplace partner/seller manager, pricing/RM, RevOps
    "seller manager", "partner manager", "revenue management",
    "revenue operations", "revops", "dynamic pricing",
    # Trading/buying assistant
    "trading assistant",
    # Accounting / audit
    "audit", "auditing", "auditor", "accounting", "aca", "acca",
    # Generic graduate scheme titles
    "management trainee", "trainee", "rotational",
]

TECH_PENALTY_KEYWORDS = [
    # "python"/"sql" removed 11 Aug 2026 — "data analyst" is an explicit
    # target sector (config.SECTOR_SEARCH_NO_ASSOCIATE) and both are
    # completely standard tools for that role, not a software-engineering
    # signal. Found via "Data Analyst" (Haystack) scoring -1.6 purely for
    # listing "SQL, Python... is a significant advantage" as a nice-to-have.
    "javascript", "java", "coding", "programming",
    "software", "developer", "computer science", "cs degree",
    "machine learning", "data science", "deep learning", "algorithms",
    "cloud", "aws", "azure", "gcp", "devops", "kubernetes", "docker",
    "api development", "backend", "frontend", "database administration",
]

TARGET_TITLES = [
    "marketplace", "ecommerce", "e-commerce", "amazon", "commercial",
    "sdr", "bdr", "sales development", "business development",
    "category", "operations", "pricing",
    "growth", "account manager", "analyst", "executive",
    "seller manager", "partner manager", "revenue management",
    "revenue operations", "revops", "trading", "audit", "accounting",
    "trainee", "management trainee",
    # Added 27 Jul 2026
    "finance", "retail", "procurement", "supply chain",
    "product analyst", "data analyst",
    "investment banking", "private equity", "asset management", "wealth management",
    # Added 11 Aug 2026 — regulatory/compliance/risk + real estate, see
    # CV_KEYWORDS comment above for context.
    "regulatory", "regulation", "compliance", "risk", "real estate", "property",
    # Added 17 Sep 2026 — "Graduate Credit Analyst" (Monzo) miss, see
    # config.py's SECTOR_SEARCH_NO_ASSOCIATE comment for context.
    "credit",
]

SENIORITY_TERMS = config.SENIORITY_TERMS

# "Associate" is genuinely ambiguous: entry-level in retail/marketing, but a
# senior title (3-6+ years) in consulting, banking, and corporate strategy
# roles. Trust it as a seniority signal only when a real description is
# available to cross-check against (the experience-years hard exclusion
# below will catch a senior "Associate" role if so) — with no description
# at all (a failed fetch, or a site we can't get past), fall back to only
# the unambiguous terms rather than risk a false positive.
AMBIGUOUS_SENIORITY_TERMS = {"associate"}
UNAMBIGUOUS_SENIORITY_TERMS = [t for t in SENIORITY_TERMS if t not in AMBIGUOUS_SENIORITY_TERMS]

# Foreign language requirements in title/description → user doesn't speak
# these. Was a soft -3 penalty only; converted to a hard exclusion 28 Jul 2026
# after "Junior Account Manager" (iwoca, actually "Account Manager - German
# speaking") still scored a 7 despite the penalty — strong CV/role alignment
# elsewhere in the listing outweighed it. Same "meet the actual requirements"
# principle as the student-status and prior-role-experience hard exclusions.
#
# Only matches phrasings that describe an actual essential skill requirement
# ("German speaking", "fluent in German", "native German speaker") — NOT a
# generic "with X" pattern, which false-matches incidental mentions like
# "liaising with German suppliers" that don't require the candidate to speak
# the language themselves. Per user instruction (28 Jul 2026): only exclude
# when the language is an essential requirement, not just mentioned in passing.
LANGUAGES_NOT_SPOKEN = [
    lang for lang in [
        "italian", "french", "german", "spanish", "polish",
        "dutch", "mandarin", "chinese", "portuguese", "arabic",
    ]
    if lang not in _LANGUAGES_SPOKEN
]
# Bare "{lang} speaker" (no "native" prefix) added 28 Jul 2026 after "Account
# Manager (Mandarin Speaker)" (TPP, rated 8) slipped through — only "native
# {lang} speaker" and "{lang} speaking" existed, not this noun-form variant.
LANGUAGE_PENALTY_TERMS = (
    [f"{lang} speaking" for lang in LANGUAGES_NOT_SPOKEN]
    + [f"{lang} speaker" for lang in LANGUAGES_NOT_SPOKEN]
    + [f"fluent in {lang}" for lang in LANGUAGES_NOT_SPOKEN]
    + [f"fluency in {lang}" for lang in LANGUAGES_NOT_SPOKEN]
    + [f"native {lang} speaker" for lang in LANGUAGES_NOT_SPOKEN]
)


def _requires_foreign_language(text: str) -> bool:
    return any_match(LANGUAGE_PENALTY_PATTERNS, text)

# Experience requirements that rule out a fresh graduate — matches "N years
# (of) experience" phrasing (e.g. "5+ years experience", "1 year experience",
# "minimum of 5 years' experience"). Requires "experience" to actually follow
# the year count, rather than matching any stray "N years" in the text (e.g.
# "10 years in business", a founding date) which isn't a candidate requirement.
# Threshold lowered from >=2 to >=1 on 28 Jul 2026 — a "1 year experience"
# requirement (Social Media Consulting Strategist, VaynerMedia, rated 10) was
# still getting through.
#
# Word-form numbers added 07 Aug 2026 — "Around **two** to **four** years'
# professional experience" (PATRIZIA SE, rated 10) used spelled-out numbers,
# which the digit-only \d{1,2} pattern couldn't match at all. Covers one
# through twelve, the realistic range for this kind of requirement.
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_NUMBER_WORD_PATTERN = "|".join(_NUMBER_WORDS.keys())
# "yr"/"yrs" abbreviation added same day, found via a systematic sweep of
# phrasings after the PATRIZIA case (user: "go through every possible
# scenario") rather than a specific flagged job.
#
# The "of" branch allows up to 4 arbitrary field-descriptor words between
# "years of" and "experience" — e.g. "1+ years of **Staffing and
# Recruiting** experience" (Morgan Spencer Recruitment, rated 8), same class
# of gap as the "billing" case fixed earlier in PRIOR_ROLE_EXPERIENCE_REGEX.
# Deliberately gated behind an explicit "of" (not allowed in the no-"of"
# branch) — without that anchor, an unrelated "10 years ago and has
# extensive experience" (a founding-date style sentence, 4 filler words then
# "experience") would also match; requiring "of" specifically after "years"
# is what distinguishes "years OF X experience" from "years ago ... experience".
#
# "practical" added to the qualifier list 18 Aug 2026 — "Finance Analyst"
# (Hyve Group, flagged as Underqualified) had "2–5 years' practical
# experience in a Finance, Accounting or FP&A role", and "practical" wasn't
# among the relevant/professional/prior/working qualifiers already allowed
# directly before "experience".
EXPERIENCE_YEARS_REGEX = re.compile(
    r"(?:(\d{1,2})|(" + _NUMBER_WORD_PATTERN + r"))"
    r"\s*\+?\s*(?:to|-)?\s*(?:(?:\d{1,2}|" + _NUMBER_WORD_PATTERN + r")\s*)?"
    r"years?'?\s*(?:of\s+(?:[a-z][\w&/-]*\s+){0,4}|(?:relevant\s+|professional\s+|prior\s+|practical\s+|work(?:ing)?\s+)?)experience"
    r"|(?:(\d{1,2})|(" + _NUMBER_WORD_PATTERN + r"))\s*\+?\s*yrs?'?\s*"
    r"(?:of\s+(?:[a-z][\w&/-]*\s+){0,4}|(?:relevant\s+|professional\s+|prior\s+|practical\s+|work(?:ing)?\s+)?)exp(?:erience)?\b",
    re.IGNORECASE,
)

# Same sweep, found three more phrasings the forward "N years ... experience"
# pattern structurally can't cover:
# - reversed order: "experience of/with (at least) N years" (years AFTER
#   the word "experience", not before)
# - "a year of experience" / "a decade of experience" (no digit or number
#   word at all — "a"/"an" standing in for one, "a decade" for ten)
# - "several years" (a deliberately vague quantifier, but still implies more
#   than the threshold regardless of exact count)
EXPERIENCE_REVERSED_REGEX = re.compile(
    r"experience\s+(?:of|with)\s+(?:at\s+least\s+|around\s+|over\s+|up\s+to\s+)?"
    r"(?:(\d{1,2})|(" + _NUMBER_WORD_PATTERN + r"))\s*\+?\s*years?\b",
    re.IGNORECASE,
)
EXPERIENCE_ARTICLE_REGEX = re.compile(
    r"\ban?\s+(year|decade)\s+(?:of\s+)?(?:relevant\s+|professional\s+|prior\s+|work(?:ing)?\s+)?experience\b",
    re.IGNORECASE,
)
EXPERIENCE_SEVERAL_YEARS_REGEX = re.compile(
    r"\bseveral\s+years?\s*'?\s*(?:of\s+)?(?:relevant\s+|professional\s+|prior\s+|work(?:ing)?\s+)?experience\b",
    re.IGNORECASE,
)

# Months-based experience requirements — "Essential 6-18 months' experience
# within Recruitment Sales Operations..." (Morgan Spencer Recruitment "Sales
# Operations Assistant", flagged 09 Aug 2026, rated 8) used a months range
# rather than years, which none of the years-based patterns above can match at
# all (they require the literal word "year(s)"). Same direct-adjacency shape
# as EXPERIENCE_YEARS_REGEX's "of X X X X experience" / bare-qualifier
# branches, just with "months" substituted for "years".
EXPERIENCE_MONTHS_REGEX = re.compile(
    r"\d{1,2}\s*\+?\s*(?:to|-)?\s*(?:\d{1,2}\s*)?months?'?\s*"
    r"(?:of\s+(?:[a-z][\w&/-]*\s+){0,4}|(?:relevant\s+|professional\s+|prior\s+|work(?:ing)?\s+)?)experience",
    re.IGNORECASE,
)

# Labelled "Experience Required: N-M years" field — "Senior Associate -
# Financial Crime Operations" (LJ Recruitment Limited, flagged 09 Aug 2026,
# rated 8) had "Experience Required: 2-5 years" as a standalone label/value
# pair. Neither the forward regex (needs "experience" AFTER the year count)
# nor the reversed regex (needs "of"/"with" directly between "experience" and
# the number) match this shape, since "Required:" sits between "experience"
# and the number instead.
EXPERIENCE_REQUIRED_LABEL_REGEX = re.compile(
    r"experience\s+required\s*:?\s*(?:(\d{1,2})|(" + _NUMBER_WORD_PATTERN + r"))"
    r"\s*\+?\s*(?:to|-)?\s*(?:\d{1,2}|" + _NUMBER_WORD_PATTERN + r")?\s*years?\b",
    re.IGNORECASE,
)

# "N years in <field>, ideally with <field> experience" — "Account Manager"
# (HERA Communication Strategies, flagged 09 Aug 2026, rated 8) had "Around
# 3+ years in PR or communications, ideally with corporate, financial,
# property o B2B experience". Structurally distinct from every pattern above:
# "years" is followed by "in" (not "of"/bare), and "experience" sits at the
# end of a long comma-separated list rather than immediately after the count.
# Deliberately anchored on the literal "ideally with" join (not bare "with")
# — a bare "with" was tried first and false-matched ordinary prose like
# "5 years in retail, working with major brands, genuine customer
# experience"; "ideally with" is specific enough to job-requirement phrasing
# ("X, ideally with Y") that it doesn't collide with company-history or
# customer-experience sentences in sanity testing.
EXPERIENCE_YEARS_IN_IDEALLY_WITH_REGEX = re.compile(
    r"(?:(\d{1,2})|(" + _NUMBER_WORD_PATTERN + r"))"
    r"\s*\+?\s*years?'?\s+in\s+(?:[a-z][\w&/-]*,?\s+){1,6}ideally with\s+(?:[a-z][\w&/-]*,?\s+){1,6}experience\b",
    re.IGNORECASE,
)

# Negation guard, added same sweep — none of the experience-years patterns
# above had one, unlike PRIOR_ROLE_EXPERIENCE_REGEX which already learned
# this lesson (28 Jul 2026, "No prior experience in marine insurance? No
# problem"). Reuses the same before/after window approach. Checked for every
# match above, not just EXPERIENCE_YEARS_REGEX, since all of them are
# vulnerable to the same "no X years experience required" / "X years
# experience is not required" phrasing.
_EXPERIENCE_NEGATIONS_BEFORE = (
    "no ", "not ", "without ", "don't ", "dont ", "doesn't ", "doesnt ",
    "didn't ", "didnt ", "never ", "n/a ",
)
# "preferred"/"advantageous"/etc. added 09 Aug 2026 — found via a William
# Blair posting ("Internship or prior work experience in financial services
# industry preferred", flagged by the user) that this list didn't catch at
# all despite "preferred" being one of the most common ways a posting signals
# something is optional rather than required.
_EXPERIENCE_NEGATIONS_AFTER = (
    "not required", "not necessary", "not essential", "not needed",
    "not a requirement", "not mandatory", "isn't required", "isn't necessary",
    "is a bonus", "is a plus", "is desirable but not essential",
    "preferred", "advantageous", "is beneficial", "would be beneficial",
)


def _experience_match_is_negated(text: str, start: int, end: int) -> bool:
    preceding = text[max(0, start - 30):start]
    following = text[end:end + 40]
    if any(neg in preceding for neg in _EXPERIENCE_NEGATIONS_BEFORE):
        return True
    if any(neg in following for neg in _EXPERIENCE_NEGATIONS_AFTER):
        return True
    return False


def _requires_experience(text: str) -> bool:
    for match in EXPERIENCE_YEARS_REGEX.finditer(text):
        if _experience_match_is_negated(text, match.start(), match.end()):
            continue
        groups = match.groups()
        digit_group = groups[0] or groups[2]
        word_group = groups[1] or groups[3]
        n = int(digit_group) if digit_group else _NUMBER_WORDS[word_group.lower()]
        if n >= 1:
            return True
    for match in EXPERIENCE_REVERSED_REGEX.finditer(text):
        if _experience_match_is_negated(text, match.start(), match.end()):
            continue
        digit_group, word_group = match.group(1), match.group(2)
        n = int(digit_group) if digit_group else _NUMBER_WORDS[word_group.lower()]
        if n >= 1:
            return True
    for match in EXPERIENCE_ARTICLE_REGEX.finditer(text):
        if not _experience_match_is_negated(text, match.start(), match.end()):
            return True
    for match in EXPERIENCE_SEVERAL_YEARS_REGEX.finditer(text):
        if not _experience_match_is_negated(text, match.start(), match.end()):
            return True
    for match in EXPERIENCE_MONTHS_REGEX.finditer(text):
        if not _experience_match_is_negated(text, match.start(), match.end()):
            return True
    for match in EXPERIENCE_REQUIRED_LABEL_REGEX.finditer(text):
        if not _experience_match_is_negated(text, match.start(), match.end()):
            return True
    for match in EXPERIENCE_YEARS_IN_IDEALLY_WITH_REGEX.finditer(text):
        if not _experience_match_is_negated(text, match.start(), match.end()):
            return True
    return False


# Requirements for specific prior-role experience without a numeric year count
# (so EXPERIENCE_YEARS_REGEX above doesn't catch them) — e.g. "Wealth Executive"
# (mbf, rated 8) required "Previous experience within a Paraplanning, Junior
# Paraplanning or Wealth Planning support role". Originally an enumerated
# phrase list, but "Capital Markets Associate" (Robert Half, rated 10, £70-80k)
# used "Proven experience within Investment Banking..." — a variant the list
# didn't cover. Rebuilt as a regex on 28 Jul 2026 to generalise across
# previous/prior/proven/demonstrable x experience/track record x within/in/of,
# instead of re-adding one exact phrase per example found. Allows one
# optional word between the qualifier and "track record"/"experience" (e.g.
# "proven billing track record") — found 28 Jul 2026 via "Experienced
# Recruitment Consultants" (Tank Recruitment), which used exactly that
# insertion and slipped through the original tighter pattern.
PRIOR_ROLE_EXPERIENCE_REGEX = re.compile(
    r"\b(?:previous|prior|proven|demonstrable)\s+(?:\w+\s+)?(?:track\s+record|experience)\s+(?:within|in|of|working\s+(?:within|in))\b"
    # "You'll already have experience in an Account Executive or Junior
    # Account Manager role..." (Zest Recycle "Account Manager - Waste
    # Management", rated 8) — no previous/prior/proven/demonstrable qualifier
    # at all, just bare "(already) have experience in/of/within". Added
    # 07 Aug 2026 same sweep as the other experience-pattern fixes.
    r"|\b(?:already\s+)?have\s+experience\s+(?:within|in|of)\b",
    re.IGNORECASE,
)

# Negation guard — "No prior experience in marine insurance? No problem" (Graduate
# Claims Executive, targetjobs UK) matched the regex above and was wrongly
# excluded, when the listing was explicitly welcoming candidates without that
# experience. Found 28 Jul 2026 while spot-checking a bulk re-rate. Skip a match
# if one of these appears in the ~25 chars right before it.
PRIOR_ROLE_EXPERIENCE_NEGATIONS = (
    "no ", "not ", "without ", "none ", "zero ", "n/a ",
    "don't ", "dont ", "doesn't ", "doesnt ", "didn't ", "didnt ", "never ",
)

# Negation can also land AFTER the matched phrase — "Prior experience in
# finance is not required" (Five Arrows internship) — rather than before it.
# Skip a match if one of these appears in the ~40 chars right after it.
# Same "preferred"/"advantageous" gap fixed in _EXPERIENCE_NEGATIONS_AFTER
# above, added here too (09 Aug 2026) since this is a separate list guarding
# a separate regex (PRIOR_ROLE_EXPERIENCE_REGEX, not the years-based ones).
PRIOR_ROLE_EXPERIENCE_TRAILING_NEGATIONS = (
    "not required", "not necessary", "not essential", "not needed",
    "not a requirement", "not mandatory", "isn't required", "isn't necessary",
    "is a bonus", "is a plus", "is desirable but not essential",
    "preferred", "advantageous", "is beneficial", "would be beneficial",
)

# "Internship OR prior work experience... is essential" (William Blair
# "Investment Banking Analyst, Services & Industrials" / "...Analyst 1,
# Technology", found 09 Aug 2026 via two links the user found manually) is a
# disjunction — internship experience alone satisfies it, and the candidate
# profile explicitly has internships. The bare qualifier-based regex above
# can't see that "prior" is one branch of an "X or prior experience" choice,
# not an unconditional requirement. Skip a match if "internship" appears
# closely before it, joined by "or"/"and" — narrow enough that a genuine
# "3 years' prior experience" requirement mentioned near an unrelated
# internship reference elsewhere in the posting still excludes correctly.
PRIOR_ROLE_EXPERIENCE_INTERNSHIP_ALTERNATIVE_REGEX = re.compile(
    r"internship\s*(?:,)?\s*(?:or|and)\s*$", re.IGNORECASE,
)

# "Our leadership team has a proven track record" describes the EMPLOYER, not
# a requirement of the candidate — "Product Specialist" (Zachary Daniels)
# matched on "leadership team with a proven track record of success". Skip a
# match if one of these appears in the ~40 chars right before it.
PRIOR_ROLE_EXPERIENCE_EMPLOYER_CONTEXT = (
    "leadership team", "our team has", "our team with", "the team has",
    "company has a", "business has a", "organisation has a", "organization has a",
    "employer has a", "management team",
)

# "Proven track record in university studies required" (William Blair,
# found 09 Aug 2026 in the same posting as the internship-or fix above) is
# asking about ACADEMIC performance, not prior work experience — a
# coincidental hit on the "track record" branch of PRIOR_ROLE_EXPERIENCE_REGEX,
# same false-positive class as the employer-context guard just above. Skip a
# match if one of these appears in the ~40 chars right after it.
PRIOR_ROLE_EXPERIENCE_ACADEMIC_CONTEXT = (
    "university studies", "academic record", "academic performance",
    "your studies", "degree classification", "gpa", "coursework",
)


# A bare "Experience in delivering X" / "Experience of managing Y" under an
# "Essential Experience"/"Essential Requirements" header is just as much a
# hard requirement as "previous/prior/proven experience in X" — the qualifier
# adjective is just missing. Found 28 Jul 2026: "Audit Associate (Public
# Sector External Audit)" (Azets, rated 10) had "Essential Experience:
# Experience in delivering audit services to public sector clients" with no
# "previous/prior/proven" qualifier, so PRIOR_ROLE_EXPERIENCE_REGEX above
# missed it entirely. Only fires within ~200 chars of an explicit "essential"
# heading, so it doesn't catch generic "you'll gain experience in..." framing
# used in genuine graduate ads. Broadened 28 Jul 2026 after "Account Manager"
# (Spark Foundry, rated 8) had "Qualifications: Experience working within
# media planning, performance marketing or digital media..." — a header
# ("Qualifications") and phrasing ("experience working within X", no verb
# like delivering/managing) neither list covered yet.
ESSENTIAL_SECTION_HEADERS = (
    "essential experience", "essential requirements", "essential criteria",
    "qualifications", "requirements", "candidate requirements",
    "skills & experience", "skills and experience", "person specification",
    "about you",
    # "what we are looking for" added 07 Aug 2026 — "Internal Audit - Assistant
    # Manager" (Forvis Mazars, rated 7) used this header and the bare-experience
    # match existed in the text already, but was never checked since this
    # header phrase wasn't recognised.
    "what we are looking for", "what we're looking for",
    # "who we're looking for" added 12 Aug 2026 — "Risk Analyst" (Balfour
    # Beatty, rated 8, flagged) used this "who" variant instead of "what";
    # BARE_EXPERIENCE_REGEX already matched "Experience working in a
    # dedicated Risk Analyst role" verbatim, but the section-header gate
    # never triggered since this exact phrasing wasn't in the list.
    "who we are looking for", "who we're looking for",
)
# "in|of" before the verb made optional 28 Jul 2026 — "Junior Asset Manager"
# (OXBO) had "Requirements: Experience managing renewable energy portfolios",
# i.e. "Experience" directly followed by the verb with no preposition, which
# the original pattern (requiring "in/of managing") didn't match. "coming
# from" added same day after "Client Solutions Consultant" (JONEX Global) had
# "About You... Professional Background: Experience coming from a Strategy
# consulting, Management consulting..." under an "About You" header (also
# newly added above).
BARE_EXPERIENCE_REGEX = re.compile(
    r"\bexperience\s+(?:(?:in|of)\s+)?(?:delivering|managing|providing|leading|handling|running)\b|\bexperience\s+(?:working\s+(?:within|in)|coming\s+from)\b",
    re.IGNORECASE,
)

# Requiring an already-held professional qualification (ACA/ACCA/etc.) is a
# different ask from a graduate scheme that sponsors you *towards* one —
# "Professional certifications such as ACA, ACCA, or similar" (same Azets
# listing) means the candidate needs to already hold it. Deliberately narrow
# so it doesn't catch "study towards ACA/ACCA", which is exactly what the
# candidate wants from a graduate accounting/audit scheme.
ALREADY_QUALIFIED_TERMS = (
    "professional certifications such as", "professional qualification such as",
    "professional qualifications such as", "aca qualified", "acca qualified",
    "aca/acca qualified", "fully qualified accountant",
    # "qualified (practice) accountant" added 06 Aug 2026 — "Audit Manager"
    # (Xeinadin, flagged) said "will be a qualified practice accountant
    # (ACCA/ACA)", noun-first phrasing the existing "ACCA/ACA qualified"
    # (adjective-first) patterns didn't cover.
    "qualified practice accountant", "qualified accountant",
    "part qualified accountant", "part-qualified accountant",
    "chartered surveyor", "qualified surveyor", "qualified actuary",
    "nearly qualified actuary", "newly qualified actuary",
    "qualified mortgage adviser", "qualified solicitor", "practising solicitor",
)

# Regex counterpart added 18 Aug 2026 to compensate for the AI qualification
# check being disabled (Anthropic API credit cost) — the plain-string list
# above only matches "X qualified" adjective-first phrasing; real postings
# just as often use "X qualification" (noun form) and/or a slash-separated
# list of acceptable acronyms ("ACA/ICAS qualification", "AAT qualification",
# "MRICS qualification"). One regex covers both forms and any combination of
# acronyms rather than needing every "A/B qualified|qualification" pairing
# spelled out as a literal string. Same ALREADY_QUALIFIED_ASPIRATIONAL_CONTEXT
# guard is applied at the call site below.
PROFESSIONAL_QUALIFICATION_REQUIRED_REGEX = re.compile(
    r"\b(?:aca|acca|cima|aat|rics|mrics|ifoa|cemap|att|cta|icas)"
    r"(?:\s*[/,]\s*(?:aca|acca|cima|aat|rics|mrics|ifoa|cemap|att|cta|icas))*"
    r"\s+qualif(?:ied|ication)\b",
    re.IGNORECASE,
)

# Guard against aspirational framing — "Axon Moore Group Ltd — Graduate
# Trainee Accountant" (rated 8) said "...drive to BECOME a fully qualified
# accountant", describing the training goal of the grad scheme itself, not a
# requirement the candidate already meets. Skip if one of these appears in the
# ~30 chars right before the match.
ALREADY_QUALIFIED_ASPIRATIONAL_CONTEXT = (
    "become a", "become an", "becoming a", "becoming an", "towards",
    "path to", "route to", "aim to", "aiming to", "aspire to",
    "study to", "studying to", "training to",
)


def _requires_prior_role_experience(text: str) -> bool:
    for term in ALREADY_QUALIFIED_TERMS:
        idx = text.find(term)
        if idx == -1:
            continue
        preceding = text[max(0, idx - 30):idx]
        if any(ctx in preceding for ctx in ALREADY_QUALIFIED_ASPIRATIONAL_CONTEXT):
            continue
        return True
    for m in PROFESSIONAL_QUALIFICATION_REQUIRED_REGEX.finditer(text):
        preceding = text[max(0, m.start() - 30):m.start()]
        if any(ctx in preceding for ctx in ALREADY_QUALIFIED_ASPIRATIONAL_CONTEXT):
            continue
        return True
    for header in ESSENTIAL_SECTION_HEADERS:
        idx = text.find(header)
        if idx == -1:
            continue
        # Widened 200 -> 450 on 12 Aug 2026 — "Risk Analyst" (Balfour Beatty,
        # rated 8, flagged) had the header match correctly but its actual
        # "Experience working in a dedicated Risk Analyst role" bullet sat
        # two other bullets (certification, degree) further down, past the
        # old 200-char cutoff. A bullet list under a requirements header can
        # run long, so the window needs enough room to reach a requirement
        # that isn't the first bullet.
        window = text[idx:idx + 450]
        if BARE_EXPERIENCE_REGEX.search(window):
            return True
    for m in PRIOR_ROLE_EXPERIENCE_REGEX.finditer(text):
        preceding = text[max(0, m.start() - 40):m.start()]
        following = text[m.end():m.end() + 40]
        if any(neg in preceding[-25:] for neg in PRIOR_ROLE_EXPERIENCE_NEGATIONS):
            continue
        if any(neg in following for neg in PRIOR_ROLE_EXPERIENCE_TRAILING_NEGATIONS):
            continue
        if any(ctx in preceding for ctx in PRIOR_ROLE_EXPERIENCE_EMPLOYER_CONTEXT):
            continue
        if any(ctx in following for ctx in PRIOR_ROLE_EXPERIENCE_ACADEMIC_CONTEXT):
            continue
        if PRIOR_ROLE_EXPERIENCE_INTERNSHIP_ALTERNATIVE_REGEX.search(preceding):
            continue
        return True
    return False


# "Must currently be a student" listings — common in finance/consulting spring
# weeks, insight days, and some internships. The candidate has already graduated, so
# these are a hard mismatch regardless of how well the sector/title matches.
# Added 27 Jul 2026 alongside the finance/IB/PE/AM/WM sector expansion.
CURRENT_STUDENT_REQUIRED_TERMS = [
    "penultimate year", "final year student", "final-year student",
    "currently enrolled", "currently studying", "current university student",
    "must be a student", "must still be studying", "still be studying",
    "undergraduate students only", "second year student", "first year student",
    "1st year student", "2nd year student", "students in their penultimate",
    "returning to university", "returning to your studies", "spring week",
    "spring insight", "insight day", "insight programme", "insight week",
    "must be in your penultimate", "must be in their penultimate",
    "open to students", "open only to students", "current students only",
    # Added 28 Jul 2026 — "Graduate Finance/Business Analyst" (The Opportunity
    # Hub UK, rated 9) required "Current undergraduate in Finance..." and
    # slipped through because this list didn't cover that exact phrasing.
    "current undergraduate", "currently an undergraduate",
    "you are an undergraduate",
    # Added 06 Aug 2026 — "Executive Search Graduate Program" (Korn Ferry,
    # flagged) required "Be on track to graduate with a 2:1 or better in
    # 2026" — future-tense, implies not-yet-graduated, a phrasing variant
    # none of the above literal matches covered.
    "on track to graduate",
]


# Same disjunction-blindness bug as PRIOR_ROLE_EXPERIENCE_INTERNSHIP_
# ALTERNATIVE_REGEX above, found in the same 09 Aug 2026 sweep: "open to
# students and graduates" is NOT a student-only requirement — it explicitly
# includes graduates too — but "open to students" as a bare substring/term
# match fires on it regardless. Only these terms use "students" as a broad,
# widenable eligibility category; the rest (final-year student, currently
# enrolled, etc.) describe a specific enrollment status that isn't changed
# by an adjacent "or graduates" mention, so they stay unconditional.
_AMBIGUOUS_STUDENT_TERMS = {
    "open to students", "open only to students", "current students only",
    "undergraduate students only",
}
_STUDENT_TERM_GRADUATE_DISJUNCTION_REGEX = re.compile(
    r"^\s*,?\s*(?:and|or|&)\s+(?:recent\s+)?graduates?\b", re.IGNORECASE,
)


def _requires_current_student_status(text: str) -> bool:
    for term, pattern in zip(CURRENT_STUDENT_REQUIRED_TERMS, CURRENT_STUDENT_REQUIRED_PATTERNS):
        m = pattern.search(text)
        if not m:
            continue
        if term in _AMBIGUOUS_STUDENT_TERMS:
            following = text[m.end():m.end() + 30]
            if _STUDENT_TERM_GRADUATE_DISJUNCTION_REGEX.search(following):
                continue
        return True
    return False


# Industries/roles consistently rejected by user, or plainly outside the
# candidate's target sectors (ecommerce/marketplace/commercial/finance/
# consulting) — checked against title+description, not just title.
INDUSTRY_PENALTY_TERMS = [
    "pharma", "pharmaceutical", "life science", "biotech", "biotechnology", "clinical research",
    "healthcare technology", "medtech",
    # Jewellery & watches — caught in title by config, caught in description here
    "jewellery", "jewelry", "jeweller", "jeweler",
    "watchmaker", "horology", "gemstone", "fine jewellery", "luxury watches", "watch brand",
    # Footwear & apparel
    "footwear", "apparel", "womenswear", "menswear", "sportswear",
    "garment", "textile", "knitwear", "outerwear",
    # Engineering / environmental / scientific trades — unrelated industry,
    # found 26 Jul 2026 (Junior Geoscientist, Water Treatment Engineer both
    # scored 10 purely on coincidental buzzword overlap with no relevance check)
    "geoscientist", "geologist", "hydrogeologist", "geophysicist", "geotechnical",
    "ground investigation", "contaminated land", "environmental consultancy",
    "water treatment", "wastewater",
    "civil engineer", "mechanical engineer", "electrical engineer", "chemical engineer",
    "structural engineer", "process engineer", "petroleum engineer", "mining engineer",
    "quantity surveyor", "site engineer",
    "ecologist", "ecology", "hydrologist", "hydrology",
    # Social media / content marketing — distinct unwanted sector, found
    # 28 Jul 2026 ("Social Media Consulting Strategist" scored a false 10
    # purely because "consulting"/"strategy" overlapped with the target
    # consulting sector; the underlying role is unrelated marketing work)
    "social media",
]

# Same list, but as a HARD exclusion (rating capped to 1 immediately) rather
# than a soft penalty — these industries are unambiguously irrelevant, so
# there's no scenario where a partial score should still let one through.
HARD_INDUSTRY_EXCLUSIONS = INDUSTRY_PENALTY_TERMS

# "Associate" roles removed entirely, per explicit user instruction 28 Jul
# 2026 — every single "Associate"-titled job flagged in this session's bulk
# re-rate turned out to be a senior/experienced hire (Capital Markets
# Associate, Investment Associate, Commercial Associate, GTM Associate, Audit
# Associate, Associate Finance Manager, etc.), consistent with the long-
# standing AMBIGUOUS_SENIORITY_TERMS note above that "associate" means
# 3-6+ yrs experience in finance/consulting specifically. Rather than keep
# patching individual description-based exclusions, hard-exclude on the TITLE
# itself — checked against title only (not full text) so an incidental
# "associate director" mention in an unrelated job's description doesn't
# trigger it.
ASSOCIATE_TITLE_REGEX = re.compile(r"\bassociate\b", re.IGNORECASE)

# "Buyer"/"buying" roles removed entirely, per explicit user instruction
# 28 Jul 2026 — de-scoring (removing the CV_KEYWORDS/TARGET_TITLES boost)
# wasn't enough: "Assistant Buyer - Home, Plush & Toys" (Warner Bros.
# Discovery) still scored 8 via unrelated keyword overlap ("Strong cv
# alignment" from other matched terms). Same fix as ASSOCIATE_TITLE_REGEX —
# hard-exclude on the TITLE only, so an incidental "liaising with our buying
# team" mention elsewhere doesn't wrongly exclude an unrelated job.
BUYER_TITLE_REGEX = re.compile(r"\bbuy(?:er|ing)\b", re.IGNORECASE)

# GRADUATE-ONLY MODE — added 18 Aug 2026, user: "for now, remove everything
# but graduate roles". Temporary, same convention as the sales/BDR pause
# above: title-only hard exclusion, doesn't touch SENIORITY_TERMS/
# SEARCH_KEYWORDS/CV_KEYWORDS, so removing this one regex + its callsite
# fully restores normal junior/entry-level/intern/trainee coverage later.
# Carved out so a title containing BOTH words (e.g. "Graduate/Junior Analyst
# Programme") still passes — only excludes when "graduate" is absent.
NON_GRADUATE_SENIORITY_TITLE_REGEX = re.compile(
    r"\bjunior\b|\bentry[\s-]level\b|\binternship\b|\bintern\b|\bplacement\b|\boff[\s-]cycle\b|\btrainee\b",
    re.IGNORECASE,
)
GRADUATE_TITLE_CARVE_OUT_REGEX = re.compile(r"\bgraduate\b", re.IGNORECASE)

# A job TITLE containing "Experienced" (e.g. "Experienced Recruitment
# Consultants", Tank Recruitment, rated 7) is about as unambiguous a signal as
# exists that the employer wants someone who already works in that field —
# fundamentally incompatible with an entry-level/graduate search regardless of
# what else matches. Title-only, same reasoning as ASSOCIATE_TITLE_REGEX.
EXPERIENCED_TITLE_REGEX = re.compile(r"\bexperienced\b", re.IGNORECASE)

# Academic/research titles have nothing to do with the candidate's target
# sectors and require a PhD — found 28 Jul 2026 via "Postdoctoral Research
# Fellow (Tian Lab) - Generative Biology Institute" (rated 7, found via
# 'junior commercial' search, scored via coincidental CV-keyword overlap in
# the description). No existing check caught it since it's not an industry
# term already in HARD_INDUSTRY_EXCLUSIONS ("biotech" etc.) — this is a title
# pattern instead.
ACADEMIC_TITLE_REGEX = re.compile(
    r"\b(?:postdoctoral|post-doctoral|postdoc|research fellow|professorship|lecturer|doctoral researcher)\b",
    re.IGNORECASE,
)

# "Paraplanner"/"paraplanning" roles removed entirely, per explicit user
# instruction 07 Aug 2026 — "Trainee Paraplanner" (Eden Rose, rated 7,
# found via generic 'graduate scheme' search) is a niche wealth-management
# support track the candidate isn't targeting, not a rating-logic bug (it
# scored via ordinary partial keyword overlap, same as any other unwanted
# sector would). Same title-only hard-exclusion pattern as Associate/Buyer/
# Experienced/Academic — not a description scan, so an incidental mention
# elsewhere doesn't wrongly exclude an unrelated job.
PARAPLANNER_TITLE_REGEX = re.compile(r"\bparaplann(?:er|ing)\b", re.IGNORECASE)

# Catering/kitchen roles — "Retail Junior Sous Chef" (Compass Group, flagged
# 09 Aug 2026, rated 9) scored highly purely off coincidental "retail"/"junior"
# keyword overlap despite being a chef job with nothing to do with any target
# sector. Title-only, same pattern as Associate/Buyer/Experienced/Paraplanner
# above — "chef" alone covers "chef", "sous chef", "head chef", "commis chef"
# etc. since \b matches the bare word inside each compound title.
CHEF_TITLE_REGEX = re.compile(r"\bchef\b", re.IGNORECASE)

# Recruitment-industry roles excluded entirely, per explicit user instruction
# 10 Aug 2026 — first flagged as just "recruitment consultant" (Ernest Gordon
# Recruitment posting), then broadened same day to "any recruitment roles"
# on follow-up. Matches the "recruit" stem so it covers Recruiter/Recruitment
# Consultant/Recruitment Resourcer/Talent Acquisition Recruiter/etc. in one
# pattern. Same title-only hard-exclusion convention as
# Associate/Buyer/Experienced/Paraplanner/Chef above — checked against title
# only so an incidental "our recruitment process" mention elsewhere doesn't
# wrongly exclude an unrelated job.
RECRUITMENT_TITLE_REGEX = re.compile(r"\brecruit\w*\b", re.IGNORECASE)

# Used to exempt SDR/BDR-titled roles from the tech penalty below (not a
# hard exclusion — see the tech_penalty calculation in rate()).
SDR_BDR_ROLE_TITLE_REGEX = re.compile(
    r"\b(?:sdr|bdr)\b|\bsales development\b|\bbusiness development representative\b",
    re.IGNORECASE,
)

# Sales/BDR/SDR pause (added 10 Aug 2026, "for now") reversed 15 Aug 2026 —
# user explicitly asked for SDR/BDR roles back, especially in tech/AI. The
# hard-exclusion regex and its (Sales)-department carve-out have been
# removed entirely rather than left dormant, exactly as originally planned
# ("removing this one regex + its two callsites fully restores the old
# behaviour"). CV_KEYWORDS/TARGET_TITLES/STRONG_TITLE_SECTORS never dropped
# sdr/bdr/business development, so scoring for these roles was unaffected
# throughout the pause — only the title-level hard block is gone now.

# Trades/engineering installation roles — "Installation Engineer (Trainee /
# Junior Electrical)" (TRS, flagged 09 Aug 2026, rated 7) scored via the same
# kind of coincidental "junior"/"trainee" seniority overlap; the role itself
# (hands-on electrical installation work) is unrelated to any target sector,
# same class of mismatch as the existing engineering-trades entries in
# HARD_INDUSTRY_EXCLUSIONS below, but this exact title phrase wasn't covered
# since the description never used the literal words "electrical engineer".
INSTALLATION_ENGINEER_TITLE_REGEX = re.compile(r"\binstallation engineer\b", re.IGNORECASE)

# Formal security clearance (BPSS/CTC/SC/DV) is a genuinely hard, months-long
# bar regardless of the candidate's specific nationality — added 18 Aug 2026
# (AI check disabled, compensating in rater.py) after "Junior Consultant"
# (ResoLex, AI-excluded) required willingness to undergo BPSS/CTC/SC
# clearances. Deliberately does NOT match on "UK national(ity)" alone — the
# candidate's actual nationality isn't known from the profile, so excluding
# on that specifically would be a guess, not a fact; the clearance acronyms
# are the concrete, verifiable signal.
SECURITY_CLEARANCE_REGEX = re.compile(
    r"\b(?:bpss|ctc|sc|dv)(?:\s*[/,]\s*(?:bpss|ctc|sc|dv))*\s+(?:security\s+)?clearances?\b",
    re.IGNORECASE,
)

# A STEM-only degree requirement is a categorical mismatch for a candidate
# with a non-STEM degree (profile "degree_subject"), regardless of how well the rest of the listing scores
# — found 28 Jul 2026 via "Client Solutions Consultant - Engineering &
# Industrial" (JONEX Global, rated 8): "Are you a high-achieving STEM
# graduate..." / "Academic Background: ...degree in Mechanical Engineering,
# Electrical Engineering, Electronics, or a closely related STEM discipline."
# Deliberately narrow to phrases naming STEM/engineering specifically as the
# required discipline — does NOT match generic "Economics, Business, Finance
# or related field" listings that happen to also mention engineering as one
# of several acceptable subjects.
STEM_DEGREE_REGEX = re.compile(
    r"\bstem\s+(?:graduate|discipline|degree|background|subject)\b"
    r"|\bdegree\s+in\s+(?:mechanical|electrical|electronic|civil|chemical|software)\s+engineering\b"
    r"|\bengineering\s+degree\s+(?:required|essential)\b"
    # Broadened 18 Aug 2026 (AI check disabled, compensating in rater.py) —
    # specific non-Economics-compatible degree subjects that showed up
    # repeatedly as an explicit requirement: law, construction/built-
    # environment, computer science/cyber security, and the general
    # "quantitative or scientific discipline" phrasing. Deliberately doesn't
    # touch generic "Economics, Finance, Business or related field" listings
    # — only fires on these specific incompatible subjects.
    r"|\b(?:degree|llb)\s+in\s+law\b|\blaw\s+degree\b|\bllb\b"
    r"|\bdegree\s+in\s+(?:building surveying|construction management|architecture|architectural technology)\b"
    r"|\bdegree\s+in\s+(?:computer science|cyber ?security)\b"
    r"|\bquantitative\s+or\s+scientific\s+discipline\b",
    re.IGNORECASE,
)

# "or <degree subject>" disjunction guard — added 18 Aug 2026, found while
# spot-checking a retrate run after an unrelated rater.py fix: "Strategy
# Analyst" (GradBay, rated 8) required "an undergraduate, Master's or PhD
# qualification in a STEM subject or Economics" — the candidate holds a
# degree in that subject, so this is explicitly NOT excluded, but the regex's "stem ...
# subject" branch fired on the "STEM subject" half of the disjunction
# without seeing the "or Economics" alternative immediately after it. Same
# disjunction-blindness bug class as PRIOR_ROLE_EXPERIENCE_INTERNSHIP_
# ALTERNATIVE_REGEX and the "open to students and graduates" guard above.
# Only guards the "stem ... subject/degree/discipline/background/graduate"
# branch — the other STEM_DEGREE_REGEX branches (specific engineering
# degrees, law, etc.) aren't touched since a disjunction there hasn't been
# observed and guarding them isn't warranted by this one case.
STEM_SUBJECT_BRANCH_REGEX = re.compile(r"\bstem\s+(?:graduate|discipline|degree|background|subject)\b", re.IGNORECASE)
STEM_ECONOMICS_DISJUNCTION_REGEX = re.compile(r"^[^.]{0,40}\bor\s+" + re.escape(_DEGREE_SUBJECT) + r"\b", re.IGNORECASE)


def _requires_stem_degree(text: str) -> bool:
    for m in STEM_DEGREE_REGEX.finditer(text):
        if STEM_SUBJECT_BRANCH_REGEX.fullmatch(m.group(0)):
            following = text[m.end():m.end() + 40]
            if STEM_ECONOMICS_DISJUNCTION_REGEX.search(following):
                continue
        return True
    return False

# A requirement for a MANUAL driving licence specifically is a concrete,
# unmeetable mismatch for a candidate who only holds an automatic licence
# (profile "has_manual_driving_licence": false) —
# added 06 Aug 2026 via "Graduate Management Trainee - Wrexham" (Enterprise,
# flagged, rated 10, "You must have a full manual UK or EU driving licence").
# The listing's own "we make accommodations for applicants who don't drive
# due to a disability" carve-out is narrow (disability only) and doesn't
# cover an automatic-only licence holder who is otherwise able to drive, so
# it isn't treated as a negation here.
MANUAL_LICENCE_REGEX = re.compile(
    r"\bmanual\s+(?:uk\s+or\s+eu\s+)?driving licen[cs]e\b|\bfull\s+manual\s+licen[cs]e\b",
    re.IGNORECASE,
)

# Some employers post a neutral external title but disclose the real
# seniority in the description via an "Internal Job Title:" line — e.g.
# "Data Analyst - Sustainability" (SC Johnson Professional, rated 8, flagged
# by user 6 Aug 2026) whose description said "Internal Job Title: Senior
# Associate, Data Analyst, Sustainability". Neither ASSOCIATE_TITLE_REGEX nor
# config.EXCLUDED_TITLE_KEYWORDS's "senior" catch this, since both only check
# the external listing title. Checked against a short window right after the
# "internal job title:" label only (not the whole description), so an
# unrelated "senior" mention elsewhere in the posting doesn't wrongly exclude
# a genuine junior role. "corporate title" added 06 Aug 2026 — "Investment
# Banking Coverage Specialist" (Deutsche Bank, flagged, rated 9) disclosed
# "Corporate Title Associate/Vice President", the same pattern under a
# different label banks commonly use instead of "Internal Job Title:". Colon
# made optional in the same fix — this site's scraped description ran the
# label straight into the value with no ":" at all (a table-layout artifact
# from the source page), unlike the SC Johnson case which did have one.
INTERNAL_JOB_TITLE_REGEX = re.compile(r"(?:internal job title|corporate title):?\s*([^\n]{0,80})", re.IGNORECASE)
INTERNAL_JOB_TITLE_SENIORITY_REGEX = re.compile(r"\b(?:senior|associate)\b", re.IGNORECASE)


def _has_senior_internal_title(text: str) -> bool:
    m = INTERNAL_JOB_TITLE_REGEX.search(text)
    if not m:
        return False
    return bool(INTERNAL_JOB_TITLE_SENIORITY_REGEX.search(m.group(1)))

# Non-English job listing phrases — distinctive phrases from major non-English languages
NON_ENGLISH_PHRASES = [
    # French
    "nous recherchons", "vous avez", "en cdi", "en cdd", "rejoindre notre",
    "profil recherché", "vos missions", "le poste",
    # German
    "wir suchen", "ihre aufgaben", "ihr profil", "stellenangebot",
    "bewerben sie", "vollzeit", "teilzeit", "kenntnisse",
    # Spanish
    "buscamos", "jornada completa", "se ofrece", "se requiere", "incorporación",
    # Dutch
    "wij zoeken", "functie-eisen", "werkzaamheden", "vacature",
    # Polish
    "poszukujemy", "wymagania", "oferujemy", "stanowisko",
    # Italian
    "cerchiamo", "offerta di lavoro", "azienda leader",
    # Portuguese
    "procuramos", "requisitos obrigatórios",
]

# Graduate scheme direct title bonus — awarded when seniority + a relevant
# sector both appear in the title.
STRONG_TITLE_SECTORS = [
    "commercial", "business development", "ecommerce", "e-commerce",
    "marketplace", "operations", "growth", "category",
    "sdr", "bdr", "sales",
    # Consulting — see CV_KEYWORDS note above on why bare "consulting"/
    # "strategy" were removed (28 Jul 2026)
    "management consulting", "strategy consulting", "business consulting",
    "corporate strategy", "consulting analyst", "consulting graduate scheme",
    # Finance / off-cycle
    "off-cycle", "off cycle", "private equity", "venture capital",
    "capital markets", "markets", "infrastructure", "investment",
    "finance", "financial", "trading", "banking", "analyst",
    "actuarial", "insurance", "asset management", "wealth management",
    # Procurement / supply chain / product-data analyst
    "procurement", "supply chain", "product analyst", "data analyst", "retail",
    # Marketplace partner/seller manager, pricing/RM, RevOps
    "account manager", "pricing", "seller manager", "partner manager",
    "revenue management", "revenue operations", "revops",
    # Accounting / audit
    "audit", "accounting",
    # Generic graduate scheme titles
    "management trainee", "trainee",
    # Regulatory/compliance/risk + real estate — added 11 Aug 2026
    "regulatory", "regulation", "compliance", "risk", "real estate", "property",
    # Credit — added 17 Sep 2026, see CV_KEYWORDS comment above.
    "credit",
]

REMOTE_TERMS = ["remote", "hybrid", "work from home", "wfh"] + [
    loc.lower() for loc in _PROFILE.get("preferred_locations", [])
]
UK_CITIES = [
    "manchester", "birmingham", "leeds", "bristol", "edinburgh",
    "glasgow", "sheffield", "liverpool", "newcastle", "nottingham",
    "cardiff", "leicester", "coventry", "reading", "brighton",
]

# Precompiled word-boundary-safe patterns — see matching.py. Plain substring
# checks let short terms false-match inside unrelated words (e.g. "intern"
# inside "international", "grad" inside "upgrade", "ey" inside "they"), which
# silently inflated ratings across every source, not just one bug found
# during the 26 Jul 2026 audit.
SENIORITY_PATTERNS = compile_terms(SENIORITY_TERMS)
UNAMBIGUOUS_SENIORITY_PATTERNS = compile_terms(UNAMBIGUOUS_SENIORITY_TERMS)
CV_KEYWORD_PATTERNS = compile_terms(CV_KEYWORDS)
TARGET_TITLE_PATTERNS = compile_terms(TARGET_TITLES)
TECH_PENALTY_PATTERNS = compile_terms(TECH_PENALTY_KEYWORDS)
LANGUAGE_PENALTY_PATTERNS = compile_terms(LANGUAGE_PENALTY_TERMS)
INDUSTRY_PENALTY_PATTERNS = compile_terms(INDUSTRY_PENALTY_TERMS)
HARD_INDUSTRY_PATTERNS = compile_terms(HARD_INDUSTRY_EXCLUSIONS)
NON_ENGLISH_PATTERNS = compile_terms(NON_ENGLISH_PHRASES)
STRONG_TITLE_SECTOR_PATTERNS = compile_terms(STRONG_TITLE_SECTORS)
CURRENT_STUDENT_REQUIRED_PATTERNS = compile_terms(CURRENT_STUDENT_REQUIRED_TERMS)


def rate(job) -> dict:
    # Normalise smart quotes to straight ones — scraped text sometimes uses
    # U+2019/U+2018 for apostrophes ("don't"), which silently failed to match
    # negation phrases like "don't " that assumed a straight quote. Found
    # 28 Jul 2026 while spot-checking the prior-role-experience exclusion.
    title = job.title.lower().replace("’", "'").replace("‘", "'")
    desc = (job.description or "").lower().replace("’", "'").replace("‘", "'")
    location = (job.location or "").lower()
    salary_str = (job.salary or "").lower()
    text = f"{title} {desc}"

    # Hard exclusions — return 1 immediately, will be filtered by MIN_RATING
    if NON_GRADUATE_SENIORITY_TITLE_REGEX.search(title) and not GRADUATE_TITLE_CARVE_OUT_REGEX.search(title):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: non-graduate seniority label (junior/entry-level/intern/placement/trainee) — graduate-only mode, temporary, 18 Aug 2026."}
    if ASSOCIATE_TITLE_REGEX.search(title):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: 'Associate' roles excluded by user preference (consistently a senior title in practice)."}
    if BUYER_TITLE_REGEX.search(title):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: 'Buyer'/'buying' roles excluded by user preference."}
    if EXPERIENCED_TITLE_REGEX.search(title):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: title explicitly asks for an 'Experienced' candidate."}
    if ACADEMIC_TITLE_REGEX.search(title):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: academic/research title, unrelated to target sectors."}
    if PARAPLANNER_TITLE_REGEX.search(title):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: 'Paraplanner' roles excluded by user preference."}
    if RECRUITMENT_TITLE_REGEX.search(title):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: recruitment-industry roles excluded by user preference."}
    if CHEF_TITLE_REGEX.search(title):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: catering/kitchen role, unrelated to target sectors."}
    if INSTALLATION_ENGINEER_TITLE_REGEX.search(title):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: trades/installation engineering role, unrelated to target sectors."}
    if _requires_stem_degree(text):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: requires a STEM/engineering degree the candidate doesn't have."}
    if _has_senior_internal_title(text):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: internal job title reveals a senior/associate-level role."}
    if not _HAS_MANUAL_LICENCE and MANUAL_LICENCE_REGEX.search(text):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: requires a manual driving licence the candidate doesn't hold."}
    if SECURITY_CLEARANCE_REGEX.search(text):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: requires formal security clearance (BPSS/CTC/SC/DV)."}
    if any_match(NON_ENGLISH_PATTERNS, text):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: Non-English job listing."}
    if any_match(HARD_INDUSTRY_PATTERNS, text):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: Unwanted/irrelevant industry."}
    if _requires_experience(text):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: description requires 1+ years experience."}
    if _requires_current_student_status(text):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: requires being a current university student."}
    if _requires_prior_role_experience(text):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: requires specific prior-role experience the candidate doesn't have."}
    if _requires_foreign_language(text):
        return {"rating": 1, "seniority_match": False, "notes": "EXCLUDED: requires a foreign language the candidate doesn't speak."}

    # 1. Seniority (max 3 pts)
    effective_seniority_patterns = SENIORITY_PATTERNS if desc.strip() else UNAMBIGUOUS_SENIORITY_PATTERNS
    seniority_match = any_match(effective_seniority_patterns, text)
    # 1.5 (not 0) when silent on seniority — added 11 Aug 2026. Every job
    # reaching this line has already survived the explicit years-of-
    # experience and prior-role-experience hard exclusions above, so "no
    # seniority word" here means the posting simply never states a level,
    # not that it's confirmed senior — a materially different case from an
    # explicit "graduate"/"junior" match, but not equivalent to zero
    # evidence either. Kept well below the 3.0 full match so this alone
    # can't clear MIN_RATING; it only closes the gap for jobs where CV/role
    # alignment is independently strong. The AI qualification check (which
    # explicitly checks "if posting requires 2+ years, reject") remains the
    # real backstop against a job that's silent because it's actually senior.
    seniority_score = 3.0 if seniority_match else 1.5

    # 2. CV Alignment (max 3 pts)
    matches = count_matches(CV_KEYWORD_PATTERNS, text)
    cv_score = min(3.0, matches * 0.5)

    # 3. Role Match (max 2 pts)
    title_matches = count_matches(TARGET_TITLE_PATTERNS, title)
    if title_matches >= 2:
        role_score = 2.0
    elif title_matches == 1:
        role_score = 1.2
    else:
        desc_matches = count_matches(TARGET_TITLE_PATTERNS, desc)
        role_score = 0.5 if desc_matches >= 2 else 0.0

    # 4. Salary (max 1 pt)
    salary_score = _score_salary(salary_str)

    # 5. Location (max 1 pt)
    location_score = _score_location(location)

    grad_title_bonus = 0.0
    if any_match(effective_seniority_patterns, title) and any_match(STRONG_TITLE_SECTOR_PATTERNS, title):
        grad_title_bonus = 2.5

    # Tech penalty — reduce score if description is CS/dev heavy. Skipped
    # entirely for SDR/BDR-titled roles (added 15 Aug 2026, alongside
    # re-enabling SDR/BDR search coverage): a sales role at a SaaS/AI company
    # will describe its own product using words like "software"/"cloud"/
    # "AI"/"machine learning" throughout the listing — that's the product
    # being sold, not a skill the candidate needs, and shouldn't be treated
    # the same as an actual engineering-role requirement.
    if SDR_BDR_ROLE_TITLE_REGEX.search(title):
        tech_penalty = 0.0
    else:
        tech_hits = count_matches(TECH_PENALTY_PATTERNS, text)
        tech_penalty = min(3.0, tech_hits * 0.8)

    # Language penalty — role requires a language the user doesn't speak
    lang_penalty = 3.0 if any_match(LANGUAGE_PENALTY_PATTERNS, text) else 0.0

    # Industry penalty — sectors user consistently rejects (soft version;
    # most of these terms are already hard-excluded above, this stays as a
    # backstop in case new terms are added here without a hard exclusion)
    industry_penalty = 2.0 if any_match(INDUSTRY_PENALTY_PATTERNS, text) else 0.0

    # Manager-without-seniority penalty — BDM/Commercial Manager = too senior
    manager_penalty = 0.0
    if "manager" in title and "account manager" not in title and not any_match(effective_seniority_patterns, title):
        manager_penalty = 2.0

    total = (seniority_score + cv_score + role_score + salary_score + location_score
             + grad_title_bonus
             - tech_penalty - lang_penalty - industry_penalty - manager_penalty)

    # Cap at 5 if no seniority — raised to 9 for strong matches (added 11 Aug
    # 2026: deverellsmith "Analyst", ICE "Analyst, Market Regulation", and
    # Haystack "Data Analyst" all hit this exact cap despite strong CV+role
    # alignment, just because the posting never literally says "junior"/
    # "graduate" — three real misses from the same root cause in one session
    # after patching individual implicit-seniority phrasings each time. Any
    # job reaching this point has already survived _requires_experience()/
    # _requires_prior_role_experience() above, so "no seniority word" here
    # means the posting is silent on experience, not that it demands it —
    # "silent" is a materially different risk than "explicitly senior".
    # Still capped at 5 (not uncapped) unless BOTH CV alignment and role
    # match are independently strong, so a weak/ambiguous job with no
    # seniority signal is unaffected. The AI qualification check remains a
    # fully independent second-pass gate on every job that clears
    # MIN_RATING regardless of this score.
    if not seniority_match:
        cap = 9.0 if (cv_score >= 2.0 and role_score >= 1.5) else 5.0
        total = min(total, cap)

    rating = max(1, min(10, round(total)))

    notes = _build_notes(seniority_match, cv_score, role_score, salary_score, location_score,
                         lang_penalty, industry_penalty, manager_penalty)

    return {
        "rating": rating,
        "seniority_match": seniority_match,
        "notes": notes,
    }


def _score_salary(salary_str: str) -> float:
    if not salary_str:
        return 0.5
    numbers = re.findall(r'[\d,]+', salary_str.replace(",", ""))
    values = []
    for n in re.findall(r'\d+', salary_str.replace(",", "")):
        v = int(n)
        if 10000 <= v <= 200000:
            values.append(v)
    if not values:
        return 0.5
    # Use the lower bound
    low = min(values)
    # Handle shorthand like "28k"
    if "k" in salary_str:
        raw = re.findall(r'(\d+)k', salary_str)
        if raw:
            low = int(raw[0]) * 1000
    if low >= _TARGET_SALARY:
        return 1.0
    if low >= _MIN_ACCEPTABLE_SALARY:
        return 0.5
    return 0.0


def _score_location(location: str) -> float:
    if not location:
        return 0.5
    if any(t in location for t in REMOTE_TERMS):
        return 1.0
    if any(city in location for city in UK_CITIES):
        return 1.0
    if "united kingdom" in location or "uk" in location:
        return 1.0
    return 0.3


def _build_notes(seniority: bool, cv: float, role: float, salary: float, location: float,
                 lang: float, industry: float, manager: float) -> str:
    parts = []
    if not seniority:
        parts.append("No seniority keywords — capped at 5")
    if cv >= 2:
        parts.append("Strong CV alignment")
    elif cv >= 1:
        parts.append("Partial CV alignment")
    else:
        parts.append("Weak CV alignment")
    if role >= 1.5:
        parts.append("strong role match")
    elif role >= 0.5:
        parts.append("partial role match")
    else:
        parts.append("weak role match")
    if salary == 1.0:
        parts.append("salary meets target")
    elif salary == 0.0:
        parts.append("salary below target")
    if lang:
        parts.append("PENALISED: foreign language required")
    if industry:
        parts.append("PENALISED: industry mismatch")
    if manager:
        parts.append("PENALISED: manager title without junior qualifier")
    return ". ".join(parts).capitalize() + "."
