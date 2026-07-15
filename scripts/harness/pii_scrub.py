"""Fail-closed PII-scrub control (HK1) -- high-precision detection ruleset.

Detection contract: high-precision machine detection + a human-ratification
recall backstop -- two layers, each doing what it is good at:

  * MACHINE layer = HIGH PRECISION, known-shape (this module). It detects only
    the well-defined PII shapes enumerated below (MUST-DETECT), each with a low
    false-block rate, and HARD-BLOCKS on any hit (no warn). It deliberately
    does NOT chase every long digit run / high-entropy token / cross-field
    reassembly -- that path produced both leaks AND an over-block storm that
    collides with the control's own reviewed_commit/content_hash fields.
  * HUMAN layer = RECALL backstop. Per-fixture, whole-artifact human
    ratification (already mandatory; the label store) is the recall catch
    for shapes / encodings / cross-field splits the machine precision mandate
    skips. "Raw never committed" bounds the residual.

MUST-DETECT shapes: email (D-1); Luhn-valid + IIN-prefixed card
after normalization (D-2); delimited SSN (D-3) and context-gated contiguous SSN
(D-3b); AWS AKIA/ASIA keys (D-4); known-vendor API keys (D-5); PEM private-key
headers (D-6); JWTs (D-7); high-entropy value ONLY under a secret-labeled key
(D-8); formatted / E.164 phone (D-9). IP is OUT (human recall).

MUST-NOT-BLOCK: pass byte-for-byte, NEVER silently redacted --
ISO-8601 datetimes, git SHAs (incl. reviewed_commit / content_hash), semver,
plain integers / 8-digit dates / config numbers, UUIDs.

PRESERVED HARD REQUIREMENTS:
  * Scrubber<->scanner independence. Two stages share NO detection
    ruleset or pattern state: the Scrubber is a regex-substitution engine
    (ruleset A, _SCRUB_*); the Scanner is a structural token/validator engine
    (ruleset B, _SCAN_*) with its OWN checksum / entropy / validity math. Each
    engine's detection math is duplicated, not shared, so blinding one engine to
    a class cannot blind the other. The ONLY shared code is the
    pre-detection Unicode normalization (a mandated common step, explicitly not
    a detection rule). The scanner receives only the cleaned bytes (no scrubber
    hints). Fault-injection test F-INDEP proves independence is real.
  * No-PII-echo. reasons / annotations / stderr / exceptions carry hit
    category + count only, never the matched substring. surfaces_hit is mapped
    to a fixed allow-list of surface names (or the generic "other").

DECISION MODEL: any MUST-DETECT hit by EITHER engine -> hard BLOCK (fail-closed,
no warn); the blocked result carries neither cleaned nor raw content. If neither
engine detects a shape, the (unmodified, byte-for-byte) copy proceeds.

SOURCE HYGIENE (QA-6): this file contains NO invisible non-ASCII
literals; every non-ASCII code point is written as an explicit backslash-u
escape. Test F-HYGIENE asserts the source is pure ASCII.
"""

import hashlib
import math
import re
import unicodedata
from collections import Counter

_SENTINEL = "[redacted]"


# ==========================================================================
# SHARED PRE-DETECTION NORMALIZATION -- NOT a detection rule.
# Used by both engines; this is the mandated common step, not shared detection.
# (Scrubber/scanner independence is scoped to DETECTION logic, not this shared
# normalizer, which is a mandated common pre-step.)
# All non-ASCII code points are explicit \uXXXX escapes (F-HYGIENE).
# ==========================================================================

# Zero-width / joiner / BOM code points that Unicode NFKC does NOT fold to a
# regular space (NFKC already folds NBSP and the en/em/thin/figure/narrow/
# ideographic spaces to U+0020). Written as escapes (F-HYGIENE).
_ZERO_WIDTH = "\u200b\u2060\ufeff"
# Dash separators that group digit runs: ASCII hyphen, en dash, em dash.
_DASHES = "-\u2013\u2014"


def _nfkc(text):
    return unicodedata.normalize("NFKC", text)


def _contiguous_digits(text):
    """NFKC-normalize, then drop whitespace, zero-width chars, and dashes so a
    grouped card/SSN digit run becomes contiguous. Dots are NOT
    stripped (so dotted-quad IPs and semver stay split -- IP is out of scope and
    semver is must-not-block). Letters and other punctuation are preserved, so
    unrelated tokens still separate digit runs."""
    out = []
    for ch in _nfkc(text):
        if ch.isspace() or ch in _ZERO_WIDTH or ch in _DASHES:
            continue
        out.append(ch)
    return "".join(out)


