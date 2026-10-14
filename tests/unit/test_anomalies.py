from datetime import date, timedelta

from bsi.anomalies.detectors import (
    Thresholds,
    detect_all,
    detect_amount_outliers,
    detect_bounce,
    detect_cash_spike,
    detect_duplicates,
    detect_low_balance,
    detect_new_payee_large,
    detect_pass_through,
    detect_round_large,
)
from bsi.classify.recurring import apply_recurring, detect_recurring
from bsi.classify.rules import apply_rules
from bsi.schema import AnomalyCode, Category
from tests.conftest_helpers import make, make_many

TH = Thresholds()
D = date


def classified(rows):
    tx = make_many(rows)
    apply_rules(tx)
    apply_recurring(tx, detect_recurring(tx))
    return tx


def codes(flags):
    return [f.code for f in flags]


def test_amount_outlier_vs_category_median():
    food = [(f"UPI/40000000000{i}/SWIGGY/swiggy@icici/Order", a, "debit", D(2024, 3, i + 1))
            for i, a in enumerate(["300", "350", "400", "320", "380", "7000"])]
    tx = classified(food)
    flags = detect_amount_outliers(tx, TH)
    assert len(flags) == 1 and flags[0].txn_idx == [5] and flags[0].code is AnomalyCode.AMOUNT_OUTLIER
    assert "usual Food" in flags[0].reason


def test_amount_outlier_needs_enough_samples():
    tx = classified([("UPI/400000000001/SWIGGY/swiggy@icici/Order", "300", "debit", D(2024, 3, 1)),
                     ("UPI/400000000002/SWIGGY/swiggy@icici/Order", "9000", "debit", D(2024, 3, 2))])
    assert detect_amount_outliers(tx, TH) == []


def test_large_payment_to_new_payee():
    tx = classified([
        ("UPI/400000000001/SWIGGY/swiggy@icici/Order", "300", "debit", D(2024, 3, 1)),
        ("NEFT-X1-SUNRISE VENTURES-TRANSFER", "100000", "debit", D(2024, 3, 14))])
    f = detect_new_payee_large(tx, TH)
    assert len(f) == 1 and f[0].txn_idx == [1] and "SUNRISE VENTURES" in f[0].reason


def test_large_payment_to_known_payee_is_not_new_payee():
    tx = classified([
        ("NEFT-X1-SUNRISE VENTURES-TRANSFER", "1000", "debit", D(2024, 3, 1)),
        ("NEFT-X2-SUNRISE VENTURES-TRANSFER", "50000", "debit", D(2024, 3, 14))])
    assert detect_new_payee_large(tx, TH) == []


def test_round_number_large_transfer():
    tx = classified([("NEFT-X1-SUNRISE VENTURES-TRANSFER", "100000", "debit", D(2024, 3, 14)),
                     ("NEFT-X2-OTHER CO-TRANSFER", "74500", "debit", D(2024, 3, 15)),
                     ("NEFT-X3-SMALL CO-TRANSFER", "5000", "debit", D(2024, 3, 16))])
    assert [f.txn_idx for f in detect_round_large(tx, TH)] == [[0]]


def test_duplicate_charge():
    tx = classified([("UPI/400000000001/MYNTRA/myntra@ybl/Purchase", "3299", "debit", D(2024, 3, 9)),
                     ("UPI/400000000002/MYNTRA/myntra@ybl/Purchase", "3299", "debit", D(2024, 3, 10))])
    f = detect_duplicates(tx, TH)
    assert len(f) == 1 and f[0].txn_idx == [0, 1]


def test_same_amount_far_apart_is_not_duplicate():
    tx = classified([("UPI/400000000001/MYNTRA/myntra@ybl/Purchase", "3299", "debit", D(2024, 3, 1)),
                     ("UPI/400000000002/MYNTRA/myntra@ybl/Purchase", "3299", "debit", D(2024, 3, 20))])
    assert detect_duplicates(tx, TH) == []


