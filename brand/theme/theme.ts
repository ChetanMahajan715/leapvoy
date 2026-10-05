// Leapvoy design tokens: used by every screen. Change colors here only.
export const palette = {
  gold: '#F5A524',      // Leap Gold, primary buttons, active states
  spark: '#FFC94D',     // highlights, logo dot, dark-mode accents
  goldDeep: '#B26A00',  // gold text/icons on light backgrounds (readable)
  ink: '#0C0F1A',       // Midnight Ink, brand base
  ink2: '#1B2033',
};

// Pure white / pure black like ChatGPT (user, 4 Oct): neutral greys only, no blue or purple tint; gold is the one
// accent (main buttons, active item, fit pills).
export const light = {
  background: '#FFFFFF',
  surface: '#F9F9F9', // sidebar, drawers
  surfaceAlt: '#F0F0F0', // hover, pressed, selected rows
  text: '#0D0D0D',
  textMuted: '#5D5D5D',
  border: '#E5E5E5',
  primary: palette.gold,
  onPrimary: '#0D0D0D',
  primarySoft: '#FFF4DC',
  primaryText: palette.goldDeep,
  userBubble: '#F0F0F0',
  scrim: 'rgba(0, 0, 0, 0.4)', // behind floating windows
  chart: palette.goldDeep, // chart bars (3:1 on white, checked with the dataviz validator)
  glass: '#FFFFFF', // cards
  glassBorder: '#E5E5E5',
  inset: '#F7F7F7', // text boxes, fact rows
  successSoft: '#E7F6EC', warningSoft: '#FDF1DE',
  cardShadow: '0px 1px 3px rgba(0, 0, 0, 0.06)',
  buttonGlow: '0px 1px 2px rgba(0, 0, 0, 0.10)',
  success: '#16A34A', warning: '#D97706', error: '#DC2626', info: '#2563EB',
};

export const dark = {
  background: '#000000',
  surface: '#0D0D0D', // sidebar, drawers
  surfaceAlt: '#1F1F1F', // hover, pressed, selected rows
  text: '#ECECEC',
  textMuted: '#A3A3A3',
  border: '#262626',
  primary: palette.gold,
  onPrimary: '#0D0D0D',
  primarySoft: 'rgba(245, 165, 36, 0.14)',
  primaryText: palette.spark,
  userBubble: '#262626',
  scrim: 'rgba(0, 0, 0, 0.7)',
  chart: palette.gold, // chart bars (3:1 on the dark surface)
  glass: '#121212', // cards
  glassBorder: '#262626',
  inset: '#0A0A0A', // text boxes, fact rows
  successSoft: 'rgba(52, 211, 153, 0.12)', warningSoft: 'rgba(251, 191, 36, 0.12)',
  cardShadow: '0px 1px 2px rgba(0, 0, 0, 0.6)',
  buttonGlow: '0px 1px 2px rgba(0, 0, 0, 0.5)',
  success: '#34D399', warning: '#FBBF24', error: '#F87171', info: '#60A5FA',
};

export const radius = { sm: 10, md: 14, lg: 18, pill: 999 };
export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };

export const fonts = {
  heading: 'PlusJakartaSans_800ExtraBold',
  semibold: 'PlusJakartaSans_600SemiBold',
  body: 'PlusJakartaSans_400Regular',
  mono: 'JetBrainsMono_400Regular',
};

// Appearance setting stored per user: 'system' | 'light' | 'dark' (default: 'system')
export type Appearance = 'system' | 'light' | 'dark';
