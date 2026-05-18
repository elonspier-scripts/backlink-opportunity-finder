import requests


DATAFORSEO_BASE_URL = "https://api.dataforseo.com/v3"


def _dataforseo_post(endpoint, tasks, login, password):
    response = requests.post(
        f"{DATAFORSEO_BASE_URL}{endpoint}",
        auth=(login, password),
        json=tasks,
        timeout=45,
    )
    response.raise_for_status()
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
    for task in task_results:
        task_keyword = task.get("data", {}).get("keyword", "")
        for result in task.get("result", []):
            for item in result.get("items", []):
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
