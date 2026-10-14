"""Ambiguous rows resolved by a MOCKED LLM with fixed responses (no network, no key)."""
import json
from datetime import date

import pytest

from bsi.classify.cache import LLMCache
from bsi.classify.llm_classifier import LLMClassifier, sanitize_narration
from bsi.classify.rules import apply_rules, is_unresolved
from bsi.llm.client import LLMError, MockClient, complete_json
from bsi.schema import Category, CategorySource
from tests.conftest_helpers import make_many


def reply(*results):
    return json.dumps({"results": [dict(zip(("id", "category", "confidence", "rationale"), r, strict=False))
                                   for r in results]})


def txns(rows):
    tx = make_many(rows)
    apply_rules(tx)
    return tx


AMBIG = [
    ("UPI/088982673821/SURESH PATEL/suresh@ybl/Payment from phone", "18000", "debit", date(2024, 3, 5)),
    ("UPI/694741323086/AMAZON/amazon@apl/Purchase", "2310", "debit", date(2024, 3, 13)),
    ("POS 4821 AMAZON WEB SERVICES AWS EMEA", "1845.20", "debit", date(2024, 3, 11)),
    ("NEFT-X1-XYZ ENTERPRISES-INV 2231", "8400", "debit", date(2024, 3, 10)),
]


def test_fixed_llm_answers_are_applied_with_source_and_confidence():
    tx = txns(AMBIG)
    assert all(is_unresolved(t) for t in tx)
    client = MockClient(responses=[reply((0, "Rent", 0.82, "monthly-looking payment to a person"),
                                         (1, "Shopping", 0.7, "Amazon retail"),
                                         (2, "Other", 0.75, "AWS is cloud infra"),
                                         (3, "Other", 0.3, "unclear"))])
    stats = LLMClassifier(client, "classify_v4").classify(tx)
    assert [t.category for t in tx] == [Category.RENT, Category.SHOPPING, Category.OTHER, Category.OTHER]
    assert all(t.category_source is CategorySource.LLM for t in tx)
    assert tx[0].category_confidence == 0.82 and "person" in tx[0].category_rationale
    assert stats.llm_calls == 1 and stats.rows_sent == 4


def test_batches_of_20():
    rows = [(f"UPI/4000000000{i:02d}/PERSON{chr(65 + i)} X/p{i}@ybl/x", "100", "debit", date(2024, 3, 1))
            for i in range(25)]
    tx = txns(rows)

    def handler(system, user, task):
        items = json.loads(user.split("```json")[1].split("```")[0])
        return reply(*[(it["id"], "Transfers", 0.6, "") for it in items])

    client = MockClient(handler=handler)
    stats = LLMClassifier(client, "classify_v4").classify(tx)
    assert stats.llm_calls == 2 and [len(c[1]) > 0 for c in client.calls]
    assert all(t.category is Category.TRANSFERS for t in tx)


def test_cache_by_normalized_counterparty():
    tx = txns([("UPI/400000000001/ANITA RAO/anita@ybl/x", "1500", "debit", date(2024, 3, 1)),
               ("UPI/400000000002/ANITA RAO/anita@ybl/y", "1600", "debit", date(2024, 3, 9))])
    client = MockClient(responses=[reply((0, "Transfers", 0.7, "person"))])
    cache = LLMCache()
    stats = LLMClassifier(client, "classify_v4", cache).classify(tx)
    assert stats.llm_calls == 1 and stats.cache_hits == 1
    assert tx[1].category is Category.TRANSFERS and "cached" in tx[1].category_rationale
    # second run reuses the cache entirely
    tx2 = txns([("UPI/400000000003/ANITA RAO/anita@ybl/z", "1700", "debit", date(2024, 4, 1))])
    stats2 = LLMClassifier(client, "classify_v4", cache).classify(tx2)
    assert stats2.llm_calls == 0 and tx2[0].category is Category.TRANSFERS


def test_cache_separates_big_and_small_amounts_for_same_person():
    tx = txns([("UPI/400000000001/SURESH PATEL/s@ybl/x", "500", "debit", date(2024, 3, 1)),
               ("UPI/400000000002/SURESH PATEL/s@ybl/y", "18000", "debit", date(2024, 3, 5))])
    client = MockClient(responses=[reply((0, "Transfers", 0.7, ""), (1, "Rent", 0.8, ""))])
    LLMClassifier(client, "classify_v4").classify(tx)
    assert [t.category for t in tx] == [Category.TRANSFERS, Category.RENT]


