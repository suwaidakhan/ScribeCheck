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

from src.lexicon import clean_terms, extract_terms_from_record

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
