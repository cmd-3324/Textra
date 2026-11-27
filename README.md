# Textra

A desktop application that turns a screenshot, a phone photo or a scan into text
you can use — plain text, Markdown or structured JSON with coordinates and
confidence scores. It runs entirely on your machine: no account, no upload, no
network call after the OCR models are cached.

Textra is a Python application with a PySide6 window over a framework-free core.
The same core drives a CLI, so a script can do exactly what the window does.

## Features

- **Drop, paste or open** — drag an image onto the window, press `Ctrl+V` for a
  screenshot, or `Ctrl+O` for a file (PNG, JPEG, WEBP, BMP, TIFF).
- **Structure, not just a string** — lines are grouped into paragraphs, headings
  and list items using their geometry, wrapped lines are rejoined and
  hyphenation is undone. The JSON output keeps every line's box and confidence.
- **Three formats** — plain text for pasting, Markdown for notes and issues,
  structured JSON for pipelines. Switching format re-renders the last result
  without running OCR again.
- **Pluggable engines** — RapidOCR (default, pip-only, CPU) and Tesseract, with a
  registry that lets a third-party backend plug in through an entry point. The
  UI and pipeline never import an engine library.
- **Image preprocessing you can turn off** — EXIF orientation, bounded resizing,
  contrast normalisation and projection-profile deskew, each recorded in the
  result so a bad scan can be explained.
- **Never freezes** — inference runs in a `QThread`; every widget update arrives
  through a typed signal. Cancel is cooperative rather than a thread kill.
- **Bounded by construction** — upload size, pixel count and side length are
  checked before decoding; one extraction has a hard wall-clock budget.
- **Observable** — structured logs with a job id per extraction, per-stage
  milliseconds in every result, and a rotating log file for bug reports.

## Requirements

- Python **3.11 or newer**.
- A desktop session for the window. The core library and its tests do not need
  one.
- Optional: the **Tesseract** binary if you prefer that engine
  (`winget install UB-Mannheim.TesseractOCR`, `brew install tesseract`, or
  `sudo apt install tesseract-ocr`).
- The first RapidOCR run downloads its models (about 15–30 MB) and caches them.
  Set `TEXTRA_MODEL_DIR` to a pre-populated directory for offline machines.

## Install and run

From a clone, with a virtual environment:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e .
```

With [uv](https://docs.astral.sh/uv/), which is faster and used for development here:

```bash
uv venv
uv pip install -e .
```

Launch the window:

```bash
textra
# or
textra-gui
# or
python -m textra
```

Open a file directly:

```bash
textra gui invoice.png
```

The Tesseract backend is an optional extra:

```bash
pip install -e ".[tesseract]"
```

## Command line

The CLI is the same service without a window — useful for scripting and for
checking an engine installation.

```bash
textra extract invoice.png                       # plain text on stdout
textra extract invoice.png -f markdown           # Markdown
textra extract invoice.png -f json -o out.json   # structured JSON to a file
textra extract photo.jpg -e tesseract --no-preprocess
textra engines                                   # what can run here, and why not
textra doctor                                    # configuration and engine check
```

Progress and a one-line summary go to stderr, so stdout stays a clean document:

```
$ textra extract scan.png -q | wc -l
42
```

Exit codes are stable, so a script can branch on the failure:

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | I/O or unexpected failure |
| 2 | bad usage |
| 3 | invalid image (empty, corrupt, unsupported, too large) |
| 4 | engine unavailable or failed |
| 5 | timeout |
| 6 | invalid configuration |
| 130 | cancelled |

## Output

Plain text separates paragraphs with a blank line. Markdown uses the detected
structure:

```markdown
## Invoice 2026-04

Billed to Acme Ltd, 12 High Street.

