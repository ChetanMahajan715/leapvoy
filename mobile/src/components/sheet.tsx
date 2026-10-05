/** Floating window over the screen (model picker, scheduling, calendar, attach): a centered card on wide screens,
 * a bottom sheet on phones. Tap outside or ✕ to close. Same component on web and Android. */
import { X } from 'lucide-react-native';
import type { ReactNode } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { IconButton } from '@/components/icon-button';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

export function Sheet({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const { colors } = useColors();
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const wide = width >= 700;
  return (
    // a plain quick fade, no bounce (user, 5 Oct): a moving window made the first tap on ✕ get lost on Android
    <Modal visible={open} transparent animationType="fade" onRequestClose={onClose}>
      <View style={[styles.backdrop, wide ? styles.center : styles.bottom]}>
        <Pressable
          accessibilityLabel="Close"
          onPress={onClose}
          style={[StyleSheet.absoluteFill, { backgroundColor: colors.scrim }]}
        />
        <View
          accessibilityViewIsModal
          style={[
            styles.panel,
            { backgroundColor: colors.surface, borderColor: colors.glassBorder, boxShadow: colors.cardShadow, maxHeight: height * (wide ? 0.8 : 0.85) },
            wide ? styles.card : [styles.sheet, { paddingBottom: Math.max(insets.bottom, spacing.md) }],
          ]}>
          {!wide ? <View style={[styles.grab, { backgroundColor: colors.border }]} /> : null}
          <View style={styles.head}>
            <Text style={[styles.title, { color: colors.text }]}>{title}</Text>
            <IconButton icon={X} label="Close" onPress={onClose} />
          </View>
          <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
            {children}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1 },
  center: { justifyContent: 'center', alignItems: 'center', padding: spacing.lg },
  bottom: { justifyContent: 'flex-end' },
  panel: { borderWidth: 1, overflow: 'hidden' },
  card: { width: '100%', maxWidth: 460, borderRadius: radius.lg },
  sheet: { width: '100%', borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, borderBottomWidth: 0 },
  grab: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, marginTop: spacing.sm },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingLeft: spacing.lg,
    paddingRight: spacing.sm, paddingTop: spacing.sm },
  title: { fontFamily: fonts.semibold, fontSize: 16 },
  body: { padding: spacing.lg, paddingTop: spacing.sm, gap: spacing.sm },
});
