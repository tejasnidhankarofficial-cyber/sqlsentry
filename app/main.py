"""FastAPI service: login, ask, history, usage."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import (LoginThrottle, check_password, make_token, normalize_username,
                      verify_token)
from app.config import Settings, get_settings
from app.ratelimit import DailyLimiter, RateLimitExceeded


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    daily_limit: int
    remaining_today: int


class AskRequest(BaseModel):
    question: str = Field(min_length=3)


class AskResponse(BaseModel):
    status: str                      # ok | cannot_answer | blocked | error
    question: str
    sql: str | None = None
    columns: list[str] = []
    rows: list[list] = []
    row_count: int = 0
    truncated: bool = False
    summary: str | None = None
    message: str | None = None
    attempts: int = 0
    latency_ms: int = 0
    remaining_today: int = 0


def create_app(pipeline=None, settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = settings or get_settings()
        pipe = pipeline
        if pipe is None:
            from app.pipeline import Pipeline  # heavy import: only when actually serving
            pipe = Pipeline(cfg)
        app.state.settings, app.state.pipeline = cfg, pipe
        app.state.limiter = DailyLimiter(pipe.audit.count_today, cfg.daily_limit_per_user,
                                         cfg.daily_limit_global)
        app.state.throttle = LoginThrottle()
        yield

    app = FastAPI(title="SQL QnA Assistant", lifespan=lifespan)

    def current_user(request: Request, authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Missing bearer token.")
        user = verify_token(authorization[7:].strip(),
                            request.app.state.settings.auth_secret.get_secret_value())
        if user is None:
            raise HTTPException(401, "Invalid or expired token. Please log in again.")
        return user

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/login", response_model=LoginResponse)
    def login(body: LoginRequest, request: Request):
        cfg: Settings = request.app.state.settings
        client = request.client.host if request.client else "unknown"
        throttle: LoginThrottle = request.app.state.throttle
        if throttle.blocked(client):
            raise HTTPException(429, "Too many failed logins. Wait a few minutes and retry.")

        username = normalize_username(body.username)
        allowed = cfg.allowed_user_set
        ok = (check_password(body.password, cfg.app_password.get_secret_value())
              and username is not None and (not allowed or username in allowed))
        if not ok:
            throttle.record_failure(client)
            # One message for every failure reason, so it leaks nothing about usernames.
            raise HTTPException(401, "Invalid username or password.")

        token = make_token(username, cfg.auth_secret.get_secret_value(), cfg.token_ttl_hours * 3600)
        return LoginResponse(token=token, username=username, daily_limit=cfg.daily_limit_per_user,
                             remaining_today=request.app.state.limiter.remaining(username))

    @app.post("/ask", response_model=AskResponse)
    def ask(body: AskRequest, request: Request, user: str = Depends(current_user)):
        cfg: Settings = request.app.state.settings
        question = body.question.strip()
        if len(question) > cfg.max_question_chars:
            raise HTTPException(422, f"Question is longer than {cfg.max_question_chars} characters.")
        limiter: DailyLimiter = request.app.state.limiter
        try:
            with limiter.reserve(user):
                ans = request.app.state.pipeline.ask(question, username=user)
        except RateLimitExceeded as e:
            raise HTTPException(429, e.message)

        r = ans.result
        return AskResponse(
            status=ans.status, question=question, sql=ans.sql,
            columns=r.columns if r else [], rows=r.rows if r else [],
            row_count=len(r.rows) if r else 0, truncated=bool(r and r.truncated),
            summary=ans.summary, message=ans.message, attempts=ans.attempts,
            latency_ms=ans.latency_ms, remaining_today=limiter.remaining(user),
        )

    @app.get("/usage")
    def usage(request: Request, user: str = Depends(current_user)):
        cfg: Settings = request.app.state.settings
        return {"username": user, "daily_limit": cfg.daily_limit_per_user,
                "remaining_today": request.app.state.limiter.remaining(user)}

    @app.get("/history")
    def history(request: Request, limit: int = 20, _: str = Depends(current_user)):
        """Recent questions from the whole team (shared view for discussion)."""
        rows = request.app.state.pipeline.audit.recent(max(1, min(limit, 100)))
        return [{**r, "created_at": r["created_at"].isoformat()} for r in rows]

    return app


app = create_app()
