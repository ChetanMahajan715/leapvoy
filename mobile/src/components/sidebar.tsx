/** Claude-style sidebar in Leapvoy colors: logo (→ new chat) + collapse · New chat · sections · More · Recents · account. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { usePathname, useRouter, type Href } from 'expo-router';
import {
  AtSign,
  Bell,
  Briefcase,
  ChartColumn,
  ChevronDown,
  ChevronUp,
  Clock,
  FileText,
  FileUser,
  MoreHorizontal,
  Pencil,
  Pin,
  PanelLeftClose,
  Radio,
  Send,
  SquarePen,
  Trash2,
  type LucideIcon,
  UserRound,
} from 'lucide-react-native';
import { useDeferredValue, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Brand } from '@/components/brand';
import { IconButton } from '@/components/icon-button';
import { Sheet } from '@/components/sheet';
import { Button } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { useMe } from '@/lib/auth';
import { openChat, useChat } from '@/lib/chat-store';
import { groupByDay } from '@/lib/group-by-day';
import { haptic } from '@/lib/haptics';
import { useNewJobs } from '@/lib/new-jobs';
import { useInbox } from '@/lib/notifications';
import { newChat, useUI } from '@/lib/ui-store';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

type Chat = { id: number; title: string; pinned: boolean; updated_at: string };
type Link = [Href, string, LucideIcon];

const MAIN: Link[] = [
  ['/jobs', 'Jobs', Briefcase],
  ['/scheduled', 'Scheduled', Clock],
  ['/sent', 'Sent', Send],
  ['/stats', 'Stats', ChartColumn],
  ['/notifications', 'Notifications', Bell],
];
const MORE: Link[] = [
  ['/profile', 'Profile', UserRound],
  ['/resumes', 'Resumes', FileUser],
  ['/templates', 'Templates', FileText],
  ['/senders', 'Email accounts', AtSign],
  ['/channels', 'Channels', Radio],
];

/** onHide: collapse (laptop) or close the drawer (phone). onGo: called after navigating (closes drawer on phones). */
export function Sidebar({ onHide, onGo }: { onHide: () => void; onGo: () => void }) {
  const { colors } = useColors();
  const router = useRouter();
  const path = usePathname();
  const [more, setMore] = useState(true); // SETUP section open
  const me = useMe();
  const [search, setSearch] = useState('');
  const q = useDeferredValue(search.trim());
  const chats = useQuery({
    queryKey: ['chats', q],
    queryFn: async () => (await api.get<Chat[]>('/chats', { params: q ? { q } : {} })).data,
  });
  const openId = useChat((s) => s.chatId);
  const all = chats.data ?? [];
  const groups = [
    ...(all.some((c) => c.pinned) ? [{ label: 'Pinned', items: all.filter((c) => c.pinned) }] : []),
    ...groupByDay(all.filter((c) => !c.pinned)),
  ];

  const go = (href: Href) => {
    router.navigate(href);
    onGo();
  };
  const startNewChat = () => {
    newChat();
    go('/');
  };
  const open = (id: number) => {
    useUI.setState({ incognito: false });
    openChat(id).catch(() => newChat()); // e.g. deleted on another device
    go('/');
  };

  const fresh = useNewJobs().data?.count ?? 0;
  const unread = useInbox().data?.unread ?? 0;
  const link = (href: Href, label: string, icon?: LucideIcon) => (
    <Row
      key={label}
      label={label}
      icon={icon}
      active={path === href}
      badge={href === '/jobs' && fresh ? fresh : href === '/notifications' && unread ? unread : undefined}
      onPress={() => go(href)}
    />
  );

  const email = me.data?.email ?? '';
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.surface }} edges={['top', 'bottom', 'left']}>
      <View style={styles.top}>
        <Pressable accessibilityRole="button" accessibilityLabel="New chat" onPress={startNewChat}>
          <Brand width={116} />
        </Pressable>
        <IconButton icon={PanelLeftClose} label="Hide sidebar" onPress={onHide} />
      </View>

      <Pressable
        accessibilityRole="button"
        onPress={startNewChat}
        style={({ pressed }) => [
          styles.newChat,
          { backgroundColor: colors.primary, boxShadow: colors.buttonGlow, opacity: pressed ? 0.85 : 1 },
        ]}>
        <SquarePen size={18} color={colors.onPrimary} strokeWidth={2} />
        <Text style={[styles.newChatText, { color: colors.onPrimary }]}>New chat</Text>
      </Pressable>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: spacing.lg }}>
        <Text style={[styles.section, { color: colors.textMuted }]}>WORK</Text>
        {MAIN.map(([href, label, icon]) => link(href, label, icon))}
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ expanded: more }}
          accessibilityLabel={more ? 'Hide setup' : 'Show setup'}
          onPress={() => setMore(!more)}
          style={styles.sectionToggle}>
          <Text style={[styles.sectionText, { color: colors.textMuted }]}>SETUP</Text>
          {more ? <ChevronUp size={14} color={colors.textMuted} strokeWidth={2} /> : <ChevronDown size={14} color={colors.textMuted} strokeWidth={2} />}
        </Pressable>
        {more ? MORE.map(([href, label, icon]) => link(href, label, icon)) : null}

        <Text style={[styles.section, { color: colors.textMuted }]}>RECENTS</Text>
        <TextInput
          value={search}
          onChangeText={setSearch}
          placeholder="Search chats"
          placeholderTextColor={colors.textMuted}
          style={[styles.search, { color: colors.text, borderColor: colors.border, fontFamily: fonts.body }]}
        />
        {groups.length === 0 ? (
          <Text style={[styles.empty, { color: colors.textMuted }]}>
            {q ? 'No chats match.' : 'Your chats will appear here.'}
          </Text>
        ) : (
          groups.map((g) => (
            <View key={g.label}>
              <Text style={[styles.day, { color: colors.textMuted }]}>{g.label}</Text>
              {g.items.map((c) => (
                <ChatRow key={c.id} chat={c} active={path === '/' && openId === c.id} onOpen={() => open(c.id)} />
              ))}
            </View>
          ))
        )}
      </ScrollView>

      <Pressable
        accessibilityRole="link"
        onPress={() => go('/settings')}
        style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
          styles.account,
          {
            borderTopColor: colors.border,
            backgroundColor: pressed || hovered || path === '/settings' ? colors.surfaceAlt : undefined,
          },
        ]}>
        <View style={[styles.avatar, { backgroundColor: colors.primary }]}>
          <Text style={{ fontFamily: fonts.semibold, color: colors.onPrimary }}>{email.slice(0, 1).toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text numberOfLines={1} style={{ fontFamily: fonts.semibold, color: colors.text }}>
            {email.split('@')[0]}
          </Text>
          <Text style={{ fontFamily: fonts.body, fontSize: 12, color: colors.textMuted }}>Settings</Text>
        </View>
      </Pressable>
    </SafeAreaView>
  );
}

