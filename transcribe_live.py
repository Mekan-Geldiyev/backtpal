import json
import json
import os
import re
import shutil
import sys
import threading
import time
import winsound
import zipfile
from pathlib import Path

import mss
import pyaudio
import requests
from dotenv import load_dotenv
from vosk import KaldiRecognizer, Model
from notion_integration import NotionTradeLogger, load_notion_credentials

load_dotenv()

MODEL_NAME = os.getenv("VOSK_MODEL_NAME", "vosk-model-en-us-0.22")
MODEL_ZIP = f"{MODEL_NAME}.zip"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_ZIP}"
BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / MODEL_NAME
ZIP_PATH = BASE_DIR / MODEL_ZIP
DESCRIPTION_COMMANDS = ("description", "descriptoin")
TITLE_COMMANDS = ("title", "titel")
PROFIT_COMMANDS = ("profit", "profits", "pnl", "p and l", "profit and loss")
NEW_TRADE_COMMANDS = ("record", "log trade", "new trade", "start trade", "log new trade")
SILENCE_SECONDS = 1.0
SCREENSHOT_DIR = BASE_DIR / "screenshots"


def download_file(url: str, out_path: Path) -> None:
    with requests.get(url, stream=True, timeout=300) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 1024 * 1024

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


def remove_model_artifacts() -> None:
    try:
        if MODEL_DIR.exists():
            shutil.rmtree(MODEL_DIR)
    except OSError:
        pass

    try:
        ZIP_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def resolve_model_dir(base_dir: Path) -> Path:
    """Resolve common extraction layouts, including nested model folders."""
    nested_dir = base_dir / MODEL_NAME
    if nested_dir.exists() and nested_dir.is_dir():
        return nested_dir
    return base_dir


def ensure_model(force_redownload: bool = False) -> Path:
    if force_redownload:
        print("Cleaning existing model artifacts for a fresh download...")
        remove_model_artifacts()

    if MODEL_DIR.exists() and not force_redownload:
        resolved = resolve_model_dir(MODEL_DIR)
        print(f"Using model: {MODEL_NAME}")
        return resolved

    print(f"Model not found. Downloading {MODEL_NAME}...")
    if MODEL_NAME == "vosk-model-en-us-0.22":
        print("This is the full-size model (~1.8GB). First download can take a while.")
    download_file(MODEL_URL, ZIP_PATH)

    print("Extracting model...")
    try:
        with zipfile.ZipFile(ZIP_PATH, "r") as zf:
            bad_file = zf.testzip()
            if bad_file is not None:
                raise zipfile.BadZipFile(f"CRC check failed for {bad_file}")
            zf.extractall(BASE_DIR)
    except (zipfile.BadZipFile, RuntimeError):
        print("Downloaded model archive appears corrupted. Retrying with a clean download...")
        remove_model_artifacts()
        raise

    try:
        ZIP_PATH.unlink(missing_ok=True)
    except OSError:
        pass

    if not MODEL_DIR.exists():
        raise RuntimeError("Model extraction failed. Could not find extracted model folder.")

    return resolve_model_dir(MODEL_DIR)


BEEP_READY   = (880, 120)   # high short - ready to speak
BEEP_SAVED   = (660, 80)    # mid short - field saved
BEEP_DONE    = (880, 80)    # two-tone done sequence
BEEP_ERROR   = (300, 200)   # low - error


def beep(freq: int, duration_ms: int) -> None:
    winsound.Beep(freq, duration_ms)


def beep_ready() -> None:
    beep(*BEEP_READY)


def beep_saved() -> None:
    beep(*BEEP_SAVED)


def beep_done() -> None:
    beep(660, 80)
    time.sleep(0.05)
    beep(880, 120)


def beep_error() -> None:
    beep(*BEEP_ERROR)


