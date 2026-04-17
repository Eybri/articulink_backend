from fastapi import APIRouter, Depends, HTTPException
from app.utils.auth_middleware import require_auth, get_current_user_id
from app.models.transcription import get_clips_by_user
from app.utils.gemini import generate_speech_analysis

router = APIRouter(prefix="/analysis", tags=["Analysis"])

@router.get("/speech-performance", dependencies=[Depends(require_auth)])
async def get_speech_analysis(user_id: str = Depends(get_current_user_id)):
    """
    Descriptive analysis of user's speech performance using Gemini.
    """
    try:
        # Fetch last 20 records to provide context for AI
        records = await get_clips_by_user(user_id, limit=20)
        
        if not records or len(records) < 3:
            return {
                "report": "Not enough data yet. Please record at least 3-5 times to get a personalized speech analysis report!",
                "status": "insufficient_data"
            }
            
        report = await generate_speech_analysis(records)
        
        return {
            "report": report,
            "status": "success",
            "record_count": len(records)
        }
        
    except Exception as e:
        print(f"Analysis API Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate speech analysis.")
