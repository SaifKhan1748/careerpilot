"""
CareerPilot - voice utilities (Phase 6)

TTS: pyttsx3 - free, offline, no API cost. Reads questions aloud.
     Fails silently if unavailable - voice output is a nice-to-have.

STT: Groq Whisper - genuinely free tier. Either live mic recording
     (press Enter to start/stop) or a pre-recorded file path.
"""

import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


def speak(text: str) -> None:
    """Best-effort TTS. Never raises - if it fails, just skip voice output."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    except Exception:
        pass


def transcribe_audio_file(file_path: str) -> str:
    """Transcribes a real audio file via Groq's free Whisper endpoint."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No audio file found at: {file_path}")

    with open(file_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            file=(file_path, f.read()),
            model="whisper-large-v3-turbo",
            response_format="json",
        )

    return transcription.text


def record_live_answer() -> str:
    """
    Live mic recording: press Enter to start, speak, press Enter again
    to stop. Saves to a temp WAV file, transcribes via free Whisper,
    returns the text. Any failure raises - caller falls back to typing.
    """
    import sounddevice as sd
    import numpy as np
    import wave
    import tempfile

    print("Press Enter to START recording...")
    input()
    print("Recording - press Enter again to STOP.")

    samplerate = 16000
    frames = []

    def callback(indata, frame_count, time_info, status):
        frames.append(indata.copy())

    stream = sd.InputStream(samplerate=samplerate, channels=1, dtype="int16", callback=callback)
    stream.start()
    input()
    stream.stop()
    stream.close()

    if not frames:
        raise RuntimeError("No audio captured - check your microphone is connected and not muted.")

    audio_data = np.concatenate(frames, axis=0)

    tmp_path = os.path.join(tempfile.gettempdir(), "careerpilot_answer.wav")
    with wave.open(tmp_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(audio_data.tobytes())

    print("Transcribing...")
    text = transcribe_audio_file(tmp_path)
    os.remove(tmp_path)
    return text