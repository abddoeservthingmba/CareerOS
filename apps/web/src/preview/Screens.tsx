/**
 * Design preview for the R1 journey — fixture data, no API.
 *
 * The four screens the exit sentence passes through: the matches feed, the job
 * detail with its explain payload, the application pack editor with its
 * fabrication flags, and the tracker.
 *
 * Every shape comes from `17-data-model.md`, and every rendering rule from the
 * module file that owns it, so the point of disagreement is the *design* rather
 * than whether the data could exist.
 */

import { useMemo, useState } from "react";

import {
  APPLICATIONS,
  BOARD_ORDER,
  COMPONENT_LABEL,
  COMPONENT_MAX,
  JOBS,
  PACK,
  SCORES,
  STATUS_LABEL,
  type Application,
  type Band,
  type FabricationFlag,
  type Job,
  type SkillsBasis,
} from "./fixtures";

const BAND_LABEL: Record<Band, string> = {
  strong: "Strong match",
  good: "Good match",
  partial: "Partial match",
  weak: "Weak match",
};

/** `AC-MATCH-02.4` — the qualifier changes how much to trust a missing-skill list. */
const BASIS_NOTE: Record<SkillsBasis, string | null> = {
  listing: null,
  dictionary: null,
  llm: "Requirements inferred from the description — the employer did not list them.",
  semantic: "This listing named no skills, so the skills score is based on overall similarity.",
  none: "This listing named no skills and has no embedding, so skills scored zero.",
};

function ScoreChip({ score, band }: { score: number; band: Band }) {
  return (
    <span className={`chip chip-${band}`}>
      <strong>{score}</strong>
      <span className="chip-band">{BAND_LABEL[band]}</span>
    </span>
  );
}

function topReasons(jobId: string): string[] {
  const explain = SCORES[jobId]?.explain;
  if (!explain) return [];
  const out: string[] = [];
  if (explain.matched_required.length > 0) {
    out.push(`Has ${explain.matched_required.slice(0, 3).join(", ")}`);
  }
  out.push(explain.location.detail);
  if (explain.missing_required.length > 0) {
    out.push(`Missing ${explain.missing_required.join(", ")}`);
  } else if (explain.salary.verdict !== "unknown") {
    out.push(explain.salary.detail);
  }
  return out.slice(0, 3);
}

/* ── 1. Matches feed ─────────────────────────────────────────────────── */

