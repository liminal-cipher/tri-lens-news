"""
Tri-Lens Daily News 실패 알림
- daily_news.py가 실패한 run에서만 실행된다
- 수신자 목록(RECIPIENTS)이 아니라 발신 계정 자신에게만 보낸다.
  독자에게 장애 메일을 보낼 이유가 없다
"""

import os
import smtplib
from email.mime.text import MIMEText

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RUN_URL = os.environ.get("RUN_URL") or "(run URL 없음)"

body = f"""Tri-Lens Daily News 실행이 실패했습니다.

로그: {RUN_URL}

메일이 오지 않은 날 이 알림도 없었다면, 워크플로가 아예 실행되지
않았다는 뜻입니다. Actions 탭에서 스케줄이 비활성화되지 않았는지
확인하세요.
"""


def main():
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "⚠️ Tri-Lens 발송 실패"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [GMAIL_ADDRESS], msg.as_string())
    print(f"실패 알림 전송 완료 → {GMAIL_ADDRESS}")


if __name__ == "__main__":
    main()
