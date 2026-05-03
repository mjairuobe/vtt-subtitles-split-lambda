# vtt-subtitles-split-lambda

AWS Lambda (Python 3.11, Container Image), die als HTTP API zwei Aufgaben ueber dieselbe URL bereitstellt:
- `GET`: statische Website mit Formular und Erklaerung
- `POST`: Upload einer Datei mit Endung `.vtt` oder `.txt` (`multipart/form-data`) und ZIP-Download der gesplitteten VTT-Dateien

Die Ausgabedateien werden als `<originalname>-1.vtt` ... `<originalname>-n.vtt` benannt.

## Beispiel

Input:
- Datei-Laenge: `15:05` (905 Sekunden)
- `t=60`

Output:
- `ceil(905/60) = 16` VTT-Dateien im ZIP.

## HTTP API Endpunkte (gleiche URL)

### `GET /`

Liefert eine statische HTML-Seite mit:
- Beschreibung der Funktion
- Upload-Formular (`file`, `t`)
- JavaScript, das per `fetch` ein `POST` an dieselbe URL sendet und den ZIP-Download startet

### `POST /`

Erwartetes Format:

- `Content-Type: multipart/form-data`
- Form-Felder:
  - `file`: Datei mit Endung `.vtt` oder `.txt` (UTF-8, Inhalt muss WebVTT sein)
  - `t`: Integer > 0 (Sekunden)

Alternativ kann `t` auch als Query-Parameter (`?t=60`) uebergeben werden.

## Lambda Responses

### Bei `GET`:
- `statusCode: 200`
- `Content-Type: text/html; charset=utf-8`

### Bei `POST` (Erfolg):

Bei Erfolg:
- `statusCode: 200`
- `isBase64Encoded: true`
- `Content-Type: application/zip`
- `Content-Disposition: attachment; filename="<basename>-chunks.zip"`

### Bei nicht erlaubter Methode (z. B. `PUT`):
- `statusCode: 405`
- JSON-Fehler mit Hinweis auf erlaubte Methoden (`GET`, `POST`)

## Projektstruktur

- `function/main.py`: Lambda-Handler (GET/POST Routing), HTML-Frontend + VTT-Splitting
- `function/requirements.txt`: Python-Abhaengigkeiten
- `Dockerfile`: Lambda-Container-Image
- `Jenkinsfile`: Build/Push/Deploy via AWS ECR + Lambda Update/Create

## Lokal testen

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r function/requirements.txt
python3 -m unittest discover -s tests -v
```