function MatchesFeed({ onOpen }: { onOpen: (id: string) => void }) {
  const [threshold, setThreshold] = useState(60);

  const eligible = useMemo(
    () => JOBS.filter((job) => (SCORES[job.id]?.score ?? 0) >= threshold),
    [threshold],
  );

  return (
    <div className="screen">
      <div className="screen-head">
        <div>
          <h2>Matches</h2>
          <p className="muted">
            {eligible.length} eligible of {JOBS.length} scored · weights <code>w1</code>
          </p>
        </div>
        <label className="threshold">
          <span>
            Minimum score <strong>{threshold}</strong>
          </span>
          <input
            type="range"
            min={0}
            max={95}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            aria-label="Minimum match score"
          />
          {/* `AC-WEB-03.4` — the slider re-queries; it never rescores. */}
          <span className="muted tiny">Filters stored scores. Nothing is recomputed.</span>
        </label>
      </div>

      {eligible.length === 0 && (
        <div className="empty">
          <p>
            <strong>Nothing matches at {threshold}.</strong>
          </p>
          <p className="muted">
            Lowering the threshold to 20 would show 3 more. Your preferences are
            yours — nothing is relaxed automatically.
          </p>
        </div>
      )}

      <ul className="cards">
        {eligible.map((job) => {
          const score = SCORES[job.id];
          if (!score) return null;
          return (
            <li key={job.id} className="card">
              <div className="card-head">
                <div>
                  <h3>
                    <button className="linklike" onClick={() => onOpen(job.id)}>
                      {job.title}
                    </button>
                  </h3>
                  <p className="muted">
                    {job.company} · {job.location} · {job.remote_mode}
                  </p>
                </div>
                <ScoreChip score={score.score} band={score.band} />
              </div>

              <ul className="reasons">
                {topReasons(job.id).map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>

              {score.explain.red_flags.length > 0 && (
                <ul className="flags">
                  {score.explain.red_flags.map((flag) => (
                    <li key={flag}>
                      <Warn /> {flag}
                    </li>
                  ))}
                </ul>
              )}

              <div className="card-foot">
                {/* `CONN-07` — attribution on the card, not in a footer. */}
                <span className="muted tiny">{job.attribution}</span>
                <span className="muted tiny">
                  {job.salary ?? "No salary stated"} · {job.posted_days_ago}d ago
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ── 2. Job detail — the six explain sections ────────────────────────── */

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="bar-row">
      <span className="bar-label">{label}</span>
      <span className="bar-track" aria-hidden="true">
        <span className="bar-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="bar-value">
        {value}
        <span className="muted"> / {max}</span>
      </span>
    </div>
  );
}

function JobDetail({ jobId, onBack, onApply }: { jobId: string; onBack: () => void; onApply: () => void }) {
  const job = JOBS.find((j) => j.id === jobId) as Job;
  const score = SCORES[jobId];
  if (!score) return null;
  const { explain, components } = score;
  const basisNote = BASIS_NOTE[explain.skills_basis];

  return (
    <div className="screen">
      <button className="back" onClick={onBack}>
        ← Matches
      </button>

      <div className="screen-head">
        <div>
          <h2>{job.title}</h2>
          <p className="muted">
            {job.company} · {job.location} · {job.employment_type.replace("_", " ")}
          </p>
        </div>
        <ScoreChip score={score.score} band={score.band} />
      </div>

      {/* 2. Matched and missing required skills */}
      <section className="panel">
        <h3>Skills</h3>
        <div className="pills">
          {explain.matched_required.map((s) => (
            <span key={s} className="pill pill-have">
              ✓ {s}
            </span>
          ))}
          {explain.missing_required.map((s) => (
            <span key={s} className="pill pill-missing">
              — {s}
            </span>
          ))}
        </div>
        {explain.missing_nice.length > 0 && (
          <p className="muted tiny">Nice to have, not required: {explain.missing_nice.join(", ")}</p>
        )}
        {basisNote && <p className="note">{basisNote}</p>}
      </section>

      {/* 3. One line each for experience, location, salary, seniority */}
      <section className="panel">
        <h3>The rest of the fit</h3>
        <dl className="verdicts">
          {(
            [
              ["Experience", explain.experience],
              ["Location", explain.location],
              ["Salary", explain.salary],
              ["Seniority", explain.seniority],
            ] as const
          ).map(([label, item]) => (
            <div key={label} className="verdict-row">
              <dt>{label}</dt>
              <dd>
                <span className={`verdict verdict-${item.verdict}`}>{item.verdict.replace(/_/g, " ")}</span>
                <span className="detail">{item.detail}</span>
              </dd>
            </div>
          ))}
        </dl>
      </section>

      {/* 4. Red flags */}
      {explain.red_flags.length > 0 && (
        <section className="panel panel-warn">
          <h3>Worth knowing</h3>
          <ul className="flags">
            {explain.red_flags.map((flag) => (
              <li key={flag}>
                <Warn /> {flag}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 6. Score composition, with each component's max */}
      <section className="panel">
        <h3>How this score was computed</h3>
        {(Object.keys(COMPONENT_MAX) as (keyof typeof COMPONENT_MAX)[]).map((key) => (
          <Bar key={key} label={COMPONENT_LABEL[key]} value={components[key]} max={COMPONENT_MAX[key]} />
        ))}
        {components.penalties !== 0 && (
          <div className="bar-row">
            <span className="bar-label">Penalties</span>
            <span className="bar-track" aria-hidden="true">
              <span className="bar-fill bar-penalty" style={{ width: `${Math.min(100, Math.abs(components.penalties))}%` }} />
            </span>
            <span className="bar-value bad">{components.penalties}</span>
          </div>
        )}
        <p className="muted tiny">
          Components are rounded for display, so they need not sum exactly to {score.score}.
          Weights <code>{score.weights_version}</code>.
        </p>

        {/* 5. Semantic fit — shown, explicitly not part of the number */}
        <p className="note">
          Semantic fit {score.embedding_sim?.toFixed(2)} — shown as a secondary signal.
          It does <strong>not</strong> affect the score.
        </p>
        {/* `AC-MATCH-02.6` — with the rationale flag off, nothing is missing here. */}
      </section>

      <section className="panel">
        <h3>The listing</h3>
        <p className="description">{job.description}</p>
        <p className="muted tiny">{job.attribution}</p>
      </section>

      <div className="actions">
        <button className="btn btn-primary" onClick={onApply}>
          Prepare application
        </button>
        <a className="btn" href={job.apply_url} target="_blank" rel="noopener noreferrer">
          View original ↗
        </a>
        <button className="btn btn-quiet">Not interested</button>
      </div>
    </div>
  );
}

/* ── 3. Application pack editor ──────────────────────────────────────── */

function highlight(text: string, flags: FabricationFlag[]) {
  const open = flags.filter((f) => f.status !== "resolved");
  let parts: (string | FabricationFlag)[] = [text];
  for (const flag of open) {
    const next: (string | FabricationFlag)[] = [];
    for (const part of parts) {
      if (typeof part !== "string") {
        next.push(part);
        continue;
      }
      const index = part.indexOf(flag.span);
      if (index === -1) {
        next.push(part);
        continue;
      }
      next.push(part.slice(0, index), flag, part.slice(index + flag.span.length));
    }
    parts = next;
  }
  return parts;
}

function ApplyPanel({ onBack }: { onBack: () => void }) {
  const [flags, setFlags] = useState(PACK.fabrication_flags);
  const open = flags.filter((f) => f.status === "open");
  const unresolvedAnswers = PACK.answers.filter((a) => a.needs_user);
  const approvable = open.length === 0 && unresolvedAnswers.length === 0;

  const override = (span: string) =>
    setFlags((current) =>
      current.map((f) => (f.span === span ? { ...f, status: "overridden" as const } : f)),
    );

  return (
    <div className="screen">
      <button className="back" onClick={onBack}>
        ← Job detail
      </button>

      <div className="screen-head">
        <div>
          <h2>Application pack</h2>
          <p className="muted">Senior Backend Engineer · Acme Payments · tone: {PACK.tone}</p>
        </div>
        <span className={`chip ${approvable ? "chip-strong" : "chip-weak"}`}>
          <strong>{PACK.status}</strong>
        </span>
      </div>

      {!approvable && (
        <div className="banner">
          <Warn />
          <div>
            <strong>Not approvable yet.</strong>
            <p className="muted tiny">
              {open.length > 0 && `${open.length} claim${open.length > 1 ? "s" : ""} we could not trace to your confirmed profile. `}
              {unresolvedAnswers.length > 0 && `${unresolvedAnswers.length} question needs your answer.`}
            </p>
          </div>
        </div>
      )}

      <section className="panel">
        <h3>Summary</h3>
        <p className="generated">{PACK.summary}</p>
        <span className="ai-badge">AI-generated · not yet edited</span>
      </section>

      <section className="panel">
        <h3>Cover letter</h3>
        <p className="generated">
          {highlight(PACK.cover_letter, flags).map((part, i) =>
            typeof part === "string" ? (
              <span key={i}>{part}</span>
            ) : (
              <mark key={i} className={`flagged flagged-${part.status}`}>
                {part.span}
                <span className="flag-note">
                  {part.status === "overridden" ? "kept by you" : part.reason}
                </span>
              </mark>
            ),
          )}
        </p>
        <span className="ai-badge">AI-generated · not yet edited</span>

        {open.length > 0 && (
          <div className="flag-list">
            {open.map((flag) => (
              <div key={flag.span} className="flag-item">
                <div>
                  <strong>“{flag.span}”</strong>
                  <p className="muted tiny">
                    {flag.reason} ({flag.entity_type})
                  </p>
                </div>
                <div className="flag-actions">
                  <button className="btn btn-small btn-primary">Edit</button>
                  <button className="btn btn-small" onClick={() => override(flag.span)}>
                    Keep anyway
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <h3>Gap acknowledged honestly</h3>
        {PACK.gap_acknowledgements.map((gap) => (
          <p key={gap.skill} className="note">
            <strong>{gap.skill}</strong> — “{gap.phrasing}”. The letter never claims a
            skill you do not have.
          </p>
        ))}
      </section>

      <section className="panel">
        <h3>Screening answers</h3>
        {PACK.answers.map((answer) => (
          <div key={answer.question} className="answer">
            <p className="answer-q">{answer.question}</p>
            {answer.needs_user ? (
              <p className="needs-user">
                <Warn /> Needs your answer — this one is marked sensitive, so nothing is
                ever suggested for it.
              </p>
            ) : (
              <p className="answer-a">
                {answer.answer} <span className="muted tiny">— from your answer bank</span>
              </p>
            )}
          </div>
        ))}
      </section>

      <div className="actions">
        <button className="btn btn-primary" disabled={!approvable}>
          Approve pack
        </button>
        <button className="btn">Regenerate</button>
        <p className="muted tiny">
          Approving does not send anything. You open the posting and apply yourself.
        </p>
      </div>
    </div>
  );
}

/* ── 4. Tracker ──────────────────────────────────────────────────────── */

function Tracker() {
  const [items, setItems] = useState<Application[]>(APPLICATIONS);

  const move = (id: string, direction: -1 | 1) =>
    setItems((current) =>
      current.map((item) => {
        if (item.id !== id) return item;
        const index = BOARD_ORDER.indexOf(item.status);
        const next = BOARD_ORDER[Math.min(BOARD_ORDER.length - 1, Math.max(0, index + direction))];
        return next ? { ...item, status: next } : item;
      }),
    );

  return (
    <div className="screen">
      <div className="screen-head">
        <div>
          <h2>Tracker</h2>
          <p className="muted">
            {items.filter((i) => i.needs_attention).length} need attention · {items.length} total
          </p>
        </div>
      </div>

      <div className="board">
        {BOARD_ORDER.map((status) => {
          const column = items.filter((item) => item.status === status);
          return (
            <section key={status} className="column" aria-label={STATUS_LABEL[status]}>
              <h3>
                {STATUS_LABEL[status]} <span className="muted">{column.length}</span>
              </h3>
              {column.map((item) => (
                <article key={item.id} className={item.needs_attention ? "tile tile-attention" : "tile"}>
                  <p className="tile-title">{item.title}</p>
                  <p className="muted tiny">{item.company}</p>
                  {item.band && <span className={`dot-band dot-${item.band}`}>{item.band}</span>}
                  {item.listing_expired && <span className="tag">listing expired</span>}
                  {item.next_action && (
                    <p className={item.needs_attention ? "next bad" : "next muted"}>{item.next_action}</p>
                  )}
                  {/* WCAG 2.2 AA: a drag is never the only way to move a card. */}
                  <div className="tile-move">
                    <button
                      className="btn btn-tiny"
                      onClick={() => move(item.id, -1)}
                      aria-label={`Move ${item.title} back`}
                      disabled={BOARD_ORDER.indexOf(item.status) === 0}
                    >
                      ← Back
                    </button>
                    <button
                      className="btn btn-tiny"
                      onClick={() => move(item.id, 1)}
                      aria-label={`Move ${item.title} forward`}
                      disabled={BOARD_ORDER.indexOf(item.status) === BOARD_ORDER.length - 1}
                    >
                      Forward →
                    </button>
                  </div>
                </article>
              ))}
              {column.length === 0 && <p className="muted tiny column-empty">Nothing here.</p>}
            </section>
          );
        })}
      </div>
      <p className="muted tiny">
        Cards move with the buttons as well as by dragging — a drag-only board is
        unusable without a mouse.
      </p>
    </div>
  );
}

function Warn() {
  return (
    <svg className="icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path
        fill="currentColor"
        d="M8 1.5 15 14H1L8 1.5Zm0 3.6-4.3 7.4h8.6L8 5.1ZM7.3 7h1.4v3H7.3V7Zm0 3.8h1.4v1.3H7.3v-1.3Z"
      />
    </svg>
  );
}

/* ── shell ───────────────────────────────────────────────────────────── */

type View = { name: "feed" } | { name: "job"; id: string } | { name: "apply" } | { name: "tracker" };

export function Preview() {
  const [view, setView] = useState<View>({ name: "feed" });

  return (
    <div className="preview">
      <nav className="tabs" aria-label="Preview screens">
        <button
          className={view.name === "feed" || view.name === "job" ? "tab tab-on" : "tab"}
          onClick={() => setView({ name: "feed" })}
        >
          Matches
        </button>
        <button
          className={view.name === "apply" ? "tab tab-on" : "tab"}
          onClick={() => setView({ name: "apply" })}
        >
          Application pack
        </button>
        <button
          className={view.name === "tracker" ? "tab tab-on" : "tab"}
          onClick={() => setView({ name: "tracker" })}
        >
          Tracker
        </button>
      </nav>

      {view.name === "feed" && <MatchesFeed onOpen={(id) => setView({ name: "job", id })} />}
      {view.name === "job" && (
        <JobDetail
          jobId={view.id}
          onBack={() => setView({ name: "feed" })}
          onApply={() => setView({ name: "apply" })}
        />
      )}
      {view.name === "apply" && <ApplyPanel onBack={() => setView({ name: "feed" })} />}
      {view.name === "tracker" && <Tracker />}
    </div>
  );
}
