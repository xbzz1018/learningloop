from __future__ import annotations

import asyncio
import smtplib
import uuid
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Any

from learningloop.config import Settings


class MailDeliveryError(RuntimeError):
    pass


class MailService:
    """SMTP sender adapted from OnCallAgent, with a safe local outbox for development."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.outbox_dir = settings.notification_outbox_dir
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.smtp_host
            and self.settings.smtp_username
            and self.settings.smtp_password
            and self.settings.smtp_sender
        )

    def send(
        self, *, recipient: str, subject: str, text: str, html: str | None = None
    ) -> dict[str, str]:
        parsed = parseaddr(recipient)[1]
        if "@" not in parsed:
            raise MailDeliveryError("invalid recipient email")
        message_id = f"<{uuid.uuid4().hex}@learningloop>"
        if not self.configured:
            path = self.outbox_dir / f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex}.txt"
            path.write_text(f"Subject: {subject}\nTo: {recipient}\n\n{text}\n", encoding="utf-8")
            return {"delivery_mode": "local_outbox", "message_id": message_id, "path": str(path)}

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr(("LearningLoop", self.settings.smtp_sender))
        message["To"] = recipient
        message["Message-ID"] = message_id
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")
        password = self.settings.smtp_password.get_secret_value()  # type: ignore[union-attr]
        use_ssl = self.settings.smtp_use_ssl or self.settings.smtp_port == 465
        smtp_type = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        try:
            with smtp_type(
                self.settings.smtp_host, self.settings.smtp_port, timeout=20
            ) as client:
                if self.settings.smtp_use_tls and not use_ssl:
                    client.starttls()
                client.login(self.settings.smtp_username, password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailDeliveryError(str(exc)) from exc
        return {"delivery_mode": "smtp", "message_id": message_id}


def render_plan_email(plan: Any) -> tuple[str, str]:
    lines = [f"LearningLoop 今日学习计划（{plan.plan_date}）", "", f"目标：{plan.goal}", ""]
    for index, task in enumerate(plan.tasks, start=1):
        mark = "[x]" if task.completed else "[ ]"
        lines.append(f"{mark} {index}. {task.title}（{task.estimated_minutes} 分钟）")
        if task.objective:
            lines.append(f"    {task.objective}")
    lines.extend(["", f"预计总时长：{plan.total_minutes} 分钟", f"完成标准：{plan.completion_criteria}"])
    text = "\n".join(lines)
    items = "".join(
        f"<li><strong>{task.title}</strong>（{task.estimated_minutes} 分钟）"
        f"<br><span>{task.objective}</span></li>" for task in plan.tasks
    )
    html = (
        f"<h2>LearningLoop 今日学习计划（{plan.plan_date}）</h2>"
        f"<p><b>目标：</b>{plan.goal}</p><ol>{items}</ol>"
        f"<p>预计总时长：{plan.total_minutes} 分钟<br>完成标准：{plan.completion_criteria}</p>"
    )
    return text, html


def render_review_email(review: Any) -> tuple[str, str]:
    text = (
        f"LearningLoop 今日学习复盘（{review.review_date}）\n\n"
        f"{review.summary}\n\n"
        f"已完成任务：{len(review.completed_task_ids)}\n"
        f"未完成任务：{len(review.unfinished_task_ids)}\n"
        f"明日重点：{', '.join(review.tomorrow_focus) or '暂无'}"
    )
    html = (
        f"<h2>LearningLoop 今日学习复盘（{review.review_date}）</h2>"
        f"<p>{review.summary}</p>"
        f"<p>已完成任务：{len(review.completed_task_ids)}<br>"
        f"未完成任务：{len(review.unfinished_task_ids)}<br>"
        f"明日重点：{', '.join(review.tomorrow_focus) or '暂无'}</p>"
    )
    return text, html


class NotificationScheduler:
    def __init__(
        self,
        settings: Settings,
        db: Any,
        daily_service: Any,
        mailer: MailService,
        *,
        autonomous_plan: Any | None = None,
        autonomous_review: Any | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.daily_service = daily_service
        self.mailer = mailer
        # 生产应用传入 AgentService 的主动入口；独立测试仍可只传 daily_service。
        self.autonomous_plan = autonomous_plan
        self.autonomous_review = autonomous_review
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def start(self) -> None:
        if self.settings.notification_scheduler_enabled and self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                # A notification failure is isolated from the Web process.
                pass
            await asyncio.sleep(max(5, self.settings.notification_poll_seconds))

    async def run_once(self, now: datetime | None = None, *, force: bool = False) -> list[dict[str, Any]]:
        async with self._lock:
            current = now or datetime.now(UTC)
            results: list[dict[str, Any]] = []
            for setting in self.db.enabled_notification_settings():
                try:
                    from zoneinfo import ZoneInfo

                    local_now = current.astimezone(ZoneInfo(setting["timezone"]))
                except Exception:
                    continue
                local_date = local_now.date().isoformat()
                for schedule_type, configured_time in (
                    ("morning_plan", setting["morning_time"]),
                    ("evening_review", setting["evening_time"]),
                ):
                    try:
                        hour, minute = (int(part) for part in configured_time.split(":", 1))
                        scheduled_local = local_now.replace(
                            hour=hour, minute=minute, second=0, microsecond=0
                        )
                    except (ValueError, TypeError):
                        continue
                    if not force:
                        if local_now < scheduled_local:
                            continue
                        if local_now - scheduled_local > timedelta(
                            hours=self.settings.notification_catchup_hours
                        ):
                            skipped = self._skip_missed(
                                setting["session_id"], local_date, schedule_type
                            )
                            if skipped:
                                results.append(skipped)
                            continue
                    result = await self._deliver(setting, local_date, schedule_type, current)
                    if result:
                        results.append(result)
            return results

    def _skip_missed(self, session_id: str, local_date: str, schedule_type: str) -> dict[str, Any] | None:
        delivery = self.db.reserve_notification_delivery(
            session_id, local_date, schedule_type, uuid.uuid4().hex
        )
        if delivery.get("status") in {"sent", "skipped"}:
            return None
        self.db.update_notification_delivery(
            delivery["id"], status="skipped", last_error="catchup_window_expired"
        )
        return {
            "status": "skipped",
            "schedule_type": schedule_type,
            "delivery_id": delivery["id"],
        }

    async def _deliver(
        self, setting: dict[str, Any], local_date: str, schedule_type: str, now: datetime
    ) -> dict[str, Any] | None:
        delivery = self.db.reserve_notification_delivery(
            setting["session_id"], local_date, schedule_type, uuid.uuid4().hex
        )
        if delivery.get("status") == "sent":
            return None
        attempts = int(delivery.get("attempts") or 0)
        if attempts >= self.settings.notification_retry_limit:
            return None
        next_attempt = delivery.get("next_attempt_at")
        if next_attempt and attempts > 0:
            try:
                if datetime.fromisoformat(next_attempt) > now:
                    return None
            except ValueError:
                pass
        try:
            if schedule_type == "morning_plan":
                if self.autonomous_plan is not None:
                    artifact = await self.autonomous_plan(
                        setting["session_id"], date.fromisoformat(local_date)
                    )
                else:
                    artifact = await self.daily_service.generate_daily_plan(setting["session_id"])
                subject = f"LearningLoop 今日学习计划 · {local_date}"
                text, html = render_plan_email(artifact)
            else:
                if self.autonomous_review is not None:
                    artifact = await self.autonomous_review(
                        setting["session_id"], date.fromisoformat(local_date)
                    )
                else:
                    artifact = await self.daily_service.generate_review(setting["session_id"])
                subject = f"LearningLoop 今日学习复盘 · {local_date}"
                text, html = render_review_email(artifact)
            sent = await asyncio.to_thread(
                self.mailer.send,
                recipient=setting["email"],
                subject=subject,
                text=text,
                html=html,
            )
            self.db.update_notification_delivery(
                delivery["id"],
                status="sent",
                attempts=attempts + 1,
                message_id=sent.get("message_id"),
                sent_at=datetime.now(UTC).isoformat(),
                last_error=None,
            )
            return {"status": "sent", "schedule_type": schedule_type, "delivery_id": delivery["id"]}
        except Exception as exc:  # noqa: BLE001 - delivery status must be persisted
            next_time = datetime.now(UTC) + timedelta(seconds=min(3_600, 60 * (2**attempts)))
            self.db.update_notification_delivery(
                delivery["id"],
                status="failed",
                attempts=attempts + 1,
                next_attempt_at=next_time.isoformat(),
                last_error=type(exc).__name__,
            )
            return {"status": "failed", "schedule_type": schedule_type, "delivery_id": delivery["id"]}


__all__ = ["MailDeliveryError", "MailService", "NotificationScheduler"]
