# 🚀 AI Backlink Opportunity Finder

Deze Streamlit app combineert Google Maps leads met SEO-partnerpagina analyse.

## ✨ Functionaliteiten

- **Google Maps via Apify:** Lokale bedrijven ophalen met contact-verrijking.
- **Google Search via DataForSEO (live organic):** Organische resultaten ophalen per keyword.
- **Keyword suggesties met volume:** Suggesties op basis van handmatige keywords en/of domein.
- **Partnerpagina detectie + AI scoring:** Analyse van linkbuilding-kansen met OpenAI.
- **Contact fallback scraping:** Als verrijking mist, wordt website scraping gebruikt voor email/social/telefoon.

## 🔑 Benodigde API keys

1. **Apify API Token** (voor Google Maps)
2. **DataForSEO Login + Password** (voor Search + keyword suggesties)
3. **OpenAI API Key** (voor AI analyse)

Voor Streamlit Cloud, zet deze in Secrets:

```toml
APIFY = "jouw_apify_token"
DATAFORSEO_LOGIN = "jouw_dataforseo_login"
DATAFORSEO_PASSWORD = "jouw_dataforseo_password"
OPENAI = "jouw_openai_key"
```
