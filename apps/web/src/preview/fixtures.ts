/**
 * Fixture data for the design preview.
 *
 * Every shape here is the one `17-data-model.md` declares, so what the preview
 * renders is what the API will actually return - the point of the exercise is
 * to react to the UX before P2-P6 build it, not to admire invented data.
 *
 * Nothing here is wired to the API. This is a mockup.
 */

export type Band = "strong" | "good" | "partial" | "weak";
export type SkillsBasis = "listing" | "dictionary" | "llm" | "semantic" | "none";

/** `match_scores.explain` — `08-matching.md` §3. */
export interface Explain {
  matched_required: string[];
  missing_required: string[];
  matched_nice: string[];
  missing_nice: string[];
  skills_basis: SkillsBasis;
  experience: { required_min_years: number | null; candidate_years: number; verdict: string; detail: string };
  location: { verdict: string; detail: string };
  salary: { verdict: string; detail: string };
  seniority: { verdict: string; detail: string };
  red_flags: string[];
}

/** `match_scores` — `17-data-model.md` §2.8. */
export interface MatchScore {
  job_id: string;
  score: number;
  band: Band;
  weights_version: string;
  components: {
    skills: number;
    experience: number;
    title: number;
    location: number;
    salary: number;
    seniority: number;
    freshness: number;
    penalties: number;
  };
  explain: Explain;
  embedding_sim: number | null;
  /** `MATCH-02b` is built-off in R1, so this is null in production. */
  rationale: string | null;
}

/** The `jobs` fields a card and a detail view read — `17` §2.6. */
export interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  remote_mode: "onsite" | "hybrid" | "remote" | "unknown";
  employment_type: string;
  salary: string | null;
  posted_days_ago: number;
  attribution: string;
  apply_url: string;
  quality_flags: string[];
  description: string;
}

/** The maxima from `08-matching.md` §2's `w1` table. Sum: 100. */
export const COMPONENT_MAX = {
  skills: 40,
  experience: 15,
  title: 15,
  location: 15,
  salary: 8,
  seniority: 4,
  freshness: 3,
} as const;

export const COMPONENT_LABEL: Record<keyof typeof COMPONENT_MAX, string> = {
  skills: "Skills",
  experience: "Experience",
  title: "Title / role",
  location: "Location",
  salary: "Salary",
  seniority: "Seniority",
  freshness: "Freshness",
};

export const JOBS: Job[] = [
  {
    id: "01JOB0000000000000000000A",
    title: "Senior Backend Engineer",
    company: "Acme Payments",
    location: "Bengaluru, IN",
    remote_mode: "hybrid",
    employment_type: "full_time",
    salary: "₹28,00,000 – ₹36,00,000 / year",
    posted_days_ago: 2,
    attribution: "Jobs by Adzuna",
    apply_url: "https://example.com/acme/senior-backend",
    quality_flags: [],
    description:
      "We are looking for a senior backend engineer to own our payments ledger. " +
      "You will work in Python and FastAPI against PostgreSQL, and help us move " +
      "to an event-driven model.\n\nRequirements: 5+ years building production " +
      "services, strong Python, PostgreSQL, and experience running services in " +
      "Kubernetes.\n\nNice to have: Terraform, Kafka, prior fintech experience.",
  },
  {
    id: "01JOB0000000000000000000B",
    title: "Backend Engineer, Platform",
    company: "Northwind Health",
    location: "Remote (India)",
    remote_mode: "remote",
    employment_type: "full_time",
    salary: null,
    posted_days_ago: 9,
    attribution: "Remotive",
    apply_url: "https://example.com/northwind/platform",
    quality_flags: ["no_salary"],
    description:
      "Join our platform team building internal APIs and developer tooling. " +
      "Python, FastAPI, MongoDB. We care about clean interfaces and good tests.",
  },
  {
    id: "01JOB0000000000000000000C",
    title: "Full Stack Developer (MERN)",
    company: "Brightline Studio",
    location: "Pune, IN",
    remote_mode: "onsite",
    employment_type: "full_time",
    salary: "₹9,00,000 – ₹12,00,000 / year",
    posted_days_ago: 41,
    attribution: "Jobs by Adzuna",
    apply_url: "https://example.com/brightline/mern",
    quality_flags: ["stale_posting", "suspicious_contact"],
    description:
      "Looking for a full stack developer. Contact us on WhatsApp at the number " +
      "below to apply quickly. Immediate joiners preferred.",
  },
];

