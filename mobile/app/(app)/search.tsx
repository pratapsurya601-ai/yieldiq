import { useEffect, useMemo, useState } from 'react';
import {
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  useColorScheme,
} from 'react-native';
import { router } from 'expo-router';
import { getAllTickers } from '@/lib/api';
import { getTheme, spacing, radius, typography } from '@/theme/tokens';

interface TickerRow {
  ticker: string;
  name: string;
}

export default function SearchScreen() {
  const scheme = useColorScheme();
  const theme = getTheme(scheme);
  const [all, setAll] = useState<TickerRow[]>([]);
  const [q, setQ] = useState('');

  useEffect(() => {
    getAllTickers()
      .then((res) => setAll(res.tickers ?? []))
      .catch(() => setAll([]));
  }, []);

  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return all.slice(0, 50);
    return all
      .filter(
        (t) =>
          t.ticker.toLowerCase().includes(needle) ||
          t.name.toLowerCase().includes(needle),
      )
      .slice(0, 50);
  }, [q, all]);

  return (
    <View style={{ flex: 1, backgroundColor: theme.bg, padding: spacing.lg }}>
      <TextInput
        placeholder="Search ticker or company"
        placeholderTextColor={theme.caption}
        value={q}
        onChangeText={setQ}
        autoCapitalize="characters"
        autoCorrect={false}
        style={{
          borderWidth: 1,
          borderColor: theme.border,
          backgroundColor: theme.surface,
          color: theme.ink,
          borderRadius: radius.md,
          paddingHorizontal: spacing.lg,
          paddingVertical: spacing.md,
          fontSize: typography.size.bodyLg,
          marginBottom: spacing.md,
        }}
      />
      <FlatList
        data={results}
        keyExtractor={(it) => it.ticker}
        renderItem={({ item }) => (
          <Pressable
            onPress={() => router.push(`/(app)/analysis/${item.ticker}`)}
            style={({ pressed }) => [
              styles.row,
              {
                borderBottomColor: theme.border,
                opacity: pressed ? 0.6 : 1,
              },
            ]}
          >
            <Text style={[styles.ticker, { color: theme.ink }]}>{item.ticker}</Text>
            <Text style={{ color: theme.caption }} numberOfLines={1}>
              {item.name}
            </Text>
          </Pressable>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
  },
  ticker: {
    fontSize: typography.size.bodyLg,
    fontWeight: typography.weight.semibold,
  },
});
