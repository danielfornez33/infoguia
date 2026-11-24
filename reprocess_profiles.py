#!/usr/bin/env python3
"""
Script para re-procesar perfiles existentes y extraer datos faltantes:
- Descripción completa (del modal #fullDescription)
- Categorías específicas del perfil
- Dirección completa de todas las sucursales
- Redes sociales reales
"""

import sys
import time
from datetime import datetime

from app import db, queue
from app.adapters import get_adapter_for_url
from app.anomaly import analyze_response
from app.config import settings
from app.events import info as log_info
from app.events import warn as log_warn
from app.ratelimit import wait_for_slot
from app.redis_client import r
from app.rotation import build_browser_headers, get_ua_rotator
from app.upsert import (
    upsert_branch,
    upsert_category,
    upsert_company,
    upsert_company_category,
    upsert_contact,
    upsert_product,
    upsert_social,
)

import httpx


def build_client():
    return httpx.Client(
        timeout=settings.http_timeout,
        follow_redirects=True,
    )


def fetch_profile(url: str, client: httpx.Client):
    headers = build_browser_headers()
    if settings.rotate_user_agents:
        headers["User-Agent"] = get_ua_rotator().get_user_agent()
    else:
        headers["User-Agent"] = settings.crawl_user_agent

    wait_for_slot("infoguia.com")
    response = client.get(url, headers=headers)

    if response.status_code in (403, 429):
        raise Exception(f"HTTP {response.status_code}")
    if response.status_code == 304:
        return None, 304

    response.raise_for_status()
    return response, response.status_code


def reprocess_profiles(limit: int = 100, batch_size: int = 10):
    client = build_client()

    # Obtener empresas que necesitan actualización
    companies = db.query(
        """
        SELECT c.clte, c.source_url, c.description, c.name
        FROM company c
        WHERE c.source_url IS NOT NULL 
          AND c.source_url != ''
          AND (c.description IS NULL OR c.description = '')
        ORDER BY c.last_seen DESC
        LIMIT %s
        """,
        (limit,),
    )

    print(f"📋 Empresas a procesar: {len(companies)}")

    processed = 0
    updated = 0
    errors = 0

    for i, company in enumerate(companies):
        clte = company["clte"]
        profile_url = company["source_url"]
        current_name = company["name"]

        if not profile_url:
            print(f"  ⚠️  [{i+1}/{len(companies)}] CLTE {clte}: Sin URL de perfil")
            continue

        try:
            print(f"  🔄 [{i+1}/{len(companies)}] Procesando {current_name} (CLTE {clte})...")

            response, status_code = fetch_profile(profile_url, client)

            if status_code == 304:
                print(f"    ⏭️  Sin cambios (304)")
                processed += 1
                continue

            adapter = get_adapter_for_url(profile_url)
            data = adapter.parse_profile(response.text, profile_url)

            # Verificar que tenemos datos nuevos
            has_new_data = False

            with db.cursor() as cur:
                # Actualizar descripción si está vacía y tenemos nueva
                if (not company["description"] or company["description"] == "") and data["description"]:
                    has_new_data = True
                    print(f"    ✅ Descripción: {data['description'][:60]}...")

                # Actualizar categorías si hay nuevas
                if data["categories"]:
                    has_new_data = True
                    for category in data["categories"]:
                        print(f"    📁 Categoría: {category['name']}")
                        upsert_category(cur, category["cat_id"], category["name"])
                        upsert_company_category(cur, clte, category["cat_id"])

                # Actualizar empresa con nueva descripción
                if has_new_data:
                    upsert_company(
                        cur,
                        {
                            "clte": clte,
                            "name": data["name"] or current_name,
                            "description": data["description"] or company["description"],
                            "verified": data["verified"],
                            "rating_pct": data["rating_pct"],
                            "store_url": data["store_url"],
                            "profile_url": profile_url,
                        },
                    )

                    # Actualizar sucursales con datos completos
                    for branch in data["branches"]:
                        upsert_branch(cur, clte, branch)
                        for contact in branch["contacts"]:
                            upsert_contact(cur, clte, branch["branch_key"], contact["type"], contact["value"])

                    # Actualizar redes sociales
                    for social in data["socials"]:
                        upsert_social(cur, clte, social["network"], social["url"])

                    # Actualizar productos si hay
                    for product in data["products"]:
                        upsert_product(cur, clte, product)

                processed += 1
                if has_new_data:
                    updated += 1

            # Rate limiting
            time.sleep(2)

        except Exception as e:
            print(f"    ❌ Error: {str(e)[:100]}")
            errors += 1
            time.sleep(5)

    print(f"\n✅ Completado:")
    print(f"   Procesados: {processed}")
    print(f"   Actualizados: {updated}")
    print(f"   Errores: {errors}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    print(f"🚀 Re-procesando hasta {limit} perfiles...")
    reprocess_profiles(limit=limit)
