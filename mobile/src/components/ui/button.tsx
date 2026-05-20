import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';

interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'destructive';
  /** Shows a spinner and blocks presses. */
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}

/** Primary action button. `primary` is the dark Smoky Black fill;
 *  `secondary` is a bordered light surface. */
export function Button({
  label,
  onPress,
  variant = 'primary',
  loading = false,
  disabled = false,
  style,
}: ButtonProps) {
  const blocked = disabled || loading;
  const surface =
    variant === 'primary'
      ? styles.primary
      : variant === 'destructive'
        ? styles.destructive
        : styles.secondary;
  const textColor =
    variant === 'primary'
      ? colors.primaryForeground
      : variant === 'destructive'
        ? colors.destructive
        : colors.foreground;

  return (
    <Pressable
      onPress={onPress}
      disabled={blocked}
      accessibilityRole="button"
      accessibilityState={{ disabled: blocked, busy: loading }}
      style={({ pressed }) => [
        styles.base,
        surface,
        pressed && !blocked && styles.pressed,
        blocked && styles.blocked,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={textColor} />
      ) : (
        <Text style={[styles.label, { color: textColor }]}>{label}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    height: 52,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  primary: {
    backgroundColor: colors.primary,
  },
  secondary: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  destructive: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.destructive,
  },
  pressed: {
    opacity: 0.85,
  },
  blocked: {
    opacity: 0.5,
  },
  label: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '600',
  },
});