def _digit_runs(text):
    """Maximal runs of ASCII digits in `text`."""
    return re.findall(r"[0-9]+", text)


# ==========================================================================
# STAGE 1 -- SCRUBBER (ruleset A: regex-substitution engine). Redacts detected
# shapes and reports the categories detected. Blindable per class for the
# cond-6 fault-injection test.
# ==========================================================================

_SCRUB_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_SCRUB_AWS = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_SCRUB_VENDOR = re.compile(
    r"sk-ant-[A-Za-z0-9\-]{20,}"
    r"|sk-[A-Za-z0-9\-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|glpat-[A-Za-z0-9_\-]{20,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}"
    r"|AIza[0-9A-Za-z_\-]{35}"
    r"|(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"
)
_SCRUB_PEM = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"
)
_SCRUB_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
# Card candidate: 13-19 digits with optional single separators between them
# (ASCII space/tab, zero-width, or a dash). NFKC has already folded exotic
# spaces to U+0020 before this runs.
_SCRUB_CARD = re.compile(
    r"[0-9](?:[ \t\u200b\u2060\ufeff\-\u2013\u2014]?[0-9]){12,18}"
)
_SCRUB_SSN_DELIM = re.compile(
    r"\b([0-9]{3})[ \t\-\u2013]([0-9]{2})[ \t\-\u2013]([0-9]{4})\b"
)
_SCRUB_SSN_CONTIG = re.compile(r"\b[0-9]{9}\b")
_SCRUB_PHONE = re.compile(
    r"\+[0-9]{8,15}\b"
    r"|(?:\([0-9]{3}\)\s?|[0-9]{3}[-.\s])[0-9]{3}[-.\s][0-9]{4}"
)
_SCRUB_SSN_CONTEXT = re.compile(r"(?i)\b(?:ssn|social[ _\-]?security)\b")
_SCRUB_SECRET_KEY = re.compile(
    r"(?i)(?:secret|token|api[_\-]?key|password|passwd|pwd"
    r"|private[_\-]?key|credential|auth)"
)


def _scr_only_digits(s):
    return "".join(c for c in s if c.isdigit())


def _scr_luhn(digits):
    total = 0
    # Double every 2nd digit counting from the RIGHT: from the left, index i is
    # doubled when i % 2 == len % 2. (The scanner's _scn_luhn does this by
    # iterating reversed(); this is the same checksum by independent code.)
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _scr_iin(d):
    if len(d) < 4:
        return False
    two, three, four = int(d[:2]), int(d[:3]), int(d[:4])
    if d[0] == "4":
        return True                                  # Visa
    if 51 <= two <= 55 or 2221 <= four <= 2720:
        return True                                  # Mastercard
    if two in (34, 37):
        return True                                  # Amex
    if d[:4] == "6011" or two == 65 or 644 <= three <= 649:
        return True                                  # Discover
    if 300 <= three <= 305 or two in (36, 38):
        return True                                  # Diners
    if 3528 <= four <= 3589:
        return True                                  # JCB
    return False


def _scr_ssn_valid(area, group, serial):
    a = int(area)
    if a == 0 or a == 666 or a >= 900:
        return False
    if int(group) == 0 or int(serial) == 0:
        return False
    return True


def _scr_entropy(s):
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


