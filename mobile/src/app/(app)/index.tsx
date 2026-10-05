import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { ArrowUp, Bell, FileText, HatGlasses, Image as ImageIcon, Plus } from 'lucide-react-native';
import { useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type NativeSyntheticEvent,
  type TextInputKeyPressEventData,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Brand } from '@/components/brand';
import { ChatCard } from '@/components/chat-cards';
import { ModelPicker } from '@/components/model-picker';
import { Sheet } from '@/components/sheet';
import type { Msg } from '@/lib/chat-events';
import { attachDocument, attachedMessage, attachPhoto, type Attached } from '@/lib/attach';
import { sendMessage, useChat } from '@/lib/chat-store';
import { AvoidKeyboard } from '@/lib/keyboard';
import { parseMarkdown, type Span } from '@/lib/markdown';
import { errorMessage } from '@/lib/api';
import { useNewJobs } from '@/lib/new-jobs';
import { useUI } from '@/lib/ui-store';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';
import Animated, { FadeIn, FadeInDown } from 'react-native-reanimated';
import { Thinking } from '@/components/motion';

const SUGGESTIONS = ["Show today's jobs", "Show yesterday's jobs", 'What is scheduled tomorrow?', 'How many replies this week?'];

function greeting(now = new Date()): string {
  const h = now.getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

/** Claude-style chat: greeting + suggestions when empty, streamed replies with job cards, composer at the bottom. */
export default function Chat() {
  const { colors } = useColors();
  const incognito = useUI((s) => s.incognito);
  const messages = useChat((s) => s.messages);
  const streaming = useChat((s) => s.streaming);
  const qc = useQueryClient();
  const router = useRouter();
  const fresh = useNewJobs().data;
  const [text, setText] = useState('');
  const [reading, setReading] = useState(false);
  const [menu, setMenu] = useState(false);
  const [inputHeight, setInputHeight] = useState(28); // grows with the text (web doesn't auto-grow)
  const [attachError, setAttachError] = useState<string | null>(null);
  const list = useRef<FlatList<Msg>>(null);
  const seen = useRef({ sig: '', at: 0 }); // the chat's last new content, and when it came
  // Follow new messages / streaming text (and their cards loading just after), but not when the user opens a
  // card's post or email later, so what they opened stays in view.
  const followNew = () => {
    const last = messages.at(-1);
    const sig = `${messages.length}:${last?.content.length ?? 0}:${last?.cards.length ?? 0}:${last?.error ?? ''}`;
    if (sig !== seen.current.sig) seen.current = { sig, at: Date.now() };
    if (Date.now() - seen.current.at < 2500) list.current?.scrollToEnd({ animated: true });
  };

  const send = async (value: string) => {
    const message = value.trim();
    if (!message || streaming) return;
    setText('');
    await sendMessage(message, incognito);
    if (!incognito) qc.invalidateQueries({ queryKey: ['chats'] }); // new title / order in Recents
  };

  /** Photo or document → its text in the message box (added under anything already typed). */
  const attach = async (pick: () => Promise<Attached | null>) => {
    setMenu(false);
    setAttachError(null);
    setReading(true);
    try {
      const got = await pick();
      if (!got) return; // picker closed
      if (!got.text.trim()) setAttachError(`No text found in ${got.name}.`);
      else setText((t) => (t.trim() ? `${t}\n\n${attachedMessage(got)}` : attachedMessage(got)));
    } catch (e) {
      setAttachError(errorMessage(e, "Couldn't read that file."));
    } finally {
      setReading(false);
    }
  };

  // Web: Enter sends, Shift+Enter makes a new line.
  const onKey = (e: NativeSyntheticEvent<TextInputKeyPressEventData>) => {
    const ev = e.nativeEvent as TextInputKeyPressEventData & { shiftKey?: boolean };
    if (Platform.OS === 'web' && ev.key === 'Enter' && !ev.shiftKey) {
      e.preventDefault();
      send(text);
    }
  };

  const canSend = !!text.trim() && !streaming;
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={['bottom', 'left', 'right']}>
      <AvoidKeyboard style={{ flex: 1 }}>
        {messages.length === 0 ? (
          <View style={styles.middle}>
            {incognito ? (
              <View style={styles.column}>
                <View style={[styles.badge, { backgroundColor: colors.surfaceAlt }]}>
                  <HatGlasses size={40} color={colors.text} strokeWidth={1.5} />
                </View>
                <Text style={[styles.hello, { color: colors.text }]}>Incognito chat</Text>
                <Text style={[styles.note, styles.center, { color: colors.textMuted, fontSize: 15 }]}>
                  This chat won’t be saved to your history or used for memory. Emails you approve are still sent and
                  tracked as usual.
                </Text>
              </View>
            ) : (
              <View style={styles.column}>
                <Brand width={150} />
                <Text style={[styles.hello, { color: colors.text }]}>{greeting()}</Text>
                {fresh?.count ? (
                  <Pressable
                    accessibilityRole="link"
                    onPress={() => router.navigate('/jobs')}
                    style={[styles.chip, styles.newJobs, { borderColor: colors.primary, backgroundColor: colors.primarySoft }]}>
                    <Bell size={16} color={colors.primaryText} strokeWidth={2} />
                    <Text style={{ fontFamily: fonts.semibold, color: colors.text }}>
                      {fresh.count} new job{fresh.count > 1 ? 's' : ''} for you. Best: {fresh.jobs[0].company} (
                      {fresh.jobs[0].fit_score}/100)
                    </Text>
                  </Pressable>
                ) : null}
                <View style={styles.chips}>
                  {SUGGESTIONS.map((s) => (
                    <Pressable
                      key={s}
                      accessibilityRole="button"
                      onPress={() => send(s)}
                      style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
                        styles.chip,
                        { borderColor: colors.border, backgroundColor: pressed || hovered ? colors.surfaceAlt : colors.surface },
                      ]}>
                      <Text style={{ fontFamily: fonts.body, color: colors.text }}>{s}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            )}
          </View>
        ) : (
          <FlatList
            ref={list}
            data={messages}
            keyExtractor={(m) => m.id}
            renderItem={({ item, index }) => (
              <Message msg={item} thinking={streaming && index === messages.length - 1} />
            )}
            contentContainerStyle={styles.list}
            onContentSizeChange={followNew}
            keyboardShouldPersistTaps="handled"
          />
        )}

        <View style={styles.bottom}>
          <View
            style={[
              styles.composer,
              { backgroundColor: colors.surface, borderColor: incognito ? colors.textMuted : colors.border },
            ]}>
            <TextInput
              value={text}
              onChangeText={setText}
              onKeyPress={onKey}
              multiline
              onContentSizeChange={(e) => setInputHeight(Math.min(180, Math.max(28, e.nativeEvent.contentSize.height)))}
              placeholder={incognito ? 'Message privately…' : 'Message Leapvoy… or paste a job post'}
              placeholderTextColor={colors.textMuted}
              style={[styles.input, { color: colors.text, fontFamily: fonts.body, height: inputHeight }]}
            />
            <Sheet open={menu} title="Add a job to the message" onClose={() => setMenu(false)}>
              <AttachChoice
                icon={ImageIcon}
                label="Photo or screenshot"
                sub="A job post image; its text is read for you"
                onPress={() => attach(attachPhoto)}
              />
              <AttachChoice
                icon={FileText}
                label="Document"
                sub="A JD as PDF (even scanned), Word .docx or text"
                onPress={() => attach(attachDocument)}
              />
            </Sheet>
            <View style={styles.tools}>
              <View style={styles.left}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Attach a job photo or document"
                onPress={() => setMenu(!menu)}
                disabled={reading}
                style={[
                  styles.round,
                  { borderColor: colors.border, borderWidth: 1, backgroundColor: menu ? colors.surfaceAlt : undefined },
                ]}>
                {reading ? (
                  <ActivityIndicator size="small" color={colors.textMuted} />
                ) : (
                  <Plus size={18} color={colors.textMuted} strokeWidth={1.8} />
                )}
              </Pressable>
              <ModelPicker kind="chat" />
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Send"
                onPress={() => send(text)}
                disabled={!canSend}
                style={[styles.round, { backgroundColor: colors.primary, opacity: canSend ? 1 : 0.5 }]}>
                <ArrowUp size={18} color={colors.onPrimary} strokeWidth={2.2} />
              </Pressable>
            </View>
          </View>
          <Text style={[styles.note, { color: attachError ? colors.error : colors.textMuted }]}>
            {attachError ?? (reading ? 'Reading the file…' : 'Nothing is sent to HR without your approval.')}
          </Text>
        </View>
      </AvoidKeyboard>
    </SafeAreaView>
  );
}

function AttachChoice({ icon: Icon, label, sub, onPress }: { icon: typeof Plus; label: string; sub: string; onPress: () => void }) {
  const { colors } = useColors();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
        styles.choice,
        { borderColor: colors.border, backgroundColor: pressed || hovered ? colors.surfaceAlt : colors.background },
      ]}>
      <View style={[styles.choiceIcon, { backgroundColor: colors.primarySoft }]}>
        <Icon size={18} color={colors.primaryText} strokeWidth={2} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 15, color: colors.text }}>{label}</Text>
        <Text style={{ fontFamily: fonts.body, fontSize: 12, color: colors.textMuted, marginTop: 2 }}>{sub}</Text>
      </View>
    </Pressable>
  );
}