export const SCORES: Record<string, MatchScore> = {
  "01JOB0000000000000000000A": {
    job_id: "01JOB0000000000000000000A",
    score: 82,
    band: "strong",
    weights_version: "w1",
    components: {
      skills: 34,
      experience: 14,
      title: 15,
      location: 11,
      salary: 8,
      seniority: 4,
      freshness: 3,
      penalties: 0,
    },
    explain: {
      matched_required: ["python", "fastapi", "postgresql"],
      missing_required: ["kubernetes"],
      matched_nice: ["docker"],
      missing_nice: ["terraform", "kafka"],
      skills_basis: "dictionary",
      experience: {
        required_min_years: 5,
        candidate_years: 5.4,
        verdict: "meets",
        detail: "You have 5 years 5 months; the listing asks for 5+.",
      },
      location: { verdict: "hybrid_same_city", detail: "Hybrid in Bengaluru, one of your locations." },
      salary: { verdict: "above_floor", detail: "Above your ₹24,00,000 floor." },
      seniority: { verdict: "match", detail: "Senior, matching your level." },
      red_flags: [],
    },
    embedding_sim: 0.71,
    rationale: null,
  },
  "01JOB0000000000000000000B": {
    job_id: "01JOB0000000000000000000B",
    score: 68,
    band: "good",
    weights_version: "w1",
    components: {
      skills: 28,
      experience: 15,
      title: 15,
      location: 15,
      salary: 4,
      seniority: 2,
      freshness: 2,
      penalties: 0,
    },
    explain: {
      matched_required: ["python", "fastapi", "mongodb"],
      missing_required: [],
      matched_nice: [],
      missing_nice: ["graphql"],
      skills_basis: "llm",
      experience: {
        required_min_years: null,
        candidate_years: 5.4,
        verdict: "not_stated",
        detail: "The listing states no experience requirement.",
      },
      location: { verdict: "remote_ok", detail: "Remote (India), and you accept remote." },
      salary: { verdict: "unknown", detail: "This listing gives no salary." },
      seniority: { verdict: "unknown", detail: "The listing does not state a level." },
      red_flags: ["This listing does not state a salary."],
    },
    embedding_sim: 0.66,
    rationale: null,
  },
  "01JOB0000000000000000000C": {
    job_id: "01JOB0000000000000000000C",
    score: 21,
    band: "weak",
    weights_version: "w1",
    components: {
      skills: 12,
      experience: 10,
      title: 8,
      location: 0,
      salary: 0,
      seniority: 2,
      freshness: 0,
      penalties: -30,
    },
    explain: {
      matched_required: ["javascript"],
      missing_required: ["react", "mongodb", "express"],
      matched_nice: [],
      missing_nice: [],
      skills_basis: "dictionary",
      experience: {
        required_min_years: 2,
        candidate_years: 5.4,
        verdict: "overqualified",
        detail: "You are more than 3 years over the band, which reduces callback odds.",
      },
      location: { verdict: "no_match", detail: "Onsite in Pune; not one of your locations." },
      salary: { verdict: "below_floor", detail: "Below your ₹24,00,000 floor." },
      seniority: { verdict: "adjacent", detail: "Mid-level; you are senior." },
      red_flags: [
        "Asks you to make contact over WhatsApp — a common scam marker.",
        "Posted 41 days ago.",
      ],
    },
    embedding_sim: 0.31,
    rationale: null,
  },
};

/** `application_packs` — `17-data-model.md` §2.9. */
export interface FabricationFlag {
  item: string;
  span: string;
  entity_type: "number" | "organization" | "title" | "credential" | "skill";
  reason: string;
  status: "open" | "resolved" | "overridden";
}

export interface Pack {
  job_id: string;
  status: "draft" | "approved" | "superseded";
  tone: "concise" | "warm" | "formal";
  summary: string;
  cover_letter: string;
  answers: { question: string; answer: string; source: string; needs_user: boolean }[];
  gap_acknowledgements: { skill: string; phrasing: string }[];
  fabrication_flags: FabricationFlag[];
}

