"""Offline checks for the response -> report -> email failure path."""

from contextlib import redirect_stderr, redirect_stdout
from email import message_from_string
from email.header import decode_header, make_header
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import requests

import daily_news
import concept_radar
import failure_report
import notify_failure


def response(status, payload):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode("utf-8")
    result.url = "https://example.invalid/model"
    return result


class FailureNotificationsTest(unittest.TestCase):
    def setUp(self):
        self.offline = patch("socket.socket", side_effect=AssertionError("Unexpected network call"))
        self.offline.start()
        self.addCleanup(self.offline.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "failure.json"
        self.env = {
            "FAILURE_REPORT_PATH": str(self.path),
            "GMAIL_ADDRESS": "sender@example.invalid",
            "GMAIL_APP_PASSWORD": "test-password-never-report",
            "RECIPIENTS": "reader@example.invalid",
            "GITHUB_WORKFLOW": "Tri-Lens Concept Radar",
            "GITHUB_ACTIONS": "true",
            "RUN_URL": "https://github.com/example/repo/actions/runs/1",
            "STEPS_JSON": json.dumps({"build": {"outcome": "failure"}}),
            "GROQ_API_KEY": "test-key-never-report",
        }
        self.environment = patch.dict(os.environ, self.env)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        failure_report.set_stage("개념 후보 선별")

    def fail_model(self, resp, action=None):
        session = Mock()
        session.post.return_value = resp
        output = io.StringIO()
        with patch.object(daily_news, "get_session", return_value=session), redirect_stdout(output), redirect_stderr(io.StringIO()):
            with self.assertRaises((requests.HTTPError, daily_news.ModelRateLimitError)):
                failure_report.run(action or (
                    lambda: daily_news.call_model("private prompt", provider="groq", model="openai/gpt-oss-120b")
                ))
        session.post.assert_called_once()
        return output.getvalue()

    def test_413_reaches_report_email_and_annotation_without_sensitive_text(self):
        payload = {"error": {"message": (
            "Request too large for model in organization private-org: "
            "tokens per minute (TPM): Limit 8000, Requested 18062, "
            "test-key-never-report test-password-never-report private prompt"
        )}}
        output = self.fail_model(response(413, payload))
        report = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(report["token_limit"], 8000)
        self.assertEqual(report["requested_tokens"], 18062)
        self.assertEqual(report["stage"], "개념 후보 선별")
        msg = notify_failure.build_message(self.env)
        body = msg.get_payload(decode=True).decode("utf-8")
        self.assertIn("18,062토큰 / TPM 한도 8,000토큰", body)
        self.assertIn("groq / openai/gpt-oss-120b", body)
        self.assertIn("HTTP 413", msg["Subject"])
        self.assertIn("Concept Radar", msg["Subject"])
        self.assertIn("::error title=Tri-Lens 실행 실패::개념 후보 선별", output)
        combined = self.path.read_text(encoding="utf-8") + body + msg["Subject"]
        for private in ("private-org", "test-key-never-report", "test-password-never-report", "private prompt"):
            self.assertNotIn(private, combined)

    def test_429_preserves_details_when_quota_retry_is_exhausted(self):
        resp = response(429, {"error": {"message": "private upstream message"}})
        resp.headers["Retry-After"] = "120"
        self.fail_model(resp)
        report = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(report["exception_type"], "ModelRateLimitError")
        self.assertEqual(report["http_status"], 429)
        self.assertIn("사용량 한도 초과", report["reason"])

    def test_failed_transport_retries_are_not_logged_as_success(self):
        resp = response(413, {})
        resp.raw = SimpleNamespace(retries=SimpleNamespace(history=[SimpleNamespace(status=413)] * 4))
        self.assertNotIn("후 성공", self.fail_model(resp))

    def test_successful_model_call_is_unchanged_and_has_no_extra_request(self):
        session = Mock()
        session.post.return_value = response(200, {"choices": [{"message": {"content": "result"}}]})
        with patch.object(daily_news, "get_session", return_value=session):
            result = failure_report.run(
                lambda: daily_news.call_model("prompt", provider="groq", model="model")
            )
        self.assertEqual(result, "result")
        session.post.assert_called_once()
        self.assertFalse(self.path.exists())

    def test_non_json_response_has_http_reason_without_inventing_token_counts(self):
        resp = response(401, {})
        resp._content = b"<html>private upstream response</html>"
        self.fail_model(resp)
        report = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(report["reason"], "모델 API 인증 실패")
        self.assertNotIn("token_limit", report)

    def test_other_error_formats_do_not_fabricate_tpm_limits(self):
        for payload in ([], {"error": "bad"}, {"error": {"message": ["bad"]}}, {"error": {"message": "context limit 9999"}}):
            with self.subTest(payload=payload):
                exc = requests.HTTPError(response=response(413, payload))
                details = failure_report.model_details("groq", "model", exc)
                self.assertEqual(details["http_status"], 413)
                self.assertNotIn("token_limit", details)

    def test_unknown_exception_reports_stage_and_type_without_raw_message(self):
        failure_report.set_stage("이메일 발송")
        with self.assertRaises(TimeoutError), redirect_stdout(io.StringIO()):
            failure_report.run(lambda: (_ for _ in ()).throw(TimeoutError("secret password")))
        msg = notify_failure.build_message(self.env)
        body = msg.get_payload(decode=True).decode("utf-8")
        self.assertIn("TimeoutError", body)
        self.assertIn("이메일 발송", body)
        self.assertIn("상세 원인은 로그에서 확인", body)
        self.assertNotIn("secret password", body)

    def test_setup_install_archive_and_missing_reports_fall_back_to_workflow_steps(self):
        self.path.write_text('{"stage": "stale build", "reason": "stale reason"}', encoding="utf-8")
        for step, expected in (("setup", "Python 설정"), ("install", "의존성 설치"), ("archive", "발송 기록 커밋 및 푸시")):
            with self.subTest(step=step):
                env = {**self.env, "STEPS_JSON": json.dumps({step: {"outcome": "failure"}})}
                body = notify_failure.build_message(env).get_payload(decode=True).decode("utf-8")
                self.assertIn(expected, body)
                self.assertNotIn("stale", body)
        for content in ("not json", "[]"):
            self.path.write_text(content, encoding="utf-8")
            self.assertEqual(notify_failure.load_report(self.env)["stage"], "콘텐츠 생성 및 이메일 발송")
        self.path.unlink()
        self.assertEqual(notify_failure.load_report(self.env)["stage"], "콘텐츠 생성 및 이메일 발송")

    def test_smtp_uses_only_sender_and_serialized_message_has_readable_subject(self):
        self.path.write_text('{"stage": "뉴스 선별", "reason": "모델 API 인증 실패", "http_status": 401}', encoding="utf-8")
        with patch.dict(os.environ, {"GITHUB_WORKFLOW": "Tri-Lens Daily News"}), patch.object(notify_failure.smtplib, "SMTP_SSL") as smtp:
            notify_failure.main()
        server = smtp.return_value.__enter__.return_value
        server.login.assert_called_once_with(self.env["GMAIL_ADDRESS"], self.env["GMAIL_APP_PASSWORD"])
        sender, recipients, raw = server.sendmail.call_args.args
        self.assertEqual(sender, self.env["GMAIL_ADDRESS"])
        self.assertEqual(recipients, [sender])
        msg = message_from_string(raw)
        subject = str(make_header(decode_header(msg["Subject"])))
        self.assertIn("Daily News", subject)
        self.assertIn("HTTP 401", subject)
        self.assertNotIn(self.env["RECIPIENTS"], raw)
        self.assertNotIn(self.env["GMAIL_APP_PASSWORD"], raw)

    def test_success_and_zero_exit_do_not_write_reports(self):
        self.assertEqual(failure_report.run(lambda: "ok"), "ok")
        with self.assertRaises(SystemExit):
            failure_report.run(lambda: sys.exit(0))
        self.assertFalse(self.path.exists())

    def test_report_write_error_preserves_original_exception(self):
        with patch.object(Path, "write_text", side_effect=OSError("private path")):
            with self.assertRaisesRegex(ValueError, "original"), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                failure_report.run(lambda: (_ for _ in ()).throw(ValueError("original")))

    def test_runner_reports_import_errors_and_preserves_nonzero_exit(self):
        script = Path(self.temp.name) / "import_failure.py"
        script.write_text("import missing_tri_lens_test_dependency\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_job.py"), str(script)],
            env=os.environ.copy(), capture_output=True, timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"::error", result.stdout)
        report = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(report["stage"], "초기화")
        self.assertEqual(report["exception_type"], "ModuleNotFoundError")

    def test_both_entrypoints_capture_the_actual_model_failure_stage(self):
        item = {"title": "Example", "url": "https://example.invalid/article", "source": "Hacker News"}
        with patch.multiple(
            daily_news, fetch_hackernews_top=Mock(return_value=[item, item]),
            fetch_geeknews=Mock(return_value=[]), fetch_hf_papers=Mock(return_value=[item]),
            recently_covered=Mock(return_value=set()), send_email=Mock(),
            LLM_PROVIDER="groq", LLM_MODEL="openai/gpt-oss-120b",
        ):
            self.fail_model(response(413, {}), daily_news.main)
            daily_news.send_email.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["stage"], "뉴스 선별")
        with patch.multiple(
            concept_radar, read_recent_archive=Mock(return_value=[item]),
            fetch_hn_recent=Mock(return_value=[]), current_geeknews=Mock(return_value=[]),
            recent_terms=Mock(return_value=[]),
        ), patch.multiple(daily_news, send_email=Mock(), LLM_PROVIDER="groq", LLM_MODEL="openai/gpt-oss-120b"):
            self.fail_model(response(413, {}), concept_radar.main)
            daily_news.send_email.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["stage"], "개념 후보 선별")


if __name__ == "__main__":
    unittest.main()
