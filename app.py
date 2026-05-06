import streamlit as st
import pandas as pd
import io
import requests
import re
import numpy as np
from bs4 import BeautifulSoup
from apify_client import ApifyClient
from urllib.parse import urlparse, urljoin
from openai import OpenAI

# ========================================================
# 0. PAGINA INSTELLINGEN & CONSTANTEN
# ========================================================
st.set_page_config(page_title="SEO & Lead Finder", layout="wide")

SOCIAL_DOMAINS = {
    "youtube.com", "facebook.com", "instagram.com", "linkedin.com", "linkedin.nl", 
    "twitter.com", "x.com", "pinterest.com", "tiktok.com", 
    "vimeo.com", "reddit.com", "wikipedia.org", "google.com",
    "apple.com", "microsoft.com", "bol.com", "nu.nl"
}

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
else:
    pages = st.sidebar.slider("Aantal pagina's diep (Google Search)", 1, 3, 2)

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
        # Poging 1: Lees het in als normaal GZIP bestand
        return pd.read_pickle(file_name)
    except OSError:
        # Poging 2: Als de browser het bestand stiekem al heeft uitgepakt tijdens downloaden
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

def process_site(home_url, ai_client, search_terms, target_keyword):
    result_data = {"url": None, "ai": None, "emails": "", "Omschrijving": "Geen beschrijving"}
    try:
        res = requests.get(home_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(res.text, 'html.parser')
        
        try:
            home_text = soup.get_text(separator=' ', strip=True)[:1500]
            prompt = f"De zoekterm van de gebruiker was: '{target_keyword}'. Geef in maximaal 2 korte zin aan wat dit bedrijf daadwerkelijk doet of verkoopt, en vermeld of ze relevant zijn voor de genoemde zoekterm. Baseer je op deze website tekst: {home_text}"
            
            ai_summary = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            result_data["Omschrijving"] = ai_summary.choices[0].message.content.strip()
        except:
            pass 
        
        partner_url = None
        for link in soup.find_all('a', href=True):
            link_text = link.get_text().lower()
            if any(t in link_text for t in search_terms):
                partner_url = urljoin(home_url, link['href'])
                break
        
        if not partner_url: 
            return result_data

        res_p = requests.get(partner_url, timeout=10)
        p_soup = BeautifulSoup(res_p.text, 'html.parser')
        p_text = p_soup.get_text()
        
        emails = list(set(re.findall(r"[a-z0-9\.\-+_]+@[a-z0-9\.\-+_]+\.[a-z]+", p_text, re.I)))
        ai_res = ai_analyze(p_text, partner_url, ai_client)

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
    elif not use_maps and not PARTNER_TERMS:
        st.error("Selecteer ten minste één taal of voer een eigen term in voor SEO Search.")
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
        opportunities = []

        with st.status("Bezig met scrapen en analyseren...", expanded=True) as status:
            
            # ---------------------------------------------------------
            # ROUTE A: GOOGLE MAPS LOKALE LEADS
            # ---------------------------------------------------------
            if use_maps:
                st.write("📍 Google Maps modus geactiveerd.")
                lang_code = target_domain.split('.')[-1]
                if lang_code == "com": lang_code = "en"
                
                all_categories = []
                if expand_categories:
                    st.write("🧠 AI is tientallen Maps-categorieën aan het verzamelen...")
                    for kw in keywords:
                        cats = get_maps_categories(kw, openai_c)
                        all_categories.extend(cats)
                    all_categories = list(set(all_categories))
                    
                    st.write(f"🔍 {len(all_categories)} categorie-filters toegepast.")

                st.write(f"🗺️ Zoeken in {location_query}...")
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
                except Exception as e:
                    st.error(f"Apify Maps call mislukt: {e}")
                    st.stop()

                st.write("🔎 Resultaten verwerken...")
                for item in apify.dataset(run["defaultDatasetId"]).iterate_items():
                    website = item.get('website')
                    title = item.get('title')
                    
                    if website:
                        dom = extract_domain(website)
                        if dom not in existing and dom not in SOCIAL_DOMAINS:
                            st.write(f"Bedrijf gevonden: **{title}**. Partner-check...")
                            
                            maps_emails = item.get('emails', [])
                            maps_phone = item.get('phoneUnformatted', item.get('phone', 'Geen'))
                            
                            maps_kw = item.get('categoryName', keywords[0] if keywords else 'Onbekend')
                            analysis = process_site(website, openai_c, PARTNER_TERMS, maps_kw)
                            
                            opportunities.append({
                                "Bedrijf": title if title and str(title).strip().upper() not in ["N/A", "NA", ""] else dom,
                                "Omschrijving": analysis['Omschrijving'] if analysis else "Kan website niet scannen",
                                "Keyword/Categorie": item.get('categoryName', 'Onbekend'),
                                "Domain": dom,
                                "Telefoon": maps_phone,
                                "Emails": ", ".join(maps_emails) if maps_emails else (analysis['emails'] if analysis and analysis['emails'] else ""),
                                "Partner URL": analysis['url'] if analysis and analysis['url'] else "Geen partnerpagina",
                                "Score Linkbuilding": analysis['ai'] if analysis and analysis['ai'] else "Geen partnerpagina gevonden"
                            })
                            existing.add(dom)

            # ---------------------------------------------------------
            # ROUTE B: GOOGLE SEARCH SEO BACKLINKS
            # ---------------------------------------------------------
            else:
                st.write("📡 Google Search Scraper aanroepen...")
                try:
                    run = apify.actor("apify/google-search-scraper").call(run_input={
                        "queries": "\n".join(keywords),
                        "maxPagesPerQuery": pages,
                        "resultsPerPage": 10,
                        "domain": target_domain
                    })
                except Exception as e:
                    st.error(f"Apify call mislukt: {e}")
                    st.stop()

                st.write("🔎 Domeinen filteren en scannen op partnerpagina's...")
                for item in apify.dataset(run["defaultDatasetId"]).iterate_items():
                    kw = item.get('searchQuery', {}).get('term') or "Onbekend"
                    for result in item.get('organicResults', []):
                        url = result.get('url')
                        dom = extract_domain(url)
                        title = result.get('title', dom)
                        
                        if dom not in existing and dom not in SOCIAL_DOMAINS:
                            st.write(f"Nieuw domein gevonden via '{kw}': **{dom}**. Partner-check...")
                            
                            analysis = process_site(url, openai_c, PARTNER_TERMS, kw)
                            
                            if analysis and analysis['url']:
                                opportunities.append({
                                    "Bedrijf": title if title and str(title).strip().upper() not in ["N/A", "NA", ""] else dom,
                                    "Omschrijving": analysis['Omschrijving'],
                                    "Keyword/Categorie": kw,
                                    "Domain": dom,
                                    "Telefoon": "N/A",
                                    "Emails": analysis['emails'],
                                    "Partner URL": analysis['url'],
                                    "Score Linkbuilding": analysis['ai']
                                })
                                existing.add(dom) 
                            else:
                                existing.add(dom)

            status.update(label="Analyse voltooid!", state="complete")

        # ========================================================
        # 5. RESULTATEN WEERGAVE
        # ========================================================
        if opportunities:
            df_final = pd.DataFrame(opportunities)
            df_final = df_final[["Bedrijf", "Omschrijving", "Keyword/Categorie", "Domain", "Telefoon", "Emails", "Partner URL", "Score Linkbuilding"]]
            
            st.success(f"{len(df_final)} Kansen gevonden!")
            st.dataframe(df_final, use_container_width=True)
            st.download_button("Download Resultaten (CSV)", df_final.to_csv(index=False), "lead_kansen.csv", "text/csv")
        else:
            st.warning("Geen nieuwe kansen of partnerpagina's gevonden.")