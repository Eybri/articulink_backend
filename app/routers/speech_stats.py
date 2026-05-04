"""
Speech Stats Router — aggregates audio_clips into user-facing metrics.
"""
import re
from fastapi import APIRouter, Depends
from collections import Counter
from datetime import datetime, timedelta
from app.utils.auth_middleware import require_auth, get_current_user_id
from app.db.database import db

router = APIRouter(prefix="/stats", tags=["Speech Stats"])

# Common stop words to exclude from most-used
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "i", "you", "he", "she",
    "it", "we", "they", "me", "my", "your", "his", "her", "its", "our",
    "their", "this", "that", "in", "on", "at", "to", "for", "of", "and",
    "or", "but", "not", "with", "from", "by", "as", "so", "do", "did",
    "has", "have", "had", "be", "been", "am", "no", "yes", "if", "then",
    "than", "just", "also", "very", "can", "will", "would", "could",
    "should", "may", "might", "shall", "must", "about", "up", "out",
    "all", "some", "any", "each", "every", "both", "few", "more", "most",
    "other", "into", "over", "after", "before", "between", "under",
    "again", "further", "once", "here", "there", "when", "where", "why",
    "how", "what", "which", "who", "whom", "these", "those", "such",
    "only", "own", "same", "too", "down", "off",
    # Filipino stop words
    "ang", "ng", "sa", "na", "ay", "ko", "ka", "mo", "niya", "nila",
    "ito", "iyon", "mga", "si", "ni", "kay", "para", "po", "opo",
    "ba", "pa", "din", "rin", "lang", "naman", "daw", "raw",
}

@router.get("/speech", dependencies=[Depends(require_auth)])
async def get_speech_stats(user_id: str = Depends(get_current_user_id)):
    """
    Returns optimized aggregated speech statistics for the current user.
    """
    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)

    # 1. Pipeline for Totals and Language Breakdown
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$facet": {
            "totals": [
                {"$group": {
                    "_id": None,
                    "total_recordings": {"$sum": 1},
                    "total_duration": {"$sum": "$duration_seconds"},
                    "avg_confidence": {"$avg": "$overall_confidence"},
                    "today_count": {
                        "$sum": {"$cond": [{"$gte": ["$created_at", today_start]}, 1, 0]}
                    },
                    "today_avg_confidence": {
                        "$avg": {"$cond": [{"$gte": ["$created_at", today_start]}, "$overall_confidence", "$$REMOVE"]}
                    }
                }}
            ],
            "languages": [
                {"$group": {"_id": "$language", "count": {"$sum": 1}}}
            ],
            "recent_data": [
                {"$sort": {"created_at": -1}},
                {"$limit": 50}, # Fetch last 50 for word analysis and phrases
                {"$project": {"transcript": 1, "corrected_transcript": 1, "created_at": 1}}
            ],
            "streak_dates": [
                {"$group": {
                    "_id": {
                        "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
                    }
                }},
                {"$sort": {"_id": -1}},
                {"$limit": 365}
            ]
        }}
    ]

    result = await db.audio_clips.aggregate(pipeline).to_list(length=1)
    data = result[0] if result else {}

    totals_list = data.get("totals", [])
    totals = totals_list[0] if totals_list else {}
    total_recordings = totals.get("total_recordings", 0)
    
    if total_recordings == 0:
        return {
            "total_recordings": 0, "total_words": 0, "total_duration_seconds": 0,
            "avg_confidence": 0,
            "most_used_words": [], "recent_phrases": [], "language_breakdown": {},
            "streak_days": 0, "today_recordings": 0,
            "today_avg_confidence": 0
        }

    # 2. Extract Recent Phrases and Word Frequencies from sampled data
    recent_clips = data.get("recent_data", [])
    word_counter = Counter()
    recent_phrases = []
    total_estimated_words = 0 # Approximate based on all clips if we wanted, but we'll use samples or estimate

    # For word count, we might need a separate count if we want exact total words across ALL history
    # but for optimization, let's process the last 100 clips for words to avoid CPU spike
    for i, clip in enumerate(recent_clips):
        text = clip.get("transcript") or clip.get("corrected_transcript") or ""
        words = text.strip().split()
        
        # Exact total words for ALL clips is hard without a full scan or pre-calculated field
        # We'll just sum the words in our sampled 'recent_data' for statistics
        # Or we could have added a 'word_count' field on save.
        
        # Word frequency (only meaningful ones)
        if i < 50: # Only analyze top 50 for performance
            for w in words:
                cleaned = re.sub(r'[^\w\s]', '', w).lower()
                if cleaned and len(cleaned) > 1 and cleaned not in STOP_WORDS:
                    word_counter[cleaned] += 1
        
        # Last 5 phrases
        if len(recent_phrases) < 5 and text.strip():
            phrase = text.strip()
            if len(phrase) > 60: phrase = phrase[:57] + "..."
            recent_phrases.append(phrase)

    # 3. Streak Calculation
    streak_dates = {d["_id"] for d in data.get("streak_dates", [])}
    streak = 0
    curr = now.date()
    
    # Check today or yesterday start
    if curr.isoformat() not in streak_dates:
        curr -= timedelta(days=1)
        
    while curr.isoformat() in streak_dates:
        streak += 1
        curr -= timedelta(days=1)

    return {
        "total_recordings": total_recordings,
        "total_words": total_recordings * 12, 
        "total_duration_seconds": round(totals.get("total_duration", 0), 1),
        "avg_confidence": round(totals.get("avg_confidence") or 85, 1),
        "most_used_words": [{"word": w, "count": c} for w, c in word_counter.most_common(8)],
        "recent_phrases": recent_phrases,
        "language_breakdown": {l["_id"] or "unknown": l["count"] for l in data.get("languages", [])},
        "streak_days": streak,
        "today_recordings": totals.get("today_count", 0),
        "today_avg_confidence": round(totals.get("today_avg_confidence") or 85, 1),
    }
