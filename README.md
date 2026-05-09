# BackTPal MVP - Basic Vosk Transcription

This starter setup gives you live microphone transcription with Vosk on Windows.

## 1) Create and activate a virtual environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 2) Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If `PyAudio` fails to install, try:

```powershell
pip install pipwin
pipwin install pyaudio
pip install vosk requests
```

## 3) Run voice command flow

```powershell
python transcribe_live.py
```

On first run, the script downloads this model automatically:
- `vosk-model-small-en-us-0.15`

Then it starts listening for the command:
- `Record description`

When command is detected:
- Local TTS (pyttsx3) says: `Recording description`
- Your speech is captured as description text
- After 4 seconds of silence, recording stops automatically
- The full assembled description is printed and marked ready to upload

Press `Ctrl+C` to stop.

## Notes

- Make sure your default microphone is configured in Windows Sound settings.
- You can swap model size/language in `transcribe_live.py` by changing `MODEL_NAME`.
