# BackTPal MVP - Basic Vosk Transcription

This starter setup gives you live microphone transcription with Vosk on Windows, integrated with Notion for trade logging.

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
pip install vosk requests python-dotenv
```

## 3) Configure Notion Integration (Optional)

To automatically log trades to your Notion journal:

1. **Get your Notion API token:**
   - Go to https://www.notion.so/my-integrations
   - Click "Create new integration"
   - Name it "BackTPal"
   - Copy your API token (starts with `ntn_`)

2. **Find your database ID:**
   - Open your Trader's Master Journal in Notion
   - Copy the URL: `https://notion.so/{DATABASE_ID}?v=...`
   - Extract the `DATABASE_ID` part

3. **Set up environment variables:**
   - Copy `.env.example` to `.env`:
     ```powershell
     Copy-Item .env.example .env
     ```
   - Edit `.env` and fill in:
     ```
     NOTION_API_TOKEN=ntn_your_token_here
     NOTION_DATABASE_ID=your_database_id_here
     TRADE_ACCOUNT=YourAccount
     TRADE_MODEL=YourStrategy
     TRADE_SESSION=YourSession
     ```

4. **Share your database with BackTPal:**
   - In Notion, go to your journal database
   - Click the "Connections" icon (top right)
   - Click "Add connection" and select your "BackTPal" integration

## 4) Run voice command flow

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
- The full assembled description is printed
- **If Notion is configured**, the trade is automatically added to your journal
- TTS confirms: `Trade logged to Notion`

Press `Ctrl+C` to stop.

## How It Works

1. **Voice Command Recognition**: Listens for "Record description" using offline Vosk STT
2. **Local Text-to-Speech**: Uses pyttsx3 (Windows SAPI5 or eSpeak) for confirmations
3. **Automatic Silence Detection**: 4-second silence triggers end of recording
4. **Notion Integration**: Uploads description and trade metadata to your journal (optional)


## Notes

- Make sure your default microphone is configured in Windows Sound settings.
- You can swap model size/language in `transcribe_live.py` by changing `MODEL_NAME`.
