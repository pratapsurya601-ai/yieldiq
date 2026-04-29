import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useColorScheme,
} from 'react-native';
import { useLocalSearchParams, Stack } from 'expo-router';
import { getAnalysis, ApiError, type AnalysisResponse } from '@/lib/api';
import { getTheme, spacing, radius, typography } from '@/theme/tokens';
import { HexAxes } from '@/components/HexAxes';

export default function AnalysisScreen() {
  const { ticker } = useLocalSearchParams<{ ticker: string }>();
  const scheme = useColorScheme();
  const theme = getTheme(scheme);

  const [data, setData] = useState<AnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    getAnalysis(ticker)
      .then(setData)
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : 'Failed to load analysis'),
      )
      .finally(() => setLoading(false));
  }, [ticker]);

  if (loading) {
    return (
      <View style={[styles.center, { backgroundColor: theme.bg }]}>
        <Stack.Screen options={{ title: ticker ?? 'Analysis', headerShown: true }} />
        <ActivityIndicator color={theme.brand} />
      </View>
    );
  }

  if (error || !data) {
    return (
      <View style={[styles.center, { backgroundColor: theme.bg }]}>
        <Stack.Screen options={{ title: ticker ?? 'Analysis', headerShown: true }} />
        <Text style={{ color: theme.danger }}>{error ?? 'No data'}</Text>
      </View>
    );
  }

  const mosColor =
    data.margin_of_safety > 0.2
      ? theme.success
      : data.margin_of_safety > 0
        ? theme.warning
        : theme.danger;

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: theme.bg }}
      contentContainerStyle={{ padding: spacing.lg }}
    >
      <Stack.Screen options={{ title: data.ticker, headerShown: true }} />

      <View
        style={[
          styles.hero,
          { backgroundColor: theme.surface, borderColor: theme.border },
        ]}
      >
        <Text style={[styles.ticker, { color: theme.ink }]}>{data.ticker}</Text>
        {data.current_price != null ? (
          <Text style={{ color: theme.caption, fontSize: typography.size.body }}>
            Current ₹{data.current_price.toFixed(2)}
          </Text>
        ) : null}

        <View style={styles.statsRow}>
          <Stat label="Fair Value" value={`₹${data.fair_value.toFixed(2)}`} color={theme.ink} />
          <Stat
            label="MoS"
            value={`${(data.margin_of_safety * 100).toFixed(0)}%`}
            color={mosColor}
          />
        </View>
        <View style={styles.statsRow}>
          <Stat label="Score" value={Math.round(data.score).toString()} color={theme.brand} />
          <Stat label="Grade" value={data.grade} color={theme.ink} />
        </View>
      </View>

      {data.hex_axes && Object.keys(data.hex_axes).length > 0 ? (
        <View
          style={[
            styles.section,
            { backgroundColor: theme.surface, borderColor: theme.border },
          ]}
        >
          <Text style={[styles.sectionTitle, { color: theme.ink }]}>Hex axes</Text>
          <View style={{ alignItems: 'center', marginTop: spacing.md }}>
            <HexAxes
              axes={data.hex_axes}
              fill={theme.brand}
              stroke={theme.brand}
              axisColor={theme.border}
              labelColor={theme.caption}
            />
          </View>
        </View>
      ) : null}

      {data.scenarios && data.scenarios.length > 0 ? (
        <View
          style={[
            styles.section,
            { backgroundColor: theme.surface, borderColor: theme.border },
          ]}
        >
          <Text style={[styles.sectionTitle, { color: theme.ink }]}>Scenarios</Text>
          {data.scenarios.map((sc) => (
            <View key={sc.name} style={styles.scenarioRow}>
              <Text style={{ color: theme.body }}>{sc.name}</Text>
              <Text style={{ color: theme.ink, fontWeight: typography.weight.semibold }}>
                ₹{sc.fair_value.toFixed(2)}
              </Text>
            </View>
          ))}
        </View>
      ) : null}
    </ScrollView>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={{ flex: 1 }}>
      <Text style={{ fontSize: typography.size.caption, opacity: 0.7 }}>{label}</Text>
      <Text style={{ fontSize: typography.size.h2, fontWeight: '700', color }}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  hero: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  ticker: {
    fontSize: typography.size.h1,
    fontWeight: typography.weight.bold,
  },
  statsRow: {
    flexDirection: 'row',
    marginTop: spacing.lg,
    gap: spacing.lg,
  },
  section: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  sectionTitle: {
    fontSize: typography.size.title,
    fontWeight: typography.weight.semibold,
  },
  scenarioRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm,
  },
});
