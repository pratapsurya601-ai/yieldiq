import { Pressable, StyleSheet, Text, View, useColorScheme } from 'react-native';
import { router } from 'expo-router';
import { useAuthStore } from '@/store/authStore';
import { clearStoredToken } from '@/lib/api';
import { getTheme, spacing, radius, typography } from '@/theme/tokens';

export default function AccountScreen() {
  const scheme = useColorScheme();
  const theme = getTheme(scheme);
  const email = useAuthStore((s) => s.email);
  const tier = useAuthStore((s) => s.tier);
  const logout = useAuthStore((s) => s.logout);

  const onSignOut = async () => {
    await clearStoredToken();
    logout();
    router.replace('/(auth)/login');
  };

  return (
    <View style={{ flex: 1, backgroundColor: theme.bg, padding: spacing.xl }}>
      <Text style={[styles.label, { color: theme.caption }]}>Signed in as</Text>
      <Text style={[styles.value, { color: theme.ink }]}>{email ?? '—'}</Text>

      <Text style={[styles.label, { color: theme.caption }]}>Plan</Text>
      <Text style={[styles.value, { color: theme.ink }]}>{tier}</Text>

      <Pressable
        testID="signout-btn"
        onPress={onSignOut}
        style={({ pressed }) => [
          styles.button,
          { backgroundColor: theme.danger, opacity: pressed ? 0.7 : 1 },
        ]}
      >
        <Text style={styles.buttonText}>Sign out</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  label: {
    fontSize: typography.size.caption,
    textTransform: 'uppercase',
    marginTop: spacing.lg,
  },
  value: {
    fontSize: typography.size.bodyLg,
    fontWeight: typography.weight.semibold,
    marginTop: spacing.xs,
  },
  button: {
    marginTop: spacing.xxl,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  buttonText: {
    color: '#fff',
    fontSize: typography.size.bodyLg,
    fontWeight: typography.weight.semibold,
  },
});
