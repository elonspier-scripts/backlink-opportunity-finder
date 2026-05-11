import streamlit as st
import pandas as pd
import io
import requests
import re
import json
import numpy as np
from bs4 import BeautifulSoup
from apify_client import ApifyClient
from urllib.parse import urlparse, urljoin, unquote
from openai import OpenAI
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
api_token = st.sidebar.text_input("Apify API Token", type="password", value=st.secrets.get("APIFY", ""))
oa_token = st.sidebar.text_input("OpenAI API Key", type="password", value=st.secrets.get("OPENAI", ""))

st.sidebar.divider()
st.sidebar.header("⚙️ Algemene Instellingen")
target_domain = st.sidebar.selectbox("Google Domein", ["google.nl", "google.be", "google.com", "google.de", "google.fr"])

# --- MAPS TOGGLE ---
st.sidebar.divider()
st.sidebar.header("📍 Lokale Leads (Google Maps)")
use_maps = st.sidebar.toggle("Activeer Google Maps Scraper", value=False, help="Zoek direct naar lokale bedrijven op de kaart inclusief contactgegevens.")

if use_maps:
    location_query = st.sidebar.text_input("Locatie", value="Amsterdam, Nederland", help="De stad of regio waar je wilt zoeken.")
    maps_max_results = st.sidebar.slider("Max leads per keyword", 5, 50, 10)
    expand_categories = st.sidebar.checkbox("AI Categorieën Uitbreiding", value=True, help="Laat AI synoniemen verzamelen voor Maps categorieën.")

# --- SEARCH TOGGLE ---
st.sidebar.divider()
st.sidebar.header("📡 Google Search Scraper")
use_serp = st.sidebar.toggle("Activeer Google Search Scraper", value=True, help="Zoek breed in de Google zoekresultaten naar partnerpagina's.")

if use_serp:
    pages = st.sidebar.slider("Aantal pagina's diep (Google Search)", 1, 3, 2)

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

with col1:
    st.subheader("Stap 1: Keywords")
    keywords_area = st.text_area("Plak keywords (onder elkaar)", height=150, placeholder="Loodgieter\nSchilder")

with col2:
    st.subheader("Stap 2: Uitsluitingen (Optioneel)")
    uploaded_file = st.file_uploader("Upload huidige referring domains (CSV/TXT)", type=['csv', 'txt'])

# ========================================================
# 3. LOGICA FUNCTIES
# ========================================================
@st.cache_data
def load_category_database():
    file_name = "categories_embeddings.pkl.gz"
    try:
        return pd.read_pickle(file_name)
    except OSError:
        try:
            return pd.read_pickle(file_name, compression=None)
        except Exception as e:
            st.error(f"Fout bij laden (onverpakt): {e}")
            return None
    except Exception as e:
        st.error(f"Algemene fout bij laden: {e}")
        return None

def extract_domain(val):
    val = str(val).lower().strip()
    if '://' in val: 
        val = urlparse(val).netloc
    return val.replace('www.', '')

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
        "url": None,
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

        # --- STAP 2: Zoek naar partnerpagina (Gratis HTML check) ---
        partner_url = find_partner_url(soup, home_url, search_terms)
        
        # Geen partnerpagina gevonden? Dan stoppen we hier! (Als force_summary aanstond heb je nu wel al de omschrijving)
        if not partner_url: 
            return result_data

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
        res_p = HTTP_SESSION.get(partner_url, timeout=10, headers=REQUEST_HEADERS)
        res_p.raise_for_status()
        p_soup = BeautifulSoup(res_p.text, 'html.parser')
        p_text = p_soup.get_text()
        emails = extract_emails_from_soup(p_soup)
        if not emails:
            emails = extract_emails_from_soup(soup)
        ai_res = ai_analyze(p_text, partner_url, ai_client)
        if check_404:
            result_data["brokenLinks"] = find_404_outbound_links(p_soup, partner_url, max_link_checks)

        result_data["url"] = partner_url
        result_data["ai"] = ai_res
        result_data["emails"] = ", ".join(emails[:3])
        
        return result_data
    except:
        return result_data

