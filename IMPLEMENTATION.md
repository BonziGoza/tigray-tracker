# Tigray OSINT Tracker — Social Media Implementation

## What this branch adds

- Optional Reddit collection through Reddit's authorized API.
- Optional X collection through X's recent-search API.
- A common source schema for news and social material.
- Gemini event extraction that explicitly treats social posts as reports/claims, not proof.
- Deterministic evidence grading: CLAIM, DEVELOPING, REPORTED, CORROBORATED, CONFIRMED.
- Social/news filters on the website.
- Social event count and Early Reports panel.
- A real scheduled GitHub Actions workflow.
- API credentials are read from GitHub Actions Secrets, never from the public page.

## Important Telegram decision

Telegram is intentionally NOT connected to the Gemini pipeline in this version. Telegram's current API terms prohibit using, accessing, or aggregating data obtained from Telegram for AI/ML development or deployment. A future Telegram integration should therefore be designed separately and reviewed against the current terms before implementation.

## Step 1 — Keep the branch

This work is on the social-osint-v2 branch. Review it before merging into main.

## Step 2 — Verify Gemini

The existing collector needs the GEMINI_API_KEY secret.

In GitHub:
Settings -> Secrets and variables -> Actions -> New repository secret

Do not put this key in index.html or any committed file.

## Step 3 — Configure X

Create or verify an approved X developer project and app with access to recent post search.

Add this GitHub Actions secret:

X_BEARER_TOKEN

The collector calls the X recent-search endpoint and limits itself to recent, non-retweet English posts matching Tigray/Ethiopia queries.

## Step 4 — Configure Reddit

Reddit's public API is currently transitioning toward the Reddit Developer Platform. If you use the Data API, register the app and follow Reddit's current migration requirements.

Add these Actions secrets:

REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET

Optional Actions variable:

REDDIT_USER_AGENT

Suggested value:

TigrayOSINTTracker/1.0 by BonziGoza

If the Reddit credentials are absent, the collector simply skips Reddit and continues.

## Step 5 — Test the workflow manually

Open:

Actions -> Update Tigray OSINT Tracker -> Run workflow

Check the logs for:

- items gathered
- news count
- social count
- candidate events
- events saved

The first run may have zero social items if credentials are not configured.

## Step 6 — Inspect data/events.json

Social sources now contain fields such as:

- source_type: social
- platform: x or reddit
- author
- published
- outlet
- url

Existing manually curated events remain protected by manual: true.

## Step 7 — Check the website

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

The tracker intentionally separates AI interpretation from evidence grading.

Gemini:
- identifies candidate events
- merges reports about the same event
- extracts location/date/type
- preserves attribution

Python:
- calculates the evidence grade

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

## Step 9 — Do not expose secrets

Never commit:

- X bearer tokens
- Reddit client secrets
- Gemini API keys
- OAuth refresh tokens
- Telegram API credentials

Use GitHub Actions Secrets.

## Operating principle

The tracker should answer:

"What is being reported, by whom, when, and how well is it corroborated?"

It should not claim:

"This social-media post proves this happened."

That distinction is central to making the project a credible OSINT research tool.
