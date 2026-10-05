import { Image } from 'react-native';

import { useColors } from '@/theme/use-colors';

const LIGHT = require('@/assets/images/wordmark-light.png');
const DARK = require('@/assets/images/wordmark-dark.png');

/** Leapvoy logo + name, matching the current theme. */
export function Brand({ width = 200 }: { width?: number }) {
  const { scheme } = useColors();
  return (
    <Image
      source={scheme === 'dark' ? DARK : LIGHT}
      style={{ width, height: width * 0.29 }}
      resizeMode="contain"
      accessibilityLabel="Leapvoy"
    />
  );
}