- Consulting, March
```

Structured JSON is a documented contract, not a dump of Python objects:

```json
{
  "schema_version": "1.0",
  "text": "Invoice 2026-04 ...",
  "image": {"source_name": "invoice.png", "format": "PNG", "width": 900, "height": 1200},
  "engine": {"name": "rapidocr", "version": "rapidocr 3.10.0", "language": "en"},
  "preprocessing": {"applied": ["resize", "deskew"], "skew_angle_degrees": -1.5},
  "timings": {"preprocessing_ms": 42.1, "recognition_ms": 380.4, "total_ms": 430.2},
  "warnings": [],
  "blocks": [
    {
      "type": "heading",
      "level": 2,
      "text": "Invoice 2026-04",
      "confidence": 0.98,
      "bbox": {"x0": 48, "y0": 30, "x1": 410, "y1": 76},
      "lines": [
        {
          "text": "Invoice 2026-04",
          "confidence": 0.98,
          "bbox": {"x0": 48, "y0": 30, "x1": 410, "y1": 76},
          "polygon": [[48, 30], [410, 30], [410, 76], [48, 76]]
        }
      ]
    }
  ]
}
```

## Configuration

Configuration comes from `TEXTRA_*` environment variables and an optional `.env`
in the working directory. Values are typed and validated at startup; a bad value
stops the application with the variable named. Every option is documented in
[`.env.example`](.env.example).

| Variable | Default | Purpose |
| --- | --- | --- |
| `TEXTRA_DEFAULT_ENGINE` | `auto` | `auto`, `rapidocr`, `tesseract` or a plugin name |
| `TEXTRA_OCR_LANGUAGE` | `en` | Engine language / script |
| `TEXTRA_EXTRACTION_TIMEOUT_SECONDS` | `60` | Hard budget per image |
| `TEXTRA_MIN_CONFIDENCE` | `0.0` | Drop lines below this score |
| `TEXTRA_MAX_IMAGE_BYTES` | `20971520` | Upload ceiling |
| `TEXTRA_MAX_IMAGE_PIXELS` | `80000000` | Decoded pixel ceiling |
| `TEXTRA_PREPROCESS_ENABLED` | `true` | Window default for the Preprocess toggle |
| `TEXTRA_PREPROCESS_MAX_DIMENSION` | `2400` | Downscale larger images |
| `TEXTRA_PREPROCESS_DESKEW` | `true` | Straighten tilted pages |
| `TEXTRA_LOG_LEVEL` | `INFO` | Log verbosity |
| `TEXTRA_LOG_FORMAT` | `console` | `console` or one-object-per-line `json` |
| `TEXTRA_LOG_FILE` | *(none)* | Rotating file handler, 2 MiB × 3 |
| `TEXTRA_UI_THEME` | `dark` | `dark` or `light` |

Example for a batch machine that should write JSON logs to a file:

```bash
export TEXTRA_LOG_FORMAT=json
export TEXTRA_LOG_FILE=/var/log/textra/textra.log
export TEXTRA_EXTRACTION_TIMEOUT_SECONDS=120
```

> `TEXTRA_MODEL_DIR` must already contain RapidOCR's models; it is an offline
> deployment switch, not a download cache you populate by hand.

## Architecture

Textra follows a ports-and-adapters split. The domain is pure Python; Qt,
Pillow, RapidOCR and Tesseract are all at the edges.

```
Textra/
├── src/textra/
│   ├── domain/
│   │   ├── models.py        frozen dataclasses: requests, blocks, results
│   │   ├── errors.py        TextraError hierarchy (one per failure kind)
│   │   └── ports.py         Protocols: OCREngine, EngineProvider,
│   │                        ImagePreprocessor, ResultFormatter
│   ├── engines/
│   │   ├── registry.py      name -> provider, availability probe, plugins
│   │   ├── rapidocr_engine.py
│   │   ├── tesseract_engine.py
│   │   └── language.py      one vocabulary, per-engine translation
│   ├── preprocessing/
│   │   ├── validation.py    sniffing, size/pixel limits, safe decode
│   │   ├── steps.py         resize, autocontrast, deskew
│   │   ├── chain.py         ordering and truthful "applied" reporting
│   │   └── pillow_preprocessor.py   the ImagePreprocessor adapter
│   ├── pipeline/layout.py   rows, paragraphs, headings, reading order
│   ├── formatting/          plain text, Markdown, JSON schema
│   ├── services/
│   │   ├── extraction_service.py   orchestration, deadlines, telemetry
│   │   └── cancellation.py         cooperative token
│   ├── ui/                  PySide6: main window, workers, widgets, theme
│   ├── config.py            typed settings and derived domain values
│   ├── logging.py           structured logs and job correlation
│   └── cli.py               terminal adapter with documented exit codes
├── tests/                   pytest suite (core runs headlessly)
├── pyproject.toml
└── .env.example
```

The flow for one image:

```
bytes ──decode/validate──▶ ImageDocument (PNG)
      ──preprocess chain──▶ ImageDocument
      ──OCREngine─────────▶ RawLine[]
      ──layout analysis───▶ TextBlock[]
      ──ResultFormatter───▶ str
