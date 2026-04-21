def ai_analyze(text, url, ai_client):
    try:
        # Fout hersteld: we gebruiken 'text' in plaats van 'page_text'
        clean_text = text[:2000] 
        
        prompt = f"""
        Je bent een SEO-expert. Analyseer de tekst van deze specifieke 'Partner/Adverteer' pagina: {url}
        
        Tekst: {clean_text} 

        Beantwoord de volgende punten:
        1. Is dit een relevante plek voor linkbuilding (gastblog, linkplaatsing)?
        2. Worden er specifieke eisen gesteld of tarieven genoemd? 
        3. Geef korte samenvatting van de pagina.
        4. Geef een score (0-10) voor de kans op succesvolle outreach.

        Output formaat:
        SCORE: [X/10] | TYPE: [bijv. Gastblog/Betaald] | ANALYSE: [Korte uitleg, max. 3 korte zinnen in bulletpoints onder elkaar.]
        """
        
        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return response.choices[0].message.content
    except Exception as e:
        # Nu zie je in je tabel ook WAAROM het mislukt (bijv. API key fout of Rate Limit)
        return f"AI Analyse mislukt: {str(e)}"
