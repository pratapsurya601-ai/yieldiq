import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  useColorScheme,
} from 'react-native';
import { router } from 'expo-router';
import { login, setStoredToken, ApiError } from '@/lib/api';
import { useAuthStore } from '@/store/authStore';
import { getTheme, spacing, radius, typography } from '@/theme/tokens';

export default function LoginScreen() {
  const scheme = useColorScheme();
  const theme = getTheme(scheme);
  const setAuth = useAuthStore((s) => s.setAuth);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await login(email.trim(), password);
      await setStoredToken(res.access_token);
      setAuth(
        res.access_token,
        res.user_id,
        res.email,
        res.tier,
        res.analyses_today ?? 0,
        res.analysis_limit ?? 5,
        res.display_name ?? null,
        res.display_name_edits_remaining ?? 3,
        res.feature_flags ?? {},
      );
      router.replace('/(app)/home');
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : 'Login failed';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={[styles.container, { backgroundColor: theme.bg }]}
    >
      <View style={styles.inner}>
        <Text style={[styles.title, { color: theme.ink }]}>YieldIQ</Text>
        <Text style={[styles.subtitle, { color: theme.caption }]}>
          Sign in to your account
        </Text>

        <TextInput
          accessibilityLabel="email"
          testID="login-email"
          style={[
            styles.input,
            { borderColor: theme.border, color: theme.ink, backgroundColor: theme.surface },
          ]}
          placeholder="Email"
          placeholderTextColor={theme.caption}
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          value={email}
          onChangeText={setEmail}
        />
        <TextInput
          accessibilityLabel="password"
          testID="login-password"
          style={[
            styles.input,
            { borderColor: theme.border, color: theme.ink, backgroundColor: theme.surface },
          ]}
          placeholder="Password"
          placeholderTextColor={theme.caption}
          secureTextEntry
          value={password}
          onChangeText={setPassword}
        />

        {error ? (
          <Text style={[styles.error, { color: theme.danger }]} testID="login-error">
            {error}
          </Text>
        ) : null}

        <Pressable
          testID="login-submit"
          accessibilityRole="button"
          onPress={onSubmit}
          disabled={loading || !email || !password}
          style={({ pressed }) => [
            styles.button,
            {
              backgroundColor: theme.brand,
              opacity: pressed || loading || !email || !password ? 0.7 : 1,
            },
          ]}
        >
          {loading ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.buttonText}>Sign in</Text>
          )}
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  inner: { flex: 1, justifyContent: 'center', padding: spacing.xl },
  title: {
    fontSize: typography.size.hero,
    fontWeight: typography.weight.bold,
    marginBottom: spacing.xs,
  },
  subtitle: {
    fontSize: typography.size.bodyLg,
    marginBottom: spacing.xl,
  },
  input: {
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    marginBottom: spacing.md,
    fontSize: typography.size.bodyLg,
  },
  button: {
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: 'center',
    marginTop: spacing.md,
  },
  buttonText: {
    color: '#fff',
    fontSize: typography.size.bodyLg,
    fontWeight: typography.weight.semibold,
  },
  error: {
    fontSize: typography.size.body,
    marginBottom: spacing.sm,
  },
});
