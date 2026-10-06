# Tigray OSINT Tracker — OSINT Implementation

## What this branch does

- Collects recent Tigray/northern Ethiopia reporting from Google News RSS, Al Jazeera RSS, and GDELT.
- Optionally collects recent Reddit posts through Reddit's authorized API.
- Sends the normalized source batch to Gemini when GEMINI_API_KEY is configured.
- Uses Gemini to identify distinct real-world events, merge reports describing the same event, extract date/place/type, and preserve source-item relationships.
- Uses deterministic Python rules for evidence grading; Gemini does not decide whether an event is confirmed.
- Falls back to deterministic local extraction if Gemini is unavailable or returns no usable events.
- Provides NEWS/SOCIAL and evidence-grade filters, an Early Reports panel, source links, and approximate map locations.
- Keeps API credentials in GitHub Actions Secrets; they are never sent to the browser.

## Gemini configuration

The workflow expects:

**Repository secret**
- GEMINI_API_KEY

**Optional repository variable**
- MODEL

If MODEL is not set, the collector defaults to `gemini-2.5-flash-lite`. You can change the repository variable later without editing Python.

The Gemini call uses the `generateContent` REST endpoint and requests JSON output. The API key is supplied to GitHub Actions only; it is never embedded in `index.html` or `data/events.json`.

Gemini is used for **organization and extraction**, not as the evidence authority. The source URLs and source metadata remain attached to every event.

## Reddit configuration

Add these Actions secrets if you want Reddit collection:

- REDDIT_CLIENT_ID
- REDDIT_CLIENT_SECRET

Optional Actions variable:

- REDDIT_USER_AGENT

Suggested value:

`TigrayOSINTTracker/1.0 by BonziGoza`

If Reddit credentials are absent, the collector skips Reddit and continues.

## X

X is intentionally **not connected** in this version. There is no X bearer token in the workflow and no X API dependency.

## Telegram

Telegram is intentionally not connected to the Gemini pipeline. A future Telegram integration should be separately reviewed against Telegram's current terms before implementation.

## How the pipeline works

```
Google News / Al Jazeera / GDELT
              +
           Reddit
              |
              v
      normalized source items
              |
              v
           Gemini
     event extraction + merging
              |
              v
     deterministic grading
              |
              v
       data/events.json
              |
              v
       public Leaflet map
```

Gemini receives numbered source items and must return the item numbers supporting each event. This lets the tracker preserve the underlying sources rather than replacing them with an AI-generated summary.

## Evidence grading

Current ladder:

**CLAIM** — one source or one social report.

**DEVELOPING** — multiple reports without sufficient independent corroboration.

**REPORTED** — multiple news outlets.

**CORROBORATED** — at least one recognized professional news source plus social reporting, when the event is not merely a party claim.

**CONFIRMED** — at least two recognized professional news sources and independent attribution.

Scores are currently 25 / 45 / 65 / 75 / 90.

These are automated research assessments, not guarantees that an event occurred.

## Important limitation: repost cascades

Five social accounts can repeat one original claim.

**5 posts != 5 independent sources**

The next backend improvement should detect:

- repost/quote relationships
- identical or near-identical text
- shared original URLs
- identical media
- common first-source claims

Until that exists, social-source counts should be treated cautiously.

## Manual workflow test

Open:

**Actions → Update Tigray OSINT Tracker → Run workflow**

Check the logs for:

- items gathered
- news count
- social count
- Gemini candidate events
- events saved

Then inspect `data/events.json`.

## Website behavior

The site currently displays:

- interactive map
- event list
- evidence-grade filters
- NEWS/SOCIAL filters
- total event count
- social-event count
- early-report count
- evidence score
- source platform labels
- links to underlying reports

Map positions are approximate.

## Retention and manual events

Automatic events are retained for 45 days based on `last_seen`.

Events marked `manual: true` are preserved and are not overwritten by the automated collector.

## Next improvements

1. Repost/cascade detection so repeated social posts do not inflate corroboration.
2. `first_reported_at` for each event.
3. Source-to-event relationship IDs.
4. Geolocation confidence.
5. Human-review queue.
6. Image/video verification metadata.
7. Configurable source/account allowlists.
8. Additional humanitarian and official sources.
9. Database storage once JSON becomes too large.

## Security

Never commit:

- Gemini API keys
- Reddit client secrets
- OAuth refresh tokens
- other provider credentials

Use GitHub Actions Secrets.

## Operating principle

The tracker should answer:

> What is being reported, by whom, when, and how well is it corroborated?

It should not answer:

> This social-media post proves this happened.
