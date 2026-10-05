# API engines: search results that don't get blocked

Most SearXNG engines scrape public search pages, which is why they get CAPTCHA'd, rate-limited and blocked. A
few engines use **official APIs** instead. They need a key, but they don't get blocked, so one or two of them
make a solid backbone that keeps results coming when the scrapers are having a bad day.

Set them up under **Configure → API engines**: paste the key, switch on *Enabled*, then *Review & apply*.

## Keep metered APIs for yourself: private engines

Switch on **Private** for anything with a usage limit or price. SearXNG then only uses that engine for requests
that carry the engine token. So:

- **your browsers** use it, once you save the token under SearXNG *Preferences → General → Engine tokens*;
- **API clients** (AI tools, scripts calling `/search?format=json`) and SearXNG Control's own canary probes
  **don't**, so automation can't burn through a free allowance.

The token is shown, with a copy button, at the top of the Engines page. Test a private engine with its
*Test* button in the engine panel, which sends the token.

## Options worth knowing

These are prices and free tiers as of October 2026. Check the provider's site before signing up; they change.

| Engine | What it is | Free allowance | Notes |
|---|---|---|---|
| `braveapi` — [Brave Search API](https://brave.com/search/api/) | Brave's own independent web index | $5 credit every month (≈ 1,000 searches) | Card required for verification. New accounts are **prepaid**: with a $0 prepaid balance and auto-reload off, the API simply pauses when the monthly credit is used up, so it can't bill you. The best general-purpose option here. |
| `exaapi` — [Exa](https://exa.ai/) | Neural search built for AI tools | $10 credit every month, no card | `search_type: auto` costs about $7 per 1,000. Strong for research-style queries, weaker for navigational ones. |
| `marginalia` — [Marginalia](https://marginalia-search.com/) | Independent index of the small, non-commercial web | Free key on request | Great as a bang (`!mar`), not as a default engine. |
| `kagi` (custom engine template) | Kagi's search API | Paid (≈ $12 per 1,000) | Add via Configure → Custom engines → *Kagi Search API*. |

A practical setup: keep your scraping engines as they are, and add **Brave Search API as a private engine**.
Give it a weight of about 1.5 (Engines → braveapi → Weight) so its independent index acts as a tie-breaker
against the Google- and Bing-backed engines. Your own searches then always have at least one source that
can't be blocked, for $0.
