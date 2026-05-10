import json
import os
import sys
import time
import zipfile
from pathlib import Path

import pyaudio
import pyttsx3
import requests
from dotenv import load_dotenv
from vosk import KaldiRecognizer, Model

from notion_integration import NotionTradeLogger, load_notion_credentials

load_dotenv()

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_ZIP = f"{MODEL_NAME}.zip"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_ZIP}"
BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / MODEL_NAME
ZIP_PATH = BASE_DIR / MODEL_ZIP
COMMAND_PHRASES = ("record description", "record descriptoin")
SILENCE_SECONDS = 4.0


def download_file(url: str, out_path: Path) -> None:
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 1024 * 64

        with out_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                file.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int((downloaded / total) * 100)
                    print(f"\rDownloading model... {pct}%", end="", flush=True)

    if total > 0:
        print("\rDownloading model... 100%")


def ensure_model() -> Path:
    if MODEL_DIR.exists():
        return MODEL_DIR

    print(f"Model not found. Downloading {MODEL_NAME}...")
    download_file(MODEL_URL, ZIP_PATH)

    print("Extracting model...")
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        zf.extractall(BASE_DIR)

    try:
        ZIP_PATH.unlink(missing_ok=True)
    except OSError:
        pass

    if not MODEL_DIR.exists():
        raise RuntimeError("Model extraction failed. Could not find extracted model folder.")

    return MODEL_DIR


def build_tts_engine() -> pyttsx3.Engine:
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")

    female_voice_id = None
    for voice in voices:
        details = f"{voice.id} {voice.name}".lower()
        if "female" in details or "zira" in details or "hazel" in details:
            female_voice_id = voice.id
            break

    if female_voice_id is not None:
        engine.setProperty("voice", female_voice_id)

    engine.setProperty("rate", 175)
    return engine


def speak(engine: pyttsx3.Engine, text: str) -> None:
    engine.say(text)
    engine.runAndWait()


def is_record_description_command(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(phrase in normalized for phrase in COMMAND_PHRASES)


def listen_loop() -> None:
    model_path = ensure_model()
    print("Loading Vosk model into memory...")
    model = Model(str(model_path))
    tts_engine = build_tts_engine()

    # Initialize Notion integration if credentials are available
    notion_logger = None
    try:
        api_token, database_id = load_notion_credentials()
        if api_token and database_id:
            notion_logger = NotionTradeLogger(api_token, database_id)
            print("✓ Connected to Notion")
        else:
            print("⚠ Notion credentials not configured (optional)")
    except ValueError:
        print("⚠ Notion credentials not configured (optional)")
    except Exception as exc:
        print(f"⚠ Could not connect to Notion: {exc}")

    audio = pyaudio.PyAudio()

    default_input = audio.get_default_input_device_info()
    sample_rate = int(default_input["defaultSampleRate"])

    print(f"Using input device: {default_input['name']}")
    print(f"Sample rate: {sample_rate}")

    recognizer = KaldiRecognizer(model, sample_rate)
    mode = "command"
    description_chunks: list[str] = []
    last_speech_time = 0.0

    stream = audio.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=sample_rate,
        input=True,
        frames_per_buffer=8000,
    )

    print("\nSay 'Record description' to start. Press Ctrl+C to stop.\n")

    try:
        while True:
            data = stream.read(4000, exception_on_overflow=False)
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").strip()
                if not text:
                    continue

                if mode == "command":
                    print(f"Final (command): {text}")
                    if is_record_description_command(text):
                        speak(tts_engine, "Recording description")
                        mode = "recording"
                        description_chunks = []
                        last_speech_time = time.monotonic()
                        recognizer = KaldiRecognizer(model, sample_rate)
                        print("Recording... speak now.")
                else:
                    description_chunks.append(text)
                    last_speech_time = time.monotonic()
                    print(f"Final (description): {text}")
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                if mode == "command":
                    if partial:
                        print(f"\rPartial (command): {partial:<80}", end="", flush=True)
                else:
                    if partial:
                        last_speech_time = time.monotonic()
                        print(f"\rPartial (description): {partial:<66}", end="", flush=True)

                    if description_chunks and (time.monotonic() - last_speech_time) >= SILENCE_SECONDS:
                        description = " ".join(description_chunks).strip()
                        print("\n\nDescription complete:")
                        print(description)
                        speak(tts_engine, "Description captured")

                        # Upload to Notion if configured
                        if notion_logger:
                            try:
                                result = notion_logger.add_trade(
                                    description=description,
                                    symbol=os.getenv("TRADE_SYMBOL"),
                                    account=os.getenv("TRADE_ACCOUNT"),
                                    model=os.getenv("TRADE_MODEL"),
                                    session=os.getenv("TRADE_SESSION"),
                                )
                                speak(tts_engine, "Trade logged to Notion")
                                
                                # Display the Notion URL
                                notion_url = result.get("notion_url")
                                if notion_url:
                                    print(f"✓ Trade page: {notion_url}")

                            except Exception as exc:
                                print(f"Failed to log trade to Notion: {exc}")
                                speak(tts_engine, "Error uploading to Notion")
                        else:
                            print("Notion is not configured. Skipping upload.")

                        mode = "command"
                        description_chunks = []
                        recognizer = KaldiRecognizer(model, sample_rate)
                        last_speech_time = 0.0
                        print("\nReady for the next trade. Say 'Record description' to start again.\n")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()


def main() -> int:
    try:
        listen_loop()
        return 0
    except requests.RequestException as exc:
        print(f"Failed to download model: {exc}")
        return 1
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
