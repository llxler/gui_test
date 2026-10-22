"""OpenRouter HTTP client: every POST reserved, including bounded 429 retries."""
import json
import os
import time
from decimal import Decimal
from pathlib import Path
import httpx

from .budget import Ledger
from .tasks import ROOT, dump


class ProviderError(RuntimeError):
    pass


class RateLimited(ProviderError):
    def __init__(self, message, retry_after=30):
        super().__init__(message)
        self.retry_after = retry_after


def parse_json(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Provider returned no text; charged response retained")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


class OpenRouter:
    def __init__(self, config, ledger=None):
        self.config = config
        self.ledger = ledger or Ledger(ROOT / "artifacts/budget.sqlite3", config["budget_usd"], config["stop_new_requests_usd"])
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise ProviderError("OPENROUTER_API_KEY is missing; use --offline for the deterministic demo")
        response = httpx.get("https://openrouter.ai/api/v1/models", timeout=30)
        response.raise_for_status()
        self.models = {m["id"]: m for m in response.json()["data"]}
        for name in config["models"]:
            if name not in self.models:
                raise ProviderError(f"Requested model unavailable: {name}; no substitution performed")

    def call(self, model, messages, out, purpose, max_tokens=None, seed=None):
        """Replay settled responses; retry only 429, with a separate reservation each time."""
        for retry in range(3):
            folder = Path(out) if retry == 0 else Path(out) / f"http-retry-{retry}"
            try:
                request_path = folder / "request.json"
                if request_path.exists():
                    request = json.loads(request_path.read_text())
                    if request["body"]["messages"] != messages or request["body"]["model"] != model:
                        raise ProviderError("Interrupted request context changed; refusing to overwrite it")
                    calls = self.ledger.summary()["calls"]
                    settled = any(c["id"] == request["call_id"] and c["actual"] is not None for c in calls)
                    response_path = folder / "response.json"
                    if settled and response_path.exists():
                        payload = json.loads(response_path.read_text())
                        return payload["choices"][0]["message"]["content"] or ""
                    error_path = folder / "error.json"
                    error = json.loads(error_path.read_text()) if error_path.exists() else {}
                    if "HTTP 429" in error.get("error", ""):
                        raise RateLimited(error["error"], error.get("retry_after", 30))
                    raise ProviderError("Unsettled interrupted request; reservation retained, no automatic retry")
                return self._single(model, messages, folder, purpose, max_tokens, seed)
            except RateLimited as error:
                if retry == 2:
                    raise
                # Each subsequent POST gets a new ledger reservation; old unknown costs remain held.
                time.sleep(max(error.retry_after, 30 * 2**retry))

    def _single(self, model, messages, out, purpose, max_tokens=None, seed=None):
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        config = self.config
        caps = config.get("model_price_caps", {}).get(model, config["price_caps_per_million"])
        max_tokens = max_tokens or config["max_tokens"]
        body = {"model": model, "messages": messages, "temperature": config["temperature"],
                "max_tokens": max_tokens, "stream": False,
                "response_format": {"type": "json_object"},
                "provider": {"allow_fallbacks": False, "require_parameters": True,
                             "max_price": {**caps, "request": 0}}}
        supported = self.models[model]["supported_parameters"]
        if model in config.get("provider_order", {}):
            body["provider"]["order"] = config["provider_order"][model]
        if "seed" in supported and seed is not None:
            body["seed"] = seed
        if "reasoning" in supported:
            body["reasoning"] = {"enabled": False}
        # UTF-8 bytes conservatively bound input tokens, plus message-template overhead.
        input_bound = sum(len(m["content"].encode()) + 256 for m in messages) + 1024
        reserve = (Decimal(input_bound)*Decimal(str(caps["prompt"])) + Decimal(max_tokens)*Decimal(str(caps["completion"]))) / 1_000_000
        call_id = self.ledger.reserve(reserve, purpose, model)
        dump(out / "request.json", {"call_id": call_id, "input_token_upper_bound": input_bound,
                                     "reserved_usd": float(reserve), "body": body,
                                     "model_metadata": self.models[model]})
        started = time.monotonic()
        try:
            response = httpx.post("https://openrouter.ai/api/v1/chat/completions", json=body,
                                  headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
                                           "X-OpenRouter-Title": "GUI DNA research prototype"}, timeout=180)
            response.raise_for_status()
            payload = response.json()
            dump(out / "response.json", payload)
            usage = payload.get("usage", {})
            if usage.get("cost") is None:
                raise ProviderError("Response has no billed cost; reservation retained and no retry issued")
            self.ledger.settle(call_id, usage["cost"], time.monotonic()-started, payload.get("id"), usage)
            if payload.get("error"):
                raise ProviderError(str(payload["error"]))
            content = payload["choices"][0]["message"]["content"]
            if content is None:
                return ""
            if not isinstance(content, str):
                raise ProviderError("Provider returned non-text content")
            return content
        except Exception as error:
            # Do not persist headers, request reprs, or credentials in diagnostics.
            detail = f"{type(error).__name__}: " + (f"HTTP {error.response.status_code}" if isinstance(error, httpx.HTTPStatusError) else str(error))
            self.ledger.uncertain(call_id, detail)
            receipt = {"call_id": call_id, "error": detail}
            if isinstance(error, httpx.HTTPStatusError):
                receipt["http_status"] = error.response.status_code
                try:
                    safe_body = json.dumps(error.response.json()).replace(os.environ.get("OPENROUTER_API_KEY", ""), "[REDACTED]")
                    receipt["provider_error"] = json.loads(safe_body).get("error")
                except (ValueError, AttributeError):
                    pass
                hint = error.response.headers.get("retry-after", "30")
                receipt["retry_after"] = int(hint) if hint.isdigit() else 30
            dump(out / "error.json", receipt)
            if receipt.get("http_status") == 429:
                raise RateLimited(detail, receipt["retry_after"]) from None
            raise ProviderError(detail) from None
