"""Drug lexicon construction from openFDA NDC records.

The network fetch is not tested here. What is tested is the filter that turns
raw NDC records, which include sunscreens and shampoos brand-named "Clear" and
"Pain", into a list of terms it is safe to call a drug mention.

The design that these tests pin down: a term reaching the lexicon through
`generic_name` or `active_ingredients` is a drug by construction and is never
second-guessed, while a term reaching it only through `brand_name` has to prove
it is not an ordinary English word. That asymmetry is the whole point. Filtering
everything through a dictionary would drop morphine, heparin, insulin, aspirin
and codeine, which are all dictionary words and all drugs.
"""

import re

import src.lexicon as lexicon
from src.lexicon import (
    clean_terms,
    component_terms,
    extract_terms_from_record,
    load_inn_terms,
)

ENGLISH = {"pain", "clear", "body", "muscle", "head", "morphine", "insulin"}


class TestExtractFromRecord:
    def test_separates_generic_from_brand(self):
        record = {
            "generic_name": "Metformin Hydrochloride",
            "brand_name": "Glucophage",
            "active_ingredients": [{"name": "METFORMIN HYDROCHLORIDE"}],
        }
        generic, brand = extract_terms_from_record(record)
        assert generic == {"metformin hydrochloride"}
        assert brand == {"glucophage"}

    def test_reads_active_ingredient_names(self):
        record = {"active_ingredients": [{"name": "SPIRONOLACTONE"}]}
        generic, brand = extract_terms_from_record(record)
        assert generic == {"spironolactone"}
        assert brand == set()

    def test_survives_missing_fields(self):
        generic, brand = extract_terms_from_record({"generic_name": "Warfarin"})
        assert generic == {"warfarin"}
        assert brand == set()

    def test_survives_null_fields(self):
        record = {"generic_name": "Warfarin", "brand_name": None}
        generic, brand = extract_terms_from_record(record)
        assert generic == {"warfarin"}
        assert brand == set()

    def test_survives_malformed_active_ingredients(self):
        # openFDA is external data. A record can carry a list of anything.
        record = {"generic_name": "Warfarin", "active_ingredients": ["not a dict"]}
        generic, brand = extract_terms_from_record(record)
        assert generic == {"warfarin"}

    def test_returns_empty_for_an_empty_record(self):
        assert extract_terms_from_record({}) == (set(), set())

    def test_splits_combination_products(self):
        # Each active in a combination is a drug a transcript can independently
        # get wrong, so each needs to be in the lexicon on its own.
        record = {"generic_name": "Amlodipine and Valsartan"}
        generic, _ = extract_terms_from_record(record)
        assert generic == {"amlodipine", "valsartan"}

    def test_splits_on_semicolons(self):
        record = {"generic_name": "Lisinopril; Hydrochlorothiazide"}
        generic, _ = extract_terms_from_record(record)
        assert generic == {"lisinopril", "hydrochlorothiazide"}


class TestCleanTerms:
    def test_drops_terms_shorter_than_four_characters(self):
        # SPEC M2: length 4 or more.
        assert clean_terms({"asa", "iron", "amoxicillin"}, set()) == {
            "iron",
            "amoxicillin",
        }

    def test_drops_english_word_collisions(self):
        # "sodium" alone is named in SPEC M2 as the example collision.
        assert "sodium" not in clean_terms({"sodium", "metformin"}, set())

    def test_keeps_a_real_drug_that_contains_a_blocked_word(self):
        # Blocking "sodium" must not block "warfarin sodium", which is the drug.
        assert "warfarin sodium" in clean_terms({"warfarin sodium"}, set())

    def test_drops_pure_numbers_and_codes(self):
        assert clean_terms({"12345", "metformin"}, set()) == {"metformin"}

    def test_lowercases_and_deduplicates(self):
        assert clean_terms({"metformin", "Metformin", "METFORMIN "}, set()) == {
            "metformin"
        }


class TestBrandNameDictionaryFilter:
    def test_drops_a_brand_name_that_is_an_ordinary_english_word(self):
        # "Pain" and "Clear" are real NDC brand names on OTC products. A
        # transcript saying "the pain is worse" is not naming a drug.
        cleaned = clean_terms(
            {"pain", "clear"}, brand_only={"pain", "clear"}, english_words=ENGLISH
        )
        assert cleaned == set()

    def test_keeps_a_brand_name_that_is_not_an_english_word(self):
        cleaned = clean_terms(
            {"glucophage"}, brand_only={"glucophage"}, english_words=ENGLISH
        )
        assert cleaned == {"glucophage"}

    def test_keeps_a_dictionary_word_that_arrived_as_a_generic_name(self):
        # This is the case the asymmetry exists for. morphine and insulin are
        # dictionary words and are unambiguously drugs.
        cleaned = clean_terms(
            {"morphine", "insulin"}, brand_only=set(), english_words=ENGLISH
        )
        assert cleaned == {"morphine", "insulin"}

    def test_a_term_that_is_both_generic_and_brand_is_kept(self):
        # "Morphine Sulfate" ships with brand_name == generic_name. Being a
        # brand name too must not disqualify it.
        cleaned = clean_terms({"morphine"}, brand_only=set(), english_words=ENGLISH)
        assert cleaned == {"morphine"}

    def test_multiword_brand_names_are_not_dictionary_filtered(self):
        # The dictionary holds single words. "muscle rub" is not in it, and a
        # two-word brand is specific enough not to fire on ordinary speech.
        cleaned = clean_terms(
            {"muscle rub"}, brand_only={"muscle rub"}, english_words=ENGLISH
        )
        assert cleaned == {"muscle rub"}


