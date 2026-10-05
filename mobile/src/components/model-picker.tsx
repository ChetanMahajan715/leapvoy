/** Like Claude / ChatGPT: pick the AI model (or Auto), with each model's free usage left today. */
import { useQueryClient } from '@tanstack/react-query';
import { Check, ChevronDown, Sparkles } from 'lucide-react-native';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Sheet } from '@/components/sheet';
import { setPick, useModels, usePicks, type PickKind } from '@/lib/models';
import { usageText } from '@/lib/usage-text';
import { fonts, radius, spacing } from '@/theme/theme';
import { useColors } from '@/theme/use-colors';

export function ModelPicker({ kind, prefix }: { kind: PickKind; prefix?: string }) {
  const { colors } = useColors();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const picked = usePicks((s) => s[kind]);
  const q = useModels();
  const models = q.data?.models ?? [];
  const current = models.find((m) => m.id === picked);
  const autoStart = models.find((m) => m.id === (kind === 'chat' ? q.data?.auto : q.data?.auto_email));
  const stateColor = (state: string) =>
    state === 'empty' ? colors.error : state === 'low' || state === 'busy' ? colors.warning : colors.success;

  const choose = (id: string | null) => {
    setPick(kind, id);
    setOpen(false);
  };
  const row = (id: string | null, title: string, sub: string, usage: string, dot: string) => {
    const on = picked === id;
    return (
      <Pressable
        key={id ?? 'auto'}
        accessibilityRole="radio"
        accessibilityState={{ selected: on }}
        onPress={() => choose(id)}
        style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
          styles.row,
          { backgroundColor: on ? colors.primarySoft : pressed || hovered ? colors.surfaceAlt : undefined },
        ]}>
        <View style={[styles.dot, { backgroundColor: dot }]} />
        <View style={{ flex: 1 }}>
          <Text style={[styles.title, { color: colors.text }]}>{title}</Text>
          <Text style={[styles.sub, { color: colors.textMuted }]}>{sub}</Text>
          <Text style={[styles.sub, { color: dot === colors.success ? colors.textMuted : dot }]}>{usage}</Text>
        </View>
        {on ? <Check size={16} color={colors.primaryText} strokeWidth={2.4} /> : null}
      </Pressable>
    );
  };

  return (
    <View style={styles.root}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={kind === 'chat' ? 'Choose the AI model' : 'Choose the AI model for writing emails'}
        onPress={() => {
          if (!open) qc.invalidateQueries({ queryKey: ['models'] }); // fresh usage when opening
          setOpen(!open);
        }}
        style={[styles.chip, { borderColor: colors.border, backgroundColor: open ? colors.surfaceAlt : undefined }]}>
        <Sparkles size={14} color={colors.primaryText} strokeWidth={2} />
        <Text numberOfLines={1} style={[styles.chipText, { color: colors.text }]}>
          {prefix ? `${prefix} ` : ''}
          {current ? current.label : 'Auto'}
        </Text>
        {current && current.state === 'empty' ? <View style={[styles.dot, { backgroundColor: colors.error }]} /> : null}
        <ChevronDown size={14} color={colors.textMuted} strokeWidth={2} />
      </Pressable>
      <Sheet open={open} title={kind === 'chat' ? 'Choose the AI model' : 'AI model for writing emails'} onClose={() => setOpen(false)}>
        <View style={[styles.menu, { borderColor: colors.border }]}>
          {row(
            null,
            'Auto (best available)',
            autoStart ? `Starts with ${autoStart.label}; switches by itself when a model's free limit is used up` : 'Leapvoy picks for you',
            'Recommended',
            colors.success,
          )}
          {models.map((m) =>
            row(m.id, m.label, `${m.maker} · ${m.note}`, usageText(m), stateColor(m.state)),
          )}
          {q.isError && !models.length ? (
            <Text style={[styles.sub, { color: colors.error, padding: spacing.sm }]}>Couldn’t load the models.</Text>
          ) : null}
          <Text style={[styles.sub, { color: colors.textMuted, padding: spacing.sm }]}>
            If the model you pick has no usage left, Leapvoy answers with the next one and shows which.
          </Text>
        </View>
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingVertical: 6,
    paddingHorizontal: spacing.md,
    maxWidth: 220,
    alignSelf: 'flex-start',
  },
  chipText: { fontFamily: fonts.semibold, fontSize: 13, flexShrink: 1 },
  root: { flexShrink: 1 },
  menu: { borderWidth: 1, borderRadius: radius.md, paddingVertical: spacing.xs },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.sm, paddingHorizontal: spacing.md },
  dot: { width: 8, height: 8, borderRadius: 4 },
  title: { fontFamily: fonts.semibold, fontSize: 14 },
  sub: { fontFamily: fonts.body, fontSize: 12, lineHeight: 17 },
});
