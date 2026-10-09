---
title: Rename literature
description: Rename academic PDF filenames and keep Markdown, references and index links synchronized.
---

Docling Math supports safe filename changes for a complete literature corpus.

A rename can affect:

- The PDF file under <code>bib/pdf/</code>.
- The corresponding Markdown note.
- Its split references note.
- Its optional asset folder.
- Links inside other Markdown files, <code>INDEX.md</code> and <code>bundle.md</code>.

## Preview first

The desktop GUI includes a filename editor and **Preview changes** action.

For the CLI, provide a mapping:

~~~json
{
  "123456.pdf": "Researcher_Author-2026-Smooth_trends.pdf"
}
~~~

Save it as <code>renames.json</code> and preview:

~~~powershell
rename-literature --map renames.json --dry-run
~~~

Apply after reviewing the plan:

~~~powershell
rename-literature --map renames.json
~~~

You can also pass individual pairs using the repeated <code>--rename</code> option.

The rename utility checks for collisions, moves files in stages, and includes rollback protections. Always maintain a separate library backup for valuable work.
