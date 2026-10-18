"""Safe failure details shared by the job runner and SMTP notification.

Only allowlisted facts are persisted. Raw exception messages, response bodies,
request URLs, prompts, and credentials never enter the notification report.
"""

import json
import os
from pathlib import Path
import re
import sys


_stage = "초기화"


def set_stage(name):
    global _stage
    _stage = name


def model_details(provider, model, exc):
    details = {"provider": provider, "model": model}
    response = getattr(exc, "response", None)
    if response is None:
        return details
    status = response.status_code
    details["http_status"] = status
    reasons = {
        400: "모델 API 요청 형식 오류",
        401: "모델 API 인증 실패",
        403: "모델 API 접근 거부",
        404: "모델 API 리소스를 찾지 못함",
        413: "모델 API 요청 크기 초과",
        429: "모델 API 사용량 한도 초과",
    }
    details["reason"] = reasons.get(status, "모델 API 요청 실패")
    # Extract numbers only; API error messages may contain account identifiers.
    if status == 413:
        try:
            payload = response.json()
        except (ValueError, TypeError):
            payload = None
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if isinstance(message, str):
            match = re.search(
                r"tokens per minute\s*\(TPM\):\s*Limit\s+(\d+),\s*Requested\s+(\d+)",
                message,
                re.IGNORECASE,
            )
            if match:
                details["token_limit"] = int(match[1])
                details["requested_tokens"] = int(match[2])
    return details


def summary(report):
    reason = report.get("reason") or "상세 원인은 로그에서 확인하세요"
    if report.get("http_status"):
        reason = f"HTTP {report['http_status']}: {reason}"
    if "token_limit" in report and "requested_tokens" in report:
        reason += (
            f" - 요청 {report['requested_tokens']:,}토큰 / "
            f"TPM 한도 {report['token_limit']:,}토큰"
        )
    return reason


def run(action):
    """Write a report on failure, then preserve the original exit/traceback."""
    try:
        return action()
    except (Exception, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code in (None, 0):
            raise
        report = {"stage": _stage, "exception_type": type(exc).__name__}
        report.update(getattr(exc, "failure_details", {}))
        path = os.environ.get("FAILURE_REPORT_PATH")
        if path:
            try:
                Path(path).write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            except OSError as report_error:
                print(f"실패 보고서 저장 실패: {type(report_error).__name__}", file=sys.stderr)
        annotation = f"{_stage} 실패 - {summary(report)}"
        annotation = annotation.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::error title=Tri-Lens 실행 실패::{annotation}", flush=True)
        raise
