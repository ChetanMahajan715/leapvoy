import type { LucideIcon } from 'lucide-react-native';
import { Pressable } from 'react-native';

import { useColors } from '@/theme/use-colors';

/** Square icon button like Claude's (panel toggle, incognito). */
export function IconButton({
  icon: Icon,
  label,
  onPress,
  active,
}: {
  icon: LucideIcon;
  label: string;
  onPress: () => void;
  active?: boolean;
}) {
  const { colors } = useColors();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ selected: !!active }}
      onPress={onPress}
      hitSlop={10} // small icon: a bigger touch area, and no shrink-on-press (an edge tap could get cancelled)
      style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => ({
        width: 36,
        height: 36,
        borderRadius: 8,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: active ? colors.primarySoft : pressed || hovered ? colors.surfaceAlt : undefined,
      })}>
      <Icon size={20} color={active ? colors.primaryText : colors.textMuted} strokeWidth={1.8} />
    </Pressable>
  );
}
