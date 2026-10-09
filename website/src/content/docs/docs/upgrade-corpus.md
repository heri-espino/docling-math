---
title: Upgrade an existing corpus
description: Add modern metadata and an Obsidian vault to libraries made with older Docling Math versions.
---

You can update libraries created with earlier versions (including v0.1) **without extracting PDFs again**.

The migration reads existing Markdown instead of starting OCR, CodeFormulaV2, TableFormer or the model download sequence.

## Quick start

From inside a project:

~~~powershell
upgrade-corpus
~~~

To choose the folder in a native dialog:

~~~powershell
upgrade-corpus --select-folder
~~~

Or name it explicitly:

~~~powershell
upgrade-corpus --corpus-dir "D:\Research\MyProject"
~~~

The path can point to the project root, <code>bib/</code> or <code>bib/extracted/</code>.

## What gets updated?

- Paper Markdown under <code>bib/extracted/</code>, preserving the extracted body.
- Split bibliography Markdown under <code>bib/references/</code>, preserving the reference body.
- Title, authors, year, DOI, journal, keywords, normalized tags and aliases when available.
- Related-paper links and PDF links for Obsidian.
- <code>INDEX.md</code> and <code>bundle.md</code> from the upgraded notes.
- A default managed vault in <code>project/obsidian-vault/</code>.

Before changing Markdown and index files, the tool snapshots the managed sources under <code>bib/.backups/</code>.

## Optional settings

Disable the vault:

~~~powershell
upgrade-corpus --select-folder --no-vault
~~~

Disable Obsidian-specific properties as well:

~~~powershell
upgrade-corpus --select-folder --no-obsidian --no-vault
~~~

Choose a custom vault:

~~~powershell
upgrade-corpus --obsidian-vault "D:\Notes\MyVault"
~~~

Embed Info/XMP metadata in original PDFs (explicit opt-in):

~~~powershell
upgrade-corpus --write-pdf-metadata
~~~

You can also use the unified CLI:

~~~powershell
docling-math --upgrade-corpus --select-folder
~~~
