"""
Anti-corruption CRM adapter.
Exposes a uniform interface: get_lead, update_lead, create_task.
Backend is selected via CRM_BACKEND env var: mock | hubspot | salesforce | sheets
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

import httpx

from .config import get_settings

settings = get_settings()
log = logging.getLogger(__name__)


# ── Circuit breaker ────────────────────────────────────────────────────────────

class _CircuitBreaker:
    """Simple circuit breaker: opens after failure_threshold failures,
    resets after reset_timeout seconds."""

    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._opened_at: Optional[float] = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.reset_timeout:
            log.info("[CRM] Circuit breaker resetting after timeout.")
            self._failures = 0
            self._opened_at = None
            return False
        return True

    def record_success(self):
        self._failures = 0
        self._opened_at = None

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.failure_threshold:
            if self._opened_at is None:
                log.warning(
                    f"[CRM] Circuit breaker OPEN after {self._failures} failures. "
                    f"Will retry in {self.reset_timeout}s."
                )
                self._opened_at = time.monotonic()


_hubspot_circuit = _CircuitBreaker()


async def _hubspot_request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """Execute an HTTP request against HubSpot with exponential backoff + circuit breaker."""
    if _hubspot_circuit.is_open:
        raise RuntimeError("[CRM] Circuit breaker is open — skipping HubSpot request.")

    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(3):
        try:
            resp = await client.request(method, url, **kwargs)
            _hubspot_circuit.record_success()
            return resp
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            _hubspot_circuit.record_failure()
            if attempt < 2:
                delay = 2 ** attempt  # 1s, 2s
                log.warning(f"[CRM] HubSpot attempt {attempt + 1} failed ({exc}). Retrying in {delay}s.")
                await asyncio.sleep(delay)
    raise last_exc


class CRMAdapter:
    async def get_lead(self, phone_hash: str) -> Optional[dict]:
        raise NotImplementedError

    async def update_lead(self, lead_id: str, fields: dict) -> bool:
        raise NotImplementedError

    async def create_task(self, task: dict) -> str:
        raise NotImplementedError


# ── Mock CRM (development / testing) ──────────────────────────────────────────

_MOCK_STORE: dict[str, dict] = {}
_TASK_COUNTER = 0


class MockCRM(CRMAdapter):
    async def get_lead(self, phone_hash: str) -> Optional[dict]:
        return _MOCK_STORE.get(phone_hash)

    async def update_lead(self, lead_id: str, fields: dict) -> bool:
        for k, v in _MOCK_STORE.items():
            if v.get("lead_id") == lead_id:
                _MOCK_STORE[k].update(fields)
                return True
        return False

    async def create_task(self, task: dict) -> str:
        global _TASK_COUNTER
        _TASK_COUNTER += 1
        task_id = f"task_{_TASK_COUNTER}"
        print(f"[MockCRM] Nueva tarea {task_id}: {json.dumps(task, ensure_ascii=False, indent=2)}")
        return task_id

    def seed_lead(self, phone_hash: str, data: dict):
        """Helper for tests."""
        _MOCK_STORE[phone_hash] = data


# ── HubSpot CRM ────────────────────────────────────────────────────────────────

class HubSpotCRM(CRMAdapter):
    BASE = "https://api.hubapi.com"

    def _headers(self):
        return {
            "Authorization": f"Bearer {settings.hubspot_api_key}",
            "Content-Type": "application/json",
        }

    async def get_lead(self, phone_hash: str) -> Optional[dict]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await _hubspot_request(
                    client, "POST",
                    f"{self.BASE}/crm/v3/objects/contacts/search",
                    headers=self._headers(),
                    json={
                        "filterGroups": [{
                            "filters": [{
                                "propertyName": "phone_hash_icesi",
                                "operator": "EQ",
                                "value": phone_hash,
                            }]
                        }],
                        "properties": [
                            "firstname", "phone_hash_icesi", "hs_lead_status",
                            "programa_interes", "segmento_icesi",
                        ],
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    if results:
                        props = results[0]["properties"]
                        return {
                            "lead_id": results[0]["id"],
                            "nombre": props.get("firstname"),
                            "segmento": props.get("segmento_icesi", "indefinido"),
                            "programa_interes": props.get("programa_interes"),
                            "estado_funnel": props.get("hs_lead_status", "lead"),
                        }
        except Exception as exc:
            log.error(f"[HubSpot] get_lead failed: {exc}")
        return None

    async def update_lead(self, lead_id: str, fields: dict) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await _hubspot_request(
                    client, "PATCH",
                    f"{self.BASE}/crm/v3/objects/contacts/{lead_id}",
                    headers=self._headers(),
                    json={"properties": fields},
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception as exc:
            log.error(f"[HubSpot] update_lead failed: {exc}")
            return False

    async def create_task(self, task: dict) -> str:
        try:
            async with httpx.AsyncClient() as client:
                resp = await _hubspot_request(
                    client, "POST",
                    f"{self.BASE}/crm/v3/objects/tasks",
                    headers=self._headers(),
                    json={
                        "properties": {
                            "hs_task_subject": task.get("titulo", "Escalamiento IA"),
                            "hs_task_body": task.get("descripcion", ""),
                            "hs_task_priority": task.get("prioridad", "MEDIUM").upper(),
                            "hs_timestamp": datetime.utcnow().isoformat() + "Z",
                        },
                        "associations": [{
                            "to": {"id": task.get("lead_id")},
                            "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 204}],
                        }] if task.get("lead_id") else [],
                    },
                    timeout=10,
                )
                if resp.status_code == 201:
                    return resp.json()["id"]
        except Exception as exc:
            log.error(f"[HubSpot] create_task failed: {exc}")
        return "error"


# ── Factory ────────────────────────────────────────────────────────────────────

_crm_instance: Optional[CRMAdapter] = None


def get_crm() -> CRMAdapter:
    global _crm_instance
    if _crm_instance is None:
        backend = settings.crm_backend.lower()
        if backend == "hubspot":
            _crm_instance = HubSpotCRM()
        else:
            _crm_instance = MockCRM()
    return _crm_instance