/** A Recents entry: tap to open. ⋯ (on hover on laptops, always on phones) or a long-press opens a floating menu:
 * Pin · Rename · Delete: rename and delete each get their own small window. */
function ChatRow({ chat, active, onOpen }: { chat: Chat; active: boolean; onOpen: () => void }) {
  const { colors } = useColors();
  const qc = useQueryClient();
  const [hover, setHover] = useState(false);
  const [sheet, setSheet] = useState<'none' | 'menu' | 'rename' | 'delete'>('none');
  const [title, setTitle] = useState(chat.title);
  const done = () => {
    setSheet('none');
    return qc.invalidateQueries({ queryKey: ['chats'] });
  };
  const patch = useMutation({
    mutationFn: (body: { title?: string; pinned?: boolean }) => api.patch(`/chats/${chat.id}`, body),
    onSuccess: done,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/chats/${chat.id}`),
    onSuccess: () => {
      if (useChat.getState().chatId === chat.id) newChat();
      return done();
    },
  });
  const rename = () => (title.trim() && title.trim() !== chat.title ? patch.mutate({ title: title.trim() }) : setSheet('none'));
  const tint = active ? colors.primaryText : colors.text;
  const dots = Platform.OS !== 'web' || hover || active || sheet !== 'none';

  const option = (Icon: LucideIcon, label: string, sub: string, onPress: () => void, danger?: boolean) => (
    <Pressable
      key={label}
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
        styles.option,
        { borderColor: colors.border, backgroundColor: pressed || hovered ? colors.surfaceAlt : colors.background },
      ]}>
      <View style={[styles.optionIcon, { backgroundColor: danger ? colors.surfaceAlt : colors.primarySoft }]}>
        <Icon size={17} color={danger ? colors.error : colors.primaryText} strokeWidth={2} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={{ fontFamily: fonts.semibold, fontSize: 15, color: danger ? colors.error : colors.text }}>{label}</Text>
        <Text style={{ fontFamily: fonts.body, fontSize: 12, color: colors.textMuted, marginTop: 2 }}>{sub}</Text>
      </View>
    </Pressable>
  );

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ selected: active }}
        onPress={onOpen}
        onLongPress={() => {
          haptic.longPress();
          setSheet('menu');
        }}
        onHoverIn={() => setHover(true)}
        onHoverOut={() => setHover(false)}
        style={({ pressed }) => [
          styles.chatRow,
          { backgroundColor: active ? colors.primarySoft : pressed || hover ? colors.surfaceAlt : undefined },
        ]}>
        {chat.pinned ? <Pin size={14} color={colors.textMuted} strokeWidth={2} /> : null}
        <Text numberOfLines={1} style={[styles.rowText, { color: tint }]}>
          {chat.title}
        </Text>
        {dots ? (
          <IconButton
            icon={MoreHorizontal}
            label="Chat options"
            onPress={() => {
              setTitle(chat.title);
              setSheet('menu');
            }}
          />
        ) : (
          <View style={styles.dotsSpace} />
        )}
      </Pressable>

      <Sheet open={sheet === 'menu'} title={chat.title} onClose={() => setSheet('none')}>
        {option(Pin, chat.pinned ? 'Unpin' : 'Pin to top', chat.pinned ? 'Back into the dated list' : 'Keep it at the top of Recents',
          () => patch.mutate({ pinned: !chat.pinned }))}
        {option(Pencil, 'Rename', 'Give the chat a clearer name', () => setSheet('rename'))}
        {option(Trash2, 'Delete', 'Remove the chat and its messages', () => setSheet('delete'), true)}
        {patch.error ? <Text style={[styles.empty, { color: colors.error }]}>{errorMessage(patch.error)}</Text> : null}
      </Sheet>

      <Sheet open={sheet === 'rename'} title="Rename chat" onClose={() => setSheet('none')}>
        <TextInput
          value={title}
          onChangeText={setTitle}
          autoFocus
          selectTextOnFocus
          maxLength={120}
          onSubmitEditing={rename}
          placeholder="Chat name"
          placeholderTextColor={colors.textMuted}
          style={[styles.field, { color: colors.text, borderColor: colors.primary, backgroundColor: colors.background }]}
        />
        <View style={styles.buttons}>
          <View style={{ flex: 1 }}>
            <Button kind="secondary" title="Cancel" onPress={() => setSheet('none')} />
          </View>
          <View style={{ flex: 1 }}>
            <Button title="Save" busy={patch.isPending} disabled={!title.trim()} onPress={rename} />
          </View>
        </View>
        {patch.error ? <Text style={[styles.empty, { color: colors.error }]}>{errorMessage(patch.error)}</Text> : null}
      </Sheet>

      <Sheet open={sheet === 'delete'} title="Delete chat?" onClose={() => setSheet('none')}>
        <Text style={{ fontFamily: fonts.body, fontSize: 14, lineHeight: 21, color: colors.text }}>
          “{chat.title}” and its messages will be deleted. This can’t be undone. Your jobs and emails are not affected.
        </Text>
        <View style={styles.buttons}>
          <View style={{ flex: 1 }}>
            <Button kind="secondary" title="Cancel" onPress={() => setSheet('none')} />
          </View>
          <View style={{ flex: 1 }}>
            <Button kind="danger" title="Delete" busy={remove.isPending} onPress={() => remove.mutate()} />
          </View>
        </View>
        {remove.error ? <Text style={[styles.empty, { color: colors.error }]}>{errorMessage(remove.error)}</Text> : null}
      </Sheet>
    </>
  );
}

function Row({
  label,
  icon: Icon,
  active,
  badge,
  onPress,
}: {
  label: string;
  icon?: LucideIcon;
  active?: boolean;
  badge?: number;
  onPress: () => void;
}) {
  const { colors } = useColors();
  const tint = active ? colors.primaryText : colors.text;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: !!active }}
      onPress={onPress}
      style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
        styles.row,
        { backgroundColor: active ? colors.primarySoft : pressed || hovered ? colors.surfaceAlt : undefined },
      ]}>
      {active ? <View style={[styles.activeBar, { backgroundColor: colors.primary }]} /> : null}
      {Icon ? <Icon size={18} color={tint} strokeWidth={1.8} /> : null}
      <Text numberOfLines={1} style={[styles.rowText, { color: tint }]}>
        {label}
      </Text>
      {badge ? (
        <View accessibilityLabel={`${badge} new`} style={[styles.badge, { backgroundColor: colors.primary }]}>
          <Text style={{ fontFamily: fonts.semibold, fontSize: 12, color: colors.onPrimary }}>{badge > 49 ? '50+' : badge}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  badge: { minWidth: 22, height: 22, borderRadius: 11, paddingHorizontal: 6, alignItems: 'center', justifyContent: 'center' },
  top: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingLeft: spacing.lg,
    paddingRight: spacing.sm,
    paddingTop: spacing.sm,
    paddingBottom: spacing.sm,
  },
  newChat: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    minHeight: 44,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  newChatText: { fontFamily: fonts.semibold, fontSize: 15 },
  activeBar: { position: 'absolute', left: 0, top: 8, bottom: 8, width: 3, borderRadius: 2 },
  sectionToggle: { flexDirection: 'row', alignItems: 'center', gap: 4, marginHorizontal: spacing.lg, marginTop: spacing.lg,
    marginBottom: spacing.xs },
  sectionText: { fontFamily: fonts.semibold, fontSize: 11, letterSpacing: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginHorizontal: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radius.sm,
  },
  rowText: { flex: 1, fontFamily: fonts.semibold, fontSize: 15 },
  section: { fontFamily: fonts.semibold, fontSize: 11, letterSpacing: 1, marginTop: spacing.lg, marginBottom: spacing.xs, paddingHorizontal: spacing.lg },
  day: { fontFamily: fonts.body, fontSize: 12, marginTop: spacing.md, paddingHorizontal: spacing.lg },
  search: {
    borderWidth: 1,
    borderRadius: radius.sm,
    marginHorizontal: spacing.md,
    marginTop: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
    fontSize: 14,
  },
  chatRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginHorizontal: spacing.sm,
    paddingLeft: spacing.md,
    paddingRight: 2,
    minHeight: 40,
    borderRadius: radius.sm,
  },
  dotsSpace: { width: 36, height: 36 },
  option: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderWidth: 1, borderRadius: radius.md, padding: spacing.md },
  optionIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  field: { borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 10, fontSize: 15,
    fontFamily: fonts.body },
  buttons: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
  empty: { fontFamily: fonts.body, fontSize: 13, paddingHorizontal: spacing.lg, paddingTop: spacing.xs },
  account: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, borderTopWidth: 1 },
  avatar: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
});
