# docling-math

High-fidelity academic PDF → Markdown extraction built on Docling, packaged as a small
Python library with an extraction CLI and a synchronized literature-renaming utility.

The default profile is optimized for mathematics-heavy papers:

- text-first Markdown;
- **CodeFormulaV2** formula enrichment;
- **TableFormer ACCURATE** table reconstruction;
- page provenance markers such as `<!-- p:12 -->`;
- optional split of late References/Bibliography sections;
- bibliographic YAML properties, original keywords, normalized tags, and aliases;
- optional PDF Info/XMP metadata and Obsidian integration;
- **no persisted figures or table PNGs by default**.

Use `--assets` only when you want visual fallbacks.

## Repository layout

```text
docling/
├─ src/
│  └─ docling_math/
│     ├─ __init__.py
│     ├─ __main__.py
│     └─ extractor.py
├─ bib/
│  └─ pdf/                  # optional local input when using this repo directly
├─ environment.yml
├─ pyproject.toml
├─ LICENSE
└─ README.md
```

At runtime, a project with `bib/pdf/` becomes:

```text
project/
└─ bib/
   ├─ pdf/                  # source PDFs
   ├─ extracted/            # primary Markdown corpus
   ├─ references/           # separated bibliography sections
   ├─ assets/               # only if --assets was requested
   ├─ INDEX.md
   ├─ bundle.md             # whole corpus, ready to pass to an AI
   └─ AGENTS.md
```

## Installation with Conda

The package currently targets **Docling 2.129.0** and Python 3.12.

### 1. Clone

```powershell
git clone https://github.com/heri-espino/docling-math.git
cd docling-math
```

### 2. Create the Conda environment

```powershell
conda env create -f environment.yml
conda activate docling-math
python -m pip install --upgrade pip
```

### 3. NVIDIA GPU: install CUDA-enabled PyTorch first

For an NVIDIA machine, install the CUDA wheel before installing this project:

