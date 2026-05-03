import base64
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


TIMING_LINE_RE = re.compile(
    r"^(?P<start>(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})\s*-->\s*"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})(?P<settings>.*)$"
)
SAFE_BASENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

HOME_PAGE_HTML = """<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>VTT Subtitle Splitter</title>
    <style>
      :root {
        color-scheme: light dark;
      }
      body {
        margin: 0;
        font-family: Arial, sans-serif;
        background: #111827;
        color: #f9fafb;
      }
      main {
        max-width: 760px;
        margin: 0 auto;
        padding: 2rem 1rem 3rem;
      }
      .card {
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 1.25rem;
        background: #1f2937;
      }
      h1 {
        margin-top: 0;
        margin-bottom: 0.5rem;
        font-size: 1.75rem;
      }
      p,
      li,
      label {
        line-height: 1.5;
      }
      form {
        display: grid;
        gap: 1rem;
        margin-top: 1rem;
      }
      input[type="file"],
      input[type="number"] {
        width: 100%;
        box-sizing: border-box;
        border: 1px solid #475569;
        border-radius: 8px;
        padding: 0.65rem 0.75rem;
        background: #0f172a;
        color: #f8fafc;
      }
      button {
        border: 0;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        background: #2563eb;
        color: #fff;
        font-weight: 700;
        cursor: pointer;
      }
      button[disabled] {
        opacity: 0.7;
        cursor: not-allowed;
      }
      .status {
        min-height: 1.5rem;
        margin-top: 0.25rem;
      }
      .hint {
        color: #cbd5e1;
        font-size: 0.95rem;
      }
      code {
        padding: 0.1rem 0.35rem;
        border-radius: 4px;
        background: #0b1220;
      }
    </style>
  </head>
  <body>
    <main>
      <section class="card">
        <h1>VTT Subtitle Splitter</h1>
        <p>
          Diese Lambda dient als statische Website (<code>GET</code>) und als API
          (<code>POST</code>) zugleich. Lade eine WebVTT-Datei hoch und waehle die
          Chunk-Laenge <code>t</code> in Sekunden.
        </p>
        <ul>
          <li>Ausgabe-Dateien: <code>&lt;name&gt;-1.vtt ... &lt;name&gt;-n.vtt</code></li>
          <li>Anzahl Dateien: <code>ceil(gesamtdauer / t)</code></li>
          <li>Leere Chunks sind erlaubt und werden mit ausgegeben.</li>
        </ul>

        <form id="split-form" method="post" enctype="multipart/form-data">
          <label>
            Untertitel-Datei (.vtt oder .txt, WEBVTT-Header optional)
            <input name="file" type="file" accept=".vtt,.txt,text/vtt,text/plain" required />
          </label>
          <label>
            Chunk-Groesse t (Sekunden)
            <input name="t" type="number" min="1" step="1" value="60" required />
          </label>
          <button id="submit-button" type="submit">Splitten und ZIP herunterladen</button>
          <p id="status" class="status hint" aria-live="polite"></p>
        </form>
        <p class="hint">
          Ohne JavaScript funktioniert das Formular ebenfalls, da es per
          <code>POST</code> an dieselbe Lambda-URL sendet.
        </p>
      </section>
    </main>
    <script>
      (() => {
        const form = document.getElementById("split-form");
        const button = document.getElementById("submit-button");
        const status = document.getElementById("status");

        const extractFilename = (contentDisposition) => {
          if (!contentDisposition) return "subtitles-chunks.zip";
          const match = /filename="([^"]+)"/i.exec(contentDisposition);
          return match ? match[1] : "subtitles-chunks.zip";
        };

        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          status.textContent = "Verarbeite Datei...";
          button.disabled = true;
          try {
            const response = await fetch(window.location.pathname, {
              method: "POST",
              body: new FormData(form),
            });

            if (!response.ok) {
              let message = `Fehler (${response.status})`;
              try {
                const payload = await response.json();
                if (payload && payload.error) {
                  message = payload.error;
                }
              } catch (_) {
              }
              throw new Error(message);
            }

            const blob = await response.blob();
            const filename = extractFilename(
              response.headers.get("content-disposition")
            );
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = filename;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            URL.revokeObjectURL(url);
            status.textContent = "Fertig: ZIP-Download gestartet.";
          } catch (error) {
            status.textContent = `Fehler: ${error.message}`;
          } finally {
            button.disabled = false;
          }
        });
      })();
    </script>
  </body>
</html>
"""


@dataclass
class Cue:
    identifier: Optional[str]
    start: float
    end: float
    settings: str
    text_lines: List[str]


