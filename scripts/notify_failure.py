"""Email safe failure details to the sending account, never to RECIPIENTS."""

import json
import os
from pathlib import Path
import smtplib
from email.mime.text import MIMEText

import failure_report


STEP_NAMES = {
    "checkout": "저장소 체크아웃",
    "setup": "Python 설정",
    "install": "의존성 설치",
    "build": "콘텐츠 생성 및 이메일 발송",
    "archive": "발송 기록 커밋 및 푸시",
}


def load_report(env):
    try:
        steps = json.loads(env.get("STEPS_JSON") or "{}")
    except (ValueError, TypeError):
        steps = {}
    if not isinstance(steps, dict):
        steps = {}
    failed = [
        key for key, value in steps.items()
        if isinstance(value, dict) and value.get("outcome") == "failure"
    ]
    # A report belongs to the build step, never a later archive/push failure.
    if "build" in failed or not failed:
        path = env.get("FAILURE_REPORT_PATH")
        if path:
            try:
                report = json.loads(Path(path).read_text(encoding="utf-8"))
                if isinstance(report, dict):
                    return report
            except (OSError, ValueError):
                pass
    names = [STEP_NAMES.get(key, key) for key in failed]
    return {"stage": ", ".join(names) or "확인되지 않은 단계"}


def build_message(env):
    report = load_report(env)
    workflow = env.get("GITHUB_WORKFLOW") or "Tri-Lens"
    stage = report.get("stage") or "확인되지 않은 단계"
    reason = failure_report.summary(report)
    lines = [f"{workflow} 실행이 실패했습니다.", "", f"실패 단계: {stage}", f"원인: {reason}"]
    if report.get("exception_type"):
        lines.append(f"오류 유형: {report['exception_type']}")
    if report.get("provider"):
        lines.append(f"모델: {report['provider']} / {report.get('model') or '(확인되지 않음)'}")
    lines += [
        "", f"로그: {env.get('RUN_URL') or '(run URL 없음)'}", "",
        "이 알림은 실행된 작업의 실패만 보고합니다. 알림이 없더라도 실행 누락이나",
        "알림 발송 실패일 수 있으므로 Actions 탭에서 확인하세요.",
    ]
    msg = MIMEText("\n".join(lines), "plain", "utf-8")
    subject = f"⚠️ {workflow} — {stage} 실패: {reason}"
    msg["Subject"] = " ".join(subject.split())[:180]
    msg["From"] = env["GMAIL_ADDRESS"]
    msg["To"] = env["GMAIL_ADDRESS"]
    return msg


def main():
    address = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    msg = build_message(os.environ)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(address, password)
        server.sendmail(address, [address], msg.as_string())
    print("실패 알림 전송 완료")


if __name__ == "__main__":
    main()
