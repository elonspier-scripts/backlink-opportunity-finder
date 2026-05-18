import requests


DATAFORSEO_BASE_URL = "https://api.dataforseo.com/v3"


def _dataforseo_post(endpoint, tasks, login, password):
    safe_login = (login or "").strip()
    safe_password = (password or "").strip()
    if not safe_login or not safe_password:
        raise RuntimeError("DataForSEO login/password ontbreekt of is leeg.")

    response = requests.post(
        f"{DATAFORSEO_BASE_URL}{endpoint}",
        auth=(safe_login, safe_password),
        json=tasks,
        timeout=45,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        if response.status_code == 401:
            raise RuntimeError(
                "DataForSEO authenticatie mislukt (401). Controleer login/password, verwijder extra spaties, en gebruik je DataForSEO API credentials."
            ) from exc
        raise
    payload = response.json()
    if payload.get("status_code") != 20000:
        raise RuntimeError(payload.get("status_message", "DataForSEO request failed"))
    return payload.get("tasks", [])


def _normalize_website(item):
    website = item.get("url") or item.get("domain") or ""
    website = str(website).strip()
    if not website:
        return ""
    if website.startswith(("http://", "https://")):
        return website
    return f"https://{website}"


def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def fetch_maps_places(keywords, location_name, language_name, depth, se_domain, login, password):
    tasks = [
        {
            "keyword": keyword,
            "location_name": location_name,
            "language_name": language_name,
            "se_domain": se_domain,
            "depth": depth,
        }
        for keyword in keywords
    ]

    task_results = _dataforseo_post("/serp/google/maps/live/advanced", tasks, login, password)

    rows = []
    for task in task_results or []:
        task_keyword = (task or {}).get("data", {}).get("keyword", "")
        for result in (task or {}).get("result") or []:
            for item in (result or {}).get("items") or []:
                website = _normalize_website(item)
                rows.append(
                    {
                        "searchString": task_keyword,
                        "title": item.get("title") or item.get("name"),
                        "website": website,
                        "categoryName": item.get("category") or item.get("main_category") or "Onbekend",
                        "phone": item.get("phone") or item.get("phone_unformatted") or "",
                        "emails": _as_list(item.get("emails")),
                        "socialProfiles": _as_list(item.get("socials")),
                    }
                )
    return rows
