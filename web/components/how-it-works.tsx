import Link from "next/link";
import { FAMILY, FAMILY_ORDER } from "@/lib/labels";
import { Card, CardContent } from "@/components/ui/card";

/**
 * The three signals, in the words a first-time reader needs, each anchored to a
 * real example from this corpus rather than to a definition.
 */
export function HowItWorks({
  examples,
}: {
  examples: Partial<Record<"T" | "B" | "G", React.ReactNode>>;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {FAMILY_ORDER.map((key, i) => {
        const f = FAMILY[key];
        return (
          <Card key={key} className="relative overflow-hidden">
            <span
              className="absolute inset-x-0 top-0 h-1"
              style={{ backgroundColor: f.tone }}
            />
            <CardContent className="space-y-3 pt-6">
              <div className="flex items-baseline gap-2">
                <span
                  className="tabular text-xs font-semibold"
                  style={{ color: f.tone }}
                >
                  {i + 1}
                </span>
                <h3 className="text-base font-semibold">{f.name}</h3>
              </div>
              <p className="text-sm text-muted-foreground">{f.blurb}</p>
              {examples[key] && (
                <div className="rounded-md border-l-2 bg-muted/40 px-3 py-2 text-xs"
                     style={{ borderLeftColor: f.tone }}>
                  <span className="mb-0.5 block font-medium">Found in this data</span>
                  <span className="text-muted-foreground">{examples[key]}</span>
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}

      <Card className="md:col-span-3">
        <CardContent className="pt-6 text-sm text-muted-foreground">
          <p>
            <strong className="text-foreground">
              The three share no inputs, and that is the whole design.
            </strong>{" "}
            Nothing about how often an account posts feeds the copied-writing check;
            nothing about who it posts alongside feeds the activity check. So when two or
            three of them point at the same account, that agreement is a real signal
            rather than one measurement counted three times. An account is only strongly
            flagged when they agree &mdash; which is why just{" "}
            <Link href="/reviewers?min_score=0.99" className="underline underline-offset-2">
              a few hundred of three million accounts
            </Link>{" "}
            score above 0.99.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
