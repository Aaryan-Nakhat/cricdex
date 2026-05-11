# commentary_translate

Live commentary translation into IN regional languages — with optional voice-cloned target-language audio (final-feature milestone).

## Sources

- ESPNCricinfo + Cricbuzz English ball-by-ball commentary feeds (text).
- YouTube broadcast audio of English commentary (for voice cloning reference).

## Targets

Hindi, Tamil, Bengali, Urdu, Sinhala, Marathi, Telugu, Kannada (priority order).

## Pipeline

1. **Text translate** — Gemini Flash with cricket-glossary system prompt.
2. **Stream** — WebSocket text feed per language + Telegram channel per language.

## Voice cloning add-on (final feature — ship last)

1. **Diarize** broadcast audio into commentator speaker turns (pyannote, free).
2. **Clone** each commentator's voice once from 6–30 s reference clip (XTTS-v2 / F5-TTS / OpenVoice — all free OSS, multilingual support).
3. **TTS in target language** using cloned voice (XTTS-v2 supports Hindi + many Indic langs; AI4Bharat IndicTTS for stronger Indic accents).
4. **Audio stream** — encoded Opus → WebRTC + browser audio element + Telegram voice msg.

### Why last

Heavy infra (GPU inference, audio streaming), high creative-rights sensitivity (commentator likeness rights), and only meaningful once translation quality + audience is proven. Ship text-only translation P1, voice-clone P3.

### Notes on rights

Cloning a real commentator's voice without consent is risky. Plan: ship with explicit on/off toggle per commentator + an "AI cricket voice" generic default (royalty-free synthetic voice). Reach out to retired commentators (Harsha Bhogle, Sunil Gavaskar, Ramiz Raja) for opt-in licensing before launching cloned voices.
