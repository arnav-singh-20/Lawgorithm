"""The number-preservation guard on translations (a wrong amount is the worst possible error)."""

from backend.translation import translator
from backend.translation.translator import numbers_preserved


def test_seen_live_lakh_error_is_caught():
    """qwen2.5:3b turned Rs 2,50,000 into 25,00,000 in Hindi."""
    original = "a security deposit of Rs 2,50,000 (which is 10 months' rent)"
    assert not numbers_preserved(original, "25,00,000 रुपये रेसिडेंस डिपोज़िट (10 महीने)")
    assert numbers_preserved(original, "2,50,000 रुपये की सुरक्षा जमा (10 महीने का किराया)")


def test_indic_digits_count_as_the_same_number():
    assert numbers_preserved("pay Rs 25,000 by the 5th", "५ तारीख तक २५,००० रुपये दें")
    assert numbers_preserved("90 days", "৯০ দিন")


def test_comma_styles_are_equivalent():
    assert numbers_preserved("Rs 250000", "Rs 2,50,000")


def test_single_digits_may_be_spelled_out():
    assert numbers_preserved("for 2 years", "दो साल तक")


def test_missing_number_fails():
    assert not numbers_preserved("notice of 30 days", "कुछ दिनों का नोटिस")


def test_validation_fails_when_a_number_changes(monkeypatch):
    class Fake:
        def simple_completion(self, system_prompt, user_input):
            if "into English" in system_prompt:
                return "You must pay a deposit of Rs 50,000."
            return "आपको 5,00,000 रुपये जमा करने होंगे।"

    monkeypatch.setattr(translator, "_get_provider", lambda: Fake())
    monkeypatch.setattr(translator, "_cosine_similarity", lambda a, b: 0.99)
    result = translator.translate_and_validate("You must pay a deposit of Rs 50,000.", "hindi")
    assert result["numbers_preserved"] is False and result["validated"] is False


# --- party roles ---------------------------------------------------------

from backend.translation.translator import roles_preserved


def test_seen_live_landlord_tenant_swap_is_caught():
    """NLLB back-translations measured live for Hindi/Tamil/Bengali/Telugu/Kannada."""
    original = "You must give the landlord a refundable security deposit of Rs 2,50,000."
    assert not roles_preserved(original, "You have to pay the tenant a repayable deposit of Rs 2,50,000.")
    assert roles_preserved(original, "You have to give the landlord a repayable security of Rs.250,000.")


def test_dropped_party_is_caught():
    original = "The landlord cannot enter the flat without giving the tenant 24 hours notice."
    assert not roles_preserved(original, "cannot enter the house without notifying the tenant within 24 hours.")
    assert not roles_preserved(original, "The tenant cannot enter the apartment without notifying the tenant.")


def test_no_parties_no_constraint():
    assert roles_preserved("You can't work for a competing business for 2 years.", "You cannot work for a rival for two years.")


def test_synonyms_count_as_the_same_party():
    assert roles_preserved("The lessee must pay rent.", "The tenant has to pay the rent.")


def test_glossary_substitutes_party_words():
    from backend.translation.glossary import apply_glossary
    out = apply_glossary("Give the Landlord the deposit; the lessee pays rent.", "hindi")
    assert out == "Give मकान मालिक the deposit; किरायेदार pays rent."
    assert apply_glossary("Give the landlord the deposit.", "english") == "Give the landlord the deposit."


def test_indian_number_words_are_understood():
    """Measured live: NLLB writes amounts the way Indians say them."""
    assert numbers_preserved("You will be paid Rs 75,000 every month.", "আপনাকে প্রতি মাসে ৭৫ হাজার টাকা দেওয়া হবে।")
    assert numbers_preserved("You will be paid Rs 75,000 every month.", "तुम्हाला दरमहा ७५ हजार रुपये दिले जातील.")
    assert numbers_preserved("pay Rs 5,00,000", "৫ লাখ টাকা দিতে হবে")
    assert numbers_preserved("pay Rs 2,50,000", "2.5 लाख रुपये")
    assert not numbers_preserved("pay Rs 2,50,000", "25 लाख रुपये")      # the real error stays caught


# --- engine chain: IndicTrans2 first, NLLB rescues what fails a check -----

def test_second_engine_rescues_a_failed_translation(monkeypatch):
    monkeypatch.setattr(translator, "_engine_chain", lambda: ["indictrans2", "nllb"])
    outputs = {"indictrans2": "आपको किरायेदार को 5,000 देने होंगे।",   # wrong amount
               "nllb": "आपको मकान मालिक को 50,000 रुपये देने होंगे।"}
    monkeypatch.setattr(translator, "_forward_with", lambda engine, text, lang: outputs[engine])
    monkeypatch.setattr(translator, "_backward", lambda text, lang: "You must pay the landlord Rs 50,000.")
    monkeypatch.setattr(translator, "_cosine_similarity", lambda a, b: 0.95)

    result = translator.translate_and_validate("You must pay the landlord Rs 50,000.", "hindi")

    assert result["validated"] is True
    assert result["engine"] == "nllb"
    assert result["attempts"] == 2


def test_broken_engine_is_skipped(monkeypatch):
    monkeypatch.setattr(translator, "_engine_chain", lambda: ["indictrans2", "nllb"])

    def forward(engine, text, lang):
        if engine == "indictrans2":
            raise RuntimeError("worker crashed")
        return "आपको 50,000 रुपये देने होंगे।"

    monkeypatch.setattr(translator, "_forward_with", forward)
    monkeypatch.setattr(translator, "_backward", lambda text, lang: "You must pay Rs 50,000.")
    monkeypatch.setattr(translator, "_cosine_similarity", lambda a, b: 0.95)

    result = translator.translate_and_validate("You must pay Rs 50,000.", "hindi")
    assert result["validated"] is True and result["engine"] == "nllb"
