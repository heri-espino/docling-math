---
title: Docling Math documentation
description: Install Docling Math, extract scientific PDFs, manage a literature corpus and build an Obsidian vault.
---

Docling Math is a **local-first scientific PDF extraction toolkit**. It aims to preserve the information that matters in academic documents: text, equations, tables, page provenance and references.

The same Python engine powers a native desktop interface and a command-line interface (CLI).

## Choose your workflow

- **[Install Docling Math](./installation/)** — prepare a local installation or use a packaged Windows build when one is available.
- **[Desktop application](./desktop/)** — open a library, add PDFs, extract papers and monitor operations with no routine terminal usage.
- **[PDF extraction](./extraction/)** — choose between the comparison, smart, hybrid and OCR strategies.
- **[Upgrade an old corpus](./upgrade-corpus/)** — add metadata and regenerate bundle/index without re-running OCR.
- **[Metadata & Obsidian](./metadata-obsidian/)** — turn Markdown papers into a linked research library.
- **[Rename literature](./rename-literature/)** — rename PDFs and update their companion files and references safely.

## Where does my data go?

The tool processes source PDFs locally. By default, a project uses a <code>bib/</code> folder with <code>pdf/</code>, <code>extracted/</code> and <code>references/</code> subfolders. A separate managed Obsidian vault can be generated alongside it.

The first extraction may download model weights. Once those weights are cached, they are reused. No cloud PDF-upload service is required for the normal extraction workflow.

## Project status

The Python desktop application is implemented. Windows installer builds are provided as a **manual GitHub Actions workflow**; availability of a tested downloadable installer should be checked in [GitHub Releases](https://github.com/heri-espino/docling-math/releases).

Read the [source code and full README](https://github.com/heri-espino/docling-math).
