import { JetBrainsMono_400Regular } from '@expo-google-fonts/jetbrains-mono';
import {
  PlusJakartaSans_400Regular,
  PlusJakartaSans_600SemiBold,
  PlusJakartaSans_800ExtraBold,
  useFonts,
} from '@expo-google-fonts/plus-jakarta-sans';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { loadServer } from '@/lib/api';
import { Opening } from '@/components/opening';
import { useAuth } from '@/lib/auth';
import { KeyboardRoot } from '@/lib/keyboard';
import { loadPicks } from '@/lib/models';
import { loadSeen } from '@/lib/new-jobs';
import { persistOptions, queryClient } from '@/lib/query';
import { fonts } from '@/theme/theme';
import { loadUI } from '@/lib/ui-store';
import { loadAppearance, useColors } from '@/theme/use-colors';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({
    PlusJakartaSans_400Regular,
    PlusJakartaSans_600SemiBold,
    PlusJakartaSans_800ExtraBold,
    JetBrainsMono_400Regular,
  });
  const status = useAuth((s) => s.status);
  const { colors, scheme } = useColors();

  useEffect(() => {
    loadAppearance();
    loadUI();
    loadSeen();
    loadPicks();
    loadServer().finally(() => useAuth.getState().init()); // the saved server address first, then the sign-in check
  }, []);

  const ready = (fontsLoaded || !!fontError) && status !== 'loading'; // fonts failed: system font, never a blank app
  useEffect(() => {
    if (ready) SplashScreen.hideAsync();
  }, [ready]);
  if (!ready) return null;

  const base = scheme === 'dark' ? DarkTheme : DefaultTheme;
  const navTheme = {
    ...base,
    colors: {
      ...base.colors,
      primary: colors.primary,
      background: colors.background,
      card: colors.surface,
      text: colors.text,
      border: colors.border,
    },
    fonts: { ...base.fonts, regular: { fontFamily: fonts.body, fontWeight: '400' as const } },
  };

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <KeyboardRoot>
          <PersistQueryClientProvider client={queryClient} persistOptions={persistOptions}>
            <ThemeProvider value={navTheme}>
              <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
              <Stack screenOptions={{ headerShown: false, animation: 'fade' }}>
                <Stack.Protected guard={status === 'signedIn'}>
                  <Stack.Screen name="(app)" />
                </Stack.Protected>
                <Stack.Protected guard={status !== 'signedIn'}>
                  <Stack.Screen name="sign-in" />
                  <Stack.Screen name="sign-up" />
                  <Stack.Screen name="forgot-password" />
                </Stack.Protected>
              </Stack>
              <Opening />
            </ThemeProvider>
          </PersistQueryClientProvider>
        </KeyboardRoot>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
