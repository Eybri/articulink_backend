import os
import torch
from faster_whisper import WhisperModel

def download_model():
    model_name = os.getenv("WHISPER_MODEL_NAME", "small")
    device = "cpu" # Download on CPU by default for portability
    compute_type = "int8"
    download_root = "./models"
    
    print(f"--- Pre-downloading Whisper Model: {model_name} ---")
    
    # This will download the model to download_root if it doesn't exist
    model = WhisperModel(
        model_name, 
        device=device, 
        compute_type=compute_type, 
        download_root=download_root
    )
    
    print(f"--- Model {model_name} successfully cached in {download_root} ---")

if __name__ == "__main__":
    download_model()
