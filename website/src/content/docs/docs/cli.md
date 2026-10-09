---
title: CLI reference
description: Common commands and options for extraction, upgrading and renaming.
---

The graphical desktop app is preferred for routine tasks. The CLI remains available for automation and reproducible workflows.

## Extract

~~~powershell
docling-math
docling-math --paper "paper.pdf"
docling-math --strategy compare
docling-math --device cuda
docling-math --assets
docling-math --rename-pdfs
~~~

Use <code>--device auto</code> to let the engine choose an available accelerator, subject to its CPU confirmation policy.

## Upgrade

~~~powershell
upgrade-corpus --select-folder
upgrade-corpus --corpus-dir "D:\Research\MyProject"
upgrade-corpus --no-vault
upgrade-corpus --write-pdf-metadata
docling-math --upgrade-corpus
~~~

## Rename

~~~powershell
rename-literature --map renames.json --dry-run
rename-literature --map renames.json
~~~

## Desktop

The Windows GUI entry point is <code>docling-math-gui</code>. It is installed alongside the CLI when the package is installed correctly.

For exhaustive options and defaults, prefer the commands' own <code>--help</code> output and the [repository README](https://github.com/heri-espino/docling-math).
