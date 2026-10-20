import { Card, CardContent } from "@/components/ui/card";

/** Shown when the FastAPI sidecar is not running or an artifact is missing. */
export function ApiError({ message }: { message: string }) {
  return (
    <Card className="border-destructive/40">
      <CardContent className="space-y-3 pt-6 text-sm">
        <p className="font-medium text-destructive">The analysis API did not answer.</p>
        <p className="text-muted-foreground">{message}</p>
        <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
{`# terminal 1 - the analysis API
cd D:\projects\BDA
uvicorn api.main:app --host 127.0.0.1 --port 8000

# terminal 2 - this dashboard
cd D:\projects\BDA\web
pnpm dev`}
        </pre>
      </CardContent>
    </Card>
  );
}
