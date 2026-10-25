"""Offline regressions for Radar batching, pacing and all-or-nothing delivery."""

from contextlib import redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import requests

import concept_radar as radar
import daily_news
from radar_batches import map_records
from radar_model import RadarModel, InputTooLarge, estimate_tokens, duration_seconds


def response(status=200, rows=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result.url = "https://example.invalid/model"
    payload = {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps(rows if rows is not None else [])}}]}
    if status != 200:
        payload = {"error": {"message": "synthetic failure"}}
    result._content = json.dumps(payload).encode()
    result.headers.update(headers or {})
    return result


class FakeClock:
    def __init__(self):
        self.now = 0
        self.waits = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.socket = patch("socket.socket", side_effect=AssertionError("Unexpected network"))
        self.socket.start()
        self.addCleanup(self.socket.stop)
        self.stdout = redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)


class ModelTest(OfflineTest):
    def setUp(self):
        super().setUp()
        self.settings = patch.multiple(daily_news, LLM_PROVIDER="groq", LLM_MODEL="openai/gpt-oss-120b")
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.key = patch.object(daily_news, "_require_key", return_value="offline-key")
        self.key.start()
        self.addCleanup(self.key.stop)
        self.session = Mock()
        self.session.post.return_value = response()
        self.session_patch = patch.object(daily_news, "get_session", return_value=self.session)
        self.session_factory = self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.clock = FakeClock()
        self.model = RadarModel(clock=self.clock.clock, sleep=self.clock.sleep)

    def test_whole_prompt_budget_prevents_network_request(self):
        with self.assertRaises(InputTooLarge):
            self.model("한" * 4000)
        self.session.post.assert_not_called()

    def test_output_is_capped_and_each_attempt_is_locally_paced(self):
        times = []
        def post(*args, **kwargs):
            times.append(self.clock.now)
            return response()
        self.session.post.side_effect = post
        self.model("a" * 6000)
        self.model("a" * 6000)
        self.assertGreaterEqual(times[1] - times[0], 61)
        body = self.session.post.call_args.kwargs["json"]
        self.assertEqual(body["max_completion_tokens"], 2000)
        self.assertEqual(body["reasoning_effort"], "low")
        self.session_factory.assert_called_with()
        self.assertEqual(self.session.post.call_count, 2)

    def test_server_remaining_and_reset_can_require_longer_wait(self):
        self.session.post.side_effect = [response(headers={
            "x-ratelimit-remaining-tokens": "1", "x-ratelimit-reset-tokens": "1m20s"
        }), response()]
        self.model("short")
        self.model("short")
        self.assertGreaterEqual(self.clock.now, 81)

    def test_429_uses_retry_after_and_retry_limit(self):
        self.session.post.side_effect = [response(429, headers={"Retry-After": "7"}), response()]
        self.model("short")
        self.assertIn(8, self.clock.waits)
        self.assertEqual(self.session.post.call_count, 2)
        self.session.post.side_effect = None
        self.session.post.return_value = response(429)
        with self.assertRaises(daily_news.ModelRateLimitError) as caught:
            self.model("short")
        self.assertEqual(caught.exception.failure_details["http_status"], 429)
        self.assertEqual(self.session.post.call_count, 5)

    def test_daily_quota_stops_immediately(self):
        self.session.post.return_value = response(429, headers={
            "x-ratelimit-remaining-requests": "0", "Retry-After": "60"
        })
        with self.assertRaises(daily_news.ModelRateLimitError):
            self.model("short")
        self.session.post.assert_called_once()
        self.assertFalse(self.clock.waits)

    def test_wait_budget_preserves_http_failure_details(self):
        self.session.post.return_value = response(429, headers={"Retry-After": "1900"})
        with self.assertRaises(daily_news.ModelRateLimitError) as caught:
            self.model("short")
        self.assertEqual(caught.exception.failure_details["http_status"], 429)
        self.assertFalse(self.clock.waits)

    def test_daily_token_quota_does_not_wait_for_a_minute_reset(self):
        resp = response(429, headers={"Retry-After": "60"})
        resp._content = json.dumps({"error": {"message": "Rate limit reached on tokens per day (TPD)"}}).encode()
        self.session.post.return_value = resp
        with self.assertRaises(daily_news.ModelRateLimitError):
            self.model("short")
        self.session.post.assert_called_once()
        self.assertFalse(self.clock.waits)

    def test_call_budget_stops_before_another_request(self):
        self.model.calls = 100
        with self.assertRaisesRegex(RuntimeError, "call budget"):
            self.model("short")
        self.session.post.assert_not_called()

    def test_413_is_not_retried_unchanged_by_transport(self):
        self.session.post.return_value = response(413)
        with self.assertRaises(requests.HTTPError):
            self.model("short")
        self.session.post.assert_called_once()

    def test_transient_retries_are_paced_too(self):
        self.session.post.side_effect = [response(503), response()]
        self.model("a" * 6000)
        self.assertGreaterEqual(self.clock.now, 61)

    def test_truncated_output_is_not_accepted(self):
        resp = response()
        payload = resp.json()
        payload["choices"][0]["finish_reason"] = "length"
        resp._content = json.dumps(payload).encode()
        self.session.post.return_value = resp
        with self.assertRaises(InputTooLarge):
            self.model("short")

    def test_gemini_retains_adapter_and_gets_output_bound(self):
        resp = response()
        resp._content = json.dumps({"candidates": [{"content": {"parts": [{"text": "[]"}]}}]}).encode()
        self.session.post.return_value = resp
        with patch.multiple(daily_news, LLM_PROVIDER="gemini", LLM_MODEL="test-model"):
            self.assertEqual(self.model("short"), "[]")
        self.assertEqual(self.session.post.call_args.kwargs["json"]["generationConfig"]["maxOutputTokens"], 2000)

    def test_duration_headers(self):
        self.assertEqual(duration_seconds("1m2.5s"), 62.5)
        self.assertEqual(duration_seconds("250ms"), .25)
        self.assertIsNone(duration_seconds("invalid"))


