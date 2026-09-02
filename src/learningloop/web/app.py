from __future__ import annotations

import asyncio
import csv
import io
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

from learningloop import __version__
from learningloop.agent import AgentService
from learningloop.auth import AuthenticationError, AuthService
from learningloop.config import Settings, get_settings
from learningloop.db import Database
from learningloop.learning.schemas import DailyPlan
from learningloop.learning.state import LearningWorkspace
from learningloop.models import ActionDecision, TaskMetadata
from learningloop.notifications import MailDeliveryError, MailService, NotificationScheduler
from learningloop.usage import aggregate_usage


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    operation: str = "chat"
    deep_mode: bool = False
    duration_days: int | None = Field(default=None, ge=1, le=365)
    domain_count: int = Field(default=1, ge=1, le=20)
    affected_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_failures: int = Field(default=0, ge=0, le=10)


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    message: str | None = Field(default=None, max_length=2_000)


class NotificationSettingsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    enabled: bool = False
    timezone: str = "Asia/Shanghai"
    morning_time: str = "08:30"
    evening_time: str = "20:30"

    @field_validator("morning_time", "evening_time")
    @classmethod
    def validate_clock_time(cls, value: str) -> str:
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
        except (ValueError, TypeError):
            raise ValueError("time must use HH:MM") from None
        if not (0 <= hour <= 23 and 0 <= minute <= 59) or len(value) != 5:
            raise ValueError("time must use HH:MM")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError("unknown timezone") from None
        return value


class TaskCompletionRequest(BaseModel):
    completed: bool = True