def parse_timestamp(value: str) -> float:
    normalized = value.strip().replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds_part = parts[1]
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_part = parts[2]
    else:
        raise ValueError(f"Invalid timestamp: {value}")

    if "." not in seconds_part:
        raise ValueError(f"Invalid timestamp milliseconds: {value}")

    seconds_raw, milliseconds_raw = seconds_part.split(".", 1)
    seconds = int(seconds_raw)
    milliseconds = int(milliseconds_raw.ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def format_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    if total_ms < 0:
        total_ms = 0

    hours = total_ms // 3_600_000
    rest = total_ms % 3_600_000
    minutes = rest // 60_000
    rest = rest % 60_000
    secs = rest // 1000
    millis = rest % 1000
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def parse_vtt(vtt_text: str) -> List[Cue]:
    text = vtt_text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]

    lines = text.split("\n")
    cues: List[Cue] = []
    i = 0

    while i < len(lines):
        current = lines[i]
        stripped = current.strip()
        if not stripped:
            i += 1
            continue

        if stripped.startswith("NOTE"):
            i += 1
            while i < len(lines) and lines[i].strip():
                i += 1
            continue

        identifier: Optional[str] = None
        timing_candidate = stripped
        timing_match = TIMING_LINE_RE.match(timing_candidate)

        if not timing_match and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            timing_match = TIMING_LINE_RE.match(next_line)
            if timing_match:
                identifier = current
                i += 1

        if not timing_match:
            i += 1
            continue

        i += 1
        text_lines: List[str] = []
        while i < len(lines) and lines[i].strip():
            text_lines.append(lines[i])
            i += 1

        start = parse_timestamp(timing_match.group("start"))
        end = parse_timestamp(timing_match.group("end"))
        if end <= start:
            continue

        cues.append(
            Cue(
                identifier=identifier,
                start=start,
                end=end,
                settings=timing_match.group("settings"),
                text_lines=text_lines,
            )
        )

    return cues


def render_vtt(cues: Iterable[Cue]) -> str:
    lines = ["WEBVTT", ""]
    for cue in cues:
        if cue.identifier:
            lines.append(cue.identifier)
        lines.append(
            f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}{cue.settings}"
        )
        lines.extend(cue.text_lines)
        lines.append("")
    return "\n".join(lines) + "\n"


def split_cues(cues: List[Cue], chunk_seconds: int) -> List[List[Cue]]:
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be > 0")

    if not cues:
        return [[]]

    max_end = max(cue.end for cue in cues)
    chunk_count = max(1, math.ceil(max_end / chunk_seconds))
    chunks: List[List[Cue]] = [[] for _ in range(chunk_count)]

    for cue in cues:
        start_idx = int(cue.start // chunk_seconds)
        end_idx = int((cue.end - 1e-9) // chunk_seconds)

        for idx in range(start_idx, min(end_idx + 1, chunk_count)):
            chunk_start = idx * chunk_seconds
            chunk_end = (idx + 1) * chunk_seconds
            overlap_start = max(cue.start, chunk_start)
            overlap_end = min(cue.end, chunk_end)
            if overlap_end <= overlap_start:
                continue

            chunks[idx].append(
                Cue(
                    identifier=cue.identifier,
                    start=overlap_start - chunk_start,
                    end=overlap_end - chunk_start,
                    settings=cue.settings,
                    text_lines=list(cue.text_lines),
                )
            )

    return chunks


def split_vtt_file(vtt_text: str, chunk_seconds: int) -> List[str]:
    normalized = vtt_text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    has_timing_line = any(TIMING_LINE_RE.match(line.strip()) for line in normalized.split("\n"))
    first_content_line = next((line.strip() for line in normalized.split("\n") if line.strip()), "")
    if first_content_line != "WEBVTT":
        if has_timing_line:
            normalized = f"WEBVTT\n\n{normalized}"
        else:
            raise ValueError(
                "Datei ist kein gueltiges WebVTT. Bitte pruefe: UTF-8 Kodierung, "
                "Zeitzeilen im Format 00:00:00.000 --> 00:00:05.000 und Leerzeilen "
                "zwischen den Untertitelbloecken."
            )

    cues = parse_vtt(normalized)
    if not cues:
        raise ValueError(
            "Keine gueltigen Untertitel-Cues gefunden. Bitte pruefe das Zeitformat "
            "(00:00:00.000 --> 00:00:05.000) und die Blockstruktur der Datei."
        )
    chunks = split_cues(cues, chunk_seconds)
    return [render_vtt(chunk) for chunk in chunks]


def parse_multipart_form(
    body: bytes, content_type: str
) -> Tuple[Dict[str, str], Optional[str], Optional[bytes]]:
    if "multipart/form-data" not in (content_type or "").lower():
        raise ValueError("Content-Type must be multipart/form-data")

    mime_message = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n"
        "\r\n"
    ).encode("utf-8") + body
    message = BytesParser(policy=default).parsebytes(mime_message)

    if not message.is_multipart():
        raise ValueError("Request body is not multipart")

    fields: Dict[str, str] = {}
    file_name: Optional[str] = None
    file_bytes: Optional[bytes] = None
    fallback_file_name: Optional[str] = None
    fallback_file_bytes: Optional[bytes] = None

    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if "form-data" not in disposition:
            continue

        field_name = part.get_param("name", header="content-disposition")
        filename = part.get_param("filename", header="content-disposition")
        payload = part.get_payload(decode=True) or b""

        if filename is not None:
            if fallback_file_bytes is None:
                fallback_file_name = filename
                fallback_file_bytes = payload
            if field_name == "file":
                file_name = filename
                file_bytes = payload
        elif field_name:
            charset = part.get_content_charset() or "utf-8"
            fields[field_name] = payload.decode(charset, errors="replace").strip()

    if file_bytes is None:
        file_name = fallback_file_name
        file_bytes = fallback_file_bytes

    return fields, file_name, file_bytes


def get_header(headers: Dict[str, str], key: str) -> Optional[str]:
    for header_key, header_value in (headers or {}).items():
        if header_key.lower() == key.lower():
            return header_value
    return None


def json_response(status_code: int, body: Dict[str, object]) -> Dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def html_response(status_code: int, html: str) -> Dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
        },
        "body": html,
    }


