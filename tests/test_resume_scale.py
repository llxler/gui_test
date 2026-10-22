import sqlite3

import pytest

from gui_dna.budget import Ledger, BudgetStop
from experiments.resume_scale import clear_manual_pause


def test_manual_resume_keeps_spent_and_unknown_costs_and_original_caps(tmp_path):
    path=tmp_path/'budget.sqlite3';ledger=Ledger(path,9,8.8)
    paid=ledger.reserve(.1,'paid','model');ledger.settle(paid,.03)
    unknown=ledger.reserve(.2,'unknown','model');ledger.uncertain(unknown,'HTTP 429')
    with sqlite3.connect(path) as db:db.execute('UPDATE policy SET halted=1')
    clear_manual_pause(path,{'not_a_budget_breach':True,'prior_policy':{'halted':0}})
    result=ledger.summary()
    assert result['exposure_usd']==.23 and result['actual_usd']==.03 and result['unsettled_calls']==1
    assert result['policy']['cap']==9_000_000 and result['policy']['stop']==8_800_000 and result['policy']['halted']==0


def test_resume_cannot_clear_charge_breach_or_pending_request(tmp_path):
    path=tmp_path/'budget.sqlite3';ledger=Ledger(path,9,8.8)
    pending=ledger.reserve(.01,'pending','model')
    with sqlite3.connect(path) as db:db.execute('UPDATE policy SET halted=1')
    pause={'not_a_budget_breach':True,'prior_policy':{'halted':0}}
    with pytest.raises(RuntimeError,match='leave ledger halted'):clear_manual_pause(path,pause)
    with pytest.raises(BudgetStop):ledger.settle(pending,.02)
    with pytest.raises(RuntimeError,match='leave ledger halted'):clear_manual_pause(path,pause)
    assert ledger.summary()['policy']['halted']==1
