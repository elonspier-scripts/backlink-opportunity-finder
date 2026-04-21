# 🚀 AI Backlink Opportunity Finder

Een krachtige tool om automatisch linkbuilding kansen te vinden door Google Search te combineren met AI-analyse. Deze app scant Google resultaten, filtert domeinen waar je al een link van hebt, en gebruikt OpenAI om de "Partner/Adverteer" pagina's van nieuwe websites te analyseren.

## ✨ Functionaliteiten

- **Google Search Integration:** Scant de top 20 resultaten voor jouw specifieke keywords via Apify.
- **Smart Filtering:** Upload een lijst met je huidige 'referring domains' om dubbele outreach te voorkomen.
- **Deep Scan:** Zoekt automatisch naar pagina's zoals `/adverteren`, `/partner` of `/gastblog`.
- **AI Analysis:** Gebruikt GPT-4o-mini om de inhoud van de partnerpagina te beoordelen op potentie (score 0-10).
- **Contact Extractie:** Vindt direct e-mailadressen op de partnerpagina voor snelle outreach.

## 🛠️ Installatie & Setup

### 1. Repository clonen of aanmaken
Zorg dat de volgende bestanden in je repository staan:
- `app.py`: De hoofdcode van de applicatie.
- `requirements.txt`: De benodigde Python bibliotheken.
- `README.md`: Deze handleiding.

### 2. API Keys configureren
Je hebt twee API keys nodig:
1. **Apify API Token:** Voor het scrapen van Google Search.
2. **OpenAI API Key:** Voor de inhoudelijke analyse van de websites.

### 3. Deployen naar Streamlit Cloud
1. Ga naar [share.streamlit.io](https://share.streamlit.io/).
2. Verbind je GitHub account en selecteer deze repository.
3. **Belangrijk:** Ga naar *Advanced Settings* > *Secrets* en voeg je keys toe:
   ```toml
   APIFY = "jouw_apify_key"
   OPENAI = "jouw_openai_key"
