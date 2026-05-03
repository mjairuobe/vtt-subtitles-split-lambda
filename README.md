# vtt-subtitles-split-lambda

AWS Lambda (Python 3.11, Container Image), die per HTTP `multipart/form-data`:
- eine WebVTT-Datei (`file`) entgegennimmt,
- den Parameter `t` (Chunk-Groesse in Sekunden) ausliest,
- die Untertitel in `t`-Sekunden-Segmente splittet,
- alle Segment-Dateien als ZIP zurueckgibt.

Die Ausgabedateien werden als `<originalname>-1.vtt` ... `<originalname>-n.vtt` benannt.

## Beispiel

Input:
- Datei-Laenge: `15:05` (905 Sekunden)
- `t=60`

Output:
- `ceil(905/60) = 16` VTT-Dateien im ZIP.

## HTTP API erwartetes Format

- `Content-Type: multipart/form-data`
- Form-Felder:
  - `file`: VTT-Datei (UTF-8)
  - `t`: Integer > 0 (Sekunden)

Alternativ kann `t` auch als Query-Parameter (`?t=60`) uebergeben werden.

## Lambda Response

Bei Erfolg:
- `statusCode: 200`
- `isBase64Encoded: true`
- `Content-Type: application/zip`
- `Content-Disposition: attachment; filename="<basename>-chunks.zip"`

## Projektstruktur

- `function/main.py`: Lambda-Handler + VTT-Splitting
- `function/requirements.txt`: Python-Abhaengigkeiten
- `Dockerfile`: Lambda-Container-Image
- `Jenkinsfile`: Build/Push/Deploy via AWS ECR + Lambda Update/Create

## Lokal testen

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r function/requirements.txt
python -m unittest discover -s tests -v
```
