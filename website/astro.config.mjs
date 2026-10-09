import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';

// GitHub project pages live at /docling-math/ instead of domain root.
export default defineConfig({
  site: 'https://heri-espino.github.io',
  base: '/docling-math/',
  integrations: [
    starlight({
      title: 'Docling Math',
      description: 'Documentation for a local-first scientific PDF extraction toolkit.',
      customCss: ['./src/styles/docs.css'],
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/heri-espino/docling-math' },
      ],
      sidebar: [
        {
          label: 'Getting started',
          items: [
            { label: 'Overview', slug: 'docs' },
            { label: 'Installation', slug: 'docs/installation' },
            { label: 'Desktop application', slug: 'docs/desktop' },
            { label: 'PDF extraction', slug: 'docs/extraction' },
          ],
        },
        {
          label: 'Library workflows',
          items: [
            { label: 'Upgrade a corpus', slug: 'docs/upgrade-corpus' },
            { label: 'Metadata & Obsidian', slug: 'docs/metadata-obsidian' },
            { label: 'Rename literature', slug: 'docs/rename-literature' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'CLI reference', slug: 'docs/cli' },
            { label: 'Troubleshooting', slug: 'docs/troubleshooting' },
          ],
        },
      ],
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
});
