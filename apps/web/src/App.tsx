import { useEffect, useState } from "react";

import { Preview } from "./preview/Screens";

/**
 * The local shell.
 *
 * Two things live here: the **design preview** of the R1 journey, rendered from
 * committed fixtures so the UX can be reacted to before P2-P6 build it, and a
 * strip showing the API's live health, which is P0's actual deliverable
 * ("both clients render live health from it", `00-scope-and-phases.md` §4).
 *
 * The preview is a mockup. Nothing in it is wired to the API, and no product
 * code has been written ahead of its phase.
 */

interface Health {
  status: string;
  product: string;
  environment: string;
  version: string;
}

/**
 * Where the API is, if there is one.
 *
 * Empty on a static host: the preview is deployed on its own, and polling a
 * `/healthz` that the SPA rewrite answers with `index.html` would report
 * "unreachable" next to a claim that Atlas is connected — two statements that
 * cannot both be checked from a page with no backend. An empty base means the
 * strip says so instead of guessing.
 */
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [reachable, setReachable] = useState(true);

  useEffect(() => {
    if (!API_BASE && import.meta.env.PROD) return;

    let cancelled = false;
    const poll = async () => {
      try {
        // `/healthz` is outside `/api/v1` and outside the generated clients
        // (`AC-FOUND-13.5`), so `fetch` here is correct rather than an
        // exception to `AC-WEB-01.2`.
        const response = await fetch(`${API_BASE}/healthz`, {
          headers: { Accept: "application/json" },
        });
        const value = (await response.json()) as Health;
        if (!cancelled) {
          setHealth(value);
          setReachable(true);
        }
      } catch {
        if (!cancelled) setReachable(false);
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const attached = Boolean(API_BASE) || !import.meta.env.PROD;

  return (
    <div className="app">
      <header className="masthead">
        {/* `README.md` §5 — the name comes from PRODUCT_NAME, never a literal. */}
        <h1>{health?.product ?? "…"}</h1>
        <span className="muted tiny">
          {health?.environment ?? "local"} · v{health?.version ?? "0.1.0"}
        </span>
      </header>

      <p className="preview-note">
        <strong>Design preview.</strong> These four screens are the R1 journey rendered
        from committed fixtures — the shapes are the ones <code>17-data-model.md</code>{" "}
        declares, but nothing here is wired to the API and no product code has been
        written ahead of its phase. It exists so the UX can be argued with now rather
        than after P2–P6 build it.
      </p>

      <Preview />

      <div className="health">
        {attached ? (
          <>
            <span>
              <span className={reachable ? "dot dot-ok" : "dot dot-bad"} aria-hidden="true">
                {reachable ? "●" : "▲"}
              </span>
              API {reachable ? health?.status ?? "…" : "unreachable"}
            </span>
            <span>
              Docker unavailable on this machine — the stack runs as processes, and the
              container criteria are verified in CI.
            </span>
          </>
        ) : (
          <span>
            <span className="dot" aria-hidden="true">
              ●
            </span>
            Design preview only — no API is attached to this deployment, so nothing on
            this page is live data.
          </span>
        )}
      </div>
    </div>
  );
}
