import { Tabs, Redirect } from 'expo-router';
import { useColorScheme } from 'react-native';
import { useAuthStore } from '@/store/authStore';
import { getTheme } from '@/theme/tokens';

export default function AppLayout() {
  const token = useAuthStore((s) => s.token);
  const scheme = useColorScheme();
  const theme = getTheme(scheme);

  if (!token) return <Redirect href="/(auth)/login" />;

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: theme.brand,
        tabBarInactiveTintColor: theme.caption,
        tabBarStyle: {
          backgroundColor: theme.bg,
          borderTopColor: theme.border,
        },
        headerStyle: { backgroundColor: theme.bg },
        headerTitleStyle: { color: theme.ink },
        sceneStyle: { backgroundColor: theme.bg },
      }}
    >
      <Tabs.Screen name="home" options={{ title: 'Home' }} />
      <Tabs.Screen name="watchlist" options={{ title: 'Watchlist' }} />
      <Tabs.Screen name="search" options={{ title: 'Search' }} />
      <Tabs.Screen name="account" options={{ title: 'Account' }} />
      {/* Hide nested route from the tab bar; it's reached by tapping a row. */}
      <Tabs.Screen name="analysis/[ticker]" options={{ href: null }} />
    </Tabs>
  );
}
