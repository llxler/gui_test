from concurrent.futures import ThreadPoolExecutor
import pytest
from gui_dna.budget import Ledger, BudgetStop


def test_persistent_reservations_settlement_and_stop(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = Ledger(path)
    first = ledger.reserve(8, "library", "model")
    ledger.uncertain(first, "timeout after sending")
    resumed = Ledger(path)
    assert resumed.summary()["exposure_usd"] == 8
    with pytest.raises(BudgetStop):
        resumed.reserve(1.01, "generate", "model")
    resumed.settle(first, 0.5)
    second = resumed.reserve(8.5, "generate", "model")
    with pytest.raises(BudgetStop):
        resumed.reserve(0.000001, "generate", "model")
    resumed.settle(second, 1)
    assert resumed.summary()["actual_usd"] == 1.5


def test_parallel_reservations_cannot_overcommit(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    def reserve(_):
        try:
            return ledger.reserve(3, "generate", "model")
        except BudgetStop:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(reserve, range(12)))
    assert sum(v is not None for v in values) == 3
    assert ledger.summary()["exposure_usd"] == 9


def test_cannot_raise_limits_or_ignore_overcharge(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = Ledger(path, limit=2, stop=1)
    Ledger(path, limit=1000, stop=1000)
    with pytest.raises(BudgetStop):
        ledger.reserve(1.01, "generate", "model")
    reservation = ledger.reserve(0.1, "generate", "model")
    with pytest.raises(BudgetStop):
        ledger.settle(reservation, 0.2)
    assert ledger.summary()["actual_usd"] == 0.2
    with pytest.raises(BudgetStop):
        ledger.reserve(0.1, "generate", "model")


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf")])
def test_invalid_costs_rejected(tmp_path, cost):
    with pytest.raises(ValueError):
        Ledger(tmp_path / "ledger.sqlite3").reserve(cost, "generate", "model")
