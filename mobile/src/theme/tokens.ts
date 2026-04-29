/**
 * Design tokens mirrored from frontend/src/app/globals.css.
 *
 * Source of truth is the webapp; we duplicate here so RN can apply the
 * same palette without pulling in Tailwind. When webapp tokens shift,
 * sync this file in the same PR — see docs/mobile_app_design.md.
 */

export const colors = {
  light: {
    bg: '#FFFFFF',
    surface: '#F8FAFC',
    border: '#E2E8F0',
    ink: '#0F172A',
    body: '#334155',
    caption: '#64748B',
    brand: '#2563EB',
    brand50: '#EFF6FF',
    success: '#059669',
    warning: '#D97706',
    danger: '#DC2626',
  },
  dark: {
    bg: '#0B1220',
    surface: '#131B2C',
    border: '#1F2A3F',
    ink: '#F8FAFC',
    body: '#CBD5E1',
    caption: '#94A3B8',
    brand: '#60A5FA',
    brand50: '#1E3A8A',
    success: '#34D399',
    warning: '#FBBF24',
    danger: '#F87171',
  },
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 6,
  md: 10,
  lg: 14,
  xl: 20,
} as const;

export const typography = {
  // Match frontend Inter / system stack. Phase 2: load Inter via expo-font.
  family: undefined as string | undefined,
  size: {
    caption: 12,
    body: 14,
    bodyLg: 16,
    title: 20,
    h2: 24,
    h1: 32,
    hero: 40,
  },
  weight: {
    regular: '400' as const,
    medium: '500' as const,
    semibold: '600' as const,
    bold: '700' as const,
  },
} as const;

export type Theme = typeof colors.light;

/**
 * Hook-free getter — pass the colorScheme from useColorScheme().
 * Defaults to light for SSR / pre-hydration paint.
 */
export function getTheme(scheme: 'light' | 'dark' | null | undefined): Theme {
  return scheme === 'dark' ? colors.dark : colors.light;
}
