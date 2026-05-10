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

To automatically log trades into your Trades database:

1. **Get your Notion API token:**
   - Go to https://www.notion.so/my-integrations
   - Click "Create new integration"
   - Name it "BackTPal"
   - Copy your API token (starts with `ntn_`)

2. **Find your Trades database ID:**
   - Open your Trades database in Notion
   - Copy the URL: `https://www.notion.so/{DATABASE_ID}?v=...`
   - Extract the `DATABASE_ID` part

3. **Set up environment variables:**
   - Copy `.env.example` to `.env`:
     ```powershell
     Copy-Item .env.example .env
     ```
   - Edit `.env` and fill in:
     ```
     NOTION_API_TOKEN=ntn_your_token_here
   NOTION_TRADES_DATABASE_ID=26fc63a3815e8108bbafdf6bd8bc7d4c
   TRADE_SYMBOL=MNQ!
     TRADE_ACCOUNT=YourAccount
     TRADE_MODEL=YourStrategy
     TRADE_SESSION=YourSession
     ```

4. **Share your database with BackTPal:**
   - Open the Trades database in Notion
   - Add the BackTPal integration to that database/page

## 4) Run voice command flow

```powershell
python transcribe_live.py
```

On first run, the script downloads this model automatically:
- `vosk-model-small-en-us-0.15`

Then it starts listening for the commands:
- `Record title`
- `Record description`
- `Record pnl`

When command is detected:
- Local TTS (pyttsx3) confirms which field is being recorded
- Your speech is captured into that field
- After 4 seconds of silence, recording stops automatically
- Once `title`, `description`, and `pnl` are all captured, the trade is uploaded to Notion
- **If Notion is configured**, the trade is automatically added as a row in your Trades database
- TTS confirms: `Trade logged to Notion`
- The app stays running so you can record the next trade without restarting

Press `Ctrl+C` to stop.

## How It Works

1. **Voice Command Recognition**: Listens for "Record description" using offline Vosk STT
2. **Local Text-to-Speech**: Uses pyttsx3 (Windows SAPI5 or eSpeak) for confirmations
3. **Automatic Silence Detection**: 4-second silence triggers end of recording
4. **Notion Integration**: Creates rows in your Trades database and fills fields like Account, Model, Symbol, Session, Entry / Exit Date, Narrative, and Actual RR Achieved when those properties exist

## Outcome Parsing

BackTPal counts outcome words in the spoken description:
- More `win` words than `loss` words sets `Actual RR Achieved` to `1`
- More `loss`, `lose`, or `lost` words sets it to `-1`
- `breakeven` sets it to `0` when it wins the word count check


## Notes

- Make sure your default microphone is configured in Windows Sound settings.
- You can swap model size/language in `transcribe_live.py` by changing `MODEL_NAME`.
