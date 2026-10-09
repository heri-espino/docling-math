# Docling Math website

A lightweight, static website in the style of [AstroWind](https://github.com/arthelokyo/astrowind):
a tailored Astro/Tailwind landing page, animated with [Motion](https://motion.dev/) and
technical documentation powered by [Starlight](https://starlight.astro.build/).

This is an **AstroWind-inspired adaptation**, not an unmodified copy of the upstream theme.
The design, copy and demonstration artwork are specific to Docling Math. The homepage does
not upload documents or execute Python in the browser.

## Develop

Node.js 22.12+ is required.

~~~bash
cd website
npm install
npm run dev
~~~

## Build

~~~bash
npm run build
npm run preview
~~~

Astro renders static output into `website/dist/`.

The project is deliberately configured for the GitHub project page at:

https://heri-espino.github.io/docling-math/

The site uses `base: '/docling-math/'`. Avoid root-absolute links that bypass that prefix.
Build assertions in GitHub Actions check that the homepage, docs and prefixed links exist.

## Documentation

Files live in `src/content/docs/docs/` so Starlight generates routes within `/docs/` and
does not take over the landing page at `/`.

- `index.md`: overview
- `installation.md`: installation and packaging status
- `desktop.md`: graphical interface
- `extraction.md`: PDF conversion and OCR
- `upgrade-corpus.md`: upgrade without OCR
- `metadata-obsidian.md`: tags, metadata and vault
- `rename-literature.md`: coordinated file renaming
- `cli.md`: command reference
- `troubleshooting.md`: help

## Deployment

The `Website — Build and Pages deploy` workflow builds the site on website PRs and deploys
on merges to `main`.

One-time repository setup: **Settings → Pages → Build and deployment → GitHub Actions**.

A successful website build does not necessarily mean GitHub Pages is published: the Pages
deployment job must also succeed.

## Credits

Design-system approach inspired by AstroWind (MIT):
https://github.com/arthelokyo/astrowind

Built with Astro, Tailwind CSS, Starlight, Motion and Inter.
