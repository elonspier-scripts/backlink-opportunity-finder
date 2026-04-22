import streamlit as st
import pandas as pd
import io
import requests
import re
from bs4 import BeautifulSoup
from apify_client import ApifyClient
from urllib.parse import urlparse, urljoin
from openai import OpenAI

# Pagina instellingen
st.set_page_config(page_title="SEO Linkbuilding Finder", layout="wide")

st.title("🚀 AI Backlink Opportunity Finder")
st.markdown("Vind exclusieve partnerpagina's en analyseer ze direct met AI.")

# ========================================================
# 1. INPUT SECTIE (SIDEBAR)
# ========================================================
st.sidebar.header("🔑 API Configuratie")

# Gebruik secrets als ze bestaan, anders tekstvelden
api_token = st.sidebar.text_input("Apify API Token", type="password", value=st.secrets.get("APIFY", ""))
oa_token = st.sidebar.text_input("OpenAI API Key", type="password", value=st.secrets.get("OPENAI", ""))

st.sidebar.divider()
st.sidebar.header("⚙️ Zoekinstellingen")
target_domain = st.sidebar.selectbox("Google Domein", ["google.nl", "google.be", "google.com", "google.de", "google.fr"])
pages = st.sidebar.slider("Aantal pagina's diep", 1, 3, 2)

st.sidebar.divider()
st.sidebar.header("🌍 Lokalisatie")
# Gebruiker kan hier zelf de termen invoeren (gescheiden door komma's)
default_terms = "partner, adverteren, samenwerken, samenwerking, gastblog, advertise"
partner_terms_input = st.sidebar.text_area("Partner-termen (gescheiden door komma's)", value=default_terms, help="Woorden die in de linktekst moeten staan om de partnerpagina te vinden.")

# Maak een lijst van de input
PARTNER_TERMS = [t.strip().lower() for t in partner_terms_input.split(",") if t.strip()]

# ========================================================
# 2. INPUT SECTIE (HOOFDSCHERM)
# ========================================================
col1, col2 = st.columns(2)

with col1:
    st.subheader("Stap 1: Keywords")
    keywords_area = st.text_area("Plak keywords (onder elkaar)", height=150, placeholder="hardloopschoenen kopen\nmarathon tips")

with col2:
    st.subheader("Stap 2: Uitsluitingen")
    uploaded_file = st.file_uploader("Upload huidige referring domains (CSV/TXT)", type=['csv', 'txt'])

# ========================================================
# 3. LOGICA FUNCTIES
# ========================================================
def extract_domain(val):
    val = str(val).lower().strip()
    if '://' in val: 
        val = urlparse(val).netloc
    return val.replace('www.', '')

def ai_analyze(text, url, ai_client):
    try:
        clean_text = text[:2000]
        prompt = f"""
        Je bent een inkoper voor link building. Analyseer de tekst van deze specifieke 'Partner/Adverteer' pagina: {url}
        
        Tekst: {clean_text} 

        doe het volgende:
        - Geef korte samenvatting van de pagina en licht kort toe wat de mogelijkheden zijn.

        Output formaat:
        SCORE: [X/10] | TYPE: [bijv. Gastblog/Betaald] | ANALYSE: [Korte uitleg, max. 2 korte zinnen in bulletpoints onder elkaar.]
        """
        
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI Analyse mislukt: {str(e)}"

def process_site(home_url, ai_client, search_terms):
    try:
        # 1. Bezoek homepage
        res = requests.get(home_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 2. Zoek partner link
        partner_url = None
        for link in soup.find_all('a', href=True):
            link_text = link.get_text().lower()
            if any(t in link_text for t in search_terms):
                partner_url = urljoin(home_url, link['href'])
                break
        
        if not partner_url: 
            return None

        # 3. Bezoek partnerpagina
        res_p = requests.get(partner_url, timeout=10)
        p_soup = BeautifulSoup(res_p.text, 'html.parser')
        p_text = p_soup.get_text()
        
        emails = list(set(re.findall(r"[a-z0-9\.\-+_]+@[a-z0-9\.\-+_]+\.[a-z]+", p_text, re.I)))
        ai_res = ai_analyze(p_text, partner_url, ai_client)

        return {"url": partner_url, "ai": ai_res, "emails": ", ".join(emails[:3])}
    except:
        return None

# ========================================================
# 4. RUNNER
# ========================================================
if st.button("🚀 Start Analyse", type="primary"):
    if not api_token or not oa_token or not uploaded_file or not keywords_area:
        st.error("Vul alle API keys in, upload een bestand en voer keywords in.")
    elif not PARTNER_TERMS:
        st.error("Voer ten minste één partner-term in de sidebar in.")
    else:
        # Domeinen inladen
        try:
            if uploaded_file.name.endswith('.csv'):
                df_ex = pd.read_csv(uploaded_file)
                existing = set(df_ex[df_ex.columns[0]].apply(extract_domain))
            else:
                existing = {extract_domain(line.decode()) for line in uploaded_file if line.strip()}
        except Exception as e:
            st.error(f"Fout bij inladen bestand: {e}")
            st.stop()

        apify = ApifyClient(api_token)
        openai_c = OpenAI(api_key=oa_token)
        
        keywords = [k.strip() for k in keywords_area.split('\n') if k.strip()]
        opportunities = []

        with st.status("Bezig met scrapen en analyseren...", expanded=True) as status:
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

            st.write(f"🔎 Domeinen filteren en scannen op termen: {', '.join(PARTNER_TERMS)}...")
            for item in apify.dataset(run["defaultDatasetId"]).iterate_items():
                kw = item.get('searchQuery', {}).get('term') or "Onbekend"
                
                for result in item.get('organicResults', []):
                    url = result.get('url')
                    dom = extract_domain(url)
                    
                    if dom not in existing:
                        st.write(f"Nieuw domein: **{dom}**. Partner-check...")
                        # Geef de PARTNER_TERMS mee aan de functie
                        analysis = process_site(url, openai_c, PARTNER_TERMS)
                        if analysis:
                            opportunities.append({
                                "Keyword": kw,
                                "Domain": dom,
                                "Partner URL": analysis['url'],
                                "AI Potentie": analysis['ai'],
                                "Emails": analysis['emails']
                            })
            status.update(label="Analyse voltooid!", state="complete")

        if opportunities:
            df_final = pd.DataFrame(opportunities)
            st.success(f"{len(df_final)} Kansen gevonden!")
            st.dataframe(df_final, use_container_width=True)
            st.download_button("Download Resultaten (CSV)", df_final.to_csv(index=False), "backlink_kansen.csv", "text/csv")
        else:
            st.warning("Geen nieuwe domeinen met partnerpagina's gevonden.")
