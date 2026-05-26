import json
import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests


LOGGER = logging.getLogger(__name__)

DATA_DIR = Path("data/transcripter")
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4",".mpeg"}
ALLOWED_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/x-m4a",
    "audio/m4a",
    "video/mp4",
}
DOWNLOAD_CONNECT_TIMEOUT = 15
DOWNLOAD_READ_TIMEOUT = 180
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
LOG_EVERY_BYTES = 5 * 1024 * 1024
FILE_PROCESSING_TIMEOUT_SECONDS = 300
FILE_POLL_INTERVAL_SECONDS = 5
DEFAULT_MODEL_NAME = "gemini-2.5-flash"
EXTRACTED_AUDIO_MIME_TYPE = "audio/mpeg"

TRANSCRIPTION_PROMPT = """ROLE
You are an Expert Transcription Editor. Your goal is to listen to the provided media file and generate a clean, verbatim, and readable transcript.

INSTRUCTIONS
Transcribe the spoken audio from the provided file.
Return Markdown only.
Remove filler words (um, ah, like, you know) and stutters while maintaining 100% factual integrity.
Organize the text into logical paragraphs based on topic shifts.
Identify and label speakers (e.g., "Speaker A", "Speaker B", "Management", "Analyst") based on the context of the call.
Preserve all numbers, dates, percentages, product names, order values, and guidance exactly as spoken.
If any speech is unclear, mark it as [inaudible] instead of guessing.
Technical Accuracy: Ensure financial and defense terms (e.g., EBITDA, QRSAM, AATRU, SSAs) are spelled correctly.
Do not summarize, interpret, or omit factual content beyond removing filler words and stutters.
"""

SUMMARY_PROMPT_TEMPLATE = """ROLE
You are a Senior Research Analyst specializing in financial analysis and the Indian equity market.

TASK
Analyze the cleaned transcript provided in the <cleaned_transcript> tags and produce a structured, high-impact summary for a data scientist's research database.

FORMAT REQUIREMENTS
Return Markdown only.
Do not invent facts that are not present in the transcript.

Sections:
1. TL;DR: A 2-3 sentence executive summary of the meeting's sentiment and core news.
2. Key Themes: A bulleted list of 3-5 main topics.
3. Action Items/Next Steps: Any future dates, guidance, or management promises mentioned and make sure you cover all the numbers mentioned in the transcript.
4. Technical Glossary: Briefly define any complex terms mentioned.
5. Signals for Research:
   - Bullish points
   - Risks/cautions
   - Watch items
6. Named Entities:
   - Company
   - Management
   - Analysts / brokers
   - Products / platforms
   - Customers / contracts if explicitly named

INPUT DATA
<cleaned_transcript>
{transcript}
</cleaned_transcript>
"""


def _default_progress(message: str) -> None:
    LOGGER.info(message)


def _import_google_genai():
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ImportError(
            "Missing Gemini SDK. Install it with `pip install google-genai`."
        ) from exc
    return genai, types


def _normalize_symbol(symbol: str) -> str:
    cleaned = "".join(
        ch for ch in str(symbol).strip().upper() if ch.isalnum() or ch in {".", "_", "-"}
    )
    if not cleaned:
        raise ValueError("Symbol is required.")
    return cleaned


def _normalize_company_name(company_name: str) -> str:
    cleaned = " ".join(str(company_name).strip().split())
    return cleaned


def _normalize_url(url: str) -> str:
    normalized = str(url).strip()
    if not normalized:
        raise ValueError("Audio URL is required.")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Please provide a valid HTTP or HTTPS audio URL.")
    return normalized


def _validate_api_key(api_key: str) -> str:
    normalized = str(api_key).strip()
    if not normalized:
        raise ValueError("Gemini API key is required.")
    return normalized


