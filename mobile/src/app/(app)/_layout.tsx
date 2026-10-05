import { Drawer } from 'expo-router/drawer';
import { HatGlasses, PanelLeftOpen } from 'lucide-react-native';
import { useWindowDimensions, View } from 'react-native';

import { IconButton } from '@/components/icon-button';
import { SecureAccount } from '@/components/secure-account';
import { ServerBanner, useServer } from '@/components/server-status';
import { Sidebar } from '@/components/sidebar';
import { PendingDeletion } from '@/components/account-security';
import { useAuth, useMe } from '@/lib/auth';
import { usePush } from '@/lib/push';
import { setSidebarCollapsed, toggleIncognito, useUI } from '@/lib/ui-store';
import { fonts } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

const SCREENS = [
  ['index', 'Chat'],
  ['jobs', 'Jobs'],
  ['scheduled', 'Scheduled'],
  ['sent', 'Sent'],
  ['channels', 'Channels'],
  ['templates', 'Templates'],
  ['resumes', 'Resumes'],
  ['profile', 'Profile'],
  ['senders', 'Email accounts'],
  ['stats', 'Stats'],
  ['notifications', 'Notifications'],
  ['settings', 'Settings'],
] as const;

export default function AppLayout() {
  const { colors } = useColors();
  const { width } = useWindowDimensions();
  const collapsed = useUI((s) => s.sidebarCollapsed);
  const incognito = useUI((s) => s.incognito);
  const offer2fa = useAuth((s) => s.offer2fa);
  const me = useMe();
  const server = useServer();
  usePush(); // phone notifications: register this phone, open the right screen on a tap

  if (offer2fa) return <SecureAccount />; // once, right after sign-up: set up 2FA or skip
  if (me.data?.delete_after && me.isFetchedAfterMount) return <PendingDeletion deleteAfter={me.data.delete_after} />; // keep it, or sign out

  const wide = width >= 1024; // laptop
  const pinned = wide && !collapsed; // sidebar always visible on the left
  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ServerBanner server={server} />
      <Drawer
        drawerContent={(props) => (
          <Sidebar
            onHide={() => (pinned ? setSidebarCollapsed(true) : props.navigation.closeDrawer())}
            onGo={() => {
              if (!pinned) props.navigation.closeDrawer();
            }}
          />
        )}
        screenOptions={({ navigation }) => ({
          drawerType: pinned ? 'permanent' : 'front',
          headerShown: true,
          headerLeft: pinned
            ? () => null
            : () => (
                <View style={{ marginLeft: 8 }}>
                  <IconButton
                    icon={PanelLeftOpen}
                    label="Show sidebar"
                    onPress={() => (wide ? setSidebarCollapsed(false) : navigation.toggleDrawer())}
                  />
                </View>
              ),
          headerStyle: { backgroundColor: colors.background },
          ...(server.state === 'ok' ? {} : { headerStatusBarHeight: 0 }), // the banner took the status-bar space
          headerShadowVisible: false,
          headerTintColor: colors.text,
          headerTitleStyle: { fontFamily: fonts.semibold, fontSize: 16 },
          drawerStyle: { backgroundColor: colors.surface, width: 280, borderRightColor: colors.border },
        })}>
        {SCREENS.map(([name, title]) =>
          name === 'index' ? (
            <Drawer.Screen
              key={name}
              name={name}
              options={{
                title: incognito ? 'Incognito chat' : title,
                headerRight: () => (
                  <View style={{ marginRight: 8 }}>
                    <IconButton icon={HatGlasses} label="Incognito chat" active={incognito} onPress={toggleIncognito} />
                  </View>
                ),
              }}
            />
          ) : (
            <Drawer.Screen key={name} name={name} options={{ title }} />
          ),
        )}
      </Drawer>
    </View>
  );
}
