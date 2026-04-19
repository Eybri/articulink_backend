# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV WHISPER_MODEL_NAME small
ENV WHISPER_DEVICE cpu
ENV WHISPER_COMPUTE_TYPE int8
ENV WHISPER_DOWNLOAD_ROOT /app/models

# Set the working directory in the container
WORKDIR /app

# Install system dependencies needed for faster-whisper and audio processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libavcodec-extra \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Pre-download the Whisper model during build to minimize cold start time
RUN python scripts/download_model.py

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