def _infer_extension(url: str, content_type: str | None) -> str:
    parsed_path = urlparse(url).path
    suffix = Path(parsed_path).suffix.lower()
    if suffix in ALLOWED_EXTENSIONS:
        return suffix

    if content_type:
        normalized_type = content_type.split(";")[0].strip().lower()
        if normalized_type in ALLOWED_CONTENT_TYPES:
            guessed = mimetypes.guess_extension(normalized_type)
            if guessed == ".mp4":
                return ".m4a"
            if guessed in ALLOWED_EXTENSIONS:
                return guessed
            if normalized_type in {"audio/mp4", "audio/x-m4a", "audio/m4a"}:
                return ".m4a"
            if normalized_type in {"audio/mpeg", "audio/mp3"}:
                return ".mp3"
            if normalized_type in {"audio/wav", "audio/x-wav"}:
                return ".wav"

            if normalized_type == "video/mp4":
                return ".mp4"

    raise ValueError("Unsupported media format. Only mp3, wav, m4a, and mp4 are supported.")


def _download_audio_to_temp(url: str, progress_callback: Callable[[str], None]) -> tuple[str, str]:
    progress_callback("Starting media download.")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "audio/mpeg, audio/*;q=0.9, */*;q=0.8",
        "Referer": "https://www.bluestarindia.com/",
    }
    
    with requests.get(
        url,
        headers=headers,
        stream=True,
        timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
    ) as response:
        response.raise_for_status()

        content_type = response.headers.get("Content-Type")
        total_bytes = int(response.headers.get("Content-Length", "0") or "0")
        file_suffix = _infer_extension(url, content_type)
        mime_type = content_type.split(";")[0].strip().lower() if content_type else mimetypes.guess_type(f"file{file_suffix}")[0]

        progress_callback(
            f"Download response received. Content-Type: {content_type or 'unknown'}, "
            f"expected size: {total_bytes or 'unknown'} bytes."
        )

        downloaded_bytes = 0
        next_log_at = LOG_EVERY_BYTES

        with tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix) as temp_file:
            temp_path = temp_file.name

            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    continue

                temp_file.write(chunk)
                downloaded_bytes += len(chunk)

                if downloaded_bytes >= next_log_at:
                    progress_callback(f"Downloaded {downloaded_bytes} bytes so far.")
                    next_log_at += LOG_EVERY_BYTES

    if downloaded_bytes == 0:
        raise ValueError("Downloaded media file is empty.")

    progress_callback(f"Download finished. Temporary file saved with {downloaded_bytes} bytes.")
    return temp_path, (mime_type or "audio/mpeg")


def _resolve_ffmpeg_executable() -> str:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path

    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError(
            "MP4 support requires ffmpeg. Install a system ffmpeg binary or add the "
            "`imageio-ffmpeg` Python package to the environment."
        ) from exc

    return imageio_ffmpeg.get_ffmpeg_exe()


