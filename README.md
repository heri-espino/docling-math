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
   └─ AGENTS.md
```

## Installation with Conda

The package currently targets **Docling 2.129.0** and Python 3.12.

### 1. Clone

```powershell
git clone https://github.com/heri-espino/docling.git
cd docling
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
```

The `compare` strategy runs both hybrid/native+OCR and forced full-page OCR, scores both,
and keeps the stronger Markdown representation.

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
ruff check src
```

## License

MIT.
