from .parsers import normalize_email, normalize_name, normalize_phone


def log_change(cur, entity: str, entity_id: str, field: str, old, new) -> None:
    old_text = "" if old is None else str(old)
    new_text = "" if new is None else str(new)
    if old_text == new_text:
        return
    cur.execute(
        """
        INSERT INTO change_log (entity, entity_id, field, old_value, new_value)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (entity, str(entity_id), field, old_text, new_text),
    )


def upsert_company(cur, data: dict) -> None:
    clte = int(data["clte"])
    cur.execute("SELECT * FROM company WHERE clte = %s", (clte,))
    old = cur.fetchone()

    name = data.get("name")
    if not name:
        name = (old or {}).get("name") or ""

    fields = {
        "name": name,
        "name_norm": normalize_name(name),
        "verified": data.get("verified"),
        "description": data.get("description"),
        "rating_pct": data.get("rating_pct"),
        "store_url": data.get("store_url"),
        "source_url": data.get("profile_url") or data.get("source_url"),
        "content_sha": data.get("content_sha"),
    }
    fields = {key: value for key, value in fields.items() if value is not None or key in {"name", "name_norm"}}

    if old is None:
        cur.execute(
            """
            INSERT INTO company
              (clte, name, name_norm, verified, description, rating_pct, store_url,
               source_url, first_seen, last_seen, content_sha)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now(), %s)
            """,
            (
                clte,
                fields.get("name") or "",
                fields.get("name_norm") or "",
                bool(fields.get("verified")),
                fields.get("description"),
                fields.get("rating_pct"),
                fields.get("store_url"),
                fields.get("source_url"),
                fields.get("content_sha"),
            ),
        )
        return

    for key in ("name", "verified", "description", "rating_pct", "store_url"):
        if key in fields:
            log_change(cur, "company", str(clte), key, old.get(key), fields[key])

    assignments = []
    params = []
    for key, value in fields.items():
        assignments.append(f"{key} = %s")
        params.append(value)
    assignments.append("last_seen = now()")
    params.append(clte)
    cur.execute(
        f"UPDATE company SET {', '.join(assignments)} WHERE clte = %s",
        tuple(params),
    )


def upsert_branch(cur, clte: int, branch: dict) -> None:
    branch_key = str(branch.get("branch_key") or "0")
    cur.execute(
        "SELECT * FROM branch WHERE clte = %s AND branch_key = %s",
        (clte, branch_key),
    )
    old = cur.fetchone()

    values = {
        "urbanization": branch.get("urbanization") or "",
        "address": branch.get("address") or "",
        "city": branch.get("city") or "",
        "phones": branch.get("phones") or "",
        "whatsapp": branch.get("whatsapp") or "",
        "email": branch.get("email") or "",
    }
    if old:
        for key, value in values.items():
            if not value and old.get(key):
                values[key] = old[key]

    if old is None:
        cur.execute(
            """
            INSERT INTO branch
              (clte, branch_key, urbanization, address, city, phones, whatsapp, email,
               first_seen, last_seen)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
            """,
            (
                clte,
                branch_key,
                values["urbanization"],
                values["address"],
                values["city"],
                values["phones"],
                values["whatsapp"],
                values["email"],
            ),
        )
    else:
        for key, value in values.items():
            log_change(cur, "branch", f"{clte}:{branch_key}", key, old.get(key), value)
        cur.execute(
            """
            UPDATE branch
            SET urbanization = %s, address = %s, city = %s, phones = %s,
                whatsapp = %s, email = %s, last_seen = now()
            WHERE clte = %s AND branch_key = %s
            """,
            (
                values["urbanization"],
                values["address"],
                values["city"],
                values["phones"],
                values["whatsapp"],
                values["email"],
                clte,
                branch_key,
            ),
        )


def upsert_contact(cur, clte: int, branch_key: str, contact_type: str, value: str) -> None:
    value = (value or "").strip()
    if not value:
        return
    if contact_type in {"phone", "whatsapp"}:
        value_norm = normalize_phone(value)
    elif contact_type == "email":
        value_norm = normalize_email(value)
    else:
        value_norm = value.lower()
    if not value_norm:
        return
    cur.execute(
        """
        INSERT INTO contact (clte, branch_key, type, value, value_norm, first_seen, last_seen)
        VALUES (%s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (clte, branch_key, type, value_norm)
        DO UPDATE SET value = EXCLUDED.value, last_seen = now()
        """,
        (clte, str(branch_key), contact_type, value, value_norm),
    )


def upsert_social(cur, clte: int, network: str, url: str) -> None:
    if not url:
        return
    cur.execute(
        """
        INSERT INTO social (clte, network, url, first_seen, last_seen)
        VALUES (%s, %s, %s, now(), now())
        ON CONFLICT (clte, url) DO UPDATE SET last_seen = now()
        """,
        (clte, network or "other", url),
    )


def upsert_category(cur, cat_id, name: str) -> None:
    try:
        cat_id = int(cat_id)
    except (TypeError, ValueError):
        return
    cur.execute(
        """
        INSERT INTO category (cat_id, name) VALUES (%s, %s)
        ON CONFLICT (cat_id) DO UPDATE SET name = COALESCE(EXCLUDED.name, category.name)
        """,
        (cat_id, name),
    )


def upsert_company_category(cur, clte: int, cat_id) -> None:
    try:
        cat_id = int(cat_id)
    except (TypeError, ValueError):
        return
    cur.execute(
        """
        INSERT INTO company_category (clte, cat_id, first_seen, last_seen)
        VALUES (%s, %s, now(), now())
        ON CONFLICT (clte, cat_id) DO UPDATE SET last_seen = now()
        """,
        (clte, cat_id),
    )


def upsert_product(cur, clte: int, product: dict) -> None:
    name = (product.get("name") or "").strip()
    if not name:
        return
    cur.execute(
        """
        INSERT INTO product (clte, name, price, image_url, url, sku, description, availability, first_seen, last_seen)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (clte, name) DO UPDATE
        SET price = EXCLUDED.price, image_url = EXCLUDED.image_url,
            url = EXCLUDED.url, sku = EXCLUDED.sku,
            description = EXCLUDED.description, availability = EXCLUDED.availability,
            last_seen = now()
        """,
        (
            clte,
            name,
            product.get("price") or "",
            product.get("image_url") or "",
            product.get("url") or "",
            product.get("sku") or "",
            product.get("description") or "",
            product.get("availability") or "",
        ),
    )


def save_snapshot(cur, url: str, url_hash: str, kind: str, status: int, headers, content_sha: str, raw_path: str) -> None:
    cur.execute(
        """
        INSERT INTO snapshot
          (url_hash, url, kind, http_status, etag, last_modified, content_sha, raw_path)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            url_hash,
            url,
            kind,
            status,
            headers.get("etag"),
            headers.get("last-modified"),
            content_sha,
            raw_path,
        ),
    )