def _maybe_extract_audio(
    media_path: str,
    mime_type: str,
    progress_callback: Callable[[str], None],
) -> tuple[str, str, list[str]]:
    cleanup_paths = [media_path]
    media_suffix = Path(media_path).suffix.lower()

    if media_suffix != ".mp4" and mime_type != "video/mp4":
        return media_path, mime_type, cleanup_paths

    ffmpeg_executable = _resolve_ffmpeg_executable()
    extracted_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    extracted_audio.close()
    extracted_audio_path = extracted_audio.name

    progress_callback("MP4 detected. Extracting audio track locally before Gemini upload.")
    command = [
        ffmpeg_executable,
        "-y",
        "-i",
        media_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        extracted_audio_path,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        if os.path.exists(extracted_audio_path):
            os.remove(extracted_audio_path)
        raise RuntimeError(f"Could not run ffmpeg for MP4 audio extraction: {exc}") from exc

    if completed.returncode != 0:
        if os.path.exists(extracted_audio_path):
            os.remove(extracted_audio_path)
        stderr = completed.stderr.strip() or completed.stdout.strip() or "Unknown ffmpeg error."
        raise RuntimeError(f"ffmpeg failed while extracting audio from MP4: {stderr}")

    if not os.path.exists(extracted_audio_path) or os.path.getsize(extracted_audio_path) == 0:
        if os.path.exists(extracted_audio_path):
            os.remove(extracted_audio_path)
        raise RuntimeError("ffmpeg completed but did not produce a usable audio file from the MP4.")

    cleanup_paths.append(extracted_audio_path)
    progress_callback("Audio extraction completed. Uploading the extracted speech-only audio file.")
    return extracted_audio_path, EXTRACTED_AUDIO_MIME_TYPE, cleanup_paths


def _create_client(api_key: str):
    genai, _ = _import_google_genai()
    return genai.Client(api_key=api_key)


def _upload_audio_file(client, audio_path: str, mime_type: str, progress_callback: Callable[[str], None]):
    _, types = _import_google_genai()
    progress_callback("Uploading media file to Gemini File API.")
    return client.files.upload(
        file=audio_path,
        config=types.UploadFileConfig(
            display_name=Path(audio_path).name,
            mime_type=mime_type,
        ),
    )


def _wait_for_file_active(client, uploaded_file, progress_callback: Callable[[str], None]):
    progress_callback("Waiting for Gemini to finish processing the media file.")
    started_at = time.time()
    current_file = uploaded_file

    while True:
        state_name = getattr(getattr(current_file, "state", None), "name", None)

        if state_name == "ACTIVE":
            progress_callback("Gemini file is active and ready.")
            return current_file

        if state_name == "FAILED":
            raise RuntimeError("Gemini File API failed to process the uploaded media file.")

        if time.time() - started_at > FILE_PROCESSING_TIMEOUT_SECONDS:
            raise TimeoutError("Timed out while waiting for Gemini to process the media file.")

        progress_callback(f"Current Gemini file state: {state_name or 'PROCESSING'}. Polling again soon.")
        time.sleep(FILE_POLL_INTERVAL_SECONDS)
        current_file = client.files.get(name=uploaded_file.name)


def _generate_text(client, model_name: str, contents, progress_callback: Callable[[str], None], stage_name: str) -> str:
    _, types = _import_google_genai()
    progress_callback(f"Running Gemini {stage_name}.")
    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    text = getattr(response, "text", None)
    if not text or not text.strip():
        raise RuntimeError(f"Gemini returned an empty response during {stage_name}.")

    return text.strip()


def transcribe_from_url(url: str) -> str:
    raise NotImplementedError(
        "This project now uses Gemini and requires an API key. Use process_audio_request(...) instead."
    )


def build_transcript_pdf(record: dict) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise ImportError(
            "PDF export requires reportlab. Install it with `pip install reportlab`."
        ) from exc

    def normalize_text(value: str) -> str:
        text = str(value or "")
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text

    def append_multiline_text(story: list, text: str, style) -> None:
        normalized = normalize_text(text)
        paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
        if not paragraphs and normalized.strip():
            paragraphs = [normalized.strip()]
        for paragraph in paragraphs:
            story.append(Paragraph(paragraph.replace("\n", "<br/>"), style))
            story.append(Spacer(1, 0.12 * inch))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading_style = styles["Heading2"]
    body_style = styles["BodyText"]

    symbol = record.get("symbol", "")
    company_name = record.get("company_name", "")
    title = company_name or symbol or "Transcript Report"

    story = [
        Paragraph(normalize_text(title), title_style),
        Spacer(1, 0.18 * inch),
    ]

    metadata_lines = [
        f"Symbol: {symbol or 'N/A'}",
        f"Company: {company_name or 'N/A'}",
        f"Created At: {record.get('created_at', 'N/A')}",
        f"Audio URL: {record.get('audio_url', 'N/A')}",
        f"Model: {record.get('model', 'N/A')}",
    ]
    append_multiline_text(story, "\n".join(metadata_lines), body_style)

    story.append(Paragraph("Summary", heading_style))
    story.append(Spacer(1, 0.12 * inch))
    append_multiline_text(story, record.get("summary", ""), body_style)

    story.append(Paragraph("Transcript", heading_style))
    story.append(Spacer(1, 0.12 * inch))
    append_multiline_text(story, record.get("transcript", ""), body_style)

    document.build(story)
    return buffer.getvalue()


def _symbol_file_path(symbol: str) -> Path:
    return DATA_DIR / f"{symbol}.json"


def load_saved_records(symbol: str) -> dict:
    normalized_symbol = _normalize_symbol(symbol)
    file_path = _symbol_file_path(normalized_symbol)

    if not file_path.exists():
        return {"symbol": normalized_symbol, "company_name": "", "records": []}

    with file_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload.get("records"), list):
        payload["records"] = []

    payload["symbol"] = normalized_symbol
    payload["company_name"] = _normalize_company_name(payload.get("company_name", ""))
    return payload


