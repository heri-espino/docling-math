# docling-math

High-fidelity academic PDF → Markdown extraction built on Docling, packaged as a small
Python library with one CLI command.

The default profile is optimized for mathematics-heavy papers:

- text-first Markdown;
- **CodeFormulaV2** formula enrichment;
- **TableFormer ACCURATE** table reconstruction;
- page provenance markers such as `<!-- p:12 -->`;
- optional split of late References/Bibliography sections;
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
rename PDFs  off
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
