import streamlit as st
import pandas as pd
import requests
import re
import json
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, unquote, parse_qs
from openai import OpenAI
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DATAFORSEO_BASE_URL = "https://api.dataforseo.com/v3"
DATAFORSEO_LOCATION_CODE_BY_DOMAIN = {
    "google.nl": 1528,
    "google.be": 1056,
    "google.com": 2840,
    "google.de": 1276,
    "google.fr": 2250,
}
DATAFORSEO_LANGUAGE_CODE_BY_DOMAIN = {
    "google.nl": "nl",
    "google.be": "nl",
    "google.com": "en",
    "google.de": "de",
    "google.fr": "fr",
}
MAPS_LANGUAGE_CODE_BY_LABEL = {
    "Dutch": "nl",
    "English": "en",
    "German": "de",
    "French": "fr",
    "Spanish": "es",
    "Italian": "it",
}
PHONE_REGEX = re.compile(r"(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)\d{2,4}[\s.-]?\d{2,4}[\s.-]?\d{0,4}")

def search_google_locations(login, password, query, limit=20):
    safe_login = (login or "").strip()
    safe_password = (password or "").strip()
    if not safe_login or not safe_password:
        raise RuntimeError("Vul DataForSEO login/password in om locaties op te zoeken.")

    response = requests.get(
        f"{DATAFORSEO_BASE_URL}/serp/google/locations",
        auth=(safe_login, safe_password),
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status_code") != 20000:
        raise RuntimeError(payload.get("status_message", "Locations request failed"))

    query_lc = (query or "").strip().lower()
    matches = []
    for task in payload.get("tasks") or []:
        for item in (task or {}).get("result") or []:
            location_name = (item.get("location_name") or "").strip()
            location_code = item.get("location_code")
            if not location_name or location_code is None:
                continue
            if query_lc and query_lc not in location_name.lower():
                continue
            matches.append({
                "location_name": location_name,
                "location_code": int(location_code),
            })

    matches = sorted(
        matches,
        key=lambda x: (
            0 if x["location_name"].lower().startswith(query_lc) else 1,
            x["location_name"],
        ),
    )

    deduped = []
    seen = set()
    for row in matches:
        key = (row["location_code"], row["location_name"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped

# ========================================================
# 0. PAGINA INSTELLINGEN & CONSTANTEN
# ========================================================
st.set_page_config(page_title="SEO & Lead Finder", layout="wide")

SOCIAL_DOMAINS = {
    "youtube.com", "facebook.com", "instagram.com", "linkedin.com", "linkedin.nl", 
    "twitter.com", "x.com", "pinterest.com", "tiktok.com", 
    "vimeo.com", "reddit.com", "wikipedia.org", "wikipedia.com", "google.com",
    "apple.com", "microsoft.com", "bol.com", "nu.nl"
}

REQUEST_HEADERS = {'User-Agent': 'Mozilla/5.0'}
EMAIL_REGEX = re.compile(r"[a-z0-9.\-+_]+@[a-z0-9.\-+_]+\.[a-z]{2,}", re.I)
SOCIAL_DOMAINS_EXTENDED = {
    "facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com",
    "youtube.com", "tiktok.com", "pinterest.com", "reddit.com", "threads.net"
}

def create_retry_session():
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

HTTP_SESSION = create_retry_session()

st.title("🚀 AI Backlink & Lead Opportunity Finder")
st.markdown("Vind exclusieve partnerpagina's via Google Search of schraap lokale leads via Google Maps.")

# ========================================================
# 1. INPUT SECTIE (SIDEBAR)
# ========================================================
st.sidebar.header("🔑 API Configuratie")
use_own_keys = st.sidebar.toggle(
    "Gebruiker voert eigen API keys in",
    value=True,
    help="Aanbevolen voor publieke apps: bezoekers gebruiken dan hun eigen credits."
)

dfs_login_default = ""
dfs_password_default = ""
oa_token_default = ""

if not use_own_keys:
    owner_access_code = st.sidebar.text_input("Owner toegangscode", type="password")
    expected_owner_code = st.secrets.get("OWNER_ACCESS_CODE", "")
    if not expected_owner_code or owner_access_code != expected_owner_code:
        st.sidebar.error("Owner toegangscode vereist om server-keys te gebruiken.")
    else:
        dfs_login_default = st.secrets.get("DATAFORSEO_LOGIN", "")
        dfs_password_default = st.secrets.get("DATAFORSEO_PASSWORD", "")
        oa_token_default = st.secrets.get("OPENAI", "")

dfs_login = st.sidebar.text_input("DataForSEO Login", value=dfs_login_default)
dfs_password = st.sidebar.text_input("DataForSEO Password", type="password", value=dfs_password_default)
oa_token = st.sidebar.text_input("OpenAI API Key", type="password", value=oa_token_default)

st.sidebar.divider()
st.sidebar.header("⚙️ Algemene Instellingen")
target_domain = st.sidebar.selectbox("Google Domein", ["google.nl", "google.be", "google.com", "google.de", "google.fr"])

# --- MAPS TOGGLE ---
st.sidebar.divider()
st.sidebar.header("📍 Lokale Leads (Google Maps)")
use_maps = st.sidebar.toggle("Activeer Google Maps Scraper", value=False, help="Zoek direct naar lokale bedrijven op de kaart inclusief contactgegevens.")
maps_max_results = 10
maps_enable_contact_fallback = False

if use_maps:
    maps_max_results = st.sidebar.slider("Max leads per keyword", 5, 50, 10)
    maps_enable_contact_fallback = st.sidebar.toggle(
        "Enable website contact fallback",
        value=False,
        help="When enabled, enrich missing contact URL, email, and social links from the website."
    )
    st.sidebar.info("Maps runs on DataForSEO. Contact fallback is optional.")

# --- SEARCH TOGGLE ---
st.sidebar.divider()
st.sidebar.header("📡 Google Search Scraper")
use_serp = st.sidebar.toggle("Activeer Google Search Scraper", value=True, help="Zoek breed in de Google zoekresultaten naar partnerpagina's.")

if use_serp:
    pages = st.sidebar.slider("Aantal pagina's diep (Google Search)", 1, 3, 2)
    st.sidebar.info("Search draait via DataForSEO live organic.")

st.sidebar.divider()
st.sidebar.header("🔗 Outbound Link Checks")
check_404_outbound = st.sidebar.toggle(
    "Check 404 outgoing links",
    value=True,
    help="Controleer alleen content-links op de gevonden partnerpagina en markeer 404 links."
)
max_outbound_checks = st.sidebar.slider(
    "Max outgoing links checked per page",
    5,
    60,
    25,
    disabled=not check_404_outbound
)

# --- PARTNER TERMEN ---
st.sidebar.divider()
st.sidebar.header("🌍 Partner Termen & Talen")
language_options = {
    "Nederlands 🇳🇱": ["partner", "adverteren", "samenwerken", "gastblog"],
    "English 🇬🇧": ["partner", "advertise", "collaborate", "guest post"],
    "Deutsch 🇩🇪": ["partner", "werben", "zusammenarbeit", "gastbeitrag"],
    "Français 🇫🇷": ["partenaire", "publicité", "collaborer", "article invité"]
}

selected_langs = st.sidebar.multiselect(
    "Selecteer talen:",
    options=list(language_options.keys()),
    default=["Nederlands 🇳🇱", "English 🇬🇧"]
)

custom_terms_input = st.sidebar.text_input("Extra eigen termen (komma gescheiden):", placeholder="affiliate, samenwerking")

PARTNER_TERMS = []
for lang in selected_langs:
    PARTNER_TERMS.extend(language_options[lang])
if custom_terms_input:
    extra_list = [t.strip().lower() for t in custom_terms_input.split(",") if t.strip()]
    PARTNER_TERMS.extend(extra_list)

PARTNER_TERMS = list(set([t.lower() for t in PARTNER_TERMS]))

with st.sidebar.expander("Actieve zoektermen"):
    st.write(PARTNER_TERMS)

# ========================================================
# 2. INPUT SECTIE (HOOFDSCHERM)
# ========================================================
col1, col2 = st.columns(2)
maps_language_code = "en"
maps_location_code_selected = None

with col1:
    st.subheader("Stap 1: Keywords")
    keywords_area = st.text_area("Plak keywords (onder elkaar)", height=150, placeholder="Loodgieter\nSchilder")

    if use_maps:
        st.markdown("**Maps instellingen**")
        default_maps_location_code = DATAFORSEO_LOCATION_CODE_BY_DOMAIN.get(target_domain)
        maps_location_code_selected = default_maps_location_code
        maps_location_lookup_query = st.text_input(
            "Adres/stad voor location_code",
            placeholder="Amsterdam",
            help="Vul adres of stad in; kies daarna een match om de juiste location_code te gebruiken."
        )

        if "maps_location_matches" not in st.session_state:
            st.session_state["maps_location_matches"] = []

        if st.button("Zoek location_code", disabled=not maps_location_lookup_query.strip()):
            if not dfs_login or not dfs_password:
                st.error("Vul DataForSEO login/password in om location codes op te zoeken.")
            else:
                try:
                    st.session_state["maps_location_matches"] = search_google_locations(
                        login=dfs_login,
                        password=dfs_password,
                        query=maps_location_lookup_query,
                        limit=20,
                    )
                    if not st.session_state["maps_location_matches"]:
                        st.warning("Geen locaties gevonden voor deze zoekterm.")
                except Exception as e:
                    st.error(f"Location lookup mislukt: {e}")

        if st.session_state["maps_location_matches"]:
            location_option_map = {
                f"{item['location_name']} | code {item['location_code']}": item["location_code"]
                for item in st.session_state["maps_location_matches"]
            }
            selected_location_label = st.selectbox(
                "Kies gevonden locatie",
                options=list(location_option_map.keys())
            )
            maps_location_code_selected = location_option_map[selected_location_label]
        st.caption(f"Actieve location_code: {maps_location_code_selected if maps_location_code_selected is not None else 'geen'}")
        maps_language_label = st.selectbox(
            "Maps language_code",
            options=[f"{label} ({code})" for label, code in MAPS_LANGUAGE_CODE_BY_LABEL.items()],
            index=0,
            help="DataForSEO Maps verwacht language_code (bijv. en, nl, de)."
        )
        maps_language_code = maps_language_label.split("(")[-1].rstrip(")")

    st.caption("De analyse gebruikt alleen de keywords uit het input veld.")

with col2:
    st.subheader("Stap 2: Uitsluitingen (Optioneel)")
    uploaded_file = st.file_uploader("Upload huidige referring domains (CSV/TXT)", type=['csv', 'txt'])

# ========================================================
# 3. LOGICA FUNCTIES
# ========================================================
def extract_domain(val):
    val = str(val).lower().strip()
    if '://' in val: 
        val = urlparse(val).netloc
    return val.replace('www.', '')

def normalize_serp_result_url(raw_url):
    candidate = str(raw_url or "").strip()
    if not candidate:
        return ""

    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"

    try:
        parsed = urlparse(candidate)
    except Exception:
        return ""

    domain = extract_domain(parsed.netloc)
    if domain.startswith("google.") and parsed.path == "/url":
        query = parse_qs(parsed.query or "")
        redirect_target = (query.get("q") or query.get("url") or [""])[0].strip()
        if redirect_target.startswith(("http://", "https://")):
            return redirect_target

    if not parsed.netloc:
        return ""
    return candidate

def ai_analyze(text, url, ai_client):
    try:
        clean_text = text[:2000]
        prompt = f"""
        Je bent een Linkbuilding-expert. Analyseer de tekst van deze 'Partner/Adverteer' pagina: {url}
        Tekst: {clean_text} 

        Beantwoord de volgende punten:
        1. Is dit een relevante plek voor linkbuilding?
        2. Worden er specifieke eisen gesteld of tarieven genoemd? 
        3. Geef korte samenvatting van de pagina.
        4. Geef een score (0-10) op basis van potentie voor linkbuidling?
        5. Welk type partnerpagina is dit (bijv. Gastblog, Adverteren, Affiliate)?

        Output formaat:
        SCORE: [X/10] | TYPE: [bijv. een van de mogelijkheden uit punt 5] | ANALYSE: [Korte uitleg, max. 3 korte en compacte zinnen in bulletpoints.]
        """
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI Analyse mislukt: {str(e)}"

def is_partner_link(link, search_terms):
    href = (link.get('href') or '').strip()
    if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
        return False

    link_blob = " ".join([
        link.get_text(separator=' ', strip=True),
        link.get('aria-label', ''),
        link.get('title', ''),
        href
    ]).lower()
    return any(term in link_blob for term in search_terms)

def find_partner_url(soup, home_url, search_terms):
    seen_hrefs = set()

    priority_selectors = [
        'footer',
        'nav',
        '[role="navigation"]',
        '[id*="footer" i]',
        '[class*="footer" i]',
        '[id*="menu" i]',
        '[class*="menu" i]',
        '[id*="nav" i]',
        '[class*="nav" i]'
    ]

    for selector in priority_selectors:
        for container in soup.select(selector):
            for link in container.find_all('a', href=True):
                href = (link.get('href') or '').strip()
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                if is_partner_link(link, search_terms):
                    return urljoin(home_url, href)

    for link in soup.find_all('a', href=True):
        href = (link.get('href') or '').strip()
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        if is_partner_link(link, search_terms):
            return urljoin(home_url, href)

    return None

def find_contact_url(soup, home_url):
    contact_tokens = [
        "contact",
        "contact-us",
        "contacten",
        "about",
        "over-ons",
        "impressum",
        "kontakt"
    ]
    seen_hrefs = set()

    priority_selectors = [
        'footer',
        'nav',
        '[role="navigation"]',
        '[id*="footer" i]',
        '[class*="footer" i]',
        '[id*="menu" i]',
        '[class*="menu" i]',
        '[id*="nav" i]',
        '[class*="nav" i]'
    ]

    for selector in priority_selectors:
        for container in soup.select(selector):
            for link in container.find_all('a', href=True):
                href = (link.get('href') or '').strip()
                if not href or href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                href_l = href.lower()
                if any(token in href_l for token in contact_tokens):
                    return urljoin(home_url, href)

    for link in soup.find_all('a', href=True):
        href = (link.get('href') or '').strip()
        if not href or href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        href_l = href.lower()
        if any(token in href_l for token in contact_tokens):
            return urljoin(home_url, href)

    for path in ["/contact", "/contact-us", "/contacten", "/about", "/over-ons", "/impressum", "/kontakt"]:
        candidate = urljoin(home_url, path)
        try:
            candidate_response = HTTP_SESSION.get(candidate, timeout=8, headers=REQUEST_HEADERS)
            if candidate_response.status_code < 400:
                return candidate
        except Exception:
            continue

    return None

def deobfuscate_email_text(text):
    if not text:
        return ""

    normalized = text.lower()
    normalized = re.sub(r"\s*(\[|\()\s*at\s*(\]|\))\s*", "@", normalized)
    normalized = re.sub(r"\s*(\[|\()\s*dot\s*(\]|\))\s*", ".", normalized)
    normalized = re.sub(r"\s+at\s+", "@", normalized)
    normalized = re.sub(r"\s+dot\s+", ".", normalized)
    normalized = normalized.replace("{at}", "@").replace("{dot}", ".")
    return normalized

def extract_emails_from_soup(soup):
    emails = set()

    page_text = soup.get_text(separator=' ', strip=True)
    emails.update(EMAIL_REGEX.findall(page_text))
    emails.update(EMAIL_REGEX.findall(deobfuscate_email_text(page_text)))

    for link in soup.find_all('a', href=True):
        href = (link.get('href') or '').strip()
        if href.lower().startswith('mailto:'):
            mailto_value = unquote(href[7:]).split('?', 1)[0]
            if mailto_value:
                emails.update(EMAIL_REGEX.findall(mailto_value))

        link_text = " ".join([
            link.get_text(separator=' ', strip=True),
            link.get('aria-label', ''),
            link.get('title', '')
        ])
        emails.update(EMAIL_REGEX.findall(deobfuscate_email_text(link_text)))

    for footer in soup.select('footer, [id*="footer" i], [class*="footer" i]'):
        footer_text = footer.get_text(separator=' ', strip=True)
        emails.update(EMAIL_REGEX.findall(footer_text))
        emails.update(EMAIL_REGEX.findall(deobfuscate_email_text(footer_text)))
        for footer_link in footer.find_all('a', href=True):
            footer_href = (footer_link.get('href') or '').strip()
            if footer_href.lower().startswith('mailto:'):
                footer_mailto = unquote(footer_href[7:]).split('?', 1)[0]
                if footer_mailto:
                    emails.update(EMAIL_REGEX.findall(footer_mailto))

    cleaned = []
    for email in emails:
        normalized_email = email.strip().strip('.,;:()[]{}<>")(')
        if normalized_email:
            cleaned.append(normalized_email.lower())

    return sorted(set(cleaned))

def is_social_link(url):
    try:
        domain = extract_domain(url)
        return any(domain == d or domain.endswith(f".{d}") for d in SOCIAL_DOMAINS_EXTENDED)
    except Exception:
        return False

def extract_social_links_from_soup(soup, base_url):
    social_links = set()
    for link in soup.find_all('a', href=True):
        href = (link.get('href') or '').strip()
        if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
            continue

        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ('http', 'https'):
            continue

        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip('/')
        if is_social_link(normalized):
            social_links.add(normalized)

    return sorted(social_links)

def collect_content_outbound_links(soup, page_url):
    content_selectors = [
        'main', 'article', '[role="main"]',
        '.content', '.entry-content', '.post-content', '.article-content', '.post'
    ]
    boilerplate_selectors = 'header, nav, footer, aside, [role="navigation"], [class*="footer" i], [id*="footer" i], [class*="menu" i], [id*="menu" i], [class*="sidebar" i], [id*="sidebar" i]'

    containers = []
    for selector in content_selectors:
        containers.extend(soup.select(selector))

    if not containers:
        body = soup.find('body')
        containers = [body] if body else [soup]

    seen_urls = set()
    outbound_links = []
    base_domain = extract_domain(page_url)

    for container in containers:
        for link in container.find_all('a', href=True):
            if link.find_parent(['header', 'nav', 'footer', 'aside']):
                continue
            if link.find_parent(attrs={'role': re.compile(r'navigation', re.I)}):
                continue
            if link.find_parent(class_=re.compile(r'footer|menu|sidebar', re.I)):
                continue
            if link.find_parent(id=re.compile(r'footer|menu|sidebar', re.I)):
                continue

            href = (link.get('href') or '').strip()
            if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
                continue

            absolute = urljoin(page_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ('http', 'https'):
                continue

            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if extract_domain(normalized) == base_domain:
                continue
            if is_social_link(normalized):
                continue
            if normalized in seen_urls:
                continue

            seen_urls.add(normalized)

            rel_attr = link.get('rel') or []
            rel_joined = " ".join([str(r).lower() for r in rel_attr])
            rel_type = "nofollow" if "nofollow" in rel_joined else "dofollow"

            outbound_links.append({
                "url": normalized,
                "anchorText": link.get_text(separator=' ', strip=True),
                "rel": rel_type
            })

    return outbound_links

def find_404_outbound_links(page_soup, page_url, max_checks):
    outbound_links = collect_content_outbound_links(page_soup, page_url)
    broken = []

    for link_data in outbound_links[:max_checks]:
        try:
            response = HTTP_SESSION.get(link_data["url"], timeout=6, headers=REQUEST_HEADERS, allow_redirects=True)
            status_code = response.status_code
            if status_code == 404:
                broken.append({
                    "#": len(broken) + 1,
                    "brokenUrl": link_data["url"],
                    "anchorText": link_data["anchorText"],
                    "statusCode": status_code,
                    "rel": link_data["rel"]
                })
        except Exception:
            continue

    return broken

# AANGEPAST: Inclusief 'force_summary' voor Maps
def process_site(home_url, ai_client, search_terms, target_keyword, force_summary=False, check_404=False, max_link_checks=25):
    result_data = {
        "url": home_url,
        "contact_url": "",
        "ai": None,
        "emails": "",
        "Omschrijving": "Geen beschrijving",
        "social_links": [],
        "brokenLinks": []
    }
    try:
        res = HTTP_SESSION.get(home_url, timeout=10, headers=REQUEST_HEADERS)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'html.parser')
        result_data["social_links"] = extract_social_links_from_soup(soup, home_url)
        
        # --- STAP 1: Forceren we de omschrijving? (Google Maps modus) ---
        if force_summary:
            try:
                home_text = soup.get_text(separator=' ', strip=True)[:1500]
                prompt = f"De zoekterm van de gebruiker was: '{target_keyword}', maar benoem het niet specifiek in je output. Geef in maximaal 2 korte telegram achtige zinnen aan wat dit bedrijf daadwerkelijk doet of verkoopt, en relevantie. Baseer het op deze website tekst: {home_text}"
                ai_summary = ai_client.chat.completions.create(
                    model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0.3
                )
                result_data["Omschrijving"] = ai_summary.choices[0].message.content.strip()
            except:
                pass 

        # --- STAP 2: Zoek naar partner- en contactpagina ---
        partner_url = find_partner_url(soup, home_url, search_terms)
        contact_url = find_contact_url(soup, home_url)
        result_data["contact_url"] = contact_url or ""

        analysis_url = partner_url or contact_url or home_url

        page_text_parts = [soup.get_text()]
        emails = set(extract_emails_from_soup(soup))

        for page_url in [u for u in [partner_url, contact_url] if u]:
            try:
                res_page = HTTP_SESSION.get(page_url, timeout=10, headers=REQUEST_HEADERS)
                res_page.raise_for_status()
                page_soup = BeautifulSoup(res_page.text, 'html.parser')
                page_text_parts.append(page_soup.get_text())
                emails.update(extract_emails_from_soup(page_soup))
                if check_404 and page_url == analysis_url:
                    result_data["brokenLinks"] = find_404_outbound_links(page_soup, page_url, max_link_checks)
            except Exception:
                continue

        # --- STAP 3: Partnerpagina gevonden! AI Samenvatting ophalen als we dat in stap 1 nog niet hadden gedaan (SERP modus) ---
        if not force_summary:
            try:
                home_text = soup.get_text(separator=' ', strip=True)[:1500]
                prompt = f"De zoekterm van de gebruiker was: '{target_keyword}', maar benoem het niet specifiek in je output. Geef in maximaal 2 korte telegram achtige zinnen aan wat dit bedrijf daadwerkelijk doet of verkoopt, en relevantie. Baseer het op deze website tekst: {home_text}"
                ai_summary = ai_client.chat.completions.create(
                    model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0.3
                )
                result_data["Omschrijving"] = ai_summary.choices[0].message.content.strip()
            except:
                pass 

        # --- STAP 4: Partnerpagina uitlezen en analyseren met AI ---
        combined_text = "\n\n".join(page_text_parts)
        ai_res = ai_analyze(combined_text, analysis_url, ai_client)

        result_data["url"] = analysis_url
        result_data["ai"] = ai_res
        result_data["emails"] = ", ".join(sorted(emails)[:3])
        
        return result_data
    except:
        return result_data

def dataforseo_post(endpoint, tasks, login, password):
    safe_login = (login or "").strip()
    safe_password = (password or "").strip()
    if not safe_login or not safe_password:
        raise RuntimeError("DataForSEO login/password ontbreekt of is leeg.")

    response = requests.post(
        f"{DATAFORSEO_BASE_URL}{endpoint}",
        auth=(safe_login, safe_password),
        json=tasks,
        timeout=45
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

def as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []

def normalize_social_values(values):
    normalized = []
    for value in as_list(values):
        if isinstance(value, dict):
            candidate = value.get("url") or value.get("link") or value.get("profileUrl")
        else:
            candidate = str(value)
        candidate = (candidate or "").strip()
        if candidate:
            normalized.append(candidate)
    return normalized

def normalize_phone_value(value):
    if not value:
        return ""
    candidate = str(value).strip()
    digits = re.sub(r"\D", "", candidate)
    if len(digits) < 8:
        return ""
    return candidate

def extract_phone_candidates_from_soup(soup):
    phones = set()
    for link in soup.find_all('a', href=True):
        href = (link.get('href') or '').strip()
        if href.lower().startswith('tel:'):
            candidate = normalize_phone_value(unquote(href[4:]).split('?', 1)[0])
            if candidate:
                phones.add(candidate)
    text = soup.get_text(separator=' ', strip=True)
    for match in PHONE_REGEX.findall(text):
        candidate = normalize_phone_value(match)
        if candidate:
            phones.add(candidate)
    return sorted(phones)

def enrich_contacts_from_website(home_url):
    enriched = {"emails": [], "phones": [], "social_links": [], "contact_url": ""}
    try:
        response = HTTP_SESSION.get(home_url, timeout=10, headers=REQUEST_HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        emails = set(extract_emails_from_soup(soup))
        phones = set(extract_phone_candidates_from_soup(soup))
        social_links = set(extract_social_links_from_soup(soup, home_url))

        contact_candidates = []
        default_contact_paths = [
            "/contact",
            "/contact-us",
            "/contacten",
            "/about",
            "/over-ons",
            "/impressum",
            "/kontakt"
        ]
        for link in soup.find_all('a', href=True):
            href = (link.get('href') or '').strip().lower()
            if any(token in href for token in ['/contact', '/contact-us', '/contacten', '/over-ons', '/about']):
                contact_candidates.append(urljoin(home_url, href))

        for path in default_contact_paths:
            contact_candidates.append(urljoin(home_url, path))

        for url in list(dict.fromkeys(contact_candidates))[:4]:
            try:
                contact_response = HTTP_SESSION.get(url, timeout=8, headers=REQUEST_HEADERS)
                contact_response.raise_for_status()
                if not enriched["contact_url"]:
                    enriched["contact_url"] = url
                contact_soup = BeautifulSoup(contact_response.text, 'html.parser')
                emails.update(extract_emails_from_soup(contact_soup))
                phones.update(extract_phone_candidates_from_soup(contact_soup))
                social_links.update(extract_social_links_from_soup(contact_soup, url))
            except Exception:
                continue

        enriched["emails"] = sorted(emails)
        enriched["phones"] = sorted(phones)
        enriched["social_links"] = sorted(social_links)
    except Exception:
        return enriched
    return enriched

def get_dataforseo_organic_results(keywords, target_domain, pages, login, password):
    language_code = DATAFORSEO_LANGUAGE_CODE_BY_DOMAIN.get(target_domain, "en")
    location_code = DATAFORSEO_LOCATION_CODE_BY_DOMAIN.get(target_domain)
    organic_rows = []
    for keyword in keywords:
        payload = {
            "keyword": keyword,
            "se_domain": target_domain,
            "language_code": language_code,
            "depth": pages * 10
        }
        if location_code:
            payload["location_code"] = location_code
        task_results = dataforseo_post("/serp/google/organic/live/advanced", [payload], login, password)
        for task in task_results or []:
            task_keyword = (task or {}).get("data", {}).get("keyword", keyword)
            for result in (task or {}).get("result") or []:
                for item in (result or {}).get("items") or []:
                    url = item.get("url") or item.get("target") or item.get("domain")
                    if not url:
                        continue
                    url = normalize_serp_result_url(url)
                    if not url:
                        continue
                    organic_rows.append({
                        "keyword": task_keyword,
                        "url": url,
                        "title": item.get("title", "")
                    })
    return organic_rows

def normalize_maps_website(item):
    website = item.get("website") or item.get("domain") or ""
    website = str(website).strip()
    if not website:
        return ""
    if website.startswith(("http://", "https://")):
        return website
    return f"https://{website}"

def build_maps_summary(item):
    title = (item.get("title") or item.get("name") or "This company").strip()
    category = (item.get("category") or item.get("main_category") or "business").strip().lower()
    address = (item.get("address") or "").strip()

    if address:
        return f"{title} is a {category} based in {address}."
    return f"{title} is a {category}."

def fetch_maps_places(keywords, location_code, language_code, depth, se_domain, login, password):
    rows = []
    for keyword in keywords:
        map_keyword = str(keyword).strip()

        payload = {
            "keyword": map_keyword,
            "language_code": language_code,
            "se_domain": se_domain,
            "depth": depth,
        }
        if location_code is not None:
            payload["location_code"] = location_code
        task_results = dataforseo_post("/serp/google/maps/live/advanced", [payload], login, password)

        for task in task_results or []:
            task_keyword = (task or {}).get("data", {}).get("keyword", keyword)
            for result in (task or {}).get("result") or []:
                for item in (result or {}).get("items") or []:
                    rows.append(
                        {
                            "searchString": task_keyword,
                            "title": item.get("title") or item.get("name"),
                            "summary": build_maps_summary(item),
                            "website": normalize_maps_website(item),
                            "sharedUrl": item.get("url") or "",
                            "contactUrl": item.get("contact_url") or "",
                            "address": item.get("address") or "",
                            "categoryName": item.get("category") or item.get("main_category") or "Onbekend",
                            "phone": item.get("phone") or item.get("phone_unformatted") or "",
                            "emails": as_list(item.get("emails")),
                            "socialProfiles": as_list(item.get("socials")),
                        }
                    )
    return rows

# ========================================================
# 4. RUNNER
# ========================================================
if st.button("🚀 Start Analyse", type="primary"):
    manual_keywords = [k.strip() for k in keywords_area.split('\n') if k.strip()]
    keywords = list(dict.fromkeys(manual_keywords))
    keyword_volumes = {kw: 0 for kw in manual_keywords}
    maps_location_code = maps_location_code_selected

    if not oa_token:
        st.error("Vul OpenAI key in.")
    elif not keywords:
        st.error("Voeg minimaal 1 keyword toe in het keyword veld.")
    elif not use_maps and not use_serp:
        st.error("❌ Zet minimaal één van de twee scrapers (Maps of Search) aan in de linker menubalk.")
    elif (use_serp or use_maps) and (not dfs_login or not dfs_password):
        st.error("Vul DataForSEO login + password in voor Maps/Search.")
    elif use_serp and not PARTNER_TERMS:
        st.error("Selecteer ten minste één taal of voer een eigen term in voor de Search Scraper.")
    else:
        existing = set()

        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df_ex = pd.read_csv(uploaded_file)
                    existing = set(df_ex[df_ex.columns[0]].dropna().apply(extract_domain))
                else:
                    existing = {extract_domain(line.decode().strip()) for line in uploaded_file if line.strip()}
                st.info(f"📁 {len(existing)} bestaande domeinen ingeladen om over te slaan.")
            except Exception as e:
                st.error(f"Fout bij inladen bestand: {e}")
                st.stop()
        
        openai_c = OpenAI(api_key=oa_token)
        
        maps_opportunities = []
        search_opportunities = []

        with st.status("Bezig met scrapen en analyseren...", expanded=True) as status:
            
            # ---------------------------------------------------------
            # ROUTE A: GOOGLE MAPS LOKALE LEADS
            # ---------------------------------------------------------
            if use_maps:
                st.write("📍 Google Maps Scraper (DataForSEO) is gestart...")
                st.write(f"🗺️ Maps zoeken met location_code: {maps_location_code if maps_location_code is not None else 'niet ingesteld'}...")
                try:
                    maps_keywords = list(dict.fromkeys([k for k in keywords if str(k).strip()]))
                    maps_items = fetch_maps_places(
                        keywords=maps_keywords,
                        location_code=maps_location_code,
                        language_code=maps_language_code,
                        depth=maps_max_results,
                        se_domain=target_domain,
                        login=dfs_login,
                        password=dfs_password
                    )

                    st.write("🔎 Maps Resultaten verwerken...")
                    for item in maps_items:
                        website = item.get('website')
                        title = item.get('title')
                        
                        if website:
                            dom = extract_domain(website)
                            if dom not in existing and dom not in SOCIAL_DOMAINS:
                                st.write(f"Maps Bedrijf gevonden: **{title}**. Partner-check...")
                                
                                maps_emails = as_list(item.get('emails'))
                                maps_phone = normalize_phone_value(item.get('phoneUnformatted', item.get('phone', '')))
                                maps_social_links = normalize_social_values(item.get('socialProfiles')) + normalize_social_values(item.get('socials'))
                                maps_kw = item.get('searchString') or item.get('searchQuery') or (keywords[0] if keywords else 'Onbekend')
                                final_emails = maps_emails
                                final_phone = maps_phone if maps_phone else "N/A"
                                final_social_links = sorted(set(maps_social_links or []))
                                final_contact_url = item.get('contactUrl', '')

                                if maps_enable_contact_fallback and website:
                                    needs_fallback = not final_contact_url or not final_emails or not final_social_links
                                    if needs_fallback:
                                        fallback_contacts = enrich_contacts_from_website(website)
                                        if not final_contact_url:
                                            final_contact_url = fallback_contacts.get("contact_url", "")
                                        if not final_emails:
                                            final_emails = fallback_contacts.get("emails", [])
                                        if not maps_phone:
                                            fallback_phones = fallback_contacts.get("phones", [])
                                            if fallback_phones:
                                                final_phone = fallback_phones[0]
                                        fallback_social = fallback_contacts.get("social_links", [])
                                        if fallback_social:
                                            final_social_links = sorted(set(final_social_links + fallback_social))

                                maps_row = {
                                    "Company": title if title and str(title).strip().upper() not in ["N/A", "NA", ""] else dom,
                                    "Category": item.get('categoryName', 'Unknown'),
                                    "Keyword": maps_kw,
                                    "Domain": dom,
                                    "Shared URL": item.get('sharedUrl', ''),
                                    "Contact URL": final_contact_url,
                                    "Address": item.get('address', ''),
                                    "Phone": final_phone,
                                    "Emails": ", ".join(final_emails) if final_emails else "",
                                    "Social Links": ", ".join(final_social_links)
                                }
                                if maps_enable_contact_fallback:
                                    maps_row["Summary"] = item.get('summary') or "No description"

                                maps_opportunities.append(maps_row)
                                existing.add(dom)
                except Exception as e:
                    st.error(f"Google Maps call mislukt (DataForSEO): {e}")

            # ---------------------------------------------------------
            # ROUTE B: GOOGLE SEARCH SEO BACKLINKS
            # ---------------------------------------------------------
            if use_serp:
                st.write("📡 Google Search Scraper (DataForSEO live organic) is gestart...")
                try:
                    organic_results = get_dataforseo_organic_results(
                        keywords=keywords,
                        target_domain=target_domain,
                        pages=pages,
                        login=dfs_login,
                        password=dfs_password
                    )
                    
                    st.write("🔎 Search Domeinen filteren en scannen op partnerpagina's...")
                    for result in organic_results:
                        kw = result.get('keyword') or "Onbekend"
                        url = result.get('url')
                        dom = extract_domain(url)
                        title = result.get('title', dom)

                        if dom not in existing and dom not in SOCIAL_DOMAINS:
                            st.write(f"Nieuw Search domein via '{kw}': **{dom}**. Partner-check...")

                            analysis = process_site(
                                url,
                                openai_c,
                                PARTNER_TERMS,
                                kw,
                                force_summary=False,
                                check_404=check_404_outbound,
                                max_link_checks=max_outbound_checks
                            )

                            if analysis and analysis['url']:
                                search_opportunities.append({
                                    "Bedrijf": title if title and str(title).strip().upper() not in ["N/A", "NA", ""] else dom,
                                    "Omschrijving": analysis['Omschrijving'],
                                    "Category": kw,
                                    "Keyword": kw,
                                    "Search Volume": keyword_volumes.get(kw, 0),
                                    "Domain": dom,
                                    "Telefoon": "N/A",
                                    "Emails": analysis['emails'],
                                    "Social Links": ", ".join(analysis['social_links']) if analysis['social_links'] else "",
                                    "Partner URL": analysis['url'],
                                    "Contact URL": analysis.get('contact_url', ''),
                                    "Score Linkbuilding": analysis['ai'],
                                    "Broken Outbound Links": json.dumps(analysis['brokenLinks']) if analysis['brokenLinks'] else "no links found"
                                })
                            existing.add(dom)
                except Exception as e:
                    st.error(f"Google Search call mislukt (DataForSEO): {e}")

            status.update(label="Analyse voltooid!", state="complete")

        # ========================================================
        # 5. RESULTATEN WEERGAVE
        # ========================================================
        # Als ze ALLEBEI aan staan, gebruiken we tabbladen (Dit is visueel veel beter dan kolommen omdat de tabellen breed zijn)
        if use_maps and use_serp:
            tab1, tab2 = st.tabs(["📍 Google Maps Resultaten", "📡 Google Search Resultaten"])
            
            with tab1:
                if maps_opportunities:
                    df_maps = pd.DataFrame(maps_opportunities)
                    maps_columns = ["Company", "Category", "Keyword", "Domain", "Shared URL", "Contact URL", "Address", "Phone", "Emails", "Social Links"]
                    if maps_enable_contact_fallback:
                        maps_columns.insert(1, "Summary")
                    df_maps = df_maps[maps_columns]
                    st.success(f"{len(df_maps)} Lokale bedrijven gevonden!")
                    st.dataframe(df_maps, use_container_width=True)
                    st.download_button("Download Maps Leads (CSV)", df_maps.to_csv(index=False), "maps_leads.csv", "text/csv", key="maps_btn_tabs")
                else:
                    st.warning("Geen Maps leads gevonden.")
                    
            with tab2:
                if search_opportunities:
                    df_search = pd.DataFrame(search_opportunities)
                    df_search = df_search[["Bedrijf", "Omschrijving", "Category", "Keyword", "Search Volume", "Domain", "Telefoon", "Emails", "Social Links", "Partner URL", "Contact URL", "Score Linkbuilding", "Broken Outbound Links"]]
                    st.success(f"{len(df_search)} Partnerpagina's gevonden via Search!")
                    st.dataframe(df_search, use_container_width=True)
                    st.download_button("Download Search Leads (CSV)", df_search.to_csv(index=False), "search_leads.csv", "text/csv", key="search_btn_tabs")
                else:
                    st.warning("Geen partnerpagina's gevonden via Google Search.")
        
        # Als ALLEEN Maps aan staat
        elif use_maps and not use_serp:
            st.subheader("📍 Google Maps Resultaten")
            if maps_opportunities:
                df_maps = pd.DataFrame(maps_opportunities)
                maps_columns = ["Company", "Category", "Keyword", "Domain", "Shared URL", "Contact URL", "Address", "Phone", "Emails", "Social Links"]
                if maps_enable_contact_fallback:
                    maps_columns.insert(1, "Summary")
                df_maps = df_maps[maps_columns]
                st.success(f"{len(df_maps)} Lokale bedrijven gevonden!")
                st.dataframe(df_maps, use_container_width=True)
                st.download_button("Download Maps Leads (CSV)", df_maps.to_csv(index=False), "maps_leads.csv", "text/csv", key="maps_btn_single")
            else:
                st.warning("Geen Maps leads gevonden.")
        
        # Als ALLEEN Search aan staat
        elif use_serp and not use_maps:
            st.subheader("📡 Google Search Resultaten")
            if search_opportunities:
                df_search = pd.DataFrame(search_opportunities)
                df_search = df_search[["Bedrijf", "Omschrijving", "Category", "Keyword", "Search Volume", "Domain", "Telefoon", "Emails", "Social Links", "Partner URL", "Contact URL", "Score Linkbuilding", "Broken Outbound Links"]]
                st.success(f"{len(df_search)} Partnerpagina's gevonden via Search!")
                st.dataframe(df_search, use_container_width=True)
                st.download_button("Download Search Leads (CSV)", df_search.to_csv(index=False), "search_leads.csv", "text/csv", key="search_btn_single")
            else:
                st.warning("Geen partnerpagina's gevonden via Google Search.")
