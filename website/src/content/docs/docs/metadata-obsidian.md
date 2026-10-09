---
title: Metadata & Obsidian
description: Generate searchable properties, bibliographic tags and a linked Obsidian vault.
---

Every new extracted paper receives YAML front matter containing bibliographic properties when they can be inferred. Tags and aliases are formatted for Obsidian.

## An example note

~~~yaml
---
title: Estimating smooth trends
authors:
  - A. Researcher
  - B. Author
year: 2026
doi: 10.1234/example
keywords:
  - Time series analysis
  - Trend estimation
tags:
  - literature
  - year/2026
  - time-series
  - trend-estimation
aliases:
  - Estimating smooth trends
---
~~~

**Keywords** represent the original terminology provided by a paper. **Tags** are normalized categories for organization and discovery. They should not be treated as author-supplied claims.

## Embedded PDF metadata

Writing into PDF Info/XMP requires an explicit flag. It can update title, authors, keywords, journal and identifiers. The original pages remain, but PDF rewriting may invalidate digital signatures.

## Obsidian library

The default corpus upgrade generates a separate Obsidian vault:

~~~text
project/
├── bib/
│   ├── pdf/
│   ├── extracted/
│   └── references/
└── obsidian-vault/
    └── Literature/
        ├── Paper.md
        ├── References/
        │   └── Paper.references.md
        ├── _Index.md
        ├── _Bundle.md
        └── Attachments/
            ├── PDFs/
            └── Assets/
~~~

The vault mirror updates note links to point to its local PDF and reference copies. Original extracted Markdown and PDFs are maintained inside <code>bib/</code>.

Run with a chosen location:

~~~powershell
upgrade-corpus --select-folder --obsidian-vault "D:\Obsidian\Science"
~~~

The optional related-paper list uses shared topic tags, not an LLM, so links are deterministic and conservative.