class TestComponentTerms:
    """Half the lexicon is multi-word, and the matcher only ever sees tokens.

    `entities.find_drug_mentions` tokenizes on `[\\w/.]+` and asks whether each
    token is in the lexicon, so a multi-word entry can never match anything. A
    reference reading "14 glargine sig 22 units" scored zero drug mentions while
    "insulin glargine" sat in the lexicon. Components are how those entries
    start counting.

    A component is weaker evidence than a whole generic name, so it is filtered
    harder: the dictionary check that applies to brand-only terms applies to
    every component, unconditionally.
    """

    def test_emits_components_of_a_multiword_generic(self):
        assert component_terms({"insulin glargine"}, english_words=set()) == {
            "insulin",
            "glargine",
        }

    def test_ignores_generics_that_are_already_one_word(self):
        assert component_terms({"metformin"}, english_words=set()) == set()

    def test_drops_components_that_are_ordinary_english_words(self):
        # These are the components that made this dangerous: "extended",
        # "release", "normal" and "treatment" all ride along on real generic
        # names and all appear in ordinary clinical speech.
        english = {"extended", "release", "normal", "treatment", "saline"}
        assert component_terms(
            {"metoprolol succinate extended release", "normal saline treatment"},
            english_words=english,
        ) == {"metoprolol"}

    def test_drops_components_on_the_collision_blocklist(self):
        # No dictionary at all, so only the blocklist can stop "sodium" and
        # "injection". This is the case where /usr/share/dict/words is missing.
        assert component_terms({"warfarin sodium injection"}, english_words=set()) == {
            "warfarin"
        }

    def test_drops_components_shorter_than_four_characters(self):
        assert component_terms({"polymyxin b sulfate"}, english_words=set()) == {
            "polymyxin"
        }

    def test_drops_components_carrying_digits_or_punctuation(self):
        # "technetium tc99m sestamibi" and "sodium chloride 0.9%" are real NDC
        # generic names. A strength, a pack size or an isotope code is not a
        # drug a transcript can name.
        emitted = component_terms(
            {"technetium tc99m sestamibi", "sodium chloride 0.9%", "insulin 5000 unit"},
            english_words=set(),
        )
        assert emitted == {"technetium", "sestamibi", "insulin"}

    def test_drops_hyphenated_components(self):
        # The matcher's token regex has no hyphen in it, so "extended-release"
        # could never match a transcript token. Keeping it would be a lexicon
        # entry that only ever inflates the size count.
        assert component_terms(
            {"diltiazem hydrochloride extended-release"}, english_words=set()
        ) == {"diltiazem"}

    def test_recovers_a_real_drug_buried_in_a_multiword_generic(self):
        # The whole reason for this function.
        assert "glargine" in component_terms(
            {"insulin glargine and lixisenatide"}, english_words={"insulin"}
        )


class TestInnList:
    """openFDA carries USAN, not INN, and AfriSpeech-200 is African clinical speech.

    Paracetamol is filed as acetaminophen and rifampicin as rifampin, so an
    entire vocabulary of what is actually prescribed across Africa, the
    antimalarials above all, was missing from a benchmark about clinical safety.
    """

    def test_carries_the_confirmed_missing_names(self):
        inn = load_inn_terms()
        for name in (
            "paracetamol",
            "chloroquine",
            "quinine",
            "rifampicin",
            "cotrimoxazole",
            "proguanil",
            "chlorproguanil",
            "amodiaquine",
            "sulfadoxine",
            "primaquine",
            "ethambutol",
            "dihydroartemisinin",
            "piperaquine",
        ):
            assert name in inn, f"{name} missing from the INN list"

    def test_every_entry_is_matchable_by_the_tokenizer(self):
        # `entities.find_drug_mentions` tokenizes on [\\w/.]+ and compares whole
        # tokens, so a hyphen in an entry makes it unmatchable forever.
        # "co-trimoxazole" has to be written "cotrimoxazole" to ever fire.
        for term in load_inn_terms():
            assert re.fullmatch(r"[a-z]{4,}", term), f"{term} can never match a token"

    def test_survives_the_dictionary_filter(self):
        # INN names are generic provenance: a drug by construction. "insulin"
        # and "quinine" are dictionary words and must not be filtered out.
        # An explicit dictionary, not the system one, so the assertion still
        # means something on a host where /usr/share/dict/words is missing.
        english = lexicon.load_english_words() | {"insulin", "quinine", "morphine"}
        kept = clean_terms(load_inn_terms(), brand_only=set(), english_words=english)
        assert kept == load_inn_terms()


class TestBuildMergesEverySource:
    def test_build_merges_openfda_components_and_the_inn_list(
        self, tmp_path, monkeypatch
    ):
        # No network. The point is that a build wires all three sources
        # together: openFDA generics, their components, and the INN file.
        monkeypatch.setattr(lexicon, "LEXICON", tmp_path / "drug_lexicon.txt")
        monkeypatch.setattr(
            lexicon,
            "fetch_openfda_terms",
            lambda *args, **kwargs: ({"insulin glargine"}, set()),
        )
        terms = lexicon.build(force=True)
        assert "insulin glargine" in terms  # the openFDA generic, untouched
        assert "glargine" in terms  # emitted component
        assert "insulin" in terms  # dictionary word, rescued by the INN list
        assert "paracetamol" in terms  # INN only, absent from openFDA
        assert "chloroquine" in terms
