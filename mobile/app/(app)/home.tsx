import { ScrollView, StyleSheet, Text, View, useColorScheme } from 'react-native';
import { useAuthStore } from '@/store/authStore';
import { getTheme, spacing, radius, typography } from '@/theme/tokens';

export default function HomeScreen() {
  const scheme = useColorScheme();
  const theme = getTheme(scheme);
  const email = useAuthStore((s) => s.email);
  const analysesToday = useAuthStore((s) => s.analysesToday);
  const analysisLimit = useAuthStore((s) => s.analysisLimit);

  const greeting = email ? email.split('@')[0] : 'there';

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: theme.bg }}
      contentContainerStyle={{ padding: spacing.xl }}
    >
      <Text style={[styles.greeting, { color: theme.ink }]}>Hi, {greeting}</Text>
      <Text style={[styles.sub, { color: theme.caption }]}>
        {analysesToday}/{analysisLimit} analyses used today
      </Text>

      <View
        style={[
          styles.card,
          { backgroundColor: theme.surface, borderColor: theme.border },
        ]}
      >
        <Text style={[styles.cardTitle, { color: theme.ink }]}>Watchlist</Text>
        <Text style={{ color: theme.body }}>
          Your saved tickers will appear here. See the Watchlist tab for the
          full list.
        </Text>
      </View>

      <View
        style={[
          styles.card,
          { backgroundColor: theme.surface, borderColor: theme.border },
        ]}
      >
        <Text style={[styles.cardTitle, { color: theme.ink }]}>
          Market indices
        </Text>
        <Text style={{ color: theme.caption }}>
          Phase 2 — wire to /api/v1/public/market-pulse
        </Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  greeting: {
    fontSize: typography.size.h1,
    fontWeight: typography.weight.bold,
    marginBottom: spacing.xs,
  },
  sub: {
    fontSize: typography.size.body,
    marginBottom: spacing.xl,
  },
  card: {
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    marginBottom: spacing.lg,
  },
  cardTitle: {
    fontSize: typography.size.title,
    fontWeight: typography.weight.semibold,
    marginBottom: spacing.sm,
  },
});
