import { Card, Screen, T } from '@/components/ui';

/** Placeholder for screens built in later steps. */
export function ComingSoon({ title, what, step }: { title: string; what: string; step: number }) {
  return (
    <Screen>
      <Card>
        <T variant="heading">{title}</T>
        <T variant="muted">{what}</T>
        <T variant="muted">Arrives in Step {step}.</T>
      </Card>
    </Screen>
  );
}