def get_maps_categories(keyword, ai_client):
    df_cats = load_category_database()
    
    if df_cats is None:
        return [keyword]

    try:
        response = ai_client.embeddings.create(
            input=[keyword],
            model="text-embedding-3-small",
            dimensions=512
        )
        query_vector = np.array(response.data[0].embedding, dtype=np.float32)

        all_vectors = np.vstack(df_cats['Embedding_Vector'].values)
        scores = np.dot(all_vectors, query_vector)

        top_indices = np.argsort(scores)[-20:][::-1]
        relevant_categories = df_cats.iloc[top_indices]['Categorie_Naam'].tolist()

        return relevant_categories
    except Exception as e:
        st.error(f"Fout bij semantisch zoeken naar categorieën: {e}")
        return [keyword]

# ========================================================
# 4. RUNNER
# ========================================================
if st.button("🚀 Start Analyse", type="primary"):
    if not api_token or not oa_token or not keywords_area:
        st.error("Vul alle API keys in en voer keywords in.")
    elif not use_maps and not use_serp:
        st.error("❌ Zet minimaal één van de twee scrapers (Maps of Search) aan in de linker menubalk.")
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
        
        apify = ApifyClient(api_token)
        openai_c = OpenAI(api_key=oa_token)
        keywords = [k.strip() for k in keywords_area.split('\n') if k.strip()]
        
        maps_opportunities = []
        search_opportunities = []

        with st.status("Bezig met scrapen en analyseren...", expanded=True) as status:
            
            # ---------------------------------------------------------
            # ROUTE A: GOOGLE MAPS LOKALE LEADS
            # ---------------------------------------------------------
            if use_maps:
                st.write("📍 Google Maps Scraper is gestart...")
                lang_code = target_domain.split('.')[-1]
                if lang_code == "com": lang_code = "en"
                
                all_categories = []
                if expand_categories:
                    st.write("🧠 AI is Maps-categorieën aan het verzamelen...")
                    for kw in keywords:
                        cats = get_maps_categories(kw, openai_c)
                        all_categories.extend(cats)
                    all_categories = list(set(all_categories))
                    st.write(f"🔍 {len(all_categories)} categorie-filters toegepast.")

                st.write(f"🗺️ Maps zoeken in {location_query}...")
                try:
                    run_input = {
                        "searchStringsArray": keywords,
                        "locationQuery": location_query,
                        "language": lang_code,
                        "maxCrawledPlacesPerSearch": maps_max_results,
                        "extractContacts": True
                    }
                    if expand_categories and all_categories:
                        run_input["categories"] = all_categories

                    run = apify.actor("nwua9Gu5YrADL7ZDj").call(run_input=run_input)
                    
                    st.write("🔎 Maps Resultaten verwerken...")
                    for item in apify.dataset(run["defaultDatasetId"]).iterate_items():
                        website = item.get('website')
                        title = item.get('title')
                        
                        if website:
                            dom = extract_domain(website)
                            if dom not in existing and dom not in SOCIAL_DOMAINS:
                                st.write(f"Maps Bedrijf gevonden: **{title}**. Partner-check...")
                                
                                maps_emails = item.get('emails', [])
                                maps_phone = item.get('phoneUnformatted', item.get('phone', 'Geen'))
                                maps_kw = item.get('categoryName', keywords[0] if keywords else 'Onbekend')
                                
                                # Let op: force_summary=True zodat AI ALTIJD de omschrijving pakt
                                analysis = process_site(
                                    website,
                                    openai_c,
                                    PARTNER_TERMS,
                                    maps_kw,
                                    force_summary=True,
                                    check_404=False,
                                    max_link_checks=max_outbound_checks
                                )
                                
                                maps_opportunities.append({
                                    "Bedrijf": title if title and str(title).strip().upper() not in ["N/A", "NA", ""] else dom,
                                    "Omschrijving": analysis['Omschrijving'] if analysis else "Geen beschrijving",
                                    "Category": item.get('categoryName', 'Onbekend'),
                                    "Domain": dom,
                                    "Telefoon": maps_phone,
                                    "Emails": ", ".join(maps_emails) if maps_emails else (analysis['emails'] if analysis and analysis['emails'] else ""),
                                    "Social Links": ", ".join(analysis['social_links']) if analysis and analysis['social_links'] else "",
                                    "Partner URL": analysis['url'] if analysis and analysis['url'] else "Geen partnerpagina",
                                    "Score Linkbuilding": analysis['ai'] if analysis and analysis['ai'] else "Geen partnerpagina gevonden"
                                })
                                existing.add(dom)
                except Exception as e:
                    st.error(f"Apify Maps call mislukt: {e}")

            # ---------------------------------------------------------
            # ROUTE B: GOOGLE SEARCH SEO BACKLINKS
            # ---------------------------------------------------------
            if use_serp:
                st.write("📡 Google Search Scraper is gestart...")
                try:
                    run = apify.actor("apify/google-search-scraper").call(run_input={
                        "queries": "\n".join(keywords),
                        "maxPagesPerQuery": pages,
                        "resultsPerPage": 10,
                        "domain": target_domain
                    })
                    
                    st.write("🔎 Search Domeinen filteren en scannen op partnerpagina's...")
                    for item in apify.dataset(run["defaultDatasetId"]).iterate_items():
                        kw = item.get('searchQuery', {}).get('term') or "Onbekend"
                        for result in item.get('organicResults', []):
                            url = result.get('url')
                            dom = extract_domain(url)
                            title = result.get('title', dom)
                            
                            if dom not in existing and dom not in SOCIAL_DOMAINS:
                                st.write(f"Nieuw Search domein via '{kw}': **{dom}**. Partner-check...")
                                
                                # Let op: force_summary=False (standaard) zodat AI de Lazy methode gebruikt
                                analysis = process_site(
                                    url,
                                    openai_c,
                                    PARTNER_TERMS,
                                    kw,
                                    force_summary=False,
                                    check_404=check_404_outbound,
                                    max_link_checks=max_outbound_checks
                                )
                                
                                # Bij Search slaan we ze ALLEEN op als er een partnerpagina is gevonden
                                if analysis and analysis['url']:
                                    search_opportunities.append({
                                        "Bedrijf": title if title and str(title).strip().upper() not in ["N/A", "NA", ""] else dom,
                                        "Omschrijving": analysis['Omschrijving'],
                                        "Category": kw,
                                        "Domain": dom,
                                        "Telefoon": "N/A",
                                        "Emails": analysis['emails'],
                                        "Social Links": ", ".join(analysis['social_links']) if analysis['social_links'] else "",
                                        "Partner URL": analysis['url'],
                                        "Score Linkbuilding": analysis['ai'],
                                        "Broken Outbound Links": json.dumps(analysis['brokenLinks']) if analysis['brokenLinks'] else "no links found"
                                    })
                                existing.add(dom) 
                except Exception as e:
                    st.error(f"Apify Search call mislukt: {e}")

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
                    df_maps = df_maps[["Bedrijf", "Omschrijving", "Category", "Domain", "Telefoon", "Emails", "Social Links", "Partner URL", "Score Linkbuilding"]]
                    st.success(f"{len(df_maps)} Lokale bedrijven gevonden!")
                    st.dataframe(df_maps, use_container_width=True)
                    st.download_button("Download Maps Leads (CSV)", df_maps.to_csv(index=False), "maps_leads.csv", "text/csv", key="maps_btn_tabs")
                else:
                    st.warning("Geen Maps leads gevonden.")
                    
            with tab2:
                if search_opportunities:
                    df_search = pd.DataFrame(search_opportunities)
                    df_search = df_search[["Bedrijf", "Omschrijving", "Category", "Domain", "Telefoon", "Emails", "Social Links", "Partner URL", "Score Linkbuilding", "Broken Outbound Links"]]
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
                df_maps = df_maps[["Bedrijf", "Omschrijving", "Category", "Domain", "Telefoon", "Emails", "Social Links", "Partner URL", "Score Linkbuilding"]]
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
                df_search = df_search[["Bedrijf", "Omschrijving", "Category", "Domain", "Telefoon", "Emails", "Social Links", "Partner URL", "Score Linkbuilding", "Broken Outbound Links"]]
                st.success(f"{len(df_search)} Partnerpagina's gevonden via Search!")
                st.dataframe(df_search, use_container_width=True)
                st.download_button("Download Search Leads (CSV)", df_search.to_csv(index=False), "search_leads.csv", "text/csv", key="search_btn_single")
            else:
                st.warning("Geen partnerpagina's gevonden via Google Search.")
