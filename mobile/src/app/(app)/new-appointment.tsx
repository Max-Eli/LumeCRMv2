import { Feather } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { useMemo, useState } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PickerSheet } from '@/components/picker-sheet';
import { Button } from '@/components/ui/button';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import {
  addDays,
  formatDuration,
  todayString,
  useCreateAppointment,
} from '@/lib/appointments';
import { useCustomers, type CustomerListItem } from '@/lib/customers';
import { useServices, type Service } from '@/lib/services';
import {
  providerDisplayName,
  useBookableProviders,
  type Provider,
} from '@/lib/staff';
import { useDebouncedValue } from '@/lib/use-debounce';

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** 15-minute slots, 8:00 AM – 8:00 PM. */
const TIME_SLOTS: { min: number; label: string }[] = (() => {
  const out: { min: number; label: string }[] = [];
  for (let m = 8 * 60; m <= 20 * 60; m += 15) {
    out.push({ min: m, label: minutesToLabel(m) });
  }
  return out;
})();

function minutesToLabel(min: number): string {
  let h = Math.floor(min / 60);
  const mm = min % 60;
  const period = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  return `${h}:${String(mm).padStart(2, '0')} ${period}`;
}

type PickerKind = 'client' | 'service' | 'provider' | 'time';

/** New-appointment form — pick a client, service, provider, day, and
 *  time, then create the appointment. */
export default function NewAppointmentScreen() {
  const params = useLocalSearchParams<{ date?: string }>();
  const createMutation = useCreateAppointment();

  const [client, setClient] = useState<CustomerListItem | null>(null);
  const [service, setService] = useState<Service | null>(null);
  const [provider, setProvider] = useState<Provider | null>(null);
  const [date, setDate] = useState(params.date || todayString());
  const [timeMin, setTimeMin] = useState<number | null>(null);
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [picker, setPicker] = useState<PickerKind | null>(null);
  const [clientQuery, setClientQuery] = useState('');

  const debouncedQuery = useDebouncedValue(clientQuery);
  const searchReady = debouncedQuery.trim().length >= 2;
  const customers = useCustomers(debouncedQuery, picker === 'client' && searchReady);
  const services = useServices();
  const providers = useBookableProviders();

  const canSubmit =
    client !== null &&
    service !== null &&
    provider !== null &&
    timeMin !== null;

  function submit() {
    if (!client || !service || !provider || timeMin === null) {
      setError('Choose a client, service, provider, and time.');
      return;
    }
    setError(null);

    const [y, m, d] = date.split('-').map(Number);
    const start = new Date(y, m - 1, d, Math.floor(timeMin / 60), timeMin % 60);
    const end = new Date(start.getTime() + service.duration_minutes * 60000);

    createMutation.mutate(
      {
        customer_id: client.id,
        service_id: service.id,
        provider_id: provider.id,
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        notes: notes.trim() || undefined,
      },
      {
        onSuccess: () => router.back(),
        onError: () =>
          setError(
            'Couldn’t create the appointment. Check the details and try again.',
          ),
      },
    );
  }

  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <View style={styles.header}>
        <Pressable
          onPress={() => router.back()}
          accessibilityRole="button"
          hitSlop={10}
        >
          <Text style={styles.cancel}>Cancel</Text>
        </Pressable>
        <Text style={styles.headerTitle}>New appointment</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.card}>
          <FormRow
            label="Client"
            value={client?.full_name ?? null}
            placeholder="Select a client"
            onPress={() => setPicker('client')}
          />
          <Divider />
          <FormRow
            label="Service"
            value={service ? service.name : null}
            placeholder="Select a service"
            onPress={() => setPicker('service')}
          />
          <Divider />
          <FormRow
            label="Provider"
            value={provider ? providerDisplayName(provider) : null}
            placeholder="Select a provider"
            onPress={() => setPicker('provider')}
          />
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Date</Text>
          <DateStrip value={date} onChange={setDate} />
        </View>

        <View style={styles.card}>
          <FormRow
            label="Time"
            value={timeMin === null ? null : minutesToLabel(timeMin)}
            placeholder="Select a time"
            onPress={() => setPicker('time')}
          />
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Notes</Text>
          <TextInput
            value={notes}
            onChangeText={setNotes}
            placeholder="Optional"
            placeholderTextColor={colors.mutedForeground}
            multiline
            style={styles.notes}
          />
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <Button
          label="Create appointment"
          onPress={submit}
          loading={createMutation.isPending}
          disabled={!canSubmit}
        />
      </ScrollView>

      <PickerSheet<CustomerListItem>
        visible={picker === 'client'}
        title="Select a client"
        items={customers.data ?? []}
        loading={customers.isLoading}
        onClose={() => setPicker(null)}
        onSelect={(c) => {
          setClient(c);
          setPicker(null);
        }}
        keyOf={(c) => String(c.id)}
        labelOf={(c) => c.full_name || 'Unnamed client'}
        sublabelOf={(c) => c.phone || c.email || undefined}
        search={{
          value: clientQuery,
          onChange: setClientQuery,
          placeholder: 'Search by name or phone',
        }}
        emptyText={
          searchReady
            ? 'No clients match that search.'
            : 'Type at least 2 letters to search.'
        }
      />

      <PickerSheet<Service>
        visible={picker === 'service'}
        title="Select a service"
        items={services.data ?? []}
        loading={services.isLoading}
        onClose={() => setPicker(null)}
        onSelect={(s) => {
          setService(s);
          setPicker(null);
        }}
        keyOf={(s) => String(s.id)}
        labelOf={(s) => s.name}
        sublabelOf={(s) =>
          `${formatDuration(s.duration_minutes)} · $${s.price_dollars}`
        }
        emptyText="No services found."
      />

      <PickerSheet<Provider>
        visible={picker === 'provider'}
        title="Select a provider"
        items={providers.data ?? []}
        loading={providers.isLoading}
        onClose={() => setPicker(null)}
        onSelect={(p) => {
          setProvider(p);
          setPicker(null);
        }}
        keyOf={(p) => String(p.id)}
        labelOf={(p) => providerDisplayName(p)}
        sublabelOf={(p) => p.job_title_name ?? undefined}
        emptyText="No bookable providers found."
      />

      <PickerSheet<{ min: number; label: string }>
        visible={picker === 'time'}
        title="Select a time"
        items={TIME_SLOTS}
        onClose={() => setPicker(null)}
        onSelect={(slot) => {
          setTimeMin(slot.min);
          setPicker(null);
        }}
        keyOf={(slot) => String(slot.min)}
        labelOf={(slot) => slot.label}
      />
    </SafeAreaView>
  );
}

