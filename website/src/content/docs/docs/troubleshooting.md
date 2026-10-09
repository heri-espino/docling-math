---
title: Troubleshooting
description: Fix library paths, missing model weights, GPU issues and Windows installation problems.
---

## The program cannot find my library

Select the project root or its <code>bib/</code> directory. An existing library should include <code>bib/pdf/</code> and <code>bib/extracted/</code>. Use **New library** to create the expected structure.

## My GPU is not available

CUDA support depends on the installed PyTorch variant, your NVIDIA driver and the accelerator's compatibility. Confirm the GPU works in the Python environment. CPU execution is possible but slower and requires explicit consent.

## The first extraction is slow

Docling Math may need to download and cache weights on the first run. Later conversions should reuse those models unless they were removed, upgraded or force-refreshed.

## Upgrade seems to reprocess documents

Use the explicit <code>upgrade-corpus</code> operation rather than forcing a new extraction. It reads existing Markdown and does not load OCR models.

## The Windows installer is not available

A manual packaging workflow exists in GitHub Actions, but the availability of a verified installer depends on successful Windows build and real-PDF validation. Check [Releases](https://github.com/heri-espino/docling-math/releases) and the [Windows workflow](https://github.com/heri-espino/docling-math/actions/workflows/windows-installer.yml).

## Report a bug

Please open a [GitHub issue](https://github.com/heri-espino/docling-math/issues) with your operating system, Docling Math version and relevant logs. Avoid including private source PDFs or sensitive document content.