def is_record_description_command(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(re.search(rf"\b{re.escape(command)}\b", normalized) for command in DESCRIPTION_COMMANDS)


def is_record_title_command(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(re.search(rf"\b{re.escape(command)}\b", normalized) for command in TITLE_COMMANDS)


def is_record_profit_command(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(re.search(rf"\b{re.escape(command)}\b", normalized) for command in PROFIT_COMMANDS)


def is_new_trade_command(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(phrase in normalized for phrase in NEW_TRADE_COMMANDS)


def is_meaningful_fragment(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    if not normalized:
        return False

    filler_words = {
        "the",
        "a",
        "an",
        "uh",
        "um",
        "hmm",
        "mm",
        "ah",
        "er",
        "yeah",
        "okay",
        "ok",
    }
    tokens = normalized.split()
    if len(tokens) == 1 and tokens[0] in filler_words:
        return False

    return True


def words_to_number(text: str) -> float | None:
    """Convert spoken number words into a numeric value."""
    units = {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
    }
    tens = {
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
    }
    scales = {"hundred": 100, "thousand": 1000, "million": 1000000}

    tokens = [t for t in text.lower().replace("-", " ").split() if t]
    if not tokens:
        return None

    sign = 1
    if tokens and tokens[0] in {"minus", "negative"}:
        sign = -1
        tokens = tokens[1:]

    # Handle digit-like sequences spoken as individual numbers: "one two eight nine" -> 1289.
    if tokens and all(token in units and units[token] < 10 for token in tokens):
        return float(sign * int("".join(str(units[token]) for token in tokens)))

    # Handle compact hundreds style: "two eighty five" -> 285.
    if len(tokens) == 3 and tokens[0] in units and units[tokens[0]] < 10:
        first = units[tokens[0]]
        tail = 0
        if tokens[1] in tens and tokens[2] in units and units[tokens[2]] < 10:
            tail = tens[tokens[1]] + units[tokens[2]]
            return float(sign * (first * 100 + tail))

    total = 0
    current = 0
    used = False
    i = 0

    while i < len(tokens):
        token = tokens[i]

        if token == "and":
            i += 1
            continue

        if token in units:
            current += units[token]
            used = True
            i += 1
            continue

        if token in tens:
            current += tens[token]
            used = True
            i += 1
            continue

        if token == "point":
            frac_digits = []
            for frac_token in tokens[i + 1 :]:
                if frac_token in units and units[frac_token] < 10:
                    frac_digits.append(str(units[frac_token]))
                elif frac_token.isdigit():
                    frac_digits.append(frac_token)
                else:
                    break

            if not frac_digits:
                return None

            base = total + current
            return sign * float(f"{base}.{''.join(frac_digits)}")

        if token in scales:
            scale = scales[token]
            if token == "hundred":
                if current == 0:
                    current = 1
                current *= scale
            else:
                if current == 0:
                    current = 1
                total += current * scale
                current = 0
            used = True
            i += 1
            continue

        if token.isdigit():
            current += int(token)
            used = True
            i += 1
            continue

        return None

    if not used:
        return None

    return float(sign * (total + current))


def parse_spoken_profit(text: str) -> float | None:
    normalized = text.lower()
    normalized = normalized.replace(",", " ")
    normalized = normalized.replace("$", " ")
    normalized = normalized.replace("dollars", " ")
    normalized = normalized.replace("dollar", " ")
    normalized = normalized.replace("bucks", " ")
    normalized = normalized.replace("usd", " ")
    normalized = normalized.replace("pnl", " ")
    normalized = normalized.replace("profit", " ")

    allowed_words = {
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "point",
        "and",
        "minus",
        "negative",
    }

    filtered_tokens = []
    for token in normalized.split():
        if token in allowed_words:
            filtered_tokens.append(token)
            continue
        if re.fullmatch(r"-?\d+(?:\.\d+)?", token):
            filtered_tokens.append(token)

    normalized = " ".join(filtered_tokens)
    if not normalized:
        return None

    sign = 1
    if normalized.startswith("minus "):
        sign = -1
        normalized = normalized[len("minus ") :]
    elif normalized.startswith("negative "):
        sign = -1
        normalized = normalized[len("negative ") :]

    # Fast path: direct numeric content like -125.5.
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        word_value = words_to_number(normalized)
        if word_value is None:
            return None
        return float(sign * word_value)

    numeric = float(match.group(0))
    if sign == -1 and numeric > 0:
        numeric = -numeric
    return numeric


def capture_screenshot() -> Path | None:
    """Capture a full-screen screenshot and return its local file path."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    timestamp = int(time.time())
    out_path = SCREENSHOT_DIR / f"trade_{timestamp}.png"
    try:
        with mss.mss() as sct:
            sct.shot(output=str(out_path))
        return out_path
    except Exception as exc:
        print(f"Could not capture screenshot: {exc}")
        return None


def listen_loop() -> None:
    retry_used = False
    while True:
        try:
            model_path = ensure_model(force_redownload=retry_used)
            print("Loading Vosk model into memory...")
            model = Model(str(model_path))
            break
        except Exception as exc:
            if retry_used:
                raise RuntimeError(
                    "Model initialization failed after retry. "
                    "Please check your internet connection and disk space, then run again."
                ) from exc

            print(f"Model initialization failed: {exc}")
            print("Retrying model download and load one time...")
            retry_used = True

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
    chunks: list[str] = []
    last_speech_time = 0.0
    
    # Trade fields accumulated across recordings
    trade_title = ""
    trade_description = ""
    trade_profit: float | None = None
    trade_screenshot_path: Path | None = None

    stream = audio.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=sample_rate,
        input=True,
        frames_per_buffer=8000,
    )

    print("\nSay one of these to start logging a trade:")
    print("  - 'record'  /  'new trade'  /  'log trade'  /  'record description'")
    print("Flow: trigger → [beep] describe → [beep] profit → uploads in background")
    print("\nPress Ctrl+C to stop.\n")

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
                    if is_record_description_command(text) or is_new_trade_command(text):
                        trade_screenshot_path = capture_screenshot()
                        if trade_screenshot_path:
                            print(f"Screenshot captured: {trade_screenshot_path}")
                        beep_ready()
                        mode = "recording_description"
                        chunks = []
                        last_speech_time = time.monotonic()
                        recognizer = KaldiRecognizer(model, sample_rate)
                        print("Listening for description...")
                else:
                    if is_meaningful_fragment(text):
                        chunks.append(text)
                        last_speech_time = time.monotonic()
                        print(f"Final ({mode}): {text}")
                    else:
                        print(f"Ignored filler ({mode}): {text}")
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                if mode == "command":
                    if partial:
                        print(f"\rPartial (command): {partial:<80}", end="", flush=True)
                else:
                    if partial:
                        if is_meaningful_fragment(partial):
                            last_speech_time = time.monotonic()
                        print(f"\rPartial ({mode}): {partial:<66}", end="", flush=True)

                    if chunks and (time.monotonic() - last_speech_time) >= SILENCE_SECONDS:
                        captured = " ".join(chunks).strip()
                        chunks = []
                        recognizer = KaldiRecognizer(model, sample_rate)

                        if mode == "recording_description":
                            trade_description = captured
                            print(f"\n\nDescription: {trade_description}")
                            beep_ready()
                            mode = "recording_profit"
                            last_speech_time = time.monotonic()
                            print("Listening for profit...")

                        elif mode == "recording_profit":
                            parsed_profit = parse_spoken_profit(captured)
                            if parsed_profit is None:
                                print("\n\nCould not parse profit. Say a number, e.g. minus 150 or 220.")
                                beep_error()
                                last_speech_time = time.monotonic()
                                # Stay in recording_profit
                            else:
                                trade_profit = parsed_profit
                                print(f"Profit: {trade_profit}")
                                beep_done()
                                mode = "command"
                                last_speech_time = 0.0

                                # Snapshot fields for background thread
                                _title       = trade_title
                                _description = trade_description
                                _profit      = trade_profit
                                _screenshot  = trade_screenshot_path

                                # Reset immediately so next trade can start
                                trade_title = ""
                                trade_description = ""
                                trade_profit = None
                                trade_screenshot_path = None
                                print("\nReady. Say 'record' to start next trade.\n")

                                # Upload in background
                                def _upload(title, description, profit, screenshot_path):
                                    auto_title = title or f"Trade {time.strftime('%H:%M')}"
                                    if notion_logger:
                                        try:
                                            result = notion_logger.add_trade(
                                                title=auto_title,
                                                description=description,
                                                profit=profit,
                                                symbol=os.getenv("TRADE_SYMBOL"),
                                                account=os.getenv("TRADE_ACCOUNT"),
                                                model=os.getenv("TRADE_MODEL"),
                                                session=os.getenv("TRADE_SESSION"),
                                                screenshot_path=screenshot_path,
                                            )
                                            notion_url = result.get("notion_url")
                                            print(f"\n✓ Trade logged: {notion_url or 'no URL'}\n")
                                        except Exception as exc:
                                            print(f"\n✗ Notion upload failed: {exc}\n")
                                    else:
                                        print("\nNotion not configured. Trade captured but not uploaded.\n")

                                threading.Thread(
                                    target=_upload,
                                    args=(_title, _description, _profit, str(_screenshot) if _screenshot else None),
                                    daemon=True,
                                ).start()
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