def save_records(symbol: str, company_name: str, records: list[dict]) -> Path:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_company_name = _normalize_company_name(company_name)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_path = _symbol_file_path(normalized_symbol)

    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "symbol": normalized_symbol,
                "company_name": normalized_company_name,
                "records": records,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )

    return file_path


def process_audio_request(
    gemini_api_key: str,
    symbol: str,
    company_name: str,
    audio_url: str,
    progress_callback: Callable[[str], None] | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
) -> dict:
    progress = progress_callback or _default_progress
    normalized_key = _validate_api_key(gemini_api_key)
    normalized_symbol = _normalize_symbol(symbol)
    normalized_company_name = _normalize_company_name(company_name) or normalized_symbol
    normalized_url = _normalize_url(audio_url)

    payload = load_saved_records(normalized_symbol)
    existing_records = payload.get("records", [])

    for record in existing_records:
        if record.get("audio_url") == normalized_url:
            progress("Matching audio URL already exists. Reusing saved transcript and summary.")
            return {
                "record": record,
                "was_cached": True,
                "save_path": str(_symbol_file_path(normalized_symbol)),
            }

    temp_path = None
    cleanup_paths: list[str] = []
    uploaded_file = None
    client = None

    try:
        temp_path, mime_type = _download_audio_to_temp(normalized_url, progress)
        upload_path, upload_mime_type, cleanup_paths = _maybe_extract_audio(
            temp_path,
            mime_type,
            progress,
        )
        client = _create_client(normalized_key)
        uploaded_file = _upload_audio_file(client, upload_path, upload_mime_type, progress)
        uploaded_file = _wait_for_file_active(client, uploaded_file, progress)

        transcript = _generate_text(
            client=client,
            model_name=model_name,
            contents=[uploaded_file, TRANSCRIPTION_PROMPT],
            progress_callback=progress,
            stage_name="transcription",
        )

        summary = _generate_text(
            client=client,
            model_name=model_name,
            contents=[SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript)],
            progress_callback=progress,
            stage_name="summary generation",
        )

        record = {
            "symbol": normalized_symbol,
            "company_name": normalized_company_name,
            "audio_url": normalized_url,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "transcript": transcript,
            "summary": summary,
            "model": model_name,
        }

        updated_records = existing_records + [record]
        save_path = save_records(normalized_symbol, normalized_company_name, updated_records)
        progress("Transcript and summary saved locally.")
        return {"record": record, "was_cached": False, "save_path": str(save_path)}
    except requests.Timeout as exc:
        raise TimeoutError("Audio download timed out.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to download audio: {exc}") from exc
    except Exception as exc:
        message = str(exc)
        if "API key" in message or "api_key" in message or "authentication" in message.lower():
            raise RuntimeError("Gemini authentication failed. Please verify the API key.") from exc
        raise
    finally:
        if uploaded_file is not None and client is not None:
            try:
                client.files.delete(name=uploaded_file.name)
                progress("Deleted uploaded Gemini file.")
            except Exception:
                progress("Could not delete the uploaded Gemini file, but local processing is complete.")

        for path in reversed(cleanup_paths or ([temp_path] if temp_path else [])):
            if path and os.path.exists(path):
                os.remove(path)
        if cleanup_paths:
            progress("Temporary media files removed.")
