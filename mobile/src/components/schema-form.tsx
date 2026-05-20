import { Feather } from '@expo/vector-icons';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import type { TemplateField } from '@/lib/treatments';

interface SchemaFormProps {
  fields: TemplateField[];
  answers: Record<string, unknown>;
  onChange: (fieldId: string, value: unknown) => void;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === 'string')
    : [];
}

/** Renders a treatment-record template schema as an editable form.
 *  The parent owns the `answers` map. */
export function SchemaForm({ fields, answers, onChange }: SchemaFormProps) {
  return (
    <View style={styles.form}>
      {fields.map((field) => (
        <View key={field.id} style={styles.field}>
          <Text style={styles.label}>
            {field.label}
            {field.required ? <Text style={styles.required}> *</Text> : null}
          </Text>
          {field.hint ? <Text style={styles.hint}>{field.hint}</Text> : null}
          <FieldControl
            field={field}
            value={answers[field.id]}
            onChange={(v) => onChange(field.id, v)}
          />
        </View>
      ))}
    </View>
  );
}

function FieldControl({
  field,
  value,
  onChange,
}: {
  field: TemplateField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (field.type === 'choice_single') {
    const selected = asString(value);
    return (
      <View style={styles.options}>
        {(field.options ?? []).map((opt) => (
          <OptionRow
            key={opt.value}
            label={opt.label}
            selected={selected === opt.value}
            onPress={() => onChange(opt.value)}
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
                onChange(
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
      onChangeText={onChange}
      multiline={multiline}
      keyboardType={field.type === 'number' ? 'numeric' : 'default'}
      placeholder={
        field.type === 'date'
          ? 'YYYY-MM-DD'
          : field.type === 'signature'
            ? 'Type your full name'
            : undefined
      }
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