def detect_http_method(event: Dict[str, object]) -> str:
    request_context = event.get("requestContext") or {}
    if isinstance(request_context, dict):
        http_info = request_context.get("http") or {}
        if isinstance(http_info, dict) and http_info.get("method"):
            return str(http_info["method"]).upper()

    http_method = event.get("httpMethod")
    if http_method:
        return str(http_method).upper()

    if event.get("body") is not None:
        return "POST"
    return "GET"


def handle_split_request(event: Dict[str, object]) -> Dict[str, object]:
    try:
        headers = event.get("headers") or {}
        content_type = get_header(headers, "Content-Type") or ""
        body = event.get("body")

        if body is None:
            return json_response(400, {"error": "Request body is required"})

        if event.get("isBase64Encoded"):
            body_bytes = base64.b64decode(body)
        else:
            body_bytes = body.encode("utf-8")

        fields, original_filename, upload_bytes = parse_multipart_form(
            body=body_bytes,
            content_type=content_type,
        )

        if upload_bytes is None:
            return json_response(400, {"error": "No file found in multipart form data"})

        if "t" not in fields:
            query_params = event.get("queryStringParameters") or {}
            if query_params.get("t"):
                fields["t"] = str(query_params["t"])

        if "t" not in fields:
            return json_response(400, {"error": "Missing required parameter 't'"})

        try:
            chunk_seconds = int(fields["t"])
        except ValueError:
            return json_response(400, {"error": "Parameter 't' must be an integer in seconds"})

        if chunk_seconds <= 0:
            return json_response(400, {"error": "Parameter 't' must be > 0"})

        try:
            vtt_text = upload_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return json_response(400, {"error": "Only UTF-8 encoded subtitle files are supported"})

        split_files = split_vtt_file(vtt_text=vtt_text, chunk_seconds=chunk_seconds)

        safe_basename = Path(original_filename or "subtitles.vtt").stem
        safe_basename = SAFE_BASENAME_RE.sub("_", safe_basename).strip("._-")
        if not safe_basename:
            safe_basename = "subtitles"
        archive_name = f"{safe_basename}-chunks.zip"

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for idx, chunk_content in enumerate(split_files, start=1):
                output_name = f"{safe_basename}-{idx}.vtt"
                zip_file.writestr(output_name, chunk_content.encode("utf-8"))

        zip_b64 = base64.b64encode(zip_buffer.getvalue()).decode("ascii")
        return {
            "statusCode": 200,
            "isBase64Encoded": True,
            "headers": {
                "Content-Type": "application/zip",
                "Content-Disposition": f'attachment; filename="{archive_name}"',
                "Cache-Control": "no-store",
            },
            "body": zip_b64,
        }
    except ValueError as exc:
        return json_response(400, {"error": str(exc)})
    except Exception as exc:  # pragma: no cover
        return json_response(500, {"error": f"Unexpected error: {str(exc)}"})


def handler(event, context):
    method = detect_http_method(event or {})

    if method == "GET":
        return html_response(200, HOME_PAGE_HTML)

    if method == "POST":
        return handle_split_request(event or {})

    return json_response(
        405,
        {
            "error": (
                f"Method {method} not allowed. Use GET for the frontend "
                "or POST for VTT processing."
            )
        },
    )
