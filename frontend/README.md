# RFQ Agent — Frontend

Single-file UI for the RFQ Intelligence Agent. No build step, no npm.

**Live backend:** https://rfq-agent-82y2.onrender.com

## What it does

1. Upload a ZIP of vendor quotation PDFs
2. Shows the ranking, scores and disqualification reasons
3. Renders the full comparison report
4. Human-in-the-loop: Approve / Select another / Hold / Reject
5. Downloads the Excel report

## Running it

Open `index.html` in a browser. That's it.

To point at a different backend without editing the file:

```
index.html?api=https://your-backend.onrender.com
```

## Deploying

Vercel serves this as a static site — no build command, no output directory.

## Known limitation

Paused reviews are held in the backend's memory, so they are lost if the
Render free instance sleeps (15 min idle) or restarts. The UI checks
`/api/rfq/status/<thread_id>` before submitting a decision and reports an
expired session rather than failing silently.
