"""
Check KB document expiry dates against manifest.yaml.

Exit codes:
  0 — all docs valid (or only warnings)
  1 — one or more documents already expired

Usage:
    python -m ingest.check_vigencia
    python -m ingest.check_vigencia --warn-days 60
"""
import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from orchestrator.config import get_settings

log = logging.getLogger("check_vigencia")
settings = get_settings()

DEFAULT_WARN_DAYS = 30


def check_vigencia(kb_path: str = None, warn_days: int = DEFAULT_WARN_DAYS) -> dict:
    """
    Parse manifest.yaml and classify docs as expired / expiring_soon / ok.
    Returns dict with those three lists plus optional 'error' key.
    """
    kb_path = kb_path or settings.kb_path
    manifest_path = os.path.join(kb_path, "manifest.yaml")

    if not os.path.exists(manifest_path):
        return {
            "expired": [], "expiring_soon": [], "ok": [],
            "error": f"manifest.yaml no encontrado en {manifest_path}",
        }

    with open(manifest_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    docs = data.get("documentos", [])
    today = date.today()
    threshold = today + timedelta(days=warn_days)

    expired, expiring_soon, ok = [], [], []

    for doc in docs:
        vigencia = doc.get("vigencia")
        if not vigencia:
            ok.append({"id": doc.get("id"), "nombre": doc.get("nombre")})
            continue
        try:
            exp_date = date.fromisoformat(str(vigencia)[:10])
        except ValueError:
            ok.append({"id": doc.get("id"), "nombre": doc.get("nombre")})
            continue

        doc_info = {
            "id": doc.get("id"),
            "nombre": doc.get("nombre"),
            "vigencia": str(vigencia),
            "aprobador": doc.get("aprobador"),
            "dias_restantes": (exp_date - today).days,
        }

        if exp_date < today:
            expired.append(doc_info)
        elif exp_date <= threshold:
            expiring_soon.append(doc_info)
        else:
            ok.append({"id": doc.get("id"), "nombre": doc.get("nombre")})

    return {"expired": expired, "expiring_soon": expiring_soon, "ok": ok}


def log_vigencia_warnings(kb_path: str = None, warn_days: int = DEFAULT_WARN_DAYS):
    """Log warnings for expired/expiring docs. Safe to call at app startup."""
    result = check_vigencia(kb_path, warn_days)

    if result.get("error"):
        log.warning(f"[KB Vigencia] {result['error']}")
        return result

    for doc in result.get("expired", []):
        log.error(
            f"[KB Vigencia] EXPIRADO: [{doc['id']}] '{doc['nombre']}' — "
            f"venció {doc['vigencia']} (hace {-doc['dias_restantes']} días). "
            f"Aprobador: {doc.get('aprobador', '?')}"
        )

    for doc in result.get("expiring_soon", []):
        log.warning(
            f"[KB Vigencia] PRÓXIMO A VENCER: [{doc['id']}] '{doc['nombre']}' — "
            f"vence en {doc['dias_restantes']} días ({doc['vigencia']}). "
            f"Aprobador: {doc.get('aprobador', '?')}"
        )

    total_issues = len(result.get("expired", [])) + len(result.get("expiring_soon", []))
    if total_issues == 0:
        log.info(f"[KB Vigencia] OK — {len(result.get('ok', []))} documentos vigentes.")

    return result


def main():
    parser = argparse.ArgumentParser(description="Verifica fechas de vigencia de la KB Icesi")
    parser.add_argument("--warn-days", type=int, default=DEFAULT_WARN_DAYS,
                        help=f"Días de anticipación para alertar (default: {DEFAULT_WARN_DAYS})")
    parser.add_argument("--path", default=None, help="Ruta de la KB (default: settings.kb_path)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = check_vigencia(kb_path=args.path, warn_days=args.warn_days)

    if result.get("error"):
        print(f"Error: {result['error']}")
        sys.exit(2)

    expired = result.get("expired", [])
    expiring_soon = result.get("expiring_soon", [])

    if expired:
        print(f"\n🔴 EXPIRADOS ({len(expired)}):")
        for doc in expired:
            print(f"  [{doc['id']}] {doc['nombre']}")
            print(f"    Venció: {doc['vigencia']} (hace {-doc['dias_restantes']} días)")
            print(f"    Aprobador: {doc.get('aprobador', '?')}")

    if expiring_soon:
        print(f"\n🟡 PRÓXIMOS A VENCER en {args.warn_days} días ({len(expiring_soon)}):")
        for doc in expiring_soon:
            print(f"  [{doc['id']}] {doc['nombre']}")
            print(f"    Vence: {doc['vigencia']} ({doc['dias_restantes']} días restantes)")
            print(f"    Aprobador: {doc.get('aprobador', '?')}")

    if not expired and not expiring_soon:
        print(f"✅ Todos los documentos KB vigentes ({len(result.get('ok', []))} docs).")
        sys.exit(0)

    sys.exit(1 if expired else 0)


if __name__ == "__main__":
    main()