class BatchTest(OfflineTest):
    def test_413_splits_then_preserves_all_original_ids(self):
        calls = []
        def model(prompt):
            records = json.loads(prompt)
            calls.append(records)
            if len(records) > 2:
                response(413).raise_for_status()
            return json.dumps(records)
        client = Mock(side_effect=model, input_budget=5000)
        records = [{"id": i, "text": "source"} for i in range(1, 9)]
        rows, leaves = map_records(records, json.dumps, lambda data, batch: data, client)
        self.assertEqual(rows, records)
        self.assertEqual(leaves, 4)
        self.assertEqual([len(c) for c in calls], [8, 4, 2, 2, 4, 2, 2])

    def test_one_long_record_is_split_without_losing_text(self):
        seen = []
        def model(prompt):
            self.assertLessEqual(estimate_tokens(prompt), 800)
            records = json.loads(prompt)
            seen.extend(records)
            return json.dumps(records)
        client = Mock(side_effect=model, input_budget=800)
        text = "한글 본문. " * 1000
        rows, leaves = map_records([{"id": 37, "text": text}],
                                  lambda batch: json.dumps(batch, ensure_ascii=False),
                                  lambda data, batch: data, client)
        self.assertGreater(leaves, 1)
        self.assertEqual({r["id"] for r in rows}, {37})
        self.assertEqual("".join(r["text"] for r in seen), text)

    def test_small_unsplittable_413_preserves_original_failure(self):
        def fail(prompt):
            response(413).raise_for_status()
        client = Mock(side_effect=fail, input_budget=5000)
        with self.assertRaises(requests.HTTPError):
            map_records([{"id": 1, "text": "small"}], json.dumps, lambda d, b: d, client)
        client.assert_called_once()

    def test_invented_or_cross_batch_evidence_is_rejected(self):
        for indices in ([9], [True], [1, 9], ["1"]):
            with self.subTest(indices=indices), self.assertRaises(ValueError):
                radar._parse_candidates([{"term": "test", "reason": "reason", "evidence_indices": indices}],
                                        [{"id": 1}])

    def test_cross_batch_alias_merge_preserves_evidence(self):
        candidates = [
            {"term": "speculative decoding", "reason": "first", "evidence_indices": [3]},
            {"term": "speculative decoding", "reason": "second", "evidence_indices": [47]},
            {"term": "speculative sampling", "reason": "alias", "evidence_indices": [98]},
        ]
        client = Mock(return_value=json.dumps([{"term": "speculative decoding", "candidate_ids": [1, 2]}]),
                      input_budget=5000)
        result = radar._consolidate(candidates, [], client)
        self.assertEqual(result, [{"term": "speculative decoding", "evidence_indices": [3, 47, 98]}])

    def test_consolidation_derives_names_from_ids_instead_of_model_spelling(self):
        candidates = [{"term": "speculative decoding", "reason": "grounded", "evidence_indices": [3]}]
        client = Mock(return_value='[{"candidate_ids":[1]}]', input_budget=5000)
        self.assertEqual(radar._consolidate(candidates, [], client),
                         [{"term": "speculative decoding", "evidence_indices": [3]}])

    def test_invalid_candidate_groups_are_repaired_once(self):
        candidates = [{"term": f"concept {i}", "reason": "grounded", "evidence_indices": [i]}
                      for i in (1, 2)]
        client = Mock(side_effect=['[{"candidate_ids":[1]},{"candidate_ids":[1,2]}]',
                                   '[{"candidate_ids":[1,2]}]'], input_budget=5000)
        self.assertEqual(radar._consolidate(candidates, [], client),
                         [{"term": "concept 1", "evidence_indices": [1, 2]}])
        self.assertEqual(client.call_count, 2)
        self.assertIn("previous answer failed validation", client.call_args.args[0])

    def test_repeated_invalid_output_stops_instead_of_dropping_rows(self):
        client = Mock(return_value='[{"term":"test","reason":"grounded","evidence_indices":[9]}]',
                      input_budget=5000)
        with self.assertRaises(ValueError):
            map_records([{"id": 1, "text": "source"}], json.dumps, radar._parse_candidates, client)
        self.assertEqual(client.call_count, 2)

    def test_validation_repair_still_respects_the_input_budget(self):
        records = [{"id": i, "text": "x" * 40} for i in range(8)]
        calls = []
        def model(prompt):
            self.assertLessEqual(estimate_tokens(prompt), 400)
            calls.append(prompt)
            return "invalid JSON" if len(calls) == 1 else prompt
        client = Mock(side_effect=model, input_budget=400)
        rows, leaves = map_records(records, json.dumps, lambda data, batch: data, client)
        self.assertEqual(rows, records)
        self.assertGreater(leaves, 1)

    def test_consolidation_has_multiple_levels_and_finishes_with_three(self):
        sizes = []
        def model(prompt):
            batch = json.loads(prompt.split("Candidates:\n", 1)[1])
            sizes.append(len(batch))
            limit = int(re.search(r"Select up to (\d+)", prompt)[1])
            return json.dumps([{"term": r["term"], "candidate_ids": [r["id"]]} for r in batch[:limit]])
        candidates = [{"term": f"concept {i}", "reason": "r" * 240, "evidence_indices": [i + 1]}
                      for i in range(80)]
        result = radar._consolidate(candidates, [], Mock(side_effect=model, input_budget=1700))
        self.assertLessEqual(len(result), 3)
        self.assertGreater(len(sizes), 3)

    def test_long_explanation_compacts_sources_and_preserves_links(self):
        prompts = []
        def model(prompt):
            prompts.append(prompt)
            self.assertLessEqual(estimate_tokens(prompt), 5000)
            if prompt.startswith("Extract only factual evidence"):
                batch = json.loads(prompt.split('Output only JSON:\n', 1)[1].split('\n', 1)[1])
                return json.dumps([{"id": r["id"], "text": "A grounded note."} for r in batch])
            return json.dumps([{"term": "speculative decoding", "definition": "definition",
                               "why_now": "why", "practical_relevance": "use", "evidence_indices": [1, 2, 3]}])
        evidence = {i: {"title": f"Article {i}", "url": f"https://example.invalid/{i}",
                        "source": "Test", "evidence_text": "긴 원문. " * 1000} for i in (1, 2, 3)}
        original = dict(evidence)
        result = radar.explain_terms([{"term": "speculative decoding", "evidence_indices": [1, 2, 3]}],
                                    evidence, Mock(side_effect=model, input_budget=5000))
        self.assertGreater(len(prompts), 3)
        self.assertEqual(result[0]["evidence_indices"], [1, 2, 3])
        self.assertEqual(evidence, original)

    def test_failure_mid_extraction_never_sends_or_archives(self):
        items = [{"title": f"Article {i}", "url": f"https://example.invalid/{i}",
                  "source": "Test", "excerpt": "Long archive excerpt. " * 100} for i in range(10)]
        client = Mock(side_effect=["[]", RuntimeError("batch failed")], input_budget=5000)
        with patch.multiple(radar, read_recent_archive=Mock(return_value=items),
                            fetch_hn_recent=Mock(return_value=[]), current_geeknews=Mock(return_value=[]),
                            recent_terms=Mock(return_value=[]), RadarModel=Mock(return_value=client),
                            write_archive=Mock()), patch.object(daily_news, "send_email") as send:
            with self.assertRaisesRegex(RuntimeError, "batch failed"):
                radar.main()
            send.assert_not_called()
            radar.write_archive.assert_not_called()

    def test_archived_inputs_are_bounded_and_every_sample_is_seen(self):
        items = radar.read_recent_archive(datetime(2026, 10, 25, tzinfo=daily_news.KST))
        self.assertEqual(len(items), 39)
        items += [{"title": f"Synthetic HN headline {i}", "source": "Hacker News"} for i in range(254)]
        seen = []
        sizes = []
        def model(prompt):
            sizes.append(estimate_tokens(prompt))
            records = json.loads(prompt.split("<candidates>\n", 1)[1].split("\n</candidates>", 1)[0])
            seen.extend(r["id"] for r in records)
            return "[]"
        result = radar.nominate_terms(items, [], Mock(side_effect=model, input_budget=5000))
        self.assertEqual(result, [])
        self.assertEqual(set(seen), set(range(1, 294)))
        self.assertGreater(len(sizes), 1)
        self.assertLessEqual(max(sizes), 5000)

    def test_main_completes_batches_before_one_delivery_and_archive(self):
        items = [{"title": f"Speculative decoding evidence {i}",
                  "url": f"https://example.invalid/{i}", "source": "Test",
                  "excerpt": "Grounded source text. " * 40} for i in range(12)]
        clock = FakeClock()
        client = RadarModel(clock=clock.clock, sleep=clock.sleep)
        prompts = []
        delivered_after = []
        def post(url, **kwargs):
            prompt = kwargs["json"]["messages"][0]["content"]
            prompts.append(prompt)
            self.assertLessEqual(estimate_tokens(prompt), 5000)
            if "<candidates>" in prompt:
                batch = json.loads(prompt.split("<candidates>\n", 1)[1].split("\n</candidates>", 1)[0])
                rows = [{"term": "speculative decoding", "reason": "Multiple sources explain the method",
                         "evidence_indices": [r["id"] for r in batch]}]
            elif prompt.startswith("Select up to"):
                batch = json.loads(prompt.split("Candidates:\n", 1)[1])
                rows = [{"term": "speculative decoding", "candidate_ids": [r["id"] for r in batch]}]
            else:
                rows = [{"term": "speculative decoding", "definition": "Definition.", "why_now": "Evidence.",
                         "practical_relevance": "Use.", "evidence_indices": [1, 2, 3]}]
            return response(rows=rows)
        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            radar, read_recent_archive=Mock(return_value=items), fetch_hn_recent=Mock(return_value=[]),
            current_geeknews=Mock(return_value=[]), recent_terms=Mock(return_value=[]),
            RadarModel=Mock(return_value=client), CONCEPT_DIR=Path(directory)
        ), patch.multiple(daily_news, LLM_PROVIDER="groq", LLM_MODEL="openai/gpt-oss-120b",
                          get_session=Mock(return_value=Mock(post=Mock(side_effect=post))),
                          _require_key=Mock(return_value="offline-key")), patch.dict(
                              "os.environ", {"GITHUB_ENV": ""}
                          ), patch.object(daily_news, "send_email", side_effect=lambda *a: delivered_after.append(len(prompts))) as send:
            radar.main()
            send.assert_called_once()
            self.assertEqual(delivered_after, [len(prompts)])
            self.assertGreater(len(prompts), 3)
            self.assertTrue(clock.waits)
            archives = list(Path(directory).glob("*.md"))
            self.assertEqual(len(archives), 1)
            content = archives[0].read_text(encoding="utf-8")
            self.assertIn("speculative decoding", content)
            self.assertIn(items[0]["url"], content)

    def test_explanation_failure_does_not_deliver_earlier_results(self):
        nominations = [{"term": f"concept {i}", "evidence_indices": [i]} for i in (1, 2)]
        evidence = {i: {"title": "Title", "source": "Test", "url": "https://example.invalid",
                        "evidence_text": "source"} for i in (1, 2)}
        first = [{"term": "concept 1", "definition": "definition", "why_now": "why",
                  "practical_relevance": "use", "evidence_indices": [1]}]
        client = Mock(side_effect=[json.dumps(first), RuntimeError("second explanation failed")], input_budget=5000)
        with patch.multiple(radar, read_recent_archive=Mock(return_value=[evidence[1]]),
                            fetch_hn_recent=Mock(return_value=[]), current_geeknews=Mock(return_value=[]),
                            recent_terms=Mock(return_value=[]), nominate_terms=Mock(return_value=nominations),
                            hydrate_evidence=Mock(return_value=evidence), RadarModel=Mock(return_value=client),
                            write_archive=Mock()), patch.object(daily_news, "send_email") as send:
            with self.assertRaisesRegex(RuntimeError, "second explanation failed"):
                radar.main()
            send.assert_not_called()
            radar.write_archive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
