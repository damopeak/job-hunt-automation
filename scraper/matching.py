import re


def compile_term(term: str) -> re.Pattern:
    """Word-boundary-safe matcher for a keyword/phrase. Plain substring
    checks let short terms false-match inside unrelated words — e.g. "intern"
    (meant to catch "internship") matches inside "international"/"internal"/
    "internet" and "grad" (meant to catch "graduate") matches inside
    "upgrade"/"degrade"/"gradient". Wrapping in \\b anchors avoids that while
    still matching multi-word phrases (e.g. "account manager") correctly.
    Boundaries are only added on sides where the term itself starts/ends with
    a word character, so intentionally-crafted terms like "lead " (trailing
    space, already guards against "leader"/"leadership") keep working as before."""
    prefix = r"\b" if term[0].isalnum() else ""
    suffix = r"\b" if term[-1].isalnum() else ""
    return re.compile(prefix + re.escape(term) + suffix, re.IGNORECASE)


def compile_terms(terms) -> list:
    return [compile_term(t) for t in terms]


def any_match(patterns: list, text: str) -> bool:
    return any(p.search(text) for p in patterns)


def count_matches(patterns: list, text: str) -> int:
    return sum(1 for p in patterns if p.search(text))
