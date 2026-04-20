import numpy as np
import av
import torch
import tempfile
import os
import traceback
import asyncio
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
import httpx
from app.utils.auth_middleware import require_auth, get_current_user_id
from app.utils.supabase_storage import upload_audio
from app.models.transcription import create_audio_clip, get_clips_by_user, delete_audio_clip

router = APIRouter(prefix="", tags=["Transcription"])

# --- Whisper Model Configuration ---
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL_NAME", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16" if WHISPER_DEVICE == "cuda" else "int8")
WHISPER_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "4"))
WHISPER_DOWNLOAD_ROOT = os.getenv("WHISPER_DOWNLOAD_ROOT", "./models")
HF_SPACE_URL = os.getenv("HF_SPACE_URL")
SKIP_LOCAL_WHISPER = os.getenv("SKIP_LOCAL_WHISPER", "false").lower() == "true"

# Global variable for lazy loading the model
_local_whisper_model = None

def get_local_whisper_model():
    """
    Lazy loads the Whisper model only when needed.
    This saves significant RAM on Render's free tier.
    """
    global _local_whisper_model
    if _local_whisper_model is None:
        from faster_whisper import WhisperModel
        print(f"--- Initializing local Whisper Model ({WHISPER_MODEL_NAME}) ---")
        _local_whisper_model = WhisperModel(
            WHISPER_MODEL_NAME, 
            device=WHISPER_DEVICE, 
            compute_type=WHISPER_COMPUTE_TYPE,
            download_root=WHISPER_DOWNLOAD_ROOT,
            cpu_threads=WHISPER_CPU_THREADS,
            num_workers=1 # Reduced for lower memory footprint
        )
    return _local_whisper_model


@router.post("/transcribe", dependencies=[Depends(require_auth)])
async def transcribe_audio(file: UploadFile = File(...), user_id: str = Depends(get_current_user_id)):
    tmp_path = None
    clean_wav_path = None
    try:
        suffix = os.path.splitext(file.filename)[-1] or ".wav"
        content = await file.read()
        if len(content) == 0:
            return {"error": "empty_file", "detail": "The audio file received was empty."}

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='wb') as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        audio = await asyncio.to_thread(decode_audio_to_numpy, tmp_path)
        sr = 16000
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
            tmp_path = None

        import soundfile as sf
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav", mode='wb') as clean_tmp:
            clean_wav_path = clean_tmp.name
            sf.write(clean_wav_path, audio, sr)

        with open(clean_wav_path, 'rb') as f:
            clean_content = f.read()

        text_result, audio_url = await asyncio.gather(
            decode_whisper(clean_content, audio),
            upload_audio(clean_content, user_id, ".wav")
        )

        for p in [tmp_path, clean_wav_path]:
            if p and os.path.exists(p):
                os.remove(p)
        tmp_path = None
        clean_wav_path = None

        text = text_result.strip()
        duration = float(len(audio) / sr)

        clip_data = {
            "user_id": user_id, "audio_url": audio_url, "transcript": text,
            "corrected_transcript": text, "speech_type": "unknown",
            "duration_seconds": duration, "processing_status": "completed",
            "device_type": "mobile",
            "language": "fil" if any(kw in text.lower() for kw in ["tagalog", "filipino", "po", "opo"]) else "en",
        }
        return await create_audio_clip(clip_data)

    except Exception as e:
        for p in [tmp_path, clean_wav_path]:
            if p and os.path.exists(p):
                os.remove(p)
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


def decode_audio_to_numpy(path):
    container = av.open(path)
    stream = container.streams.audio[0]
    resampler = av.AudioResampler(format='fltp', layout='mono', rate=16000)
    frames = []
    for frame in container.decode(stream):
        resampled = resampler.resample(frame)
        if resampled:
            for rf in resampled:
                frames.append(rf.to_ndarray().flatten())
    final = resampler.resample(None)
    if final:
        for rf in final:
            frames.append(rf.to_ndarray().flatten())
    container.close()
    if not frames:
        raise Exception("Could not decode any audio frames from the file.")
    return np.concatenate(frames).astype(np.float32)


async def decode_whisper(audio_binary, audio_numpy):
    """
    Tries remote transcription via Hugging Face Space first,
    falls back to local Whisper model if remote fails.
    """
    if HF_SPACE_URL:
        try:
            print(f"--- Attempting remote transcription at {HF_SPACE_URL} ---")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    HF_SPACE_URL,
                    files={"file": ("audio.wav", audio_binary, "audio/wav")},
                    timeout=30.0
                )
                if response.status_code == 200:
                    text = response.json().get("text", "").strip()
                    if text:
                        print("--- Remote transcription successful ---")
                        return text
                else:
                    print(f"--- Remote transcription failed with status {response.status_code} ---")
        except Exception as e:
            print(f"--- Remote transcription error: {str(e)} ---")

    # Fallback to local Whisper model
    if SKIP_LOCAL_WHISPER:
        print("--- Local fallback skipped due to SKIP_LOCAL_WHISPER=true ---")
        return "Transcription error: Remote service unavailable."

    print("--- Using local Whisper fallback ---")
    local_model = get_local_whisper_model()
    segments, _ = await asyncio.to_thread(
        local_model.transcribe, audio_numpy, beam_size=1, language="tl", task="transcribe"
    )
    return " ".join([s.text for s in segments]).strip()


@router.get("/history", dependencies=[Depends(require_auth)])
async def get_history(user_id: str = Depends(get_current_user_id), skip: int = 0, limit: int = 50):
    try:
        return await get_clips_by_user(user_id, skip=skip, limit=limit)
    except Exception as e:
        return {"error": "history_fetch_error", "detail": str(e)}


@router.delete("/history/{clip_id}", dependencies=[Depends(require_auth)])
async def delete_history_item(clip_id: str, user_id: str = Depends(get_current_user_id)):
    try:
        success = await delete_audio_clip(clip_id)
        return {"message": "Deleted successfully"} if success else {"error": "delete_failed", "detail": "Item not found"}
    except Exception as e:
        return {"error": "delete_error", "detail": str(e)}
