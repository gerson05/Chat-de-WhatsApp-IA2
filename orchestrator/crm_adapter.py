"""
Anti-corruption CRM adapter.
Exposes a uniform interface: get_lead, update_lead, create_task.
Backend is selected via CRM_BACKEND env var: mock | hubspot | salesforce | sheets
"""
import json
import os
from datetime import datetime
from typing import Optional

import httpx

from .config import get_settings

settings = get_settings()


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
        async with httpx.AsyncClient() as client:
            resp = await client.get(
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
        return None

    async def update_lead(self, lead_id: str, fields: dict) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{self.BASE}/crm/v3/objects/contacts/{lead_id}",
                headers=self._headers(),
                json={"properties": fields},
                timeout=10,
            )
            return resp.status_code == 200

    async def create_task(self, task: dict) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
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
