# 🚀 AI Backlink Opportunity Finder

Deze Streamlit app combineert Google Maps leads met SEO-partnerpagina analyse.

## ✨ Functionaliteiten

- **Google Maps via DataForSEO:** Lokale bedrijven ophalen inclusief website/telefoon en verdere website-verrijking.
- **Maps taal via language_code:** Kies in de app een taalcode (bijv. English -> `en`, Dutch -> `nl`).
- **Google Search via DataForSEO (live organic):** Organische resultaten ophalen per keyword.
- **Directe keyword-run:** Scraping draait alleen op de keywords die je handmatig invoert.
- **Partnerpagina detectie + AI scoring:** Analyse van linkbuilding-kansen met OpenAI.
- **Contact fallback scraping:** Contact/about-pagina's worden meegepakt voor email/social/telefoon als provider-data mist.

## 🔑 Benodigde API keys

1. **DataForSEO Login + Password** (voor Maps en Search)
2. **OpenAI API Key** (voor AI analyse)

Voor Streamlit Cloud, zet deze in Secrets:

```toml
DATAFORSEO_LOGIN = "jouw_dataforseo_login"
DATAFORSEO_PASSWORD = "jouw_dataforseo_password"
OPENAI = "jouw_openai_key"
```
