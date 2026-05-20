import { StyleSheet, Text, View } from 'react-native';

import { fonts, radius } from '@/constants/theme';
import { STATUS_META, type AppointmentStatus } from '@/lib/appointments';

/** Tinted status chip for an appointment. */
export function StatusPill({ status }: { status: AppointmentStatus }) {
  const meta = STATUS_META[status];
  return (
    <View style={[styles.pill, { backgroundColor: meta.bg }]}>
      <Text style={[styles.label, { color: meta.fg }]}>{meta.label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: radius.pill,
    alignSelf: 'flex-start',
  },
  label: {
    fontFamily: fonts.sans,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 0.2,
  },
});
