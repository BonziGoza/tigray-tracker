# Tigray OSINT Tracker — Free OSINT Implementation

## What this branch adds

- Optional Reddit collection through Reddit's authorized API.
- A common source schema for news and social material.
- Deterministic evidence grading: CLAIM, DEVELOPING, REPORTED, CORROBORATED, CONFIRMED.
- Social/news filters on the website.
- Social event count and Early Reports panel.
- A real scheduled GitHub Actions workflow.
- API credentials are read from GitHub Actions Secrets, never from the public page.

## Important Telegram decision

Telegram is intentionally NOT connected to the Gemini pipeline in this version. Telegram's current API terms prohibit using, accessing, or aggregating data obtained from Telegram for AI/ML development or deployment. A future Telegram integration should therefore be designed separately and reviewed against the current terms before implementation.

## Step 1 — Keep the branch

This work is on the social-osint-v2 branch. Review it before merging into main.

## Step 2 — Configure Reddit

Reddit's public API is currently transitioning toward the Reddit Developer Platform. If you use the Data API, register the app and follow Reddit's current migration requirements.

Add these Actions secrets:

REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET

Optional Actions variable:

REDDIT_USER_AGENT

Suggested value:

TigrayOSINTTracker/1.0 by BonziGoza

If the Reddit credentials are absent, the collector simply skips Reddit and continues.

## Step 3 — Test the workflow manually

Open:

Actions -> Update Tigray OSINT Tracker -> Run workflow

Check the logs for:

- items gathered
- news count
- social count
- candidate events
- events saved

The first run may have zero social items if credentials are not configured.

## Step 4 — Inspect data/events.json

Social sources now contain fields such as:

- source_type: social
- platform: x or reddit
- author
- published
- outlet
- url

Existing manually curated events remain protected by manual: true.

## Step 5 — Check the website

The website now has:

- evidence-grade filters
- NEWS/SOCIAL filters
- total event count
- social event count
- early-report count
- evidence score
- source platform labels
- an Early Reports panel

## Evidence grading

The tracker now uses deterministic Python rules rather than a paid AI API. Each source is retained with its platform metadata, and the collector assigns an evidence grade from the available source mix.

Current ladder:

CLAIM — one source or one social report.

DEVELOPING — multiple sources/social reports without sufficient independent corroboration.

REPORTED — multiple news outlets.

CORROBORATED — at least one professional news source plus social reporting, where the event is not merely a party claim.

CONFIRMED — at least two recognized professional news sources and independent attribution.

These labels are automated research assessments, not guarantees that an event occurred.

## Important limitation: repost cascades

Five social accounts can all repeat one original claim.

Therefore:

5 posts != 5 independent sources

The next major backend improvement should detect:

- repost/quote relationships
- identical or near-identical text
- shared original URLs
- identical media
- common first-source claims

This should become an independent-source calculation before using social counts in a stronger evidence grade.

## Step 8 — Recommended next development

1. Add a configurable source allowlist for known organizations and accounts.
2. Add first_reported_at to every event.
3. Add source-to-event relationship IDs.
4. Add repost/cascade detection.
5. Add separate confidence for geolocation.
6. Add a human-review queue.
7. Add image/video verification metadata.
8. Preserve raw source metadata according to platform terms and an explicit retention policy.
9. Add a database when JSON becomes too large.
10. Add additional humanitarian and official sources.

## Step 8 — Do not expose secrets

Never commit:

- Reddit client secrets
- OAuth refresh tokens
- Telegram API credentials

There are currently no paid API keys required by the collector.

Use GitHub Actions Secrets.

## Operating principle

The tracker should answer:

"What is being reported, by whom, when, and how well is it corroborated?"

It should not claim:

"This social-media post proves this happened."

That distinction is central to making the project a credible OSINT research tool.
