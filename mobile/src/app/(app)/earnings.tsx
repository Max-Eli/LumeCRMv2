import { Feather } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useMemo } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, layout, radius, spacing } from '@/constants/theme';
import {
  formatCents,
  useCommissionEntries,
  useCommissionTotals,
  type CommissionEntry,
  type CommissionTotalRow,
} from '@/lib/commissions';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/** Commission earnings — net for the month, per-provider breakdown,
 *  and the line-by-line ledger. A provider sees their own; an
 *  owner/manager sees the team's. */
export default function EarningsScreen() {
  const range = useMemo(() => {
    const now = new Date();
    const from = new Date(now.getFullYear(), now.getMonth(), 1);
    return {
      from: from.toISOString(),
      to: now.toISOString(),
      label: `${MONTHS[now.getMonth()]} ${now.getFullYear()}`,
    };
  }, []);

  const totals = useCommissionTotals(range);
  const entries = useCommissionEntries(range);

  const totalRows = totals.data ?? [];
  const net = totalRows.reduce((sum, r) => sum + r.net_cents, 0);
  const ledger = [...(entries.data ?? [])].sort((a, b) =>
    b.accrued_at.localeCompare(a.accrued_at),
  );
  const loading = totals.isLoading || entries.isLoading;

  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <View style={styles.header}>
        <Pressable
          onPress={() => router.back()}
          accessibilityRole="button"
          accessibilityLabel="Back"
          hitSlop={10}
          style={styles.back}
        >
          <Feather name="chevron-left" size={24} color={colors.foreground} />
        </Pressable>
        <Text style={styles.headerTitle}>Earnings</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        {loading ? (
          <Skeleton style={{ height: 130, borderRadius: radius.lg }} />
        ) : (
          <View style={styles.totalCard}>
            <Text style={styles.totalLabel}>{range.label}</Text>
            <Text style={styles.totalValue}>{formatCents(net)}</Text>
            <Text style={styles.totalCaption}>Net commission</Text>
          </View>
        )}

        {totalRows.length > 1 ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>By provider</Text>
            <View style={styles.card}>
              {totalRows.map((row, i) => (
                <ProviderRow key={row.membership_id} row={row} divided={i > 0} />
              ))}
            </View>
          </View>
        ) : null}

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Activity</Text>
          {loading ? (
            <Skeleton style={{ height: 80, borderRadius: radius.lg }} />
          ) : ledger.length === 0 ? (
            <Text style={styles.empty}>
              No commission activity this month.
            </Text>
          ) : (
            <View style={styles.card}>
              {ledger.map((entry, i) => (
                <EntryRow key={entry.id} entry={entry} divided={i > 0} />
              ))}
            </View>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function ProviderRow({
  row,
  divided,
}: {
  row: CommissionTotalRow;
  divided: boolean;
}) {
  return (
    <View style={[styles.row, divided && styles.rowDivided]}>
      <Text style={styles.rowName}>
        {row.first_name} {row.last_name}
      </Text>
      <Text style={styles.rowAmount}>{formatCents(row.net_cents)}</Text>
    </View>
  );
}

function EntryRow({
  entry,
  divided,
}: {
  entry: CommissionEntry;
  divided: boolean;
}) {
  const reversal = entry.kind === 'reversal';
  return (
    <View style={[styles.row, divided && styles.rowDivided]}>
      <View style={styles.entryText}>
        <Text style={styles.rowName} numberOfLines={1}>
          {entry.line_description}
        </Text>
        <Text style={styles.entrySub} numberOfLines={1}>
          {entry.invoice_number} · sale {formatCents(entry.line_subtotal_cents)}
          {reversal ? ' · reversal' : ''}
        </Text>
      </View>
      <Text
        style={[styles.rowAmount, reversal && { color: colors.destructive }]}
      >
        {formatCents(entry.amount_cents)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  back: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '600',
    color: colors.foreground,
  },
  content: {
    width: '100%',
    maxWidth: layout.contentMaxWidth,
    alignSelf: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.lg,
  },
  totalCard: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    padding: spacing.xl,
    alignItems: 'center',
    gap: 2,
  },
  totalLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    textTransform: 'uppercase',
    letterSpacing: 1.5,
    color: colors.mutedForeground,
  },
  totalValue: {
    fontFamily: fonts.serif,
    fontSize: 40,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  totalCaption: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  section: { gap: spacing.sm },
  sectionTitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '700',
    color: colors.foreground,
  },
  empty: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  card: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    paddingHorizontal: spacing.lg,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
    paddingVertical: spacing.md,
  },
  rowDivided: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  entryText: { flex: 1, gap: 2 },
  rowName: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  entrySub: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  rowAmount: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '700',
    color: colors.foreground,
  },
});
