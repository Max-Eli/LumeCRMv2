import { useState } from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';

import { PickerSheet } from '@/components/picker-sheet';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import type { Appointment } from '@/lib/appointments';
import {
  formatMoney,
  PAYMENT_METHODS,
  useCloseInvoice,
  useInvoiceForAppointment,
  useReopenInvoice,
  type InvoiceStatus,
  type PaymentMethod,
} from '@/lib/invoices';

const STATUS_STYLE: Record<InvoiceStatus, { label: string; fg: string; bg: string }> = {
  open: { label: 'Open', fg: '#B7791F', bg: '#FBF0E0' },
  paid: { label: 'Paid', fg: '#2F7D52', bg: '#E5F0EA' },
  void: { label: 'Voided', fg: '#9A9B9C', bg: '#ECEDEE' },
};

/** Invoice section for the appointment detail — view line items and
 *  totals, close an open invoice, or reopen a paid one. */
export function AppointmentInvoice({
  appointment,
}: {
  appointment: Appointment;
}) {
  const { data: invoice, isLoading } = useInvoiceForAppointment(appointment.id);
  const close = useCloseInvoice(invoice?.id ?? 0);
  const reopen = useReopenInvoice(invoice?.id ?? 0);
  const [methodPicker, setMethodPicker] = useState(false);

  function onReopen() {
    Alert.alert('Reopen this invoice?', 'It will move back to open.', [
      { text: 'Back', style: 'cancel' },
      {
        text: 'Reopen',
        onPress: () => reopen.mutate('Reopened from the staff app'),
      },
    ]);
  }

  return (
    <View style={styles.section}>
      <Text style={styles.title}>Invoice</Text>

      {isLoading ? (
        <Skeleton style={{ height: 120, borderRadius: radius.lg }} />
      ) : !invoice ? (
        <Text style={styles.empty}>No invoice for this appointment.</Text>
      ) : (
        <View style={styles.card}>
          <View style={styles.cardHead}>
            <Text style={styles.number}>{invoice.invoice_number}</Text>
            <View
              style={[
                styles.pill,
                { backgroundColor: STATUS_STYLE[invoice.status].bg },
              ]}
            >
              <Text
                style={[
                  styles.pillText,
                  { color: STATUS_STYLE[invoice.status].fg },
                ]}
              >
                {STATUS_STYLE[invoice.status].label}
              </Text>
            </View>
          </View>

          {invoice.line_items.map((line) => (
            <View key={line.id} style={styles.line}>
              <Text style={styles.lineDesc} numberOfLines={1}>
                {line.description}
                {line.quantity > 1 ? `  ×${line.quantity}` : ''}
              </Text>
              <Text style={styles.lineAmount}>
                {formatMoney(line.line_subtotal_cents)}
              </Text>
            </View>
          ))}

          <View style={styles.divider} />
          <TotalRow label="Subtotal" value={invoice.subtotal_cents} />
          <TotalRow label="Tax" value={invoice.tax_cents} />
          <TotalRow label="Total" value={invoice.total_cents} emphasis />

          {invoice.status === 'open' ? (
            <Button
              label="Close invoice"
              onPress={() => setMethodPicker(true)}
              loading={close.isPending}
              style={styles.action}
            />
          ) : invoice.status === 'paid' ? (
            <View style={styles.action}>
              <Text style={styles.paidNote}>
                Paid
                {invoice.payment_method
                  ? ` · ${labelForMethod(invoice.payment_method)}`
                  : ''}
              </Text>
              {invoice.is_reopen_window_open ? (
                <Button
                  label="Reopen invoice"
                  variant="secondary"
                  onPress={onReopen}
                  loading={reopen.isPending}
                />
              ) : null}
            </View>
          ) : null}

          {close.isError || reopen.isError ? (
            <Text style={styles.error}>
              Couldn&apos;t update the invoice. Try again.
            </Text>
          ) : null}
        </View>
      )}

      <PickerSheet<{ value: PaymentMethod; label: string }>
        visible={methodPicker}
        title="Payment method"
        items={PAYMENT_METHODS}
        onClose={() => setMethodPicker(false)}
        onSelect={(m) => {
          setMethodPicker(false);
          close.mutate(m.value);
        }}
        keyOf={(m) => m.value}
        labelOf={(m) => m.label}
      />
    </View>
  );
}

function TotalRow({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: number;
  emphasis?: boolean;
}) {
  return (
    <View style={styles.totalRow}>
      <Text style={[styles.totalLabel, emphasis && styles.totalStrong]}>
        {label}
      </Text>
      <Text style={[styles.totalValue, emphasis && styles.totalStrong]}>
        {formatMoney(value)}
      </Text>
    </View>
  );
}

function labelForMethod(method: PaymentMethod): string {
  return PAYMENT_METHODS.find((m) => m.value === method)?.label ?? method;
}

const styles = StyleSheet.create({
  section: { gap: spacing.sm },
  title: {
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
    padding: spacing.lg,
    gap: spacing.sm,
  },
  cardHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  number: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '700',
    color: colors.foreground,
  },
  pill: {
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  pillText: {
    fontFamily: fonts.sans,
    fontSize: 11,
    fontWeight: '600',
  },
  line: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
  },
  lineDesc: {
    flex: 1,
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.foreground,
  },
  lineAmount: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.foreground,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: 2,
  },
  totalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  totalLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  totalValue: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.foreground,
  },
  totalStrong: {
    fontWeight: '700',
    fontSize: fontSize.base,
    color: colors.foreground,
  },
  action: {
    marginTop: spacing.sm,
    gap: spacing.sm,
  },
  paidNote: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  error: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.destructive,
  },
});