class Scrubber:
    """Stage 1 regex-substitution engine (ruleset A)."""

    ALL_RULES = ("EMAIL", "CREDIT_CARD", "SSN", "AWS_KEY", "API_KEY",
                 "PRIVATE_KEY", "JWT", "SECRET_HIGH_ENTROPY", "PHONE")

    def __init__(self, disabled_rules=None):
        self.disabled = set(disabled_rules or ())

    def _on(self, label):
        return label not in self.disabled

    def scrub(self, text, key_context=""):
        """Return (cleaned_text, hit_categories). Redacts detected shapes."""
        hits = []
        s = _nfkc(text)

        # D-8: whole-value high-entropy under a secret-labeled key.
        if self._on("SECRET_HIGH_ENTROPY") and key_context and _SCRUB_SECRET_KEY.search(key_context):
            stripped = s.strip()
            if len(stripped) >= 32 and _scr_entropy(stripped) >= 4.0:
                hits.append("SECRET_HIGH_ENTROPY")
                return _SENTINEL, hits

        def rec(label):
            def repl(_m):
                hits.append(label)
                return _SENTINEL
            return repl

        # String shapes.
        if self._on("PRIVATE_KEY"):
            s = _SCRUB_PEM.sub(rec("PRIVATE_KEY"), s)
        if self._on("JWT"):
            s = _SCRUB_JWT.sub(rec("JWT"), s)
        if self._on("AWS_KEY"):
            s = _SCRUB_AWS.sub(rec("AWS_KEY"), s)
        if self._on("API_KEY"):
            s = _SCRUB_VENDOR.sub(rec("API_KEY"), s)
        if self._on("EMAIL"):
            s = _SCRUB_EMAIL.sub(rec("EMAIL"), s)

        # Digit shapes (card before phone so a valid card is not partly matched).
        if self._on("CREDIT_CARD"):
            def repl_card(m):
                # A card is a FULL contiguous 13-19-digit run (after separator
                # normalization) that passes Luhn + IIN. Extracting a card
                # embedded in a longer numeric run is intentionally NOT attempted
                # -- it is inherently low-precision (QA-10 over-block on long
                # numeric IDs) and is left to human recall (as QA-7/QA-9).
                digits = _scr_only_digits(m.group(0))
                if 13 <= len(digits) <= 19 and _scr_luhn(digits) and _scr_iin(digits):
                    hits.append("CREDIT_CARD")
                    return _SENTINEL
                return m.group(0)
            s = _SCRUB_CARD.sub(repl_card, s)

        if self._on("SSN"):
            def repl_delim(m):
                if _scr_ssn_valid(m.group(1), m.group(2), m.group(3)):
                    hits.append("SSN")
                    return _SENTINEL
                return m.group(0)
            s = _SCRUB_SSN_DELIM.sub(repl_delim, s)
            if _SCRUB_SSN_CONTEXT.search(s) or _SCRUB_SSN_CONTEXT.search(key_context or ""):
                def repl_contig(m):
                    d = m.group(0)
                    if _scr_ssn_valid(d[:3], d[3:5], d[5:]):
                        hits.append("SSN")
                        return _SENTINEL
                    return d
                s = _SCRUB_SSN_CONTIG.sub(repl_contig, s)

        if self._on("PHONE"):
            s = _SCRUB_PHONE.sub(rec("PHONE"), s)

        return s, hits


# ==========================================================================
# STAGE 2 -- SCANNER (ruleset B: structural token / validator engine). Detects
# the same shapes by a DIFFERENT technique, with its OWN math. References none
# of the _SCRUB_* patterns nor the Scrubber class.
# ==========================================================================

_SCAN_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_SCAN_SSN_DELIM = re.compile(
    r"([0-9]{3})[ \t\-\u2013]([0-9]{2})[ \t\-\u2013]([0-9]{4})"
)
_SCAN_PHONE = re.compile(
    r"\+[0-9]{8,15}"
    r"|\([0-9]{3}\)[ ]?[0-9]{3}[-.\s][0-9]{4}"
    r"|[0-9]{3}[-.\s][0-9]{3}[-.\s][0-9]{4}"
)
_SCAN_SECRET_KEY = re.compile(
    r"(?i)(?:secret|token|api[_\-]?key|password|passwd|pwd"
    r"|private[_\-]?key|credential|auth)"
)
_SCAN_SSN_CONTEXT = re.compile(r"(?i)(?:ssn|social[ _\-]?security)")
_SCAN_PUNCT = " \t\r\n.,;:()[]{}<>\"'`"
_SCAN_B64URL = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)
_SCAN_VENDOR_PREFIXES = (
    "sk-ant-", "sk-", "glpat-", "ghp_", "gho_", "ghu_", "ghs_", "ghr_",
    "xoxb-", "xoxa-", "xoxp-", "xoxr-", "xoxs-", "AIza",
    "sk_live_", "sk_test_", "rk_live_", "rk_test_", "pk_live_", "pk_test_",
)


def _scn_is_email(tok):
    tok = tok.strip(_SCAN_PUNCT)
    if tok.count("@") != 1:
        return False
    local, _, domain = tok.partition("@")
    if not local or "." not in domain:
        return False
    tld = domain.rsplit(".", 1)[-1]
    return tld.isalpha() and len(tld) >= 2


def _scn_is_aws(tok):
    if len(tok) != 20 or tok[:4] not in ("AKIA", "ASIA"):
        return False
    return all(c.isdigit() or (c.isupper() and c.isalpha()) for c in tok[4:])


