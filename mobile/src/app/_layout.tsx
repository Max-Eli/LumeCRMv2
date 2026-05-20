import '@/global.css';

import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { colors } from '@/constants/theme';
import { AppLockProvider } from '@/lib/app-lock';
import { AuthProvider, useAuth } from '@/lib/auth';

// Hold the splash screen until the auth provider has restored (or
// ruled out) a session, so the first painted screen is the right one.
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <StatusBar style="dark" />
        <AuthProvider>
          <AppLockProvider>
            <RootNavigator />
          </AppLockProvider>
        </AuthProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

/**
 * Auth-aware routing. Exactly one route group is reachable at a time;
 * `Stack.Protected` guards keep the others off the navigation graph
 * entirely, so there is no client-side path into a screen the current
 * auth state shouldn't allow.
 */
function RootNavigator() {
  const { status } = useAuth();

  useEffect(() => {
    if (status !== 'loading') {
      SplashScreen.hideAsync();
    }
  }, [status]);

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    >
      <Stack.Protected guard={status === 'signed-in'}>
        <Stack.Screen name="(app)" />
      </Stack.Protected>

      <Stack.Protected guard={status === 'need-credentials'}>
        <Stack.Screen name="login" />
      </Stack.Protected>

      {/* `loading` shows the workspace route underneath the splash, so
          the navigator always has a mounted screen during the launch
          check. */}
      <Stack.Protected
        guard={status === 'need-workspace' || status === 'loading'}
      >
        <Stack.Screen name="workspace" />
      </Stack.Protected>
    </Stack>
  );
}

