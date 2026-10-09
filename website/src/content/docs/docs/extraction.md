---
title: PDF extraction
description: Extract scientific text, LaTeX-like mathematics, tables, and split references.
---

Docling Math targets high-fidelity extraction of academic PDFs, including mathematical expressions and tables.

## Extraction modes

| Strategy | Behavior |
| --- | --- |
| **compare** (default) | Compares hybrid and full-page OCR candidates, then chooses an output using diagnostics. |
| **smart** | Uses OCR selectively when needed. |
| **hybrid** | Preserves a hybrid pipeline without forcing full-page OCR. |
| **ocr** | Uses full-page OCR. |

Try **compare** when document quality is unpredictable. The settings and which backends are available depend on the installed Docling environment.

## Extract a library

Place PDFs in the project's <code>bib/pdf/</code> folder and run:

~~~powershell
docling-math
~~~

Select a single document using:

~~~powershell
docling-math --paper "my-paper.pdf"
~~~

Or set a strategy explicitly:

~~~powershell
docling-math --strategy smart
~~~

## Output

A typical corpus has this shape:

~~~text
project/
└── bib/
    ├── pdf/
    │   └── paper.pdf
    ├── extracted/
    │   └── paper.md
    ├── references/
    │   └── paper.references.md
    ├── INDEX.md
    └── bundle.md
~~~

Figures and table crops are optional, enabled with <code>--assets</code>. Reference splitting is supported so bibliographies can be searched without swamping the main paper's content.

## Additional settings

~~~powershell
docling-math --assets --rename-pdfs
~~~

To opt in to metadata writing **inside the source PDF**:

~~~powershell
docling-math --write-pdf-metadata
~~~

Rewriting the PDF container can invalidate existing digital signatures. Metadata inside the generated Markdown is enabled by default.