function Message({ msg, thinking }: { msg: Msg; thinking: boolean }) {
  const { colors } = useColors();
  if (msg.role === 'user') {
    return (
      <Animated.View entering={FadeInDown.duration(240)} style={[styles.userBubble, { backgroundColor: colors.userBubble }]}>
        <Text selectable style={[styles.text, { color: colors.text }]}>
          {msg.content}
        </Text>
      </Animated.View>
    );
  }
  return (
    <Animated.View entering={FadeIn.duration(260)} style={styles.assistant}>
      {msg.content ? <Markdown text={msg.content} /> : null}
      {msg.cards.map((c, i) => (
        <ChatCard key={i} card={c} />
      ))}
      {thinking && (!msg.content || msg.status) ? <Thinking status={msg.status} /> : null}
      {msg.error ? <Text style={[styles.text, { color: colors.error }]}>{msg.error}</Text> : null}
      {msg.answeredBy && !thinking ? (
        <Text style={[styles.note, { color: colors.textMuted }]}>Answered by {msg.answeredBy}</Text>
      ) : null}
    </Animated.View>
  );
}

function Markdown({ text }: { text: string }) {
  const { colors } = useColors();
  const spans = (list: Span[]) =>
    list.map((s, i) => (
      <Text
        key={i}
        style={
          s.bold
            ? { fontFamily: fonts.semibold }
            : s.code
              ? { fontFamily: fonts.mono, fontSize: 14, backgroundColor: colors.surfaceAlt }
              : undefined
        }>
        {s.text}
      </Text>
    ));
  return (
    <View style={{ gap: spacing.sm }}>
      {parseMarkdown(text).map((b, i) =>
        b.kind === 'li' ? (
          <View key={i} style={styles.li}>
            <Text style={[styles.text, { color: colors.textMuted, minWidth: 18 }]}>{b.mark}</Text>
            <Text selectable style={[styles.text, { color: colors.text, flex: 1 }]}>
              {spans(b.spans)}
            </Text>
          </View>
        ) : (
          <Text key={i} selectable style={[styles.text, { color: colors.text }]}>
            {spans(b.spans)}
          </Text>
        ),
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  middle: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: spacing.lg },
  column: { width: '100%', maxWidth: 760, alignItems: 'center', gap: spacing.lg },
  hello: { fontFamily: fonts.heading, fontSize: 30, textAlign: 'center' },
  badge: { width: 72, height: 72, borderRadius: 36, alignItems: 'center', justifyContent: 'center' },
  newJobs: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, justifyContent: 'center' },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: spacing.sm, paddingHorizontal: spacing.md },
  list: { width: '100%', maxWidth: 760, alignSelf: 'center', padding: spacing.lg, gap: spacing.lg },
  userBubble: { alignSelf: 'flex-end', maxWidth: '85%', borderRadius: radius.lg, paddingVertical: spacing.sm, paddingHorizontal: spacing.md },
  assistant: { gap: spacing.md },
  text: { fontFamily: fonts.body, fontSize: 15, lineHeight: 23 },
  li: { flexDirection: 'row', gap: spacing.xs, paddingLeft: spacing.xs },
  bottom: { alignItems: 'center', paddingHorizontal: spacing.lg, paddingBottom: spacing.md, gap: spacing.sm },
  composer: { width: '100%', maxWidth: 760, borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, gap: spacing.sm },
  input: { minHeight: 28, maxHeight: 180, fontSize: 16, outlineWidth: 0 }, // web: no focus box inside the composer
  tools: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-end' },
  left: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, flexShrink: 1 },
  choice: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderWidth: 1, borderRadius: radius.md, padding: spacing.md },
  choiceIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },

  round: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  note: { fontFamily: fonts.body, fontSize: 12 },
  center: { textAlign: 'center', maxWidth: 520, lineHeight: 22 },
});
