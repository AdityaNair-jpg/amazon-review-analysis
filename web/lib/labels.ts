/**
 * Plain-English names for everything the pipeline calls by its internal name.
 *
 * The pipeline's vocabulary is the literature's vocabulary — `loo_rating_dev`,
 * `max_in_7d`, `ECDF percentile`, `Jaccard`. That is correct inside the code and
 * useless on a screen. Every label a visitor reads comes from here instead, and
 * the internal name is kept alongside so anyone who wants to trace a number back
 * to the code still can.
 */

export type FamilyKey = "T" | "B" | "G";

export const FAMILY = {
  T: {
    key: "T" as const,
    name: "Copied writing",
    short: "Copying",
    tone: "var(--chart-2)",
    question: "Did this account post words that appear somewhere else?",
    blurb:
      "Reviews that reuse text — their own, or someone else's. Identical wording across different accounts and different products is the least ambiguous signal there is.",
    internal: "text",
  },
  B: {
    key: "B" as const,
    name: "Unusual activity",
    short: "Activity",
    tone: "var(--chart-3)",
    question: "Does this account post like a normal shopper?",
    blurb:
      "How and when an account posts. Dozens of reviews in one day, a lifetime of three weeks, ratings that disagree with everyone else who bought the same thing.",
    internal: "behaviour",
  },
  G: {
    key: "G" as const,
    name: "Moves in a pack",
    short: "Pack",
    tone: "var(--chart-4)",
    question: "Does this account keep turning up alongside the same others?",
    blurb:
      "Whether an account keeps appearing on the same products as the same other accounts, within days of them. One shared interest is a coincidence; ten is a schedule.",
    internal: "graph",
  },
} satisfies Record<FamilyKey, {
  key: FamilyKey; name: string; short: string; tone: string;
  question: string; blurb: string; internal: string;
}>;

export const FAMILY_ORDER: FamilyKey[] = ["T", "B", "G"];

export const familyOf = (key: string) =>
  FAMILY[key as FamilyKey] ?? {
    key: "T" as FamilyKey, name: key, short: key, tone: "var(--muted-foreground)",
    question: "", blurb: "", internal: key,
  };

/** Internal feature name -> what it actually measures, in words. */
export const FEATURE: Record<string, { label: string; hint: string }> = {
  // Copied writing
  self_dup_rate: {
    label: "Repeats its own reviews",
    hint: "Share of this account's reviews whose text it had already posted elsewhere.",
  },
  summary_reuse_rate: {
    label: "Repeats its own headlines",
    hint: "Share of review titles this account had already used before.",
  },
  summary_is_text_rate: {
    label: "Headline is the whole review",
    hint: "Reviews where the title and the body are the same text — a sign of minimal effort.",
  },
  exact_dup_rate: {
    label: "Text found word-for-word elsewhere",
    hint: "Share of reviews whose exact text also appears on another account or product.",
  },
  neardup_rate: {
    label: "Reviews that are near-copies",
    hint: "Share of reviews that are at least 70% identical to another review in the corpus.",
  },
  neardup_max_cluster: {
    label: "Largest copy group it belongs to",
    hint: "How many reviews share near-identical wording with this account's text.",
  },
  mean_words: {
    label: "Writes short reviews",
    hint: "Average review length. Paid reviews skew short; this counts short as more suspicious.",
  },
  words_cv: {
    label: "Every review the same length",
    hint: "Real reviewers vary. Uniform length across every review suggests a template.",
  },
  exclaim_rate: {
    label: "Heavy on exclamation marks",
    hint: "Exclamation marks per word.",
  },
  upper_rate: {
    label: "SHOUTS in capitals",
    hint: "Share of characters that are capital letters.",
  },

  // Unusual activity
  max_in_7d: {
    label: "Busiest week",
    hint: "The most reviews this account posted in any seven-day stretch.",
  },
  max_per_day: {
    label: "Busiest single day",
    hint: "The most reviews this account posted in one day.",
  },
  reviews_per_active_day: {
    label: "Reviews per active day",
    hint: "How many reviews it writes on the days it writes at all.",
  },
  lifespan_days: {
    label: "Short-lived account",
    hint: "Days between first and last review. A whole review history inside a week is unusual.",
  },
  gap_cv: {
    label: "Posts in bursts, not steadily",
    hint: "How irregular the gaps between reviews are. Steady beats spiky.",
  },
  rating_entropy: {
    label: "Always gives the same rating",
    hint: "Whether the account ever discriminates between products, or just stamps one score.",
  },
  loo_rating_dev: {
    label: "Disagrees with everyone else",
    hint: "How far its rating sits from what every other reviewer of the same product said.",
  },
  early_tendency: {
    label: "Arrives early on new products",
    hint: "Tends to be among the first to review something — where a push has most effect.",
  },

  // Moves in a pack
  coreview_weight: {
    label: "Overlap with other accounts",
    hint: "How many products it reviewed alongside the same other accounts, within 30 days.",
  },
  coreview_degree: {
    label: "Number of accounts it overlaps with",
    hint: "How many other accounts it shares products with.",
  },
  ring_size: {
    label: "Size of its group",
    hint: "How many accounts are in the tightly-connected group this one belongs to.",
  },
  ring_density: {
    label: "How tightly knit that group is",
    hint: "1.0 means every member of the group overlaps with every other member.",
  },
  max_product_eigen: {
    label: "Reviews hub products",
    hint: "Whether the products it reviews sit at the centre of the co-review network.",
  },
  mean_product_pagerank: {
    label: "Prominence of the products it reviews",
    hint: "PageRank of its products within the product co-review network.",
  },
};

export const featureLabel = (name: string) => FEATURE[name]?.label ?? name;
export const featureHint = (name: string) => FEATURE[name]?.hint ?? "";

/** Column headings that used to expose internal vocabulary. */
export const METRIC: Record<string, { label: string; hint: string }> = {
  score: {
    label: "Suspicion score",
    hint: "0 to 1. High only when several independent methods agree, so it is deliberately hard to score highly.",
  },
  score_any: {
    label: "Flagged by any method",
    hint: "High if even one method finds this account extreme. Wider net, weaker evidence.",
  },
  density: {
    label: "How tightly knit",
    hint: "1.0 means every account in the group overlaps with every other one.",
  },
  mean_shared: {
    label: "Shared products per pair",
    hint: "On average, how many products any two members of this group both reviewed within 30 days.",
  },
  mean_jaccard: {
    label: "Text similarity",
    hint: "1.0 is word-for-word identical. Measured exactly, not estimated.",
  },
  span_days: {
    label: "Active over",
    hint: "Days between the first and last review in this group.",
  },
  n_reviewers: { label: "Accounts", hint: "Distinct accounts involved." },
  n_products: { label: "Products", hint: "Distinct products involved." },
  n_reviews: { label: "Reviews", hint: "Total reviews involved." },
  max_daily_z: {
    label: "Burst strength",
    hint: "How far one day's review count exceeded what was expected for a product this size, on that date.",
  },
};

export const metricLabel = (name: string) => METRIC[name]?.label ?? name;
export const metricHint = (name: string) => METRIC[name]?.hint ?? "";