class TaskResultRequest(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    answer: str = Field(default="", max_length=8_000)
    notes: str = Field(default="", max_length=4_000)
    error_category: Literal[
        "concept-gap", "application-failure", "expression-unclear", "knowledge-confusion"
    ] | None = None
    completed: bool = True


class ActionDecisionRequest(BaseModel):
    decision: ActionDecision
    message: str | None = Field(default=None, max_length=2_000)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings.database_path)
    service = AgentService(settings, db)
    daily = service.daily
    mailer = MailService(settings)
    notification_scheduler = NotificationScheduler(
        settings,
        db,
        daily,
        mailer,
        autonomous_plan=service.run_autonomous_plan,
        autonomous_review=service.run_autonomous_review,
    )
    auth = AuthService(settings, db)
    package_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=package_dir / "templates")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        notification_scheduler.start()
        try:
            yield
        finally:
            await notification_scheduler.stop()

    app = FastAPI(title="LearningLoop", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.service = service
    app.mount("/static", StaticFiles(directory=package_dir / "static"), name="static")

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    def current_user(request: Request, *, redirect: bool = False) -> dict:
        if not settings.auth_enabled:
            return {"id": "local", "username": "local"}
        user = auth.user_from_token(request.cookies.get(settings.auth_cookie_name))
        if user:
            return user
        if redirect:
            raise HTTPException(status_code=303, headers={"Location": "/login"})
        raise HTTPException(status_code=401, detail="authentication required")

    def owner_session(request: Request, session_id: str) -> tuple[dict, dict]:
        user = current_user(request)
        session = db.get_session_for_owner(session_id, user["id"])
        if session is None:
            raise HTTPException(404, "session not found")
        return user, session

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if not settings.auth_enabled:
            return RedirectResponse("/", status_code=307)
        if auth.user_from_token(request.cookies.get(settings.auth_cookie_name)):
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login", response_class=HTMLResponse)
    async def login_form(request: Request, username: str = Form(...), password: str = Form(...)):
        if not settings.auth_enabled:
            return RedirectResponse("/", status_code=307)
        try:
            user = auth.authenticate(username, password)
        except AuthenticationError:
            return templates.TemplateResponse(
                request, "login.html", {"error": "用户名或密码错误"}, status_code=401
            )
        token, expires_at = auth.issue_session(user["id"])
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            settings.auth_cookie_name,
            token,
            max_age=max(60, int((expires_at - datetime.now(UTC)).total_seconds())),
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite="lax",
        )
        return response

    @app.post("/api/v1/auth/login")
    async def login_api(request: Request, body: LoginRequest):
        if not settings.auth_enabled:
            return {"status": "disabled", "user": current_user(request)}
        try:
            user = auth.authenticate(body.username, body.password)
        except AuthenticationError as exc:
            raise HTTPException(401, "invalid username or password") from exc
        token, expires_at = auth.issue_session(user["id"])
        response = JSONResponse({"user": {"id": user["id"], "username": user["username"]}})
        response.set_cookie(
            settings.auth_cookie_name,
            token,
            max_age=max(60, int((expires_at - datetime.now(UTC)).total_seconds())),
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite="lax",
        )
        return response

    @app.post("/api/v1/auth/logout")
    async def logout(request: Request):
        auth.revoke(request.cookies.get(settings.auth_cookie_name))
        response = JSONResponse({"status": "logged_out"})
        response.delete_cookie(settings.auth_cookie_name)
        return response

    @app.post("/logout")
    async def logout_form(request: Request):
        auth.revoke(request.cookies.get(settings.auth_cookie_name))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(settings.auth_cookie_name)
        return response

    @app.get("/api/v1/auth/me")
    async def me(request: Request):
        user = current_user(request)
        return {"user": {"id": user["id"], "username": user["username"]}}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, session_id: str | None = None, view: str = "workspace"):
        user = current_user(request, redirect=True)
        owner_id = user["id"]
        if view not in {"workspace", "plan", "progress", "review", "usage", "notifications"}:
            view = "workspace"
        sessions = db.list_sessions(owner_id=owner_id)
        if session_id is None and sessions:
            session_id = sessions[0]["id"]
        messages = db.recent_messages(session_id, 100) if session_id else []
        current_session = db.get_session_for_owner(session_id, owner_id) if session_id else None
        if session_id and current_session is None:
            raise HTTPException(404, "session not found")
        state = (
            LearningWorkspace(settings.workspace_dir, session_id).snapshot() if session_id else None
        )
        usage = aggregate_usage(
            db.usage_rows(session_id=session_id, owner_id=owner_id)
        ).model_dump(mode="json")
        plan_rows = daily.plan_rows(session_id) if session_id else []
        completed_rows = sum(1 for row in plan_rows if row["completed"])
        plan_progress = {
            "completed": completed_rows,
            "total": len(plan_rows),
            "percent": round(completed_rows / len(plan_rows) * 100) if plan_rows else 0,
        }
        today = daily.local_today().isoformat() if session_id else None
        today_plan_row = db.get_daily_plan(session_id, today) if session_id and today else None
        today_review_row = db.get_daily_review(session_id, today) if session_id and today else None
        notification = db.get_notification_settings(session_id) if session_id else None
        recent_calls = (
            db.model_calls(session_id=session_id, limit=10, owner_id=owner_id)
            if session_id
            else []
        )
        deliveries = (
            db.notification_deliveries(session_id=session_id, limit=20, owner_id=owner_id)
            if session_id
            else []
        )
        pending = db.pending_actions(session_id, owner_id=owner_id) if session_id else []
        run_rows = db.runs_for_session(session_id, owner_id=owner_id, limit=1) if session_id else []
        latest_run = run_rows[0] if run_rows else None
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "sessions": sessions,
                "session_id": session_id,
                "messages": messages,
                "current_session": current_session,
                "state": state,
                "usage": usage,
                "pending": pending,
                "plan_rows": plan_rows,
                "plan_progress": plan_progress,
                "view": view,
                "today_plan": today_plan_row["payload"] if today_plan_row else None,
                "today_review": today_review_row["payload"] if today_review_row else None,
                "notification": notification,
                "recent_calls": recent_calls,
                "deliveries": deliveries,
                "current_user": user,
                "latest_run": latest_run,
            },
        )

    @app.post("/api/v1/sessions", status_code=201)
    async def create_session(request: Request):
        user = current_user(request)
        return service.create_session(owner_id=user["id"])

    @app.get("/api/v1/sessions")
    async def list_sessions(request: Request):
        user = current_user(request)
        return {"sessions": db.list_sessions(owner_id=user["id"])}

    @app.patch("/api/v1/sessions/{session_id}")
    async def update_session(request: Request, session_id: str, body: dict[str, object]):
        owner_session(request, session_id)
        values: dict[str, object] = {}
        if "title" in body:
            title = str(body.get("title") or "").strip()
            if not title or len(title) > 120:
                raise HTTPException(422, "title must contain 1-120 characters")
            values["title"] = title
        if "pinned" in body:
            if not isinstance(body["pinned"], bool):
                raise HTTPException(422, "pinned must be boolean")
            values["pinned"] = int(body["pinned"])
        if not values:
            raise HTTPException(422, "title or pinned is required")
        db.update_session(session_id, **values)
        return db.get_session(session_id)

    @app.delete("/api/v1/sessions/{session_id}")
    async def delete_session(request: Request, session_id: str):
        owner_session(request, session_id)
        db.delete_session(session_id)
        return {"status": "deleted", "session_id": session_id}

    @app.post("/api/v1/sessions/{session_id}/messages", status_code=202)
    async def post_message(request: Request, session_id: str, body: MessageRequest):
        owner_session(request, session_id)
        try:
            after_event_id = db.last_event_id(session_id)
            run_id = service.submit(
                session_id,
                body.content,
                TaskMetadata(**body.model_dump(exclude={"content"})),
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return {
            "run_id": run_id,
            "session_id": session_id,
            "after_event_id": after_event_id,
        }

    @app.post("/api/v1/sessions/{session_id}/retry", status_code=202)
    async def retry_message(request: Request, session_id: str):
        _, session = owner_session(request, session_id)
        latest = db.latest_message(session_id)
        if latest is None:
            raise HTTPException(409, "no user message to retry")
        try:
            after_event_id = db.last_event_id(session_id)
            run_id = service.submit(
                session_id,
                latest["content"],
                TaskMetadata(operation="retry"),
                persist_user=False,
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"run_id": run_id, "session_id": session_id, "after_event_id": after_event_id}

    @app.get("/api/v1/sessions/{session_id}/events")
    async def events(request: Request, session_id: str, after: int = 0):
        owner_session(request, session_id)

        async def stream():
            cursor = after
            idle_cycles = 0
            while idle_cycles < 600:
                rows = db.events_after(session_id, cursor)
                if rows:
                    idle_cycles = 0
                    for row in rows:
                        cursor = row["id"]
                        yield (
                            f"id: {cursor}\n"
                            f"event: {row['type']}\n"
                            f"data: {json.dumps(row, ensure_ascii=False, default=str)}\n\n"
                        )
                else:
                    idle_cycles += 1
                    if idle_cycles % 15 == 0:
                        yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v1/sessions/{session_id}/state")
    async def session_state(request: Request, session_id: str):
        _, session = owner_session(request, session_id)
        latest_run_rows = db.runs_for_session(session_id, owner_id=session["owner_id"], limit=1)
        return {
            "session": session,
            "latest_run": latest_run_rows[0] if latest_run_rows else None,
            "learning": LearningWorkspace(settings.workspace_dir, session_id).snapshot(),
            "checkpoint": db.latest_checkpoint(session_id),
            "today_plan": db.get_daily_plan(session_id, daily.local_today().isoformat()),
            "today_review": db.get_daily_review(session_id, daily.local_today().isoformat()),
        }

    @app.get("/api/v1/sessions/{session_id}/runs")
    async def session_runs(request: Request, session_id: str, limit: int = Query(100, ge=1, le=500)):
        user, _ = owner_session(request, session_id)
        return {"runs": db.runs_for_session(session_id, owner_id=user["id"], limit=limit)}

    @app.get("/api/v1/sessions/{session_id}/activity")
    async def session_activity(request: Request, session_id: str, limit: int = Query(100, ge=1, le=500)):
        user, _ = owner_session(request, session_id)
        return {
            "events": db.recent_events(session_id, limit=limit),
            "runs": db.runs_for_session(session_id, owner_id=user["id"], limit=min(limit, 100)),
        }

    @app.get("/api/v1/runs/{run_id}")
    async def run_detail(request: Request, run_id: str):
        user = current_user(request)
        run = db.get_run_for_owner(run_id, user["id"])
        if run is None:
            raise HTTPException(404, "run not found")
        return run

    @app.get("/api/v1/runs/{run_id}/trace")
    async def run_trace(request: Request, run_id: str):
        user = current_user(request)
        run = db.get_run_for_owner(run_id, user["id"])
        if run is None:
            raise HTTPException(404, "run not found")
        return {
            "run": run,
            "events": db.events_for_run(run_id),
            "artifacts": db.agent_artifacts_for_run(run_id, owner_id=user["id"]),
            "model_calls": db.model_calls_for_run(run_id, owner_id=user["id"]),
        }

    @app.get("/api/v1/sessions/{session_id}/agent-status")
    async def agent_status(request: Request, session_id: str, limit: int = Query(20, ge=1, le=100)):
        user, session = owner_session(request, session_id)
        runs = db.agent_runs_for_session(session_id, owner_id=user["id"], limit=limit)
        return {
            "session_id": session_id,
            "session_status": session["status"],
            "active_run_id": session.get("current_run_id"),
            "runs": runs,
            "latest": runs[0] if runs else None,
        }

    @app.get("/api/v1/plans/{session_id}/today")
    async def today_plan(request: Request, session_id: str, force: bool = False):
        owner_session(request, session_id)
        plan = await daily.generate_daily_plan(session_id, force=force)
        return plan.model_dump(mode="json")

    @app.get("/api/v1/plans/{session_id}")
    async def plan_overview(request: Request, session_id: str):
        owner_session(request, session_id)
        rows = daily.plan_rows(session_id)
        completed = sum(1 for row in rows if row["completed"])
        return {
            "rows": rows,
            "progress": {
                "completed": completed,
                "total": len(rows),
                "percent": round(completed / len(rows) * 100) if rows else 0,
            },
        }

    @app.get("/api/v1/plans/{session_id}/tasks/{task_id}")
    async def task_detail(request: Request, session_id: str, task_id: str):
        owner_session(request, session_id)
        try:
            task = daily.get_task(session_id, daily.local_today(), task_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"session_id": session_id, "plan_date": daily.local_today(), "task": task.model_dump(mode="json")}

    @app.post("/api/v1/plans/{session_id}/tasks/{task_id}/start")
    async def start_task(request: Request, session_id: str, task_id: str):
        owner_session(request, session_id)
        try:
            plan = daily.mark_task_started(session_id, daily.local_today(), task_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return plan.model_dump(mode="json")

    @app.post("/api/v1/plans/{session_id}/tasks/{task_id}/result")
    async def record_task_result(
        request: Request, session_id: str, task_id: str, body: TaskResultRequest
    ):
        owner_session(request, session_id)
        try:
            return await service.record_task_result(
                session_id,
                daily.local_today(),
                task_id,
                score=body.score,
                answer=body.answer,
                notes=body.notes,
                error_category=body.error_category,
                completed=body.completed,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/v1/reviews/{session_id}/due")
    async def due_reviews(request: Request, session_id: str):
        owner_session(request, session_id)
        state = LearningWorkspace(settings.workspace_dir, session_id).snapshot()
        return {"reviews": state["due_reviews"]}

    @app.post("/api/v1/reviews/{session_id}/items/{concept_id}/result")
    async def record_review_result(
        request: Request, session_id: str, concept_id: str, body: TaskResultRequest
    ):
        owner_session(request, session_id)
        try:
            return await service.record_review_result(
                session_id,
                concept_id,
                score=body.score,
                answer=body.answer,
                notes=body.notes,
                error_category=body.error_category,
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/v1/plans/{session_id}/tasks/{task_id}/complete")
    async def complete_task(request: Request, session_id: str, task_id: str, body: TaskCompletionRequest):
        owner_session(request, session_id)
        if not body.completed:
            raise HTTPException(400, "only completion is supported")
        try:
            today = daily.local_today()
            current = db.get_daily_plan(session_id, today.isoformat())
            if current and any(item.get("id") == task_id for item in current["payload"].get("tasks", [])):
                plan = daily.mark_task_complete(session_id, today, task_id)
            else:
                workspace = LearningWorkspace(settings.workspace_dir, session_id)
                workspace.mark_stage_completed(task_id)
                if current:
                    saved = DailyPlan.model_validate(current["payload"])
                    plan = saved.model_copy(
                        update={
                            "tasks": [
                                task.model_copy(update={"completed": True})
                                if task.stage_id == task_id
                                else task
                                for task in saved.tasks
                            ]
                        }
                    )
                    db.save_daily_plan(plan)
                else:
                    plan = await daily.generate_daily_plan(session_id, today)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return plan.model_dump(mode="json")

    @app.get("/api/v1/reviews/{session_id}/today")
    async def today_review(request: Request, session_id: str, force: bool = False):
        owner_session(request, session_id)
        review = await daily.generate_review(session_id, force=force)
        return review.model_dump(mode="json")

    @app.get("/api/v1/notifications/settings/{session_id}")
    async def notification_settings(request: Request, session_id: str):
        owner_session(request, session_id)
        return db.get_notification_settings(session_id) or {
            "session_id": session_id,
            "email": "",
            "enabled": False,
            "timezone": settings.notification_timezone,
            "morning_time": settings.notification_morning_time,
            "evening_time": settings.notification_evening_time,
        }

    @app.put("/api/v1/notifications/settings/{session_id}")
    async def update_notification_settings(request: Request, session_id: str, body: NotificationSettingsRequest):
        owner_session(request, session_id)
        current = db.get_notification_settings(session_id)
        requested_enabled = body.enabled
        effective_enabled = body.enabled and bool(current and current.get("verified_at"))
        return db.save_notification_settings(
            session_id,
            email=body.email.strip(),
            enabled=effective_enabled,
            timezone=body.timezone,
            morning_time=body.morning_time,
            evening_time=body.evening_time,
        ) | {
            "activation_required": requested_enabled and not effective_enabled,
            "message": "请先发送成功的测试邮件后再启用定时提醒。"
            if requested_enabled and not effective_enabled
            else "提醒设置已保存。",
        }

    @app.post("/api/v1/notifications/test/{session_id}")
    async def test_notification(request: Request, session_id: str):
        owner_session(request, session_id)
        setting = db.get_notification_settings(session_id)
        if not setting or not setting.get("email"):
            raise HTTPException(409, "notification email is not configured")
        try:
            sent = await asyncio.to_thread(
                mailer.send,
                recipient=setting["email"],
                subject="LearningLoop 邮件测试",
                text="LearningLoop 邮件提醒配置成功。",
                html="<p>LearningLoop 邮件提醒配置成功。</p>",
            )
        except MailDeliveryError as exc:
            raise HTTPException(502, f"SMTP 发送失败：{exc}") from exc
        if sent.get("delivery_mode") == "smtp":
            db.mark_notification_verified(session_id)
        return sent

    @app.get("/api/v1/notifications/deliveries")
    async def notification_deliveries(request: Request, session_id: str | None = None, limit: int = Query(100, ge=1, le=1_000)):
        user = current_user(request)
        if session_id:
            owner_session(request, session_id)
        return {"deliveries": db.notification_deliveries(session_id=session_id, limit=limit, owner_id=user["id"])}

    @app.get("/api/v1/actions/pending")
    async def pending_actions(request: Request, session_id: str | None = None):
        user = current_user(request)
        if session_id:
            owner_session(request, session_id)
        return {"actions": db.pending_actions(session_id, owner_id=user["id"])}

    @app.get("/api/v1/actions/{action_id}")
    async def action_detail(request: Request, action_id: str):
        user = current_user(request)
        action = db.get_action(action_id, owner_id=user["id"])
        if action is None:
            raise HTTPException(404, "action not found")
        return action

    @app.post("/api/v1/actions/{action_id}/decision")
    async def action_decision(request: Request, action_id: str, body: ActionDecisionRequest):
        user = current_user(request)
        if db.get_action(action_id, owner_id=user["id"]) is None:
            raise HTTPException(404, "action not found")
        try:
            return await service.decide_action(action_id, body.decision, body.message)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/v1/approvals/{approval_id}")
    async def decide_approval(request: Request, approval_id: str, body: ApprovalDecision):
        user = current_user(request)
        approval = db.get_approval(approval_id)
        if approval is None or db.get_session_for_owner(approval["session_id"], user["id"]) is None:
            raise HTTPException(404, "approval not found")
        try:
            decision = ActionDecision.EXECUTE if body.decision == "approve" else ActionDecision.REJECT
            return await service.decide_action(approval_id, decision, body.message)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/v1/usage")
    async def usage(request: Request, session_id: str | None = None, day: str | None = None):
        user = current_user(request)
        if session_id:
            owner_session(request, session_id)
        rows = db.usage_rows(session_id=session_id, day=day, owner_id=user["id"])
        return aggregate_usage(rows).model_dump(mode="json")

    @app.get("/api/v1/usage/agents")
    async def usage_agents(request: Request, session_id: str | None = None):
        user = current_user(request)
        if session_id:
            owner_session(request, session_id)
        return {
            "agents": db.usage_by_agent_role(session_id=session_id, owner_id=user["id"])
        }

    @app.get("/api/v1/usage/calls")
    async def usage_calls(request: Request, session_id: str | None = None, limit: int = Query(100, ge=1, le=1_000)):
        user = current_user(request)
        if session_id:
            owner_session(request, session_id)
        return {"calls": db.model_calls(session_id=session_id, limit=limit, owner_id=user["id"])}

    @app.get("/api/v1/usage/export")
    async def usage_export(request: Request, format: Literal["csv", "json"] = "json", session_id: str | None = None):
        user = current_user(request)
        if session_id:
            owner_session(request, session_id)
        rows = db.model_calls(session_id=session_id, limit=100_000, owner_id=user["id"])
        if format == "json":
            return JSONResponse(rows)
        output = io.StringIO(newline="")
        if rows:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=learningloop-usage.csv"},
        )

    @app.get("/health")
    async def health():
        checked = {
            f"{row['provider_alias']}_{row['model_route']}": row
            for row in db.fetch_all("SELECT * FROM provider_capabilities")
        }
        providers = {
            f"{alias}_{route}": {
                "configured": bool(provider.flash_key if route == "flash" else provider.pro_key),
                "model": provider.flash_model if route == "flash" else provider.pro_model,
                "capabilities": checked.get(f"{alias}_{route}"),
            }
            for alias, provider in settings.providers.items()
            for route in ("flash", "pro")
        }
        return {"status": "ok", "version": __version__, "providers": providers}

    return app
