from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from retriqs.api.storage_paths import resolve_storage_paths
from retriqs.utils import logger


OPENAI_CODEX_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
OPENAI_CODEX_REDIRECT_HOST = "localhost"
OPENAI_CODEX_REDIRECT_PORT = 1455
OPENAI_CODEX_REDIRECT_PATH = "/auth/callback"
OPENAI_CODEX_REDIRECT_URI = (
    f"http://{OPENAI_CODEX_REDIRECT_HOST}:{OPENAI_CODEX_REDIRECT_PORT}"
    f"{OPENAI_CODEX_REDIRECT_PATH}"
)
OPENAI_CODEX_OAUTH_SCOPES = "openid email profile offline_access"
# Inferred from widely used Codex/OpenClaw OAuth flows. Keep overrideable for safety.
OPENAI_CODEX_CLIENT_ID = os.getenv(
    "OPENAI_CODEX_CLIENT_ID", "app_EMoamEEZ73f0CkXaXp7hrann"
)
OPENAI_CODEX_ORIGINATOR = os.getenv("OPENAI_CODEX_ORIGINATOR", "codex_cli")


def _urlsafe_b64_no_padding(raw_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")


def _pkce_challenge(verifier: str) -> str:
    return _urlsafe_b64_no_padding(hashlib.sha256(verifier.encode("utf-8")).digest())


def _decode_jwt_payload_unverified(token: str) -> dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding)
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


@dataclass
class OpenAICodexTokenRecord:
    access_token: str
    refresh_token: str
    expires_at: float
    account_id: str | None = None
    email: str | None = None

    @property
    def expires_at_iso(self) -> str:
        return datetime.fromtimestamp(
            self.expires_at, tz=timezone.utc
        ).isoformat()

    def is_expired(self, skew_seconds: int = 60) -> bool:
        return time.time() >= (self.expires_at - skew_seconds)


@dataclass
class PendingOpenAICodexAuthFlow:
    state: str
    code_verifier: str
    status: str = "pending"
    authorization_url: str | None = None
    error: str | None = None
    started_at: float = 0.0
    completed_at: float | None = None