export const PACK: Pack = {
  job_id: "01JOB0000000000000000000A",
  status: "draft",
  tone: "concise",
  summary:
    "Backend engineer with five years building payment and ledger systems in " +
    "Python and PostgreSQL, most recently at Vantage Retail.",
  cover_letter:
    "I have spent the last five years building backend services in Python, " +
    "most of it on systems where correctness of money mattered. At Vantage " +
    "Retail I led a team of 12 rebuilding the settlement ledger, cutting " +
    "reconciliation time by 40%.\n\n" +
    "I have not run Kubernetes in production, though I have operated " +
    "containerised services with Docker Compose and would be glad to pick it up.\n\n" +
    "Acme's move to an event-driven model is the part I would most like to work on.",
  answers: [
    {
      question: "What is your notice period?",
      answer: "60 days, negotiable to 45.",
      source: "answer_bank:notice_period",
      needs_user: false,
    },
    {
      question: "Are you authorised to work in India?",
      answer: "Yes.",
      source: "answer_bank:work_authorization",
      needs_user: false,
    },
    {
      question: "What is your current CTC?",
      answer: "",
      source: "sensitive",
      needs_user: true,
    },
  ],
  gap_acknowledgements: [
    {
      skill: "kubernetes",
      phrasing: "I have not run Kubernetes in production, though I have operated containerised services with Docker Compose",
    },
  ],
  fabrication_flags: [
    {
      item: "cover_letter",
      span: "led a team of 12",
      entity_type: "number",
      reason: "No confirmed profile field mentions a team of 12.",
      status: "open",
    },
    {
      item: "cover_letter",
      span: "cutting reconciliation time by 40%",
      entity_type: "number",
      reason: "No confirmed bullet contains 40%.",
      status: "open",
    },
  ],
};

/** `applications` — `17-data-model.md` §2.10. */
export type ApplicationStatus =
  | "saved"
  | "preparing"
  | "applied"
  | "screening"
  | "interview"
  | "offer";

export interface Application {
  id: string;
  title: string;
  company: string;
  status: ApplicationStatus;
  band: Band | null;
  next_action: string | null;
  needs_attention: boolean;
  listing_expired: boolean;
  source: "match" | "search" | "manual";
}

export const BOARD_ORDER: ApplicationStatus[] = [
  "saved",
  "preparing",
  "applied",
  "screening",
  "interview",
  "offer",
];

export const STATUS_LABEL: Record<ApplicationStatus, string> = {
  saved: "Saved",
  preparing: "Preparing",
  applied: "Applied",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
};

export const APPLICATIONS: Application[] = [
  {
    id: "01APP001",
    title: "Senior Backend Engineer",
    company: "Acme Payments",
    status: "preparing",
    band: "strong",
    next_action: "Resolve 2 fabrication flags",
    needs_attention: true,
    listing_expired: false,
    source: "match",
  },
  {
    id: "01APP002",
    title: "Backend Engineer, Platform",
    company: "Northwind Health",
    status: "saved",
    band: "good",
    next_action: null,
    needs_attention: false,
    listing_expired: false,
    source: "match",
  },
  {
    id: "01APP003",
    title: "Staff Engineer, Billing",
    company: "Fernbank",
    status: "applied",
    band: "good",
    next_action: "Follow up in 2 days",
    needs_attention: false,
    listing_expired: false,
    source: "search",
  },
  {
    id: "01APP004",
    title: "Backend Engineer",
    company: "Loop Logistics",
    status: "applied",
    band: null,
    next_action: "Follow up — 9 days overdue",
    needs_attention: true,
    listing_expired: true,
    source: "manual",
  },
  {
    id: "01APP005",
    title: "Senior Engineer, Core",
    company: "Halcyon",
    status: "screening",
    band: "strong",
    next_action: "Recruiter call Thursday",
    needs_attention: false,
    listing_expired: false,
    source: "match",
  },
  {
    id: "01APP006",
    title: "Backend Engineer, Payments",
    company: "Meridian",
    status: "interview",
    band: "strong",
    next_action: "Technical round, 24 Sep 14:00",
    needs_attention: false,
    listing_expired: false,
    source: "match",
  },
];