def _scn_is_vendor(tok):
    for p in _SCAN_VENDOR_PREFIXES:
        if not tok.startswith(p):
            continue
        rest = tok[len(p):]
        if p == "AIza":
            return len(rest) >= 35 and all(c in _SCAN_B64URL for c in rest[:35])
        if p in ("sk-ant-", "sk-", "glpat-"):
            return len(rest) >= 20
        if p in ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"):
            return len(rest) >= 20
        if p.startswith("xox"):
            return len(rest) >= 10
        return len(rest) >= 16       # stripe-style sk_live_ / pk_test_ / ...
    return False


def _scn_is_jwt(tok):
    parts = tok.split(".")
    if len(parts) != 3 or not all(parts):
        return False
    if not (parts[0].startswith("eyJ") and parts[1].startswith("eyJ")):
        return False
    return all(all(c in _SCAN_B64URL for c in p) for p in parts)


def _scn_luhn(d):
    total, alt = 0, False
    for ch in reversed(d):
        n = ord(ch) - 48
        if alt:
            n <<= 1
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def _scn_card_prefix(d):
    if len(d) < 4:
        return False
    p2, p3, p4 = int(d[:2]), int(d[:3]), int(d[:4])
    return (
        d[0] == "4"
        or 51 <= p2 <= 55 or 2221 <= p4 <= 2720
        or p2 in (34, 37)
        or d[:4] == "6011" or p2 == 65 or 644 <= p3 <= 649
        or 300 <= p3 <= 305 or p2 in (36, 38)
        or 3528 <= p4 <= 3589
    )


def _scn_ssn_valid(nine):
    area = int(nine[:3])
    return not (area == 0 or area == 666 or area >= 900
                or int(nine[3:5]) == 0 or int(nine[5:]) == 0)


def _scn_entropy(s):
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    acc = 0.0
    for c in freq.values():
        p = c / n
        acc -= p * math.log2(p)
    return acc


class Scanner:
    """Stage 2 structural token/validator engine (ruleset B)."""

    def scan(self, cleaned_text, key_context=""):
        hits = []
        s = _nfkc(cleaned_text)
        tokens = s.split()

        for tok in tokens:
            if _scn_is_email(tok):
                hits.append("EMAIL")
                break
        for tok in tokens:
            if _scn_is_jwt(tok.strip(_SCAN_PUNCT)):
                hits.append("JWT")
                break
        if _SCAN_PEM.search(s):
            hits.append("PRIVATE_KEY")
        for tok in tokens:
            if _scn_is_aws(tok.strip(_SCAN_PUNCT)):
                hits.append("AWS_KEY")
                break
        for tok in tokens:
            if _scn_is_vendor(tok.strip(_SCAN_PUNCT)):
                hits.append("API_KEY")
                break

        # Card + contiguous SSN over the de-grouped digit form.
        has_ctx = bool(_SCAN_SSN_CONTEXT.search(s)
                       or _SCAN_SSN_CONTEXT.search(key_context or ""))
        card_hit = ssn_hit = False
        for run in _digit_runs(_contiguous_digits(cleaned_text)):
            # A card / SSN is a FULL contiguous run of the exact shape length.
            # Extracting a card/SSN embedded in a longer numeric run is NOT
            # attempted: low-precision (QA-10 over-block on long numeric IDs);
            # left to human recall (as QA-7/QA-9).
            if not card_hit and 13 <= len(run) <= 19 and _scn_luhn(run) and _scn_card_prefix(run):
                hits.append("CREDIT_CARD")
                card_hit = True
            if not ssn_hit and len(run) == 9 and has_ctx and _scn_ssn_valid(run):
                hits.append("SSN")
                ssn_hit = True
        # Delimited SSN (D-3, no context required).
        if not ssn_hit:
            m = _SCAN_SSN_DELIM.search(s)
            if m and _scn_ssn_valid(m.group(1) + m.group(2) + m.group(3)):
                hits.append("SSN")

        if _SCAN_PHONE.search(s):
            hits.append("PHONE")

        if key_context and _SCAN_SECRET_KEY.search(key_context):
            st = s.strip()
            if len(st) >= 32 and _scn_entropy(st) >= 4.0:
                hits.append("SECRET_HIGH_ENTROPY")

        return hits


# ==========================================================================
# Full-surface fixture handling (keys AND values; per-leaf, NO
# cross-leaf reassembly -- that is human recall).
# ==========================================================================

_KNOWN_SURFACES = ("filename", "fields", "rubric", "payload", "commit_message")
_BOUNDARIES = frozenset({"import-into-repo", "egress-to-judge"})


