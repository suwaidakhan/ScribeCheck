"""Drug lexicon, built from the openFDA NDC directory.

SPEC section 5, M2. The lexicon decides what counts as a drug mention, so it
sets the denominator for drug accuracy. Get it wrong and M2 measures something
other than drugs.

A first build of this lexicon took generic and brand names together, straight
from openFDA, and produced a list whose most frequent matches against real
AfriSpeech clinical transcripts were "pain" (91 clips), "body" (51), "clear"
(37), "muscle" (36) and "head" (26). Those are all genuine NDC brand names, on
OTC products called things like Muscle Rub and Clear Eyes. Left in, they would
have made drug accuracy a measurement of how well each provider transcribes the
word "pain".

So provenance decides how hard a term has to work to stay:

  generic_name, active_ingredients   a drug by construction, never questioned
  brand_name only                    must not be an ordinary English word

The asymmetry is the point. Running everything through a dictionary would drop
morphine, heparin, insulin, aspirin and codeine, which are all dictionary words
and all drugs. Running nothing through it keeps "pain".

SPEC section 9 limitation 3 already says lexicon coverage is partial, and this
leans further towards precision than recall on purpose: a missed drug costs one
observation, while a false drug term costs every clip that says the word.

Run directly to build it:  python -m src.lexicon [--force]
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import requests

from src.config import LEXICON, LEXICON_FALLBACK

OPENFDA_NDC = "https://api.fda.gov/drug/ndc.json"
PAGE_SIZE = 1000
# The public tier refuses skip beyond 25,000, so the search below spends that
# budget on prescription products rather than on sunscreens.
MAX_RECORDS = 25_000
PRESCRIPTION_ONLY = 'product_type:"HUMAN PRESCRIPTION DRUG"'

# Shipped with macOS and most Linux distributions. Absence is handled, not fatal.
SYSTEM_WORDLIST = Path("/usr/share/dict/words")

# Salts, bases, excipients and dosage forms that ride along on real drug names.
# Dropped whole-string only, so "warfarin sodium" and "insulin glargine" survive
# while a transcript saying "her sodium was low" does not become a drug mention.
COLLISION_BLOCKLIST: frozenset[str] = frozenset(
    {
        "sodium",
        "chloride",
        "potassium",
        "calcium",
        "magnesium",
        "citrate",
        "carbonate",
        "bicarbonate",
        "phosphate",
        "sulfate",
        "sulphate",
        "acetate",
        "hydrochloride",
        "hydroxide",
        "oxide",
        "peroxide",
        "tartrate",
        "maleate",
        "succinate",
        "fumarate",
        "gluconate",
        "lactate",
        "nitrate",
        "bromide",
        "iodide",
        "borate",
        "silicate",
        "besylate",
        "mesylate",
        "tosylate",
        "palmitate",
        "stearate",
        "water",
        "alcohol",
        "ethanol",
        "glycerin",
        "glycerol",
        "petrolatum",
        "lanolin",
        "paraffin",
        "starch",
        "dextrose",
        "sucrose",
        "lactose",
        "cream",
        "gel",
        "ointment",
        "powder",
        "solution",
        "syrup",
        "lotion",
        "tablet",
        "tablets",
        "capsule",
        "capsules",
        "injection",
        "spray",
        "unspecified",
        "kit",
        "swab",
        "patch",
        "film",
        "suspension",
        # Prescription products that are also everyday clinical vocabulary.
        # Medical oxygen and glucose injection are real NDC prescription
        # entries, so the prescription-only search does not remove them, and
        # "her glucose was 120" is not a drug mention.
        "glucose",
        "oxygen",
        "nitrogen",
        "helium",
        "carbon dioxide",
        "air",
        # Anatomy, organ and lab-value words that reach the lexicon through
        # homeopathic and organ-derived NDC entries: "CHOLESTEROL" is a real
        # generic name (Cholesterinum), and "SUS SCROFA PITUITARY GLAND,
        # POSTERIOR" splits to leave "posterior" behind. In clinical dictation
        # these name a body part or a lab result, not a prescribing decision.
        "posterior",
        "anterior",
        "gland",
        "pituitary",
        "thyroid",
        "adrenal",
        "cholesterol",
        "bilirubin",
        "creatinine",
        "albumin",
        "hemoglobin",
        "haemoglobin",
        "protein",
        "collagen",
        "keratin",
        "placenta",
        "cartilage",
        "marrow",
        "mucosa",
        "drops",
    }
)

_ALPHA_RE = re.compile(r"[a-z]")
# NDC name strings list every active in a combination product, separated by a
# comma, a semicolon, "and", or a plus. Slash is deliberately not a separator:
# in this directory it joins a product to its dosage form, as in "neomycin
# sulfate, polymyxin b sulfate and dexamethasone suspension/ drops", and
# splitting on it produced a lexicon entry for the word "drops".
_SPLIT_RE = re.compile(r"\s*(?:;|,|\band\b|\+)\s*")


def load_english_words(path: Path = SYSTEM_WORDLIST) -> set[str]:
    """Single lowercase English words, used to disqualify brand names only.

    Returns an empty set if the wordlist is missing. That degrades the filter
    to the blocklist alone rather than failing the build, and `build` prints
    which of the two happened so the difference is never silent.
    """
    if not path.exists():
        return set()
    return {
        word.strip().lower()
        for word in path.read_text(errors="ignore").split("\n")
        if word.strip()
    }


def extract_terms_from_record(record: dict) -> tuple[set[str], set[str]]:
    """Split one NDC record into (generic terms, brand terms).

    Generic terms come from `generic_name` and `active_ingredients[].name`.
    Brand terms come from `brand_name`. The split is what lets `clean_terms`
    apply the dictionary filter to brand names alone.
    """
    generic: set[str] = set()
    brand: set[str] = set()

    generic |= _split_name(record.get("generic_name"))
    brand |= _split_name(record.get("brand_name"))

    ingredients = record.get("active_ingredients")
    if isinstance(ingredients, list):
        for ingredient in ingredients:
            # openFDA is external data; a list can hold anything.
            if isinstance(ingredient, dict):
                generic |= _split_name(ingredient.get("name"))

    return generic, brand


def _split_name(raw: object) -> set[str]:
    """Lowercase a name field and split combination products into their actives."""
    if not raw or not isinstance(raw, str):
        return set()
    return {part.strip() for part in _SPLIT_RE.split(raw.lower()) if part.strip()}


def clean_terms(
    terms: set[str],
    brand_only: set[str] | None = None,
    english_words: set[str] | None = None,
) -> set[str]:
    """Drop everything that would turn a drug mention into a false positive.

    `brand_only` holds the terms whose only provenance is a brand name. Those,
    and only those, are checked against `english_words`, and only when they are
    a single word, since the dictionary holds single words and a two-word brand
    is specific enough not to fire on ordinary speech.
    """
    brand_only = brand_only or set()
    english_words = english_words or set()

    cleaned: set[str] = set()
    for term in terms:
        term = term.strip().lower()
        if len(term) < 4:  # SPEC M2: length 4 or more.
            continue
        if not _ALPHA_RE.search(term):  # Bare NDC codes.
            continue
        if term in COLLISION_BLOCKLIST:
            continue
        if term in brand_only and " " not in term and term in english_words:
            continue
        cleaned.add(term)
    return cleaned


def fetch_openfda_terms(
    max_records: int = MAX_RECORDS,
) -> tuple[set[str], set[str]]:
    """Page through prescription NDC records, returning (generic, brand-only).

    openFDA needs no key. Partial results beat a clean exception, so a network
    error after the first page stops the loop and keeps what was read; only a
    total failure raises, and only then does the caller fall back.
    """
    generic: set[str] = set()
    brand: set[str] = set()
    records_read = 0
    skip = 0

    while skip < max_records:
        try:
            response = requests.get(
                OPENFDA_NDC,
                params={"search": PRESCRIPTION_ONLY, "limit": PAGE_SIZE, "skip": skip},
                timeout=60,
            )
        except requests.RequestException:
            if records_read == 0:
                raise
            print(f"  openFDA: network error at skip={skip}, keeping what was read.")
            break

        if response.status_code in (400, 404):
            # 404 means skip ran past the result set. 400 is the public tier's
            # answer once skip crosses its ceiling. Both mean there is no more.
            break
        response.raise_for_status()

        results = response.json().get("results", [])
        if not results:
            break
        for record in results:
            record_generic, record_brand = extract_terms_from_record(record)
            generic |= record_generic
            brand |= record_brand

        records_read += len(results)
        skip += PAGE_SIZE
        print(
            f"  openFDA: {records_read} records, {len(generic)} generic terms",
            flush=True,
        )
        time.sleep(0.3)  # 240 requests/min public limit, stay well under it.

    if records_read == 0:
        raise RuntimeError("openFDA returned no records at all.")
    print(f"  openFDA: read {records_read} prescription records.")
    # A brand name that is also a generic name is a drug, not a brand-only term.
    return generic, brand - generic


def build(force: bool = False) -> set[str]:
    """Build the lexicon, cache it to disk, and return it.

    Falls back to the committed list only if openFDA is unreachable, and says
    so, because a silent fallback would move M2's denominator with nothing in
    the results showing why.
    """
    if LEXICON.exists() and not force:
        return load()

    english = load_english_words()
    print(
        f"English wordlist: {len(english)} words from {SYSTEM_WORDLIST}"
        if english
        else f"English wordlist missing at {SYSTEM_WORDLIST}. "
        "Brand names will be filtered by the blocklist alone."
    )

    try:
        generic, brand_only = fetch_openfda_terms()
        source = "openFDA NDC directory, prescription products"
    except (requests.RequestException, RuntimeError) as exc:
        print(f"openFDA unreachable ({exc}). Falling back to the committed list.")
        if not LEXICON_FALLBACK.exists():
            raise RuntimeError(
                "openFDA is unreachable and data/drug_lexicon_fallback.txt is "
                "missing, so no lexicon can be built. Restore the fallback file."
            ) from exc
        generic = {
            line.strip()
            for line in LEXICON_FALLBACK.read_text().split("\n")
            if line.strip()
        }
        brand_only = set()
        source = "committed fallback list"

    terms = clean_terms(
        generic | brand_only, brand_only=brand_only, english_words=english
    )

    LEXICON.parent.mkdir(parents=True, exist_ok=True)
    LEXICON.write_text("\n".join(sorted(terms)) + "\n")
    print(
        f"Lexicon: {len(terms)} terms from {source}\n"
        f"  {len(generic)} generic, {len(brand_only)} brand-only before filtering\n"
        f"  -> {LEXICON}"
    )
    return terms


def load() -> set[str]:
    """Read the cached lexicon. Raises if it was never built."""
    if not LEXICON.exists():
        raise FileNotFoundError(
            f"{LEXICON} does not exist. Run `python -m src.lexicon` first."
        )
    return {line.strip() for line in LEXICON.read_text().split("\n") if line.strip()}


if __name__ == "__main__":
    build(force="--force" in sys.argv)
