"""Thin HTTP client for TypeSafe AI's System One endpoint (Jev).

Wire format (see typesafe-sdk ``_core/endpoints.py`` / ``_schemas/models.py``):

    POST {base}/v1/systemone
    {"state": ..., "model": "jev-...", "questions": {name: {"type": ..., ...}}}
    -> {"model": "...", "usage": {...}, "answers": {name: {"type": "choice",
        "choice": "...", "confidence": 0.9, "probabilities": {...}} | ...}}

The official SDK requires Python 3.10+ and pydantic, so this module talks to
the endpoint directly with ``requests``.  It never raises on network/API
errors: robot control code must fall back to "no proposal" instead.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

try:
    import requests
except ImportError:  # pragma: no cover - only on incomplete deployments
    requests = None

DEFAULT_BASE_URL = "https://api.typesafe.ai"
SYSTEM_ONE_PATH = "/v1/systemone"
RETRY_STATUSES = {429, 500, 502, 503, 504, 529}


def normalize_answers(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Flatten a System One response into plain dicts keyed by question name."""
    answers = payload.get("answers") or {}
    result: Dict[str, Dict[str, Any]] = {}
    for name, raw in answers.items():
        if not isinstance(raw, dict):
            continue
        kind = raw.get("type")
        if kind == "choice":
            result[name] = {
                "type": "choice",
                "choice": raw.get("choice"),
                "confidence": float(raw.get("confidence", 0.0)),
                "probabilities": {k: float(v) for k, v in (raw.get("probabilities") or {}).items()},
            }
        elif kind == "noul":
            result[name] = {"type": "noul", "noul": float(raw.get("noul", 0.5))}
        elif kind == "score":
            result[name] = {
                "type": "score",
                "score": float(raw.get("score", 0.0)),
                "confidence": float(raw.get("confidence", 0.0)),
                "probabilities": {str(k): float(v) for k, v in (raw.get("probabilities") or {}).items()},
            }
        # Unknown answer types (future API) are ignored, like the official SDK.
    return result


class JevClient:
    """Calls Jev once per decision; returns normalized answers or None."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 1.5,
        max_retries: int = 1,
        session: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key:
            raise ValueError("TYPESAFE_API_KEY is required")
        if session is None:
            if requests is None:
                raise RuntimeError("requests is required for the Jev client")
            session = requests.Session()
        self.url = base_url.rstrip("/") + SYSTEM_ONE_PATH
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session
        self._sleep = sleep
        self._headers = {
            "Authorization": "Bearer {}".format(api_key),
            "Content-Type": "application/json",
        }
        self.last_error: Optional[str] = None

    def system_one(self, state: Any, questions: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        body = {"state": state, "model": self.model, "questions": questions}
        started = time.monotonic()
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.post(self.url, json=body, headers=self._headers, timeout=self.timeout)
            except Exception as exc:  # timeouts, DNS, connection resets
                self.last_error = "{}: {}".format(type(exc).__name__, exc)
            else:
                if resp.status_code == 200:
                    try:
                        payload = resp.json()
                    except ValueError:
                        self.last_error = "invalid JSON response"
                        return None
                    self.last_error = None
                    return {
                        "answers": normalize_answers(payload),
                        "model": payload.get("model", self.model),
                        "usage": payload.get("usage") or {},
                        "latency_ms": int((time.monotonic() - started) * 1000),
                    }
                self.last_error = "HTTP {}: {}".format(resp.status_code, (resp.text or "")[:200])
                if resp.status_code not in RETRY_STATUSES:
                    return None
            if attempt < self.max_retries:
                self._sleep(0.25 * (2 ** attempt))
        return None
