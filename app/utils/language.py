from langdetect import detect, detect_langs

def detect_language(text: str) -> str:
    """
    Detects if the text is English or Filipino (Tagalog).
    Returns 'en' or 'fil'.
    """
    if not text or len(text.strip()) < 3:
        return "en"
        
    try:
        # Get language probabilities
        langs = detect_langs(text)
        
        # langdetect uses 'tl' for Tagalog
        for l in langs:
            if l.lang == 'tl':
                return "fil"
            if l.lang == 'en':
                return "en"
                
        # Fallback to the top detected language if neither en nor tl is dominant
        # but map to our supported codes
        top_lang = detect(text)
        if top_lang == 'tl':
            return "fil"
        return "en"
    except Exception as e:
        print(f"Language detection error: {e}")
        # Secondary heuristic fallback
        tagalog_keywords = ["sa", "ang", "ng", "mga", "isang", "si", "po", "opo", "ko", "mo", "ni", "ay", "na", "lang", "pa"]
        if any(f" {kw} " in f" {text.lower()} " for kw in tagalog_keywords):
            return "fil"
        return "en"