class ScrubResult:
    """Outcome of a full-surface scrub+scan.

    On block: `cleaned` and `cleaned_filename` are None -- the object cannot
    carry the candidate onward. On allow: `cleaned` maps surface-label -> the
    ORIGINAL leaf text (byte-for-byte; MUST-NOT-BLOCK content is never silently
    modified, AC-2).
    """

    def __init__(self, boundary):
        self.boundary = boundary
        self.blocked = False
        self.categories = Counter()     # category -> count (never content)
        self.surfaces_hit = []          # allow-listed surface labels only
        self.cleaned = None
        self.cleaned_filename = None

    @property
    def decision(self):
        return "block" if self.blocked else "allow"

    def reason_summary(self):
        return [
            {"code": "PII_DETECTED", "category": cat, "count": n}
            for cat, n in sorted(self.categories.items())
        ]

    def annotations(self):
        if not self.blocked:
            return []
        return [{
            "severity": "error",
            "message": "PII-scrub blocked at boundary '%s'; surfaces flagged: %s"
                       % (self.boundary, ", ".join(sorted(set(self.surfaces_hit)))),
        }]


def _record(result, surface_root, scrubber, scanner, text, key_context):
    """Detect over a single scalar leaf/key with BOTH engines; record hits."""
    cleaned, s_hits = scrubber.scrub(text, key_context)
    sc_hits = scanner.scan(cleaned, key_context)
    # Dedup per (surface, category): a scrubber hit AND a scanner hit on the
    # SAME leaf for the same class are ONE distinct PII occurrence, not two
    # (n-1). dict.fromkeys preserves first-seen order.
    for cat in dict.fromkeys(list(s_hits) + list(sc_hits)):
        result.categories[cat] += 1
        result.surfaces_hit.append(surface_root)


def _walk(obj, surface_root, label, key_context, scrubber, scanner, result, cleaned_map):
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            _record(result, surface_root, scrubber, scanner, ks, ks)   # scan the KEY
            child = "%s.%s" % (label, ks) if label else ks
            _walk(v, surface_root, child, ks, scrubber, scanner, result, cleaned_map)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _walk(v, surface_root, "%s[%d]" % (label, i), key_context,
                  scrubber, scanner, result, cleaned_map)
    else:
        text = "" if obj is None else str(obj)
        _record(result, surface_root, scrubber, scanner, text, key_context)
        cleaned_map[label] = text     # ORIGINAL bytes preserved for allow (AC-2)


def _clean_filename(cleaned_text):
    digest = hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest()[:16]
    return "fixture-%s.txt" % digest


def evaluate(fixture, boundary, scrubber=None, scanner=None):
    """Run the fail-closed two-stage pipeline over a full-surface fixture.

    FAIL-CLOSED: any MUST-DETECT hit by either engine OR any error -> block, and
    the blocked result carries neither cleaned nor raw content.
    """
    result = ScrubResult(boundary)

    if boundary not in _BOUNDARIES:
        result.blocked = True
        result.categories["INVALID_BOUNDARY"] += 1
        return result

    scrubber = scrubber if scrubber is not None else Scrubber()
    scanner = scanner if scanner is not None else Scanner()

    cleaned_map = {}
    try:
        if not isinstance(fixture, dict):
            _walk(fixture, "other", "other", "", scrubber, scanner, result, cleaned_map)
        else:
            ordered = [n for n in _KNOWN_SURFACES if n in fixture]
            ordered += [n for n in fixture if n not in _KNOWN_SURFACES]
            for name in ordered:
                if name in _KNOWN_SURFACES:
                    _walk(fixture[name], name, name, name,
                          scrubber, scanner, result, cleaned_map)
                else:
                    # caller-added top-level key may itself be PII -> scan it,
                    # report under generic "other" (never echo the raw key).
                    _record(result, "other", scrubber, scanner, str(name), str(name))
                    _walk(fixture[name], "other", "other.%s" % name, str(name),
                          scrubber, scanner, result, cleaned_map)
    except Exception:  # noqa: BLE001 -- fail-closed on ANY error
        result.blocked = True
        result.categories["SCRUB_ERROR"] += 1
        return result

    if result.categories:
        result.blocked = True          # any hit -> BLOCK; cleaned stays None
        return result

    result.cleaned = cleaned_map
    if boundary == "import-into-repo":
        joined = "\n".join(cleaned_map.get(k, "") for k in sorted(cleaned_map))
        result.cleaned_filename = _clean_filename(joined)
    return result
