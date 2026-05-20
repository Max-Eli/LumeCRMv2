import { Feather } from '@expo/vector-icons';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { SignaturePad } from '@/components/signature-pad';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import type { FormField } from '@/lib/forms';

interface FormRendererProps {
  fields: FormField[];
  answers: Record<string, unknown>;
  onAnswer: (fieldId: string, value: unknown) => void;
  onSignature: (data: string | null) => void;
  /** Fires true while a signature stroke is in progress — lets the
   *  parent ScrollView freeze so the draw doesn't scroll the page. */
  onSignatureDraw?: (drawing: boolean) => void;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === 'string')
    : [];
}

/** Renders a consent/intake form schema. `paragraph` fields are
 *  display-only (legal/clinical body); `signature` fields render the
 *  drawable pad. */
export function FormRenderer({
  fields,
  answers,
  onAnswer,
  onSignature,
  onSignatureDraw,
}: FormRendererProps) {
  return (
    <View style={styles.form}>
      {fields.map((field) => {
        if (field.type === 'paragraph') {
          return (
            <View key={field.id} style={styles.paragraph}>
              {field.label ? (
                <Text style={styles.paragraphHeading}>{field.label}</Text>
              ) : null}
              {field.body ? (
                <Text style={styles.paragraphBody}>{field.body}</Text>
              ) : null}
            </View>
          );
        }

        return (
          <View key={field.id} style={styles.field}>
            <Text style={styles.label}>
              {field.label}
              {field.required ? <Text style={styles.required}> *</Text> : null}
            </Text>
            {field.help_text ? (
              <Text style={styles.hint}>{field.help_text}</Text>
            ) : null}
            <FieldControl
              field={field}
              value={answers[field.id]}
              onAnswer={(v) => onAnswer(field.id, v)}
              onSignature={onSignature}
              onSignatureDraw={onSignatureDraw}
            />
          </View>
        );
      })}
    </View>
  );
}

function FieldControl({
  field,
  value,
  onAnswer,
  onSignature,
  onSignatureDraw,
}: {
  field: FormField;
  value: unknown;
  onAnswer: (v: unknown) => void;
  onSignature: (data: string | null) => void;
  onSignatureDraw?: (drawing: boolean) => void;
}) {
  if (field.type === 'signature') {
    return (
      <SignaturePad
        onChange={onSignature}
        onDrawStart={() => onSignatureDraw?.(true)}
        onDrawEnd={() => onSignatureDraw?.(false)}
      />
    );
  }

  if (field.type === 'choice_single') {
    const selected = asString(value);
    return (
      <View style={styles.options}>
        {(field.options ?? []).map((opt) => (
          <OptionRow
            key={opt.value}
            label={opt.label}
            selected={selected === opt.value}
            onPress={() => onAnswer(opt.value)}
          />
        ))}
      </View>
    );
  }

  if (field.type === 'choice_multiple') {
    const selected = asStringArray(value);
    return (
      <View style={styles.options}>
        {(field.options ?? []).map((opt) => {
          const on = selected.includes(opt.value);
          return (
            <OptionRow
              key={opt.value}
              label={opt.label}
              selected={on}
              multiple
              onPress={() =>
                onAnswer(
                  on
                    ? selected.filter((v) => v !== opt.value)
                    : [...selected, opt.value],
                )
              }
            />
          );
        })}
      </View>
    );
  }

  const multiline = field.type === 'long_text';
  return (
    <TextInput
      value={asString(value)}
      onChangeText={onAnswer}
      multiline={multiline}
      placeholder={field.type === 'date' ? 'YYYY-MM-DD' : field.placeholder}
      placeholderTextColor={colors.mutedForeground}
      style={[styles.input, multiline && styles.multiline]}
    />
  );
}

function OptionRow({
  label,
  selected,
  multiple = false,
  onPress,
}: {
  label: string;
  selected: boolean;
  multiple?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole={multiple ? 'checkbox' : 'radio'}
      accessibilityState={{ selected }}
      style={[styles.option, selected && styles.optionSelected]}
    >
      <View
        style={[
          multiple ? styles.checkbox : styles.radio,
          selected && styles.markSelected,
        ]}
      >
        {selected ? (
          <Feather name="check" size={13} color={colors.accentForeground} />
        ) : null}
      </View>
      <Text style={styles.optionLabel}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  form: {
    gap: spacing.lg,
  },
  field: {
    gap: spacing.xs,
  },
  paragraph: {
    gap: spacing.xs,
  },
  paragraphHeading: {
    fontFamily: fonts.serif,
    fontSize: fontSize.lg,
    color: colors.foreground,
    letterSpacing: -0.3,
  },
  paragraphBody: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.foreground,
    lineHeight: 22,
  },
  label: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.foreground,
  },
  required: {
    color: colors.destructive,
  },
  hint: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    color: colors.mutedForeground,
  },
  input: {
    minHeight: 48,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.foreground,
  },
  multiline: {
    minHeight: 96,
    textAlignVertical: 'top',
  },
  options: {
    gap: spacing.xs,
  },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  optionSelected: {
    borderColor: colors.accent,
  },
  radio: {
    width: 20,
    height: 20,
    borderRadius: radius.pill,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: radius.sm,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markSelected: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  optionLabel: {
    flex: 1,
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.foreground,
  },
});
