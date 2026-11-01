# Model Prices (API)

Compiled 2026-09-27. Prices are official API list prices in USD per 1M tokens. Input price = plain (uncached) input. Where a vendor publishes peak/off-peak tiers, the lowest published tier (off-peak) is listed with the peak rate in parentheses. Verification status of each row is given in the notes below.

| model id | release date | $ in/1M | $ out/1M | context window | reasoning_effort support | source URL |
|---|---|---|---|---|---|---|
| `deepseek-flash` (DeepSeek-V4.1-Flash) | 2026-09-10 | $0.15 (off-peak; $0.30 peak) | $0.60 (off-peak; $1.20 peak) | 1M (max output 384K) | Yes — `reasoning_effort` (low/high/max) in thinking mode (default); non-thinking mode supported | https://api-docs.deepseek.com/quick_start/pricing/ |
| `deepseek-v4-pro` (DeepSeek-V4-Pro-0813) | 2026-04-24 (GA update 2026-08-13) | $0.66 (off-peak; $1.32 peak) | $1.98 (off-peak; $3.96 peak) | 1M (max output 384K) | Yes — `reasoning_effort` (low/high/max) in thinking mode (default); non-thinking mode supported | https://api-docs.deepseek.com/quick_start/pricing/ |
| `gemini-3.8-flash` | 2026-09-02 | $0.75 (introductory through 2026-12-31; $1.50 from 2027-01-01) | $3.75 (introductory; $7.50 from 2027-01-01) | 1M (output limit ~65.5K) | Yes — `thinking_level` low/medium/high (not named `reasoning_effort`) | https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/ |
| `grok-4.7` | 2026-09-21 | $2.00 (<200K-token prompts; $4.00 at ≥200K, applied to whole request) | $6.00 (<200K; $12.00 at ≥200K) | 500K | Yes — `reasoning_effort` low/medium/high/xhigh (default high; reasoning cannot be disabled) | https://docs.x.ai/docs/models/grok-4.7 |
| `gpt-5.6` (alias → `gpt-5.6-sol`) | 2026-07-09 | $5.00 (promotional $4.00 through at least 2026-11-21) | $30.00 (promotional $20.00) | 1.05M (max output 128K) | Yes — `reasoning_effort` low/medium/high/xhigh/max (`none` default) | https://developers.openai.com/api/docs/models/gpt-5.6-sol |
| `gpt-6-astra` | 2026-09-03 (announced; general API availability 2026-09-04) | $10.00 (long-context >272K input: $20.00) | $50.00 (long-context: $75.00) | 1.05M (max input 922K; max output 128K) | Yes — `reasoning_effort` low/medium/high/xhigh/max | https://developers.openai.com/api/docs/models/gpt-6-astra |

## Verification notes

- **DeepSeek (both models): VERIFIED against vendor pages fetched directly** on 2026-09-27. Pricing from https://api-docs.deepseek.com/quick_start/pricing/ (the page lists `deepseek-flash` as the model name for DeepSeek-V4.1-Flash and `deepseek-v4-pro` for DeepSeek-V4-Pro-0813). Peak hours: 01:00–04:00 and 06:00–10:00 UTC, Mon–Fri, excluding Chinese public holidays; off-peak = 50% of peak. Cached-input prices (not in table): V4.1-Flash $0.003 off-peak/$0.006 peak; V4-Pro $0.022/$0.044. Release dates from the official change log: https://api-docs.deepseek.com/updates (entries 2026-09-10 "DeepSeek-V4.1-Flash Release" and 2026-04-24 "DeepSeek-V4 … API now supports V4-Pro and V4-Flash"; 2026-08-13 "DeepSeek-V4-Pro Update" GA). `reasoning_effort` confirmed in the official Thinking Mode guide: https://api-docs.deepseek.com/guides/thinking_mode.
- **Gemini 3.8 Flash: VERIFIED against vendor blog** (fetched directly; article published_time meta = 2026-09-02T15:00Z). Prices quoted in the official Google blog post; cached-input price ($0.075/1M) and `thinking_level` (low/medium/high) are from the official ai.google.dev pricing/model docs (page not reachable from this network; content verified via search-engine snippets of ai.google.dev/gemini-api/docs/pricing).
- **Grok 4.7: NOT directly verified from a vendor page.** docs.x.ai and x.ai are network-blocked from the research environment. The prices, release date, context window, and reasoning_effort levels are cross-confirmed by multiple third-party sources (llm-stats.com, TechRepublic, Modellix, OrcaRouter, Eesel) that cite the official model page https://docs.x.ai/docs/models/grok-4.7 and xAI's launch announcement. Treat as best available; re-verify against docs.x.ai when reachable.
- **GPT-5.6: pricing from the official OpenAI pricing page** (developers.openai.com/api/docs/pricing) and model page (gpt-5.6-sol), obtained via search-engine snippets because developers.openai.com returns HTTP 403 to direct fetches. Standard list price $5.00/$30.00; a promotional price of $4.00/$20.00 is in effect through at least 2026-11-21 (both are published on the official pages). Release date 2026-07-09 per the official OpenAI Help Center model release notes (help.openai.com/articles/9624314-model-release-notes) and the API changelog. Long-context (>272K input): 2x input, 1.5x output.
- **GPT-6-Astra: from the official OpenAI model page** (developers.openai.com/api/docs/models/gpt-6-astra), obtained via search-engine snippets (direct fetch returns HTTP 403). Standard pricing $10.00/$50.00; cached input $1.00/1M; cache writes $12.50/1M; long-context (>272K input tokens) billed at 2x input and 1.5x output for the full request. Release date 2026-09-03 (announced to Daybreak-gated organizations), general API availability 2026-09-04.

## Source URLs (all)

1. DeepSeek pricing: https://api-docs.deepseek.com/quick_start/pricing/
2. DeepSeek change log: https://api-docs.deepseek.com/updates
3. DeepSeek Thinking Mode: https://api-docs.deepseek.com/guides/thinking_mode
4. Google announcement (Gemini 3.8 Flash): https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/
5. Google Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
6. xAI Grok 4.7 model page: https://docs.x.ai/docs/models/grok-4.7
7. OpenAI GPT-5.6 Sol model page: https://developers.openai.com/api/docs/models/gpt-5.6-sol
8. OpenAI pricing: https://developers.openai.com/api/docs/pricing
9. OpenAI GPT-6-Astra model page: https://developers.openai.com/api/docs/models/gpt-6-astra
10. OpenAI Help Center model release notes: https://help.openai.com/articles/9624314-model-release-notes

## Relay-verified prices (user dashboard, 2026-09-27)
- grok-4.7 stable route: /bin/bash.22 in / /bin/bash.66 out per 1M (award route /bin/bash.02//bin/bash.06 also exists; stable chosen for experiment reliability).
- gpt-5.6-sol / gpt-6-astra / gemini-3.8-flash relay prices: pending user confirmation.

- grok-4.7 route: award/stable routes are auto-switched by the platform; plain model id  works. Cost table uses stable prices.
