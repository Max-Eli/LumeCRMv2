import { useState } from 'react';
import {
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from 'react-native';

import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';

interface TextFieldProps extends TextInputProps {
  label: string;
  /** Validation message shown beneath the field. */
  error?: string | null;
}

/** Labelled text input with focus + error states. */
export function TextField({ label, error, style, ...inputProps }: TextFieldProps) {
  const [focused, setFocused] = useState(false);

  return (
    <View style={styles.container}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        {...inputProps}
        onFocus={(e) => {
          setFocused(true);
          inputProps.onFocus?.(e);
        }}
        onBlur={(e) => {
          setFocused(false);
          inputProps.onBlur?.(e);
        }}
        placeholderTextColor={colors.mutedForeground}
        style={[
          styles.input,
          focused && styles.inputFocused,
          error != null && styles.inputError,
          style,
        ]}
      />
      {error != null ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: spacing.xs,
  },
  label: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.foreground,
  },
  input: {
    height: 52,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    paddingHorizontal: spacing.md,
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    color: colors.foreground,
  },
  inputFocused: {
    borderColor: colors.ring,
  },
  inputError: {
    borderColor: colors.destructive,
  },
  error: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    color: colors.destructive,
  },
});
