from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import uuid
from pathlib import Path

import uvicorn

from learningloop.agent import AgentService
from learningloop.auth import AuthenticationError, AuthService
from learningloop.backup import BackupError, backup_database, restore_database
from learningloop.config import get_settings
from learningloop.db import Database
from learningloop.doctor import CapabilityDoctor
from learningloop.learning.daily import DailyLearningService
from learningloop.notifications import MailService, NotificationScheduler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="learningloop")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Start the local Web application")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    doctor = subparsers.add_parser("doctor", help="Inspect provider configuration")
    doctor.add_argument("--live", action="store_true", help="Run bounded real-model checks")
    cleanup = subparsers.add_parser("cleanup", help="Remove expired operational records")
    cleanup.add_argument("--days", type=int)
    plan = subparsers.add_parser("plan", help="Inspect or generate a daily plan")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_today = plan_sub.add_parser("today", help="Generate today's plan")
    plan_today.add_argument("--session-id", required=True)
    notify = subparsers.add_parser("notifications", help="Manage scheduled email notifications")
    notify_sub = notify.add_subparsers(dest="notification_command", required=True)
    notify_test = notify_sub.add_parser("test", help="Send a test email")
    notify_test.add_argument("--session-id", required=True)
    run_once = notify_sub.add_parser("run-once", help="Run due reminders once")
    run_once.add_argument("--force", action="store_true")
    history = notify_sub.add_parser("history", help="Show delivery history")
    history.add_argument("--session-id")
    users = subparsers.add_parser("users", help="Manage private instance accounts")
    users_sub = users.add_subparsers(dest="user_command", required=True)
    user_create = users_sub.add_parser("create", help="Create a local account")
    user_create.add_argument("username")
    user_create.add_argument("--password-stdin", action="store_true")
    user_disable = users_sub.add_parser("disable", help="Disable an account")
    user_disable.add_argument("username")
    users_sub.add_parser("list", help="List local accounts")
    backup = subparsers.add_parser("backup", help="Create or restore a SQLite backup")
    backup_sub = backup.add_subparsers(dest="backup_command", required=True)
    backup_create = backup_sub.add_parser("create", help="Create a consistent backup")
    backup_create.add_argument("--output", required=True)
    backup_restore = backup_sub.add_parser("restore", help="Restore a backup")
    backup_restore.add_argument("--input", required=True)
    backup_restore.add_argument("--confirm", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()
    db = Database(settings.database_path)
    if args.command == "serve":
        uvicorn.run(
            "learningloop.web.app:create_app",
            factory=True,
            host=args.host or settings.host,
            port=args.port or settings.port,
            reload=False,
        )
        return 0
    if args.command == "doctor":
        doctor = CapabilityDoctor(settings, db)
        result = asyncio.run(doctor.run_live()) if args.live else doctor.configured()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "cleanup":
        result = db.cleanup(args.days or settings.raw_message_retention_days)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "plan":
        service = AgentService(settings, db)
        daily = DailyLearningService(settings, db, service.gateway)
        plan = asyncio.run(daily.generate_daily_plan(args.session_id))
        print(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0
    if args.command == "notifications":
        if args.notification_command == "history":
            print(json.dumps(db.notification_deliveries(args.session_id), ensure_ascii=False, indent=2))
            return 0
        service = AgentService(settings, db)
        daily = DailyLearningService(settings, db, service.gateway)
        mailer = MailService(settings)
        if args.notification_command == "test":
            setting = db.get_notification_settings(args.session_id)
            if not setting or not setting.get("email"):
                print(json.dumps({"status": "error", "message": "email not configured"}, ensure_ascii=False))
                return 1
            result = mailer.send(
                recipient=setting["email"],
                subject="LearningLoop 邮件测试",
                text="LearningLoop 邮件提醒配置成功。",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        scheduler = NotificationScheduler(settings, db, daily, mailer)
        result = asyncio.run(scheduler.run_once(force=args.force))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "users":
        auth = AuthService(settings, db)
        if args.user_command == "list":
            print(json.dumps(db.list_users(), ensure_ascii=False, indent=2))
            return 0
        if args.user_command == "disable":
            if not db.set_user_disabled(args.username, True):
                print(json.dumps({"status": "error", "message": "user not found"}, ensure_ascii=False))
                return 1
            print(json.dumps({"status": "disabled", "username": args.username}, ensure_ascii=False))
            return 0
        password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Password: ")
        try:
            password_hash = auth.hash_password(password)
            user = db.create_user(uuid.uuid4().hex, args.username.strip(), password_hash)
        except (AuthenticationError, ValueError) as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps({"status": "created", "user": user}, ensure_ascii=False))
        return 0
    if args.command == "backup":
        try:
            result = (
                backup_database(settings.database_path, Path(args.output))
                if args.backup_command == "create"
                else restore_database(
                    Path(args.input), settings.database_path, confirm=args.confirm
                )
            )
        except BackupError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
