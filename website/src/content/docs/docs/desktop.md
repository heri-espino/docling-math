---
title: Desktop application
description: Manage local scientific PDFs without typing CLI commands.
---

The Docling Math desktop application offers a native graphical interface built on top of the Python extraction library.

## Open or create a library

Choose **Open library** to select an existing project folder or its <code>bib/</code> directory. Choose **New library** to create the standard corpus structure inside a chosen folder.

The selected library contains PDFs, extracted Markdown and split reference notes.

## Extract PDFs

On the **Extract PDFs** screen:

1. Select or create a library.
2. Click **Add PDF files…** and choose one or more papers.
3. Select the extraction strategy and computing device.
4. Enable optional automatic renaming, embedded PDF metadata or figure/table assets.
5. Start extraction.

Conversion runs in a separate process so the graphical window can stay responsive. Follow activity and errors on the **Activity** tab. CPU fallback requires explicit consent.

The normal GUI workflow creates an Obsidian-ready library after extraction.

## Upgrade library

The **Upgrade library** screen updates an existing corpus without OCR or model loading. It refreshes Markdown properties and reference notes, rebuilds <code>INDEX.md</code> and <code>bundle.md</code>, and can create or update the vault.

## Rename papers

The **Rename papers** screen includes a filename editor, an optional JSON mapping import, a preview and explicit confirmation before applying changes.

## What is not included yet?

Drag-and-drop onto the application, a signed public Windows installer, Zotero syncing and autonomous agents remain future work. Use the file selection dialog in the current version.
