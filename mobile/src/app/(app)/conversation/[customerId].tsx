import { Feather } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import { formatTime } from '@/lib/appointments';
import {
  useConversation,
  useMarkThreadRead,
  useSendMessage,
  type Message,
} from '@/lib/messaging';

/** SMS conversation with one client — history + composer. */
export default function ConversationScreen() {
  const { customerId } = useLocalSearchParams<{ customerId: string }>();
  const id = Number(customerId);

  const { data, isLoading, isError, refetch } = useConversation(id);
  const send = useSendMessage(id);
  const markRead = useMarkThreadRead(id);
  const [draft, setDraft] = useState('');

  useEffect(() => {
    markRead.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const messages = data?.messages ?? [];
  const reversed = [...messages].reverse();
  const name = data
    ? `${data.customer.first_name} ${data.customer.last_name}`.trim()
    : 'Conversation';
  const optedOut = data ? !data.customer.sms_opt_in : false;

  function onSend() {
    const body = draft.trim();
    if (!body || send.isPending) return;
    send.mutate(body, { onSuccess: () => setDraft('') });
  }

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
        <Text style={styles.headerTitle} numberOfLines={1}>
          {name}
        </Text>
      </View>

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 8 : 0}
      >
        {isLoading ? (
          <View style={styles.centered}>
            <ActivityIndicator color={colors.accent} />
          </View>
        ) : isError ? (
          <View style={styles.centered}>
            <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
            <Text style={styles.centeredText}>
              Couldn&apos;t load this conversation.
            </Text>
            <Pressable onPress={() => refetch()} accessibilityRole="button" hitSlop={8}>
              <Text style={styles.retry}>Try again</Text>
            </Pressable>
          </View>
        ) : (
          <FlatList
            data={reversed}
            keyExtractor={(m) => String(m.id)}
            inverted
            contentContainerStyle={styles.thread}
            showsVerticalScrollIndicator={false}
            renderItem={({ item }) => <Bubble message={item} />}
            ListEmptyComponent={
              <View style={styles.empty}>
                <Text style={styles.emptyText}>
                  No messages yet. Send the first one below.
                </Text>
              </View>
            }
          />
        )}

        {optedOut ? (
          <Text style={styles.optOut}>
            This client hasn&apos;t opted in to SMS — a message may not be
            delivered.
          </Text>
        ) : null}

        <View style={styles.composer}>
          <TextInput
            value={draft}
            onChangeText={setDraft}
            placeholder="Write a message"
            placeholderTextColor={colors.mutedForeground}
            multiline
            style={styles.input}
          />
          <Pressable
            onPress={onSend}
            disabled={!draft.trim() || send.isPending}
            accessibilityRole="button"
            accessibilityLabel="Send"
            style={[
              styles.send,
              (!draft.trim() || send.isPending) && styles.sendDisabled,
            ]}
          >
            {send.isPending ? (
              <ActivityIndicator color={colors.primaryForeground} size="small" />
            ) : (
              <Feather name="arrow-up" size={20} color={colors.primaryForeground} />
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Bubble({ message }: { message: Message }) {
  const outbound = message.direction === 'outbound';
  return (
    <View style={[styles.bubbleRow, outbound && styles.bubbleRowOut]}>
      <View style={[styles.bubble, outbound ? styles.bubbleOut : styles.bubbleIn]}>
        <Text style={[styles.bubbleText, outbound && styles.bubbleTextOut]}>
          {message.body}
        </Text>
      </View>
      <Text style={styles.bubbleTime}>
        {formatTime(message.sent_at ?? message.created_at)}
        {message.status === 'failed' ? ' · failed' : ''}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  back: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    flex: 1,
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '600',
    color: colors.foreground,
  },
  thread: {
    padding: spacing.lg,
    gap: spacing.md,
    flexGrow: 1,
  },
  bubbleRow: {
    alignItems: 'flex-start',
    maxWidth: '82%',
    gap: 2,
  },
  bubbleRowOut: {
    alignSelf: 'flex-end',
    alignItems: 'flex-end',
  },
  bubble: {
    borderRadius: radius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  bubbleIn: {
    backgroundColor: colors.muted,
    borderTopLeftRadius: radius.sm,
  },
  bubbleOut: {
    backgroundColor: colors.primary,
    borderTopRightRadius: radius.sm,
  },
  bubbleText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.foreground,
    lineHeight: 21,
  },
  bubbleTextOut: {
    color: colors.primaryForeground,
  },
  bubbleTime: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    color: colors.mutedForeground,
    paddingHorizontal: spacing.xs,
  },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  input: {
    flex: 1,
    maxHeight: 120,
    minHeight: 44,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    backgroundColor: colors.card,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.sm,
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.foreground,
  },
  send: {
    width: 44,
    height: 44,
    borderRadius: radius.pill,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendDisabled: {
    opacity: 0.4,
  },
  optOut: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    color: colors.destructive,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xs,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    padding: spacing.xl,
  },
  centeredText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  retry: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
  empty: {
    paddingVertical: spacing.xxl,
    alignItems: 'center',
  },
  emptyText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
});