def test_repeated_atm_withdrawals_are_not_duplicates():
    tx = classified([("ATM-CASH WDL/BENGALURU ATM 1/111111", "10000", "debit", D(2024, 3, 1)),
                     ("ATM-CASH WDL/BENGALURU ATM 1/222222", "10000", "debit", D(2024, 3, 1))])
    assert detect_duplicates(tx, TH) == []


def test_pass_through():
    tx = classified([("IMPS/400000000001/NEHA SHARMA/FUND TRANSFER", "75000", "credit", D(2024, 3, 20)),
                     ("IMPS/400000000002/ROHAN VERMA/FUND TRANSFER", "74500", "debit", D(2024, 3, 22))])
    f = detect_pass_through(tx, TH)
    assert len(f) == 1 and f[0].txn_idx == [0, 1]


def test_pass_through_ignores_unrelated_debit():
    tx = classified([("IMPS/400000000001/NEHA SHARMA/FUND TRANSFER", "75000", "credit", D(2024, 3, 20)),
                     ("IMPS/400000000002/ROHAN VERMA/FUND TRANSFER", "20000", "debit", D(2024, 3, 22))])
    assert detect_pass_through(tx, TH) == []


def test_low_and_negative_balance_once_per_dip():
    tx = [make("UPI/1/X/x@ybl/a", "100", "debit", D(2024, 3, 1), 0, "5000"),
          make("UPI/2/X/x@ybl/a", "4200", "debit", D(2024, 3, 2), 1, "800"),
          make("UPI/3/X/x@ybl/a", "100", "debit", D(2024, 3, 3), 2, "700"),
          make("UPI/4/X/x@ybl/a", "2000", "debit", D(2024, 3, 4), 3, "-1300")]
    f = detect_low_balance(tx, TH)
    assert [x.txn_idx for x in f] == [[1]]
    assert detect_low_balance(tx[:1], TH) == []


def test_bounce_charge():
    tx = classified([("CHQ RTN CHG-INSUFFICIENT FUNDS-214279", "590", "debit", D(2024, 3, 16)),
                     ("UPI/400000000001/SWIGGY/swiggy@icici/Order", "300", "debit", D(2024, 3, 17))])
    assert [f.txn_idx for f in detect_bounce(tx, TH)] == [[0]]


def test_cash_spike_vs_normal_withdrawals():
    spike = classified([(f"ATM-CASH WDL/BENGALURU ATM 1/11111{i}", "10000", "debit", D(2024, 3, 21) + timedelta(i))
                        for i in range(4)])
    normal = classified([("ATM-CASH WDL/BENGALURU ATM 1/111111", "5000", "debit", D(2024, 3, 4)),
                         ("ATM-CASH WDL/BENGALURU ATM 1/222222", "3000", "debit", D(2024, 3, 20))])
    assert len(detect_cash_spike(spike, TH)) == 1
    assert detect_cash_spike(normal, TH) == []


def test_large_salary_credit_is_not_flagged():
    tx = classified([("NEFT-X1-TECHNOVA SOLUTIONS PVT LTD-SALARY JAN24", "250000", "credit", D(2024, 1, 1)),
                     ("UPI/400000000001/SWIGGY/swiggy@icici/Order", "300", "debit", D(2024, 1, 2)),
                     ("NEFT-X2-FRIEND-REPAY", "249000", "debit", D(2024, 1, 2))])
    assert tx[0].category is Category.SALARY
    flags = detect_all(tx)
    assert all(0 not in f.txn_idx for f in flags if f.code is not AnomalyCode.PASS_THROUGH)
    assert AnomalyCode.PASS_THROUGH not in codes(flags)  # salary credit is exempt from pass-through too


def test_recurring_rent_and_salary_not_flagged_in_full_run():
    rows = []
    for m in (1, 2, 3):
        rows.append(("NEFT-X1-ZENITH ANALYTICS LLP-PAY", "150000", "credit", D(2024, m, 1)))
        rows.append(("UPI/400000000001/SURESH PATEL/suresh@ybl/Payment from phone", "50000", "debit", D(2024, m, 5)))
    flags = detect_all(classified(rows))
    assert flags == []


def test_detect_all_sorted_and_empty_input():
    assert detect_all([]) == []
