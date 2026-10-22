import json
from types import SimpleNamespace
import pytest
import httpx

from gui_dna.budget import Ledger
from gui_dna.provider import OpenRouter, ProviderError, parse_json
from gui_dna.tasks import ROOT


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret-never-log")
    provider = object.__new__(OpenRouter)
    provider.config = json.loads((ROOT / "configs/experiment.json").read_text())
    provider.ledger = Ledger(tmp_path / "ledger.sqlite3")
    provider.models = {"test-model": {"supported_parameters": []}}
    return provider


def test_accounting_and_no_key_in_artifacts(tmp_path, monkeypatch):
    provider = client(tmp_path, monkeypatch)
    requests = []
    def post(*args, **kwargs):
        requests.append(kwargs)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "id": "test-generation", "usage": {"cost": 0.0001, "prompt_tokens": 5, "completion_tokens": 10},
            "choices": [{"message": {"content": '{"code":"ok"}'}}]})
    monkeypatch.setattr("gui_dna.provider.httpx.post", post)
    raw = provider.call("test-model", [{"role": "user", "content": "test"}], tmp_path / "call", "generate")
    assert json.loads(raw)["code"] == "ok"
    assert len(requests) == 1
    assert requests[0]["json"]["provider"]["allow_fallbacks"] is False
    assert provider.ledger.summary()["actual_usd"] == 0.0001
    assert all("test-secret-never-log" not in p.read_text() for p in (tmp_path / "call").glob("*.json"))


@pytest.mark.parametrize("missing_cost", [False, True])
def test_unknown_charge_is_reserved_without_retry(tmp_path, monkeypatch, missing_cost):
    provider = client(tmp_path, monkeypatch)
    requests = []
    def post(*args, **kwargs):
        requests.append(kwargs)
        if not missing_cost:
            raise TimeoutError("timeout after transmission")
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"usage": {}})
    monkeypatch.setattr("gui_dna.provider.httpx.post", post)
    with pytest.raises(ProviderError):
        provider.call("test-model", [{"role": "user", "content": "test"}], tmp_path / "call", "generate")
    assert len(requests) == 1
    summary = provider.ledger.summary()
    assert summary["actual_usd"] == 0
    assert summary["exposure_usd"] > 0
    assert summary["unsettled_calls"] == 1


def test_null_content_is_charged_and_parsing_fails_cleanly(tmp_path, monkeypatch):
    provider = client(tmp_path, monkeypatch)
    monkeypatch.setattr("gui_dna.provider.httpx.post", lambda *a, **k: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"id": "null-response", "usage": {"cost": 0.001},
                                                    "choices": [{"message": {"content": None}}]}))
    raw = provider.call("test-model", [{"role": "user", "content": "test"}], tmp_path / "call", "library")
    assert raw == ""
    assert provider.ledger.summary()["actual_usd"] == 0.001
    with pytest.raises(ValueError, match="no text"):
        parse_json(raw)


def test_per_model_cap_is_used_for_routing_and_reservation(tmp_path, monkeypatch):
    provider = client(tmp_path, monkeypatch)
    provider.config['model_price_caps'] = {'test-model': {'prompt': 3, 'completion': 15}}
    sent = []
    monkeypatch.setattr('gui_dna.provider.httpx.post', lambda *a, **k: sent.append(k) or SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {'id': 'receipt', 'usage': {'cost': .001},
                                                   'choices': [{'message': {'content': '{}'}}]}))
    provider.call('test-model', [{'role': 'user', 'content': 'abcd'}], tmp_path/'call', 'v2')
    request = json.loads((tmp_path/'call/request.json').read_text())
    assert sent[0]['json']['provider']['max_price'] == {'prompt': 3, 'completion': 15, 'request': 0}
    assert request['reserved_usd'] == ((4+256+1024)*3+6000*15)/1_000_000


def test_routing_rejection_is_diagnosable_without_exposing_key(tmp_path, monkeypatch):
    provider = client(tmp_path, monkeypatch)
    monkeypatch.setattr('gui_dna.provider.httpx.post', lambda url, **k: httpx.Response(
        403, json={'error': {'message': 'region unavailable test-secret-never-log'}}, request=httpx.Request('POST', url)))
    with pytest.raises(ProviderError):
        provider.call('test-model', [{'role': 'user', 'content': 'check'}], tmp_path/'call', 'probe')
    receipt = (tmp_path/'call/error.json').read_text()
    assert 'region unavailable' in receipt and 'test-secret-never-log' not in receipt


def test_rate_limit_retry_has_new_reservation_and_can_resume_without_recharge(tmp_path, monkeypatch):
    provider = client(tmp_path, monkeypatch)
    sent, delays = [], []
    monkeypatch.setattr("gui_dna.provider.time.sleep", delays.append)
    def post(*args, **kwargs):
        sent.append(kwargs)
        if len(sent) == 1:
            return httpx.Response(429, headers={"retry-after": "45"}, request=httpx.Request("POST", args[0]))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "id": "after-rate-limit", "usage": {"cost": 0.001}, "choices": [{"message": {"content": "{}"}}]})
    monkeypatch.setattr("gui_dna.provider.httpx.post", post)
    messages = [{"role": "user", "content": "test"}]
    assert provider.call("test-model", messages, tmp_path / "call", "generate") == "{}"
    summary = provider.ledger.summary()
    assert len(summary["calls"]) == 2 and summary["unsettled_calls"] == 1
    assert summary["exposure_usd"] > summary["actual_usd"] == 0.001
    assert delays == [45]
    assert provider.call("test-model", messages, tmp_path / "call", "generate") == "{}"
    assert len(sent) == 2
