import asyncio
import io
import os
import time
import wave
import logging
import tempfile
import traceback
import httpx
import soundfile as sf
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from app.utils import tokens
from app.models.user import get_user_by_id
from app.routers.transcribe import decode_audio_to_numpy

# Configure logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Streaming Transcription"])

HF_SPACE_URL = os.getenv("HF_SPACE_URL")
# Process every 3 seconds of accumulated audio
STREAMING_CHUNK_INTERVAL = 3.0 

async def get_ws_user(token: str):
    """Validate JWT token from query parameter."""
    try:
        payload = tokens.decode_access_token(token)
        if payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        user = await get_user_by_id(user_id)
        if not user or user.get("status") == "inactive":
            return None
        return user_id
    except Exception:
        return None

class StreamManager:
    def __init__(self, websocket: WebSocket, user_id: str):
        self.websocket = websocket
        self.user_id = user_id
        # Constants for audio processing
        self.SAMPLE_RATE = 16000
        self.MIN_CHUNK_SIZE = 1600 # ~50ms of audio at 16kHz

    async def add_audio(self, data: bytes):
        """Process the incoming discrete audio chunk immediately."""
        await self.process_buffer(data)

    async def _is_ws_connected(self):
        """Helper to check if the WebSocket is in a valid state for sending."""
        return self.websocket.client_state.name == "CONNECTED"

    async def process_buffer(self, audio_chunk: bytes):
        """Decode incoming buffer and send to HF Space."""
        if not audio_chunk or len(audio_chunk) < self.MIN_CHUNK_SIZE:
            return

        try:
            # Save chunk to temp file to decode with 'av' (handles WAV headers automatically)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp.write(audio_chunk)
                tmp_path = tmp.name

            # Decode to numpy (16kHz mono)
            audio_np = await asyncio.to_thread(decode_audio_to_numpy, tmp_path)
            
            # Cleanup temp file immediately
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

            # Check RMS energy to act as Voice Activity Detection (VAD)
            # This prevents sending background noise to Whisper which causes hallucinations
            import numpy as np
            rms_energy = np.sqrt(np.mean(audio_np**2))
            if rms_energy < 0.002:  # Silence threshold
                logger.info(f"Streaming VAD: Silence detected (RMS: {rms_energy:.4f}), skipping chunk.")
                return

            # Convert numpy back to clean WAV for HF Space
            wav_io = io.BytesIO()
            sf.write(wav_io, audio_np, self.SAMPLE_RATE, format='WAV', subtype='PCM_16')
            wav_bytes = wav_io.getvalue()

            if HF_SPACE_URL:
                logger.info(f"Streaming: Sending chunk ({len(wav_bytes)} bytes) to HF for {self.user_id}")
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        HF_SPACE_URL,
                        files={"file": ("stream.wav", wav_bytes, "audio/wav")},
                        timeout=15.0
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        text = result.get("text", "").strip()
                        if text and await self._is_ws_connected():
                            await self.websocket.send_json({
                                "type": "transcript",
                                "text": text,
                                "is_final": False
                            })
                    else:
                        logger.error(f"HF Space Error ({response.status_code}): {response.text}")
        except Exception as e:
            logger.error(f"Streaming processing error for user {self.user_id}: {str(e)}")
            logger.debug(traceback.format_exc())

@router.websocket("/stream-transcribe")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """WebSocket endpoint for real-time transcription."""
    try:
        await websocket.accept()
    except Exception as e:
        logger.error(f"WebSocket accept failed: {e}")
        return
    
    user_id = await get_ws_user(token)
    if not user_id:
        try:
            if websocket.client_state.name == "CONNECTED":
                await websocket.send_json({"type": "error", "message": "Unauthorized"})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except:
            pass
        return

    logger.info(f"User {user_id} connected for streaming transcription")
    manager = StreamManager(websocket, user_id)
    
    try:
        while True:
            data = await websocket.receive_bytes()
            await manager.add_audio(data)
    except WebSocketDisconnect:
        logger.info(f"Streaming: WebSocket disconnected for user {user_id}")
    except Exception as e:
        if await manager._is_ws_connected():
            logger.error(f"Streaming: WebSocket error for user {user_id}: {e}")
    finally:
        # Final cleanup
        try:
            if await manager._is_ws_connected():
                await websocket.close()
        except:
            pass
