import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { PALETTE_KEYWORDS } from '@/components/command-palette/CommandPalette';
import { PANEL_ROUTES, PANEL_ROUTE_PATHS } from '@/routes/panelRoutes';
import { routes } from '@/routes';

// Four hand-kept nav lists let a page go missing from the sidebar or fall back to the "3X-UI"
// title; the manifest replaced them, and these tests hold it to the router and the bundle.

const translationDir = resolve(process.cwd(), '..', 'internal', 'web', 'translation');

function flattenKeys(obj: Record<string, unknown>, prefix = ''): string[] {
  const keys: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const key = `${prefix}${k}`;
    if (v !== null && typeof v === 'object') {
      keys.push(...flattenKeys(v as Record<string, unknown>, `${key}.`));
    } else {
      keys.push(key);
    }
  }
  return keys;
}

describe('panel navigation', () => {
  it('lists every route once', () => {
    expect(new Set(PANEL_ROUTE_PATHS).size).toBe(PANEL_ROUTE_PATHS.length);
  });

  it('does not expose sponsor pages', () => {
    expect(PANEL_ROUTE_PATHS).not.toContain('/sponsors');
    expect(Object.keys(PALETTE_KEYWORDS)).not.toContain('/sponsors');
  });

  it('removes sponsor API and donation copy from active translations', () => {
    const translationFiles = readdirSync(translationDir).filter((file) => file.endsWith('.json'));
    for (const file of translationFiles) {
      const translation = JSON.parse(
        readFileSync(join(translationDir, file), 'utf8'),
      ) as Record<string, unknown>;
      const keys = flattenKeys(translation);
      expect(keys).not.toContain('menu.donate');
      expect(keys).not.toContain('menu.sponsors');
      expect(keys).not.toContain('pages.sponsors');
    }
    const openapi = JSON.parse(
      readFileSync(resolve(process.cwd(), 'public/openapi.json'), 'utf8'),
    ) as { paths: Record<string, unknown>; components?: { schemas?: Record<string, unknown> } };
    expect(openapi.paths).not.toHaveProperty('/sponsors');
    expect(openapi.components?.schemas).not.toHaveProperty('Sponsor');
    expect(openapi.components?.schemas).not.toHaveProperty('SponsorList');
  });

  it('uses the owned repository for sidebar and subscription documentation links', () => {
    const sidebar = readFileSync(resolve(process.cwd(), 'src/layouts/AppSidebar.tsx'), 'utf8');
    const subscription = readFileSync(
      resolve(process.cwd(), 'src/pages/settings/SubscriptionGeneralTab.tsx'),
      'utf8',
    );
    expect(sidebar).toContain('https://github.com/shiyi-log/X-ray');
    expect(sidebar).not.toContain('https://github.com/MHSanaei/3x-ui');
    expect(sidebar).not.toContain('donate.sanaei.dev');
    expect(subscription).toContain(
      'https://github.com/shiyi-log/X-ray/blob/main/docs/custom-subscription-templates.md',
    );
    expect(subscription).not.toContain('https://github.com/MHSanaei/3x-ui');
  });

  it('routes every manifest path', () => {
    const childPaths = (routes[0].children ?? []).map((child) =>
      child.index ? '/' : `/${child.path ?? ''}`,
    );
    expect(childPaths.sort()).toEqual([...PANEL_ROUTE_PATHS].sort());
  });

  it('translates every title key', () => {
    const enKeys = new Set(
      flattenKeys(
        JSON.parse(readFileSync(join(translationDir, 'en-US.json'), 'utf8')) as Record<
          string,
          unknown
        >,
      ),
    );
    for (const route of PANEL_ROUTES) {
      expect(enKeys.has(route.titleKey)).toBe(true);
    }
  });

  it('gives every route command-palette keywords', () => {
    expect(Object.keys(PALETTE_KEYWORDS).sort()).toEqual([...PANEL_ROUTE_PATHS].sort());
  });
});