```powershell
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

Verify:

```powershell
python -c "import torch; print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"
```

### 4. Install the library

```powershell
python -m pip install -e .
```

After that, extraction is a single command:

```powershell
docling-math
```

## GPU-first safety rule

`docling-math` uses `--device auto` by default, but its policy is stricter than simply
delegating to Docling:

1. use CUDA when available;
2. otherwise use Apple MPS when available;
3. otherwise print a warning and ask:

```text
¿Continuar con CPU? Esto puede ser mucho más lento. [y/N]:
```

CPU is not used unless you type `y` or `yes`. The same confirmation is required when
`--device cpu` is explicitly requested.

## Default extraction

Put PDFs in `bib/pdf/` and run from that project (or any subdirectory):

```powershell
docling-math
```

Defaults:

```text
device       auto, GPU first
strategy     compare
math         on  (CodeFormulaV2)
tables       on  (TableFormer ACCURATE)
assets       off
references   split
page markers on
bundle       on  (bib/bundle.md)
metadata     on  (YAML + keywords + tags + aliases)
rename PDFs  off
PDF metadata off
Obsidian     off
model cache  ~/.cache/docling/models
```

The `compare` strategy runs both hybrid/native+OCR and forced full-page OCR, scores both,
and keeps the stronger Markdown representation.

## Persistent model cache

On the first run, docling-math prefetches the Docling weights it needs into a persistent
user-level cache:

    ~/.cache/docling/models

Later runs reuse that directory instead of downloading the weights again. The selected
layout preset is cached explicitly too; the default academic profile uses Egret Large.

To use another cache location:

    docling-math --artifacts-path D:\models\docling

Or set DOCLING_ARTIFACTS_PATH. To intentionally revalidate/redownload the cache:

    docling-math --refresh-models

## AI-ready corpus bundle

After every run, docling-math rebuilds:

    bib/bundle.md

The bundle contains a corpus map followed by every extracted paper, with explicit document
boundaries and provenance paths. YAML front matter from the individual files is removed
inside the bundle to reduce noise. Split bibliographies are omitted by default.

Include those bibliographies when you need citation chaining:

    docling-math --bundle-references

Disable bundle generation:

    docling-math --no-bundle

## Upgrade an existing corpus without OCR

Users coming from docling-math 0.1 or another older version do not need to extract their
papers again. The upgrade tool reads the Markdown already present in the corpus and migrates
it to the current metadata/index/bundle format.

The simplest command from inside an existing project is:

```powershell
upgrade-corpus
```

The same workflow is available through the main CLI:

```powershell
docling-math --upgrade-corpus
```

A normal upgrade:

- reads the existing `bib/extracted/*.md`;
- adds or refreshes title, authors, year, journal, DOI, keywords, tags, aliases, and topics;
- preserves the extracted Markdown body;
- rebuilds `INDEX.md`;
- rebuilds `bundle.md`;
- backs up the previous `INDEX.md` and `bundle.md` under `bib/.backups/upgrade-<timestamp>/`;
- does not run Docling, OCR, CodeFormulaV2, TableFormer, CUDA, or model downloads.

PDF metadata remains opt-in because it rewrites PDF containers:

```powershell
upgrade-corpus --write-pdf-metadata
```

Obsidian properties and related-paper links can be added during the same migration:

```powershell
upgrade-corpus --obsidian
```

Or migrate and create/update the Obsidian mirror in one command:

```powershell
upgrade-corpus --obsidian-vault "C:\Users\Heri\Documents\My Vault"
```

### Choose exactly which folder to transform

You do not need to move into the project directory. Pass the folder directly:

```powershell
upgrade-corpus --corpus-dir "D:\Research\Trend-Estimation"
```

The selected path may be any of these:

```text
D:\Research\Trend-Estimation
D:\Research\Trend-Estimation\bib
D:\Research\Trend-Estimation\bib\extracted
```

docling-math resolves all three to the same corpus.

For users who do not want to type a path, open the operating system's native folder picker:

```powershell
upgrade-corpus --select-folder
```

or:

```powershell
docling-math --upgrade-corpus --select-folder
```

Select the project root, `bib`, or `bib/extracted`; the tool detects the corpus
automatically.

A full migration of an old corpus can therefore be:

```powershell
upgrade-corpus `
  --select-folder `
  --write-pdf-metadata `
  --obsidian-vault "C:\Users\Heri\Documents\My Vault"
```

This still does not re-run extraction or OCR.

## Bibliographic metadata and tags

Every newly extracted Markdown note receives structured YAML metadata by default. The same
`PaperMetadata` object is used by canonical filenames, Markdown properties, PDF metadata,
the index, the AI bundle, and the future GUI.

When available, docling-math records:

```yaml
---
id: CortesToto_Espino-2011-Estimacion_de_tendencia
title: Estimacion de tendencia
authors:
  - Daniela Cortes-Toto
  - Heriberto Espino
year: 2011
journal: Journal of Trend Research
doi: 10.1234/example
keywords:
  - Trend estimation
  - Time series analysis
tags:
  - literature
  - year/2011
  - author/cortestoto
  - author/espino
  - trend-estimation
  - time-series
aliases:
  - Estimacion de tendencia
topics:
  - time-series
  - trend-estimation
source_pdf: ../pdf/CortesToto_Espino-2011-Estimacion_de_tendencia.pdf
...
---
```

`keywords` preserve author-provided terminology from the paper. `tags` are normalized
library labels for retrieval and Obsidian. Tags are intentionally conservative: literature,
publication year, up to two authors, and up to five topic tags derived from original
keywords.

Disable metadata on new Markdown outputs:

```powershell
docling-math --no-metadata
```

Upgrade already-extracted Markdown without re-running OCR or loading GPU models:

```powershell
docling-math --refresh-metadata
```

## Embedded PDF metadata

PDF modification is opt-in because the source PDF is otherwise treated as immutable:

```powershell
docling-math --write-pdf-metadata
```

This writes regular PDF Info metadata and XMP metadata while preserving the document pages.
Fields include title, authors, publication year, journal, DOI, original keywords, normalized
tags, and the abstract when available.

This operation rewrites the PDF container. Do not use it when you need to preserve an
existing digital signature byte-for-byte; rewriting a signed PDF can invalidate its
signature.

Because an intentional PDF metadata rewrite changes the PDF modification time, docling-math
refreshes the companion Markdown afterwards so it does not trigger unnecessary extraction on
the next run.

## Obsidian integration

Enable Obsidian-ready properties and wikilinks:

```powershell
docling-math --obsidian
```

This adds a PDF wikilink and the `literature-note` CSS class. By default it also computes
up to five `related` links between papers that share normalized topic tags:

```yaml
pdf: "[[CortesToto_Espino-2011-Estimacion_de_tendencia.pdf]]"
related:
  - "[[Smith_Jones-2014-Time_series_smoothing]]"
```

Disable relationship generation while keeping the other Obsidian properties:

```powershell
docling-math --obsidian --no-related-papers
```

Existing notes are upgraded without OCR when `--obsidian` is used.

To maintain a ready-to-open copy inside an Obsidian vault:

```powershell
docling-math --obsidian-vault "C:\Users\Heri\Documents\Obsidian Vault"
```

This creates or updates:

```text
Obsidian Vault/
└─ Literature/
   ├─ Paper_A.md
   ├─ Paper_B.md
   ├─ References/
   ├─ _Index.md
   ├─ _Bundle.md
   └─ Attachments/
      ├─ PDFs/
      │  ├─ Paper_A.pdf
      │  └─ Paper_B.pdf
      └─ Assets/
```

The vault option implies `--obsidian`. The copied notes rewrite their provenance paths to
the vault mirror, so PDF, split-reference, and optional asset links remain valid there. It
copies only managed literature files and does not delete or modify unrelated vault content.

## Optional canonical PDF names

PDF renaming is opt-in:

```powershell
docling-math --rename-pdfs
```

When authors, publication year, and title can be inferred confidently from the extracted
paper, the PDF and its companion outputs are renamed to:

```text
Author1_Author2-Year-Title_of_article.pdf
```

Only the first two author surnames are used. Hyphenated surnames are joined, accents and
filesystem-hostile punctuation are normalized, and title words are separated with
underscores.

For example:

```text
Daniela Cortes-Toto y Heriberto Espino
2011
Estimacion de tendencia
```

becomes:

```text
CortesToto_Espino-2011-Estimacion_de_tendencia.pdf
```

The corresponding `extracted/*.md`, `references/*.md`, optional assets directory,
`INDEX.md`, and regenerated `bundle.md` stay synchronized. Existing extracted papers
can be renamed without re-running OCR. If metadata is incomplete or the destination name
already exists, docling-math leaves the original name unchanged rather than guessing or
overwriting files.

## Manual corpus renaming

For explicit renames of an existing literature corpus, use the separate
`rename_literature` tool. It does not load Docling or any GPU models.

### Python API

```python
from docling_math import rename_literature

rename_literature(
    {
        "123456.pdf": "CortesToto_Espino-2011-Estimacion_de_tendencia.pdf",
        "download.pdf": "Smith_Jones-2024-Another_paper.pdf",
    },
    repo=r"C:\path\to\project",
)
```

The dictionary is `current_name -> desired_name`. The `.pdf` extension is optional.

### CLI with direct pairs

```powershell
rename_literature --rename "123456.pdf=CortesToto_Espino-2011-Estimacion_de_tendencia.pdf"
```

Repeat `--rename` for several papers:

```powershell
rename_literature `
  --rename "123456.pdf=CortesToto_Espino-2011-Estimacion_de_tendencia.pdf" `
  --rename "download.pdf=Smith_Jones-2024-Another_paper.pdf"
```

### CLI with a JSON dictionary

Create `renames.json`:

```json
{
  "123456.pdf": "CortesToto_Espino-2011-Estimacion_de_tendencia.pdf",
  "download.pdf": "Smith_Jones-2024-Another_paper.pdf"
}
```

Then run:

```powershell
rename_literature --map renames.json
```

Preview everything first without modifying files:

```powershell
rename_literature --map renames.json --dry-run
```

For every mapping, the tool synchronizes:

- `bib/pdf/old.pdf -> new.pdf`
- `bib/extracted/old.md -> new.md`
- `bib/references/old.references.md -> new.references.md`
- `bib/assets/old/ -> new/` when present
- all active Markdown references under `bib/`, including front-matter IDs,
  `INDEX.md`, `bundle.md`, and cross-references from other Markdown files.

Historical files inside `bib/.backups/` are intentionally not rewritten. Before changing
anything, the tool validates the full mapping and every destination. File moves use a
two-phase transaction, so swaps such as `A.pdf -> B.pdf` and `B.pdf -> A.pdf` are safe.
If any destination would overwrite an unrelated file, the operation stops before making
changes.

## Common commands

One paper:

```powershell
docling-math --paper "last-name-or-title-fragment"
```

Faster adaptive OCR:

```powershell
docling-math --strategy smart
```

Persist table/figure crops:

```powershell
docling-math --assets
```

Disable mathematical enrichment:

```powershell
docling-math --no-math
```

Disable table structure enrichment:

```powershell
docling-math --no-tables
```

Force reprocessing:

```powershell
docling-math --force
```

Rename PDFs using inferred academic metadata:

```powershell
docling-math --rename-pdfs
```

Refresh only metadata without OCR:

```powershell
docling-math --refresh-metadata
```

Upgrade an entire legacy corpus without OCR:

```powershell
upgrade-corpus --select-folder
```

Write metadata inside PDFs:

```powershell
docling-math --write-pdf-metadata
```

Prepare notes for Obsidian:

```powershell
docling-math --obsidian
```

Sync into an Obsidian vault:

```powershell
docling-math --obsidian-vault "C:\path\to\Obsidian Vault"
```

Use another project explicitly:

```powershell
docling-math --repo C:\path\to\paper-project
```

See every option:

```powershell
docling-math --help
```

## Python entry point

The installed package can also be invoked with:

```powershell
python -m docling_math
```

The console command and module entry point call the same pipeline.

## Development

```powershell
python -m pip install -e ".[dev]"
python -m compileall src
pytest -q
ruff check src
```

## License

MIT.

## Fast copy and paste

```powershell
git clone https://github.com/heri-espino/docling-math.git
cd docling-math

conda env create -f environment.yml
conda activate docling-math

python -m pip install --upgrade pip

python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

python -c "import torch; print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"

python -m pip install -e .
```
