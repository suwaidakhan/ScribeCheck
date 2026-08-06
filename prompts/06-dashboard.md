# Prompt 06 — Dashboard

Precondition: `taxonomy/failure_taxonomy.csv` is fully labeled. Verify no empty failure_code or severity cells; if any exist, list the row_ids and stop.

Tasks:
1. Compute the taxonomy summary: S1 counts per provider and per tier, code distribution. Write `results/taxonomy_summary.csv`. Merge S1 rates into a final headline table.
2. I will design the layout in Google Stitch and give you a screenshot plus any exported code. Match that design. Until I provide it, build a clean provisional version so nothing blocks.
3. Build `dashboard/index.html`: one static file, all data inlined as JSON, no backend, no external calls except a CDN chart library if needed. Sections: headline table with S1 column, tier chart, severity chart, 5 annotated failure examples (text only, chosen from S1 rows), method note, license attribution line for AfriSpeech-200.
4. Test locally, then deploy to Vercel and give me the URL. Mobile check: readable on a phone-width viewport.
5. Commit.

Definition of done: live URL, loads under 2 seconds, headline table shows the S1 column, attribution present. Then stop.