def test_rule_resolved_rows_are_never_sent():
    tx = txns([("UPI/400000000001/SWIGGY/swiggy@icici/Order", "300", "debit", date(2024, 3, 1)),
               ("NEFT-X1-XYZ ENTERPRISES-INV", "8400", "debit", date(2024, 3, 2))])
    client = MockClient(responses=[reply((1, "Other", 0.5, ""))])
    LLMClassifier(client, "classify_v4").classify(tx)
    sent = client.calls[0][1]
    assert "SWIGGY" not in sent and "XYZ ENTERPRISES" in sent
    assert tx[0].category_source is CategorySource.RULE and tx[0].category is Category.FOOD


def test_low_confidence_becomes_other():
    tx = txns([("NEFT-X1-XYZ ENTERPRISES-INV", "8400", "debit", date(2024, 3, 2))])
    LLMClassifier(MockClient(responses=[reply((0, "Shopping", 0.2, "guess"))]), "classify_v4").classify(tx)
    assert tx[0].category is Category.OTHER and tx[0].category_source is CategorySource.LLM


def test_invalid_category_retries_then_succeeds():
    tx = txns([("NEFT-X1-XYZ ENTERPRISES-INV", "8400", "debit", date(2024, 3, 2))])
    client = MockClient(responses=[reply((0, "Groceries", 0.9, "")), reply((0, "Other", 0.6, "ok"))])
    stats = LLMClassifier(client, "classify_v4").classify(tx)
    assert stats.llm_calls == 2 and tx[0].category is Category.OTHER and tx[0].category_confidence == 0.6


def test_persistent_garbage_falls_back_to_other_without_crashing():
    tx = txns([("NEFT-X1-XYZ ENTERPRISES-INV", "8400", "debit", date(2024, 3, 2))])
    stats = LLMClassifier(MockClient(responses=["not json at all"]), "classify_v4").classify(tx)
    assert stats.failures == 1 and tx[0].category is Category.OTHER and tx[0].category_confidence == 0.0


def test_markdown_fenced_json_is_accepted():
    tx = txns([("NEFT-X1-XYZ ENTERPRISES-INV", "8400", "debit", date(2024, 3, 2))])
    fenced = "Sure!\n```json\n" + reply((0, "Other", 0.5, "")) + "\n```"
    LLMClassifier(MockClient(responses=[fenced]), "classify_v4").classify(tx)
    assert tx[0].category_confidence == 0.5


def test_pii_is_not_sent():
    tx = txns([("UPI/400000000001/AARAV MEHTA/aarav@ybl/self 50100234567890", "9000", "debit", date(2024, 3, 2))])
    client = MockClient(responses=[reply((0, "Transfers", 0.7, ""))])
    LLMClassifier(client, "classify_v4").classify(tx, holder="AARAV MEHTA")
    system, user, _ = client.calls[0]
    blob = system + user
    assert "AARAV" not in blob.upper().replace("ACCOUNT_HOLDER", "") and "MEHTA" not in blob.upper()
    assert "50100234567890" not in blob and "400000000001" not in blob


def test_sanitize_narration():
    s = sanitize_narration("UPI/123456789012/AARAV MEHTA/x", holder="Aarav Mehta")
    assert "AARAV" not in s.upper().replace("ACCOUNT_HOLDER", "") and "123456789012" not in s


def test_v1_free_text_is_parsed_leniently():
    tx = txns([("NEFT-X1-XYZ ENTERPRISES-INV", "8400", "debit", date(2024, 3, 2))])
    client = MockClient(responses=["I think this is most likely Shopping, maybe Other."])
    LLMClassifier(client, "classify_v1").classify(tx)
    assert tx[0].category is Category.SHOPPING and "Categorize this bank transaction" in client.calls[0][1]


def test_default_mock_client_works_offline_for_every_prompt_version():
    for v in ("classify_v1", "classify_v2", "classify_v3", "classify_v4"):
        tx = txns(AMBIG)
        stats = LLMClassifier(MockClient(), v).classify(tx)
        assert stats.failures == 0 and all(t.category_source is CategorySource.LLM for t in tx), v


def test_complete_json_raises_after_retries():
    from pydantic import BaseModel

    class M(BaseModel):
        x: int

    with pytest.raises(LLMError):
        complete_json(MockClient(responses=["nope"]), "s", "u", M)
