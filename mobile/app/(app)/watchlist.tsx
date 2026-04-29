import { useEffect, useState, useCallback } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
  useColorScheme,
} from 'react-native';
import { router } from 'expo-router';
import { getWatchlist, ApiError, type WatchlistItem } from '@/lib/api';
import { getTheme, spacing, radius, typography } from '@/theme/tokens';

export default function WatchlistScreen() {
  const scheme = useColorScheme();
  const theme = getTheme(scheme);

  const [items, setItems] = useState<WatchlistItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getWatchlist();
      setItems(res.items ?? []);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load watchlist');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <View style={[styles.center, { backgroundColor: theme.bg }]}>
        <ActivityIndicator color={theme.brand} />
      </View>
    );
  }

  return (
    <FlatList
      style={{ backgroundColor: theme.bg }}
      contentContainerStyle={{ padding: spacing.lg }}
      data={items ?? []}
      keyExtractor={(it) => it.ticker}
      ListEmptyComponent={
        <Text style={{ color: theme.caption, textAlign: 'center', marginTop: spacing.xl }}>
          {error ?? 'No tickers yet. Search and add some.'}
        </Text>
      }
      renderItem={({ item }) => (
        <Pressable
          onPress={() => router.push(`/(app)/analysis/${item.ticker}`)}
          style={({ pressed }) => [
            styles.row,
            {
              backgroundColor: theme.surface,
              borderColor: theme.border,
              opacity: pressed ? 0.7 : 1,
            },
          ]}
        >
          <View style={{ flex: 1 }}>
            <Text style={[styles.ticker, { color: theme.ink }]}>{item.ticker}</Text>
            <Text style={{ color: theme.caption, fontSize: typography.size.caption }}>
              FV {fmt(item.fair_value)} · MoS {fmtPct(item.margin_of_safety)}
            </Text>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Text style={[styles.score, { color: theme.brand }]}>
              {item.score != null ? Math.round(item.score) : '—'}
            </Text>
            {item.grade ? (
              <Text style={{ color: theme.caption }}>{item.grade}</Text>
            ) : null}
          </View>
        </Pressable>
      )}
    />
  );
}

function fmt(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return n.toFixed(2);
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return `${(n * 100).toFixed(0)}%`;
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.lg,
    borderRadius: radius.md,
    borderWidth: 1,
    marginBottom: spacing.sm,
  },
  ticker: {
    fontSize: typography.size.bodyLg,
    fontWeight: typography.weight.semibold,
  },
  score: {
    fontSize: typography.size.title,
    fontWeight: typography.weight.bold,
  },
});
