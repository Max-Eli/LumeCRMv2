import { useRef } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import SignatureScreen, {
  type SignatureViewRef,
} from 'react-native-signature-canvas';

import { colors, fonts, fontSize, radius } from '@/constants/theme';

/** CSS injected into the signature webview — strips its default
 *  chrome so it reads as a plain bordered canvas. */
const WEB_STYLE = `
  .m-signature-pad { box-shadow: none; border: none; }
  .m-signature-pad--body { border: none; }
  .m-signature-pad--footer { display: none; }
  body, html { height: 100%; margin: 0; background: #ffffff; }
`;

/** A drawable signature canvas. Reports the signature as a base64 PNG
 *  data URL on every stroke end; reports null when cleared. */
export function SignaturePad({
  onChange,
}: {
  onChange: (data: string | null) => void;
}) {
  const ref = useRef<SignatureViewRef>(null);

  return (
    <View style={styles.wrap}>
      <View style={styles.canvas}>
        <SignatureScreen
          ref={ref}
          onOK={(signature) => onChange(signature)}
          onEmpty={() => onChange(null)}
          onClear={() => onChange(null)}
          onEnd={() => ref.current?.readSignature()}
          autoClear={false}
          webStyle={WEB_STYLE}
          backgroundColor="#ffffff"
          penColor="#100C08"
        />
      </View>
      <Pressable
        onPress={() => ref.current?.clearSignature()}
        accessibilityRole="button"
        style={styles.clear}
      >
        <Text style={styles.clearText}>Clear signature</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: 6,
  },
  canvas: {
    height: 200,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: 'hidden',
    backgroundColor: '#ffffff',
  },
  clear: {
    alignSelf: 'flex-end',
  },
  clearText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
});
