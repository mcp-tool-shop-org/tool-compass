// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';

// https://astro.build/config
export default defineConfig({
  site: 'https://mcp-tool-shop-org.github.io',
  base: '/tool-compass',
  integrations: [
    starlight({
      title: 'Tool Compass',
      description: 'Tool Compass handbook',
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/mcp-tool-shop-org/tool-compass' },
      ],
      sidebar: [
        // Diátaxis-aligned grouping (https://diataxis.fr/). Order: tutorials
        // (learn) → how-to (do) → reference (look up) → explanation (understand).
        {
          label: 'Overview',
          items: [
            { label: 'Handbook', slug: 'handbook' },
          ],
        },
        {
          label: 'Tutorials',
          items: [
            { label: 'Beginners', slug: 'handbook/beginners' },
            { label: 'Getting Started', slug: 'handbook/getting-started' },
          ],
        },
        {
          label: 'How-To Guides',
          items: [
            { label: 'Operations', slug: 'handbook/operations' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'Tools', slug: 'handbook/tools' },
            { label: 'Configuration', slug: 'handbook/configuration' },
          ],
        },
        {
          label: 'Explanation',
          items: [
            { label: 'Architecture', slug: 'handbook/architecture' },
          ],
        },
      ],
      customCss: ['./src/styles/starlight-custom.css'],
      disable404Route: true,
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
});