class OpenAICodexAuthManager:
    def __init__(self) -> None:
        storage_root = Path(resolve_storage_paths().rag_root)
        storage_root.mkdir(parents=True, exist_ok=True)
        self._token_path = storage_root / "openai_codex_auth.json"
        self._lock = threading.RLock()
        self._pending_flows: dict[str, PendingOpenAICodexAuthFlow] = {}
        self._callback_server: ThreadingHTTPServer | None = None
        self._callback_thread: threading.Thread | None = None

    def _load_token_record_unlocked(self) -> OpenAICodexTokenRecord | None:
        if not self._token_path.exists():
            return None
        payload = json.loads(self._token_path.read_text(encoding="utf-8"))
        return OpenAICodexTokenRecord(**payload)

    def _save_token_record_unlocked(self, record: OpenAICodexTokenRecord) -> None:
        self._token_path.write_text(
            json.dumps(asdict(record), indent=2), encoding="utf-8"
        )

    def clear_token(self) -> None:
        with self._lock:
            if self._token_path.exists():
                self._token_path.unlink()

    def get_connection_status(self) -> dict[str, Any]:
        with self._lock:
            record = self._load_token_record_unlocked()
            if not record:
                return {"connected": False}
            return {
                "connected": True,
                "account_id": record.account_id,
                "email": record.email,
                "expires_at": record.expires_at_iso,
                "expired": record.is_expired(),
            }

    def _start_callback_server_unlocked(self) -> None:
        if self._callback_server is not None:
            return

        manager = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != OPENAI_CODEX_REDIRECT_PATH:
                    self.send_response(404)
                    self.end_headers()
                    return

                params = parse_qs(parsed.query)
                state = (params.get("state") or [None])[0]
                code = (params.get("code") or [None])[0]
                error = (params.get("error") or [None])[0]
                error_description = (params.get("error_description") or [None])[0]

                if state:
                    manager._handle_callback_result(
                        state=state,
                        code=code,
                        error=error,
                        error_description=error_description,
                    )

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    (
                        "<html><body><script>window.close && window.close();</script>"
                        "<p>OpenAI authentication received. You can return to Retriqs.</p>"
                        "</body></html>"
                    ).encode("utf-8")
                )

            def log_message(self, format: str, *args: Any) -> None:
                return

        try:
            self._callback_server = ThreadingHTTPServer(
                (OPENAI_CODEX_REDIRECT_HOST, OPENAI_CODEX_REDIRECT_PORT), CallbackHandler
            )
        except OSError as exc:
            raise RuntimeError(
                "OpenAI Codex auth callback server could not start on "
                f"{OPENAI_CODEX_REDIRECT_HOST}:{OPENAI_CODEX_REDIRECT_PORT}"
            ) from exc
        self._callback_thread = threading.Thread(
            target=self._callback_server.serve_forever,
            name="openai-codex-auth-callback",
            daemon=True,
        )
        self._callback_thread.start()

    def start_login(self) -> dict[str, Any]:
        with self._lock:
            self._start_callback_server_unlocked()

            state = secrets.token_hex(16)
            verifier = _urlsafe_b64_no_padding(secrets.token_bytes(32))
            challenge = _pkce_challenge(verifier)
            query = {
                "client_id": OPENAI_CODEX_CLIENT_ID,
                "redirect_uri": OPENAI_CODEX_REDIRECT_URI,
                "response_type": "code",
                "scope": OPENAI_CODEX_OAUTH_SCOPES,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "prompt": "login",
                "codex_cli_simplified_flow": "true",
                "id_token_add_organizations": "true",
                "originator": OPENAI_CODEX_ORIGINATOR,
            }
            authorization_url = (
                f"{OPENAI_CODEX_AUTHORIZE_URL}?{urlencode(query, doseq=True)}"
            )
            self._pending_flows[state] = PendingOpenAICodexAuthFlow(
                state=state,
                code_verifier=verifier,
                authorization_url=authorization_url,
                started_at=time.time(),
            )
            return {
                "state": state,
                "authorization_url": authorization_url,
                "redirect_uri": OPENAI_CODEX_REDIRECT_URI,
            }

    def get_flow_status(self, state: str) -> dict[str, Any]:
        with self._lock:
            flow = self._pending_flows.get(state)
            if not flow:
                return {"state": state, "status": "unknown"}
            payload = {
                "state": flow.state,
                "status": flow.status,
                "error": flow.error,
                "completed_at": flow.completed_at,
            }
            if flow.status == "completed":
                payload["connection"] = self.get_connection_status()
            return payload

    def _exchange_code_for_tokens(self, code: str, code_verifier: str) -> dict[str, Any]:
        response = httpx.post(
            OPENAI_CODEX_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": OPENAI_CODEX_CLIENT_ID,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": OPENAI_CODEX_REDIRECT_URI,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    def _refresh_token_unlocked(self, refresh_token: str) -> OpenAICodexTokenRecord:
        response = httpx.post(
            OPENAI_CODEX_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": OPENAI_CODEX_CLIENT_ID,
                "refresh_token": refresh_token,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        return self._token_record_from_token_payload(payload, fallback_refresh=refresh_token)

    def _token_record_from_token_payload(
        self, payload: dict[str, Any], fallback_refresh: str | None = None
    ) -> OpenAICodexTokenRecord:
        access_token = str(payload["access_token"])
        refresh_token = str(payload.get("refresh_token") or fallback_refresh or "")
        expires_in = int(payload.get("expires_in") or 3600)
        jwt_payload = _decode_jwt_payload_unverified(access_token)
        account_id = (
            jwt_payload.get("account_id")
            or jwt_payload.get("accountId")
            or jwt_payload.get("sub")
        )
        email = jwt_payload.get("email")
        return OpenAICodexTokenRecord(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + expires_in,
            account_id=str(account_id) if account_id else None,
            email=str(email) if email else None,
        )

    def _handle_callback_result(
        self,
        *,
        state: str,
        code: str | None,
        error: str | None,
        error_description: str | None,
    ) -> None:
        with self._lock:
            flow = self._pending_flows.get(state)
            if not flow:
                return
            if error:
                flow.status = "error"
                flow.error = error_description or error
                flow.completed_at = time.time()
                return
            if not code:
                flow.status = "error"
                flow.error = "Missing authorization code"
                flow.completed_at = time.time()
                return

        try:
            token_payload = self._exchange_code_for_tokens(code, flow.code_verifier)
            record = self._token_record_from_token_payload(token_payload)
            with self._lock:
                self._save_token_record_unlocked(record)
                flow.status = "completed"
                flow.error = None
                flow.completed_at = time.time()
        except Exception as exc:
            logger.exception("OpenAI Codex OAuth callback handling failed")
            with self._lock:
                flow.status = "error"
                flow.error = str(exc)
                flow.completed_at = time.time()

    def get_access_token(self) -> str:
        with self._lock:
            record = self._load_token_record_unlocked()
            if not record:
                raise RuntimeError("OpenAI Codex is not connected")
            if not record.is_expired():
                return record.access_token
            if not record.refresh_token:
                raise RuntimeError("OpenAI Codex token expired and no refresh token is available")
            refreshed = self._refresh_token_unlocked(record.refresh_token)
            self._save_token_record_unlocked(refreshed)
            return refreshed.access_token


_manager: OpenAICodexAuthManager | None = None


def get_openai_codex_auth_manager() -> OpenAICodexAuthManager:
    global _manager
    if _manager is None:
        _manager = OpenAICodexAuthManager()
    return _manager