```

Two consequences worth stating: the UI cannot contain OCR logic because it never
sees an engine, and replacing RapidOCR with a hosted VLM means writing one class,
not editing the service.

### Adding an engine

Implement the two protocols on one class and register it with an entry point:

```python
# my_engine/engine.py
from textra.domain.models import EngineAvailability, EngineSettings


class MyEngine:
    name = "my_engine"

    @classmethod
    def availability(cls, settings: EngineSettings) -> EngineAvailability:
        return EngineAvailability(cls.name, True, "my backend 1.0")

    @classmethod
    def create(cls, settings: EngineSettings) -> "MyEngine":
        return cls()

    def initialize(self) -> None: ...  # load whatever the backend needs

    def recognize(self, image_png: bytes) -> tuple: ...  # return tuple[RawLine, ...]

    def close(self) -> None: ...
```

```toml
# the plugin's own pyproject.toml
[project.entry-points."textra.engines"]
my_engine = "my_engine.engine:MyEngine"
```

The registry loads it on start, lists it in the engine menu and probes its
availability. A broken plugin is logged and skipped rather than breaking startup.

## Development

```bash
uv pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy
pytest
```

The suite covers configuration validation, image limits, each preprocessing step,
layout recovery, all three formatters, the registry, service orchestration
(timeout, cancellation, engine reuse, error mapping) and the CLI. The Qt smoke
test runs with `QT_QPA_PLATFORM=offscreen`, so no display is required.

Real OCR is an opt-in integration test because the first run downloads models:

```bash
TEXTRA_LIVE_OCR=1 pytest -m live
```

## Performance notes

- RapidOCR on a modern 4-core CPU reads an A4 page in roughly 0.3–1.5 s after the
  models are warm; the first call also pays model initialisation.
- Preprocessing is capped at 2400 px on the long side. Larger images cost
  quadratically more in the detector and gain nothing in accuracy.
- The deskew search runs on a 900 px thumbnail in two passes; a full-resolution
  sweep would cost more than the OCR call it improves.
- Extraction is serialised inside the service. One local engine already saturates
  the CPU; queueing is faster than contending, and it keeps timeouts meaningful.

## Known limitations

- **Two-column pages are read row by row.** The layout analyser has no page
  segmentation, so a newspaper-style column layout interleaves its columns.
  Single-column documents, forms, receipts and screenshots are the target.
- **A timeout does not stop native inference.** Python cannot kill a running C
  call; the request fails at its deadline and the late result is discarded. The
  next extraction queues behind the still-running call.
- **Images travel through PNG internally.** Preprocessing already rewrote the
  pixels; PNG avoids a second lossy encode. Very large scans therefore use more
  memory than the original JPEG.
- **Structure is inferred from geometry.** A bold short sentence can be read as
  a heading, and a list without visible markers as a paragraph. The JSON `bbox`
  and `confidence` let a downstream step correct this.
- **Deskew handles moderate rotation** (±6° by default, two-pass search). A photo
  taken at 30° needs a different rectification strategy.
- **One image at a time.** There is no batch queue in the window; loop the CLI or
  call `ExtractionService` from a script for that.
- **No PDF input.** Convert pages to images first; PDF text extraction is a
  different problem with better tools.

## License

MIT 2026. See [LICENSE](LICENSE).