function FormRow({
  label,
  value,
  placeholder,
  onPress,
}: {
  label: string;
  value: string | null;
  placeholder: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
    >
      <View style={styles.rowText}>
        <Text style={styles.rowLabel}>{label}</Text>
        <Text
          style={[styles.rowValue, !value && styles.rowPlaceholder]}
          numberOfLines={1}
        >
          {value ?? placeholder}
        </Text>
      </View>
      <Feather name="chevron-right" size={18} color={colors.mutedForeground} />
    </Pressable>
  );
}

function DateStrip({
  value,
  onChange,
}: {
  value: string;
  onChange: (day: string) => void;
}) {
  const days = useMemo(
    () => Array.from({ length: 30 }, (_, i) => addDays(todayString(), i)),
    [],
  );
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.strip}
    >
      {days.map((d) => {
        const [y, m, dd] = d.split('-').map(Number);
        const weekday = DOW[new Date(y, m - 1, dd).getDay()];
        const selected = d === value;
        return (
          <Pressable
            key={d}
            onPress={() => onChange(d)}
            style={[styles.dayPill, selected && styles.dayPillSelected]}
          >
            <Text
              style={[styles.dayPillDow, selected && styles.dayPillTextSelected]}
            >
              {weekday}
            </Text>
            <Text
              style={[styles.dayPillNum, selected && styles.dayPillTextSelected]}
            >
              {dd}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

function Divider() {
  return <View style={styles.divider} />;
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  cancel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.accent,
    fontWeight: '600',
  },
  headerTitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '600',
    color: colors.foreground,
  },
  headerSpacer: {
    width: 52,
  },
  content: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.lg,
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
    gap: spacing.md,
    paddingVertical: spacing.md,
  },
  rowPressed: {
    opacity: 0.6,
  },
  rowText: {
    flex: 1,
    gap: 2,
  },
  rowLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  rowValue: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  rowPlaceholder: {
    fontWeight: '400',
    color: colors.mutedForeground,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
  },
  section: {
    gap: spacing.sm,
  },
  sectionLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.foreground,
  },
  strip: {
    gap: spacing.sm,
    paddingVertical: 2,
  },
  dayPill: {
    width: 52,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: 'center',
    gap: 2,
  },
  dayPillSelected: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  dayPillDow: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    color: colors.mutedForeground,
  },
  dayPillNum: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '700',
    color: colors.foreground,
  },
  dayPillTextSelected: {
    color: colors.primaryForeground,
  },
  notes: {
    minHeight: 80,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    padding: spacing.md,
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.foreground,
    textAlignVertical: 'top',
  },
  error: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.destructive,
  },
});
