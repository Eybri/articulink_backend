from fastapi import APIRouter, Depends, HTTPException
from app.utils.gemini import generate_gemini_reply
from app.models.user_memory import get_user_memory, create_or_update_memory
from app.models.chat import save_chat_message, get_chat_history, delete_chat_history, delete_specific_message
from app.utils.auth_middleware import require_auth, get_current_user_id
from typing import List, Dict

router = APIRouter(
    prefix="/api/v1/chatbot",
    tags=["Chatbot"],
    dependencies=[Depends(require_auth)]
)


@router.post("/message")
async def send_message(payload: Dict, user_id: str = Depends(get_current_user_id)):
    """Stateful chat endpoint with DB persistence and AI memory."""
    messages: List[Dict[str, str]] = payload.get("messages")
    if not messages:
        raise HTTPException(status_code=400, detail="Messages required")

    user_msg = messages[-1]
    if user_msg["role"] == "user":
        await save_chat_message(user_id, "user", user_msg["content"])

    memory = await get_user_memory(user_id)
    user_summary = memory["summary"] if memory else None

    reply = await generate_gemini_reply(messages=messages[-8:], user_summary=user_summary)
    await save_chat_message(user_id, "assistant", reply)

    if len(messages) % 15 == 0:
        summary_prompt = "Summarize the user's communication needs, struggles, and goals in 2–3 sentences."
        summary = await generate_gemini_reply(
            messages + [{"role": "assistant", "content": summary_prompt}],
            user_summary
        )
        await create_or_update_memory(user_id, summary)

    return {"role": "assistant", "content": reply}


@router.get("/history")
async def get_history(user_id: str = Depends(get_current_user_id)):
    return await get_chat_history(user_id)


@router.delete("/history")
async def clear_history(user_id: str = Depends(get_current_user_id)):
    count = await delete_chat_history(user_id)
    return {"message": f"Deleted {count} messages"}


@router.delete("/history/{timestamp}")
async def delete_message(timestamp: str, user_id: str = Depends(get_current_user_id)):
    success = await delete_specific_message(user_id, timestamp)
    if not success:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"message": "Message deleted successfully"}
