"""Bounded, paced model requests used only by Concept Radar.

The byte-based token estimate is deliberately cautious for ordinary English and
Korean prose, not an exact tokeniser. HTTP 413 is left to the caller to split.
"""

import math
import re
import time

import requests

import daily_news
import failure_report


INPUT_BUDGET = 5000
OUTPUT_BUDGET = 2000
TPM_BUDGET = 8000
MAX_WAIT_SECONDS = 1800
MAX_CALLS = 100


class InputTooLarge(ValueError):
    pass


def estimate_tokens(text):
    # Include room for message framing; 413 splitting covers estimation errors.
    return math.ceil(len(text.encode("utf-8")) / 2) + 128


def duration_seconds(value):
    """Parse Groq reset headers such as 1m2.5s or 250ms."""
    value = str(value or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return float(value)
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", value)
    if not parts or "".join(n + unit for n, unit in parts) != value:
        return None
    scale = {"ms": .001, "s": 1, "m": 60, "h": 3600}
    return sum(float(n) * scale[unit] for n, unit in parts)


def daily_quota_exhausted(response):
    if response.headers.get("x-ratelimit-remaining-requests") == "0":
        return True
    try:
        payload = response.json()
    except ValueError:
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    message = error.get("message", "") if isinstance(error, dict) else ""
    return isinstance(message, str) and bool(re.search(
        r"(?:tokens|requests) per day|\b(?:TPD|RPD)\b", message, re.IGNORECASE
    ))


class RadarModel:
    def __init__(self, *, clock=None, sleep=None):
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.waited = 0
        self.calls = 0
        self.input_budget = INPUT_BUDGET
        self.remaining = None
        self.reset_at = 0
        self.sent = []

    def wait(self, seconds):
        seconds = max(0, seconds)
        if self.waited + seconds > MAX_WAIT_SECONDS:
            raise daily_news.ModelRateLimitError("Radar waiting budget exhausted")
        if seconds:
            print(f"  Radar API 대기 {seconds:.1f}초", flush=True)
            self.waited += seconds
            self.sleep(seconds)

    def _pace(self, cost):
        now = self.clock()
        self.sent = [(at, tokens) for at, tokens in self.sent if now - at < 61]
        if self.remaining is not None and now < self.reset_at and cost > self.remaining:
            self.wait(self.reset_at - now + 1)
        # Local rolling reservations also work when headers are absent. Reserve
        # the entire output allowance, including reasoning, for every attempt.
        now = self.clock()
        self.sent = [(at, tokens) for at, tokens in self.sent if now - at < 61]
        while sum(tokens for _, tokens in self.sent) + cost > TPM_BUDGET:
            self.wait(self.sent[0][0] + 61 - self.clock())
            now = self.clock()
            self.sent = [(at, tokens) for at, tokens in self.sent if now - at < 61]
        self.sent.append((self.clock(), cost))

    def _observe(self, response):
        self.remaining = None
        reset = duration_seconds(response.headers.get("x-ratelimit-reset-tokens"))
        try:
            remaining = float(response.headers.get("x-ratelimit-remaining-tokens", ""))
        except (TypeError, ValueError):
            return
        if math.isfinite(remaining) and reset is not None:
            self.remaining = max(0, remaining)
            self.reset_at = self.clock() + reset

    def __call__(self, prompt):
        provider = daily_news.LLM_PROVIDER
        build, extract, default_model = daily_news.PROVIDERS[provider]
        model = daily_news.LLM_MODEL or default_model
        retries = 0
        session = None
        try:
            if estimate_tokens(prompt) > self.input_budget:
                raise InputTooLarge("Radar prompt exceeds input budget")
            url, headers, body = build(model, prompt)
            if provider == "gemini":
                body["generationConfig"] = {"maxOutputTokens": OUTPUT_BUDGET}
            else:
                body["max_completion_tokens"] = OUTPUT_BUDGET
                if model in {"openai/gpt-oss-120b", "openai/gpt-oss-20b"}:
                    body["reasoning_effort"] = "low"
            # POST retries must pass through pacing too, not urllib3's hidden loop.
            session = daily_news.get_session()
            quota_retries = 0
            transient_retries = 0
            while True:
                if self.calls >= MAX_CALLS:
                    raise RuntimeError("Radar model call budget exhausted")
                self._pace(estimate_tokens(prompt) + OUTPUT_BUDGET)
                self.calls += 1
                print(f"  Radar API 호출 {self.calls}: 입력 추정 {estimate_tokens(prompt)}토큰", flush=True)
                try:
                    response = session.post(url, headers=headers, json=body, timeout=120)
                except (requests.ConnectionError, requests.Timeout):
                    if transient_retries >= 2:
                        raise
                    transient_retries += 1
                    retries += 1
                    self.wait(2 ** transient_retries)
                    continue
                self._observe(response)
                if response.status_code == 429:
                    delay = daily_news.quota_retry_delay(response)
                    # Groq's request counter is daily, not per-minute.
                    if daily_quota_exhausted(response):
                        delay = None
                    if delay is None or quota_retries >= 2:
                        error = daily_news.ModelRateLimitError("Radar API quota exhausted")
                        error.response = response
                        raise error
                    try:
                        self.wait(max(1, delay + 1))
                    except daily_news.ModelRateLimitError as exc:
                        exc.response = response
                        raise
                    quota_retries += 1
                    retries += 1
                    continue
                if response.status_code in {500, 502, 503, 504} and transient_retries < 2:
                    transient_retries += 1
                    retries += 1
                    self.wait(2 ** transient_retries)
                    continue
                response.raise_for_status()
                payload = response.json()
                if provider == "gemini":
                    finishes = [c.get("finishReason") for c in payload.get("candidates", [])]
                    truncated = "MAX_TOKENS" in finishes
                else:
                    truncated = any(c.get("finish_reason") == "length" for c in payload.get("choices", []))
                if truncated:
                    raise InputTooLarge("Radar output truncated; reduce the task")
                return extract(payload)
        except Exception as exc:
            exc.failure_details = failure_report.model_details(provider, model, exc)
            raise
        finally:
            if session is not None:
                session.close()
            daily_news.model_retries.append(retries)
            daily_news.models_used.append(f"{provider}:{model}")
