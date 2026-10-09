---
title: Installation
description: Install Docling Math locally, use CUDA where supported, and access the graphical interface.
---

Docling Math runs on your computer. The desktop interface uses the same extraction engine as the Python CLI.

## Windows installer

A per-user Windows installer build is defined in the repository, but it is **experimental** until a packaged release has been built and tested with real PDFs.

- Check [GitHub Releases](https://github.com/heri-espino/docling-math/releases) for published installers.
- Advanced users can open [Build Windows desktop installer](https://github.com/heri-espino/docling-math/actions/workflows/windows-installer.yml), choose the CUDA or CPU variant and download a successful build artifact.
- A future signed installer will be distributed from Releases; the current build may be unsigned.

The installer is designed to create Start menu and optional Desktop shortcuts without needing a system-wide Python installation.

## Install the Python project (developers)

A Python 3.12 environment is recommended. From a clone of the repository:

~~~powershell
conda env create -f environment.yml
conda activate docling-math
python -m pip install -e .
~~~

For an existing environment:

~~~powershell
conda env update -f environment.yml --prune
python -m pip install -e .
~~~

After installation, the application is available as **docling-math-gui**. On Windows, the GUI-script entry point can be opened directly from the environment's Scripts directory.

You can also use the CLI:

~~~powershell
docling-math --help
upgrade-corpus --help
rename-literature --help
~~~

## NVIDIA GPU / CPU

The engine prefers an available accelerator when configured for auto selection. A compatible PyTorch installation is required for CUDA support.

CPU extraction is slower and the program requires explicit acknowledgement before using CPU as a fallback. The desktop app exposes this as a checkbox.

On first use, Docling model weights may be downloaded and cached. The models are reused on subsequent runs.

## Configuration notes

- Python: 3.11–3.13 supported by the declared package range; 3.12 is recommended.
- Model cache: typically in your home directory under <code>.cache/docling/models</code>.
- Operating-system compatibility: verify the required PyTorch and Docling runtimes for your platform.
- The README contains platform-specific and package requirements.

See [Troubleshooting](./troubleshooting/) if model downloads or GPU detection fail.
