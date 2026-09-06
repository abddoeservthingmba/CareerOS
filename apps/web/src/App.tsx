import { useEffect, useState } from "react";

/**
 * The P0 deliverable: "both clients render live health from it"
 * (`00-scope-and-phases.md` §4).
 *
 * `/healthz` and `/readyz` sit outside `/api/v1` and outside the generated
 * clients (`AC-FOUND-13.5`), so reaching them with `fetch` is correct rather
 * than an exception to `AC-WEB-01.2` - that rule bans a hand-written call to an
 * `/api/` path, and these are not one. Every product screen from P1 onward uses
 * the generated client.
 */

interface Health {
  status: string;
  product: string;
  environment: string;
  version: string;
  uptime_seconds: number;
  time: string;
}

interface Readiness {
  status: string;
  checks: Record<string, string>;
  not_yet_checked: string[];
  time: string;
}

type Load<T> =
  | { state: "loading" }
  | { state: "ok"; value: T }
  | { state: "error"; reason: string };

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  // `/readyz` answers 503 with a body worth showing, so a non-2xx is not
  // automatically an error here.
  if (response.status >= 500 && response.status !== 503) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

function useEndpoint<T>(path: string, intervalMs: number): Load<T> {
  const [result, setResult] = useState<Load<T>>({ state: "loading" });

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const value = await get<T>(path);
        if (!cancelled) setResult({ state: "ok", value });
      } catch (error) {
        if (!cancelled) {
          setResult({
            state: "error",
            reason: error instanceof Error ? error.message : "unreachable",
          });
        }
      }
    };

    void poll();
    const timer = setInterval(() => void poll(), intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [path, intervalMs]);

  return result;
}

function Dot({ ok }: { ok: boolean }) {
  // `AC-WEB-07.4`: state is never carried by colour alone.
  return (
    <span className={ok ? "dot dot-ok" : "dot dot-bad"} aria-hidden="true">
      {ok ? "●" : "▲"}
    </span>
  );
}

export function App() {
  const health = useEndpoint<Health>("/healthz", 5000);
  const ready = useEndpoint<Readiness>("/readyz", 5000);

  const productName = health.state === "ok" ? health.value.product : "…";

  return (
    <main>
      <header>
        {/* `README.md` §5 / `AC-FOUND-02.4`: the product name comes from
            PRODUCT_NAME, never a literal in the client. */}
        <h1>{productName}</h1>
        <p className="subtitle">
          P0 · infrastructure proving · the client rendering live health from the API
        </p>
      </header>

      <section aria-labelledby="liveness">
        <h2 id="liveness">Liveness — <code>/healthz</code></h2>
        {health.state === "loading" && <p className="muted">Checking…</p>}
        {health.state === "error" && (
          <p className="bad">
            <Dot ok={false} /> API unreachable — {health.reason}
            <br />
            <span className="muted">
              Start it with <code>py infra/scripts/run_api.py</code>
            </span>
          </p>
        )}
        {health.state === "ok" && (
          <dl>
            <dt>Status</dt>
            <dd>
              <Dot ok={health.value.status === "ok"} /> {health.value.status}
            </dd>
            <dt>Environment</dt>
            <dd>{health.value.environment}</dd>
            <dt>Version</dt>
            <dd>{health.value.version}</dd>
            <dt>Uptime</dt>
            <dd>{health.value.uptime_seconds}s</dd>
            <dt>Server time (UTC)</dt>
            <dd>
              <code>{health.value.time}</code>
            </dd>
          </dl>
        )}
      </section>

      <section aria-labelledby="readiness">
        <h2 id="readiness">Readiness — <code>/readyz</code></h2>
        {ready.state === "loading" && <p className="muted">Checking…</p>}
        {ready.state === "error" && (
          <p className="bad">
            <Dot ok={false} /> {ready.reason}
          </p>
        )}
        {ready.state === "ok" && (
          <>
            <p>
              <Dot ok={ready.value.status === "ready"} /> {ready.value.status}
            </p>
            <dl>
              {Object.entries(ready.value.checks).map(([name, outcome]) => (
                <div key={name} className="row">
                  <dt>{name}</dt>
                  <dd>
                    <Dot ok={outcome === "ok"} /> {outcome}
                  </dd>
                </div>
              ))}
            </dl>
            {ready.value.not_yet_checked.length > 0 && (
              <p className="muted">
                Not yet checked: {ready.value.not_yet_checked.join(", ")} — these
                join <code>/readyz</code> with <code>FOUND-10</code> and{" "}
                <code>DATA-03</code>. Named rather than omitted, so a green tick
                never means less than it looks.
              </p>
            )}
          </>
        )}
      </section>

      <footer className="muted">
        Polling every 5s. Mongo is a real Atlas cluster; Docker is unavailable on
        this machine, so the stack runs as processes rather than containers.
      </footer>
    </main>
  );
}
