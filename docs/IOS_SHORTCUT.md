# Auto-sync Apple Health → HealthOS (iOS Shortcuts)

HealthOS has an ingest API that accepts health metrics from anywhere — iOS Shortcuts can read
Apple Health and push to it on a schedule. Two minutes of setup, then steps/weight/water sync
themselves.

## 0. Get your ingest token

1. Open HealthOS → **Settings → Devices & import**
2. Copy the **ingest token** (it's shown once per generation — rotate if it leaks)

The ingest endpoint is:

```
POST <your-healthos-url>/api/v1/integrations/ingest
Authorization: Bearer <token>
Content-Type: application/json
```

Accepted metrics: `steps`, `weight`, `water_ml`, `sleep_minutes`, `active_calories`, `heart_rate`.
`external_id` makes re-runs idempotent (same ID = counted as duplicate, never double-logged).

> If you run HealthOS on your Mac and your iPhone is on the same network, your URL is
> `http://<mac-ip>:3000`. For anywhere-sync, put it behind Tailscale or a tunnel —
> the token is the only secret, treat the URL as private too.

## 1. Shortcut: today's steps (runs every evening)

Create a new Shortcut called **"HealthOS: Steps"**:

1. **Find Health Samples**
   - Type: `Steps`
   - Start Date: `Today` (start of day) · End Date: `Today` (end of day)
2. **Calculate Statistics of Health Samples** → Operation: `Sum`
3. **Get text from** — build the JSON body. Add a **Text** action containing:
   ```
   {"source":"apple_health","events":[{"metric":"steps","value":<Sum>,"observed_at":"<Current Date ISO8601>","external_id":"steps-<Current Date yyyy-MM-dd>"}]}
   ```
   Insert variables via the variable picker: `Statistics` result for `<Sum>`,
   `Current Date` (formatted ISO 8601) for `observed_at`, and `Current Date`
   (custom format `yyyy-MM-dd`) for the external_id.
4. **Get Contents of URL**
   - URL: `http://<host>/api/v1/integrations/ingest`
   - Method: `POST`
   - Headers: `Authorization` = `Bearer <token>`, `Content-Type` = `application/json`
   - Request Body: Text → the Text action from step 3
5. (optional) **Show Notification** — "Steps synced ✓" if the response contains `"accepted"`

**Automate it:** Shortcuts → Automation → New Automation → **Time of Day** 21:45, Repeat Daily →
choose this shortcut → set to **Run Immediately** (no confirmation).

## 2. Shortcut: morning weight

**"HealthOS: Weight"**:

1. **Find Health Samples** — Type: `Weight`, Sort by: `End Date` (latest first), Limit: `1`
2. **Get Details of Health Samples** — Detail: `Value`
3. **Text** body:
   ```
   {"source":"apple_health","events":[{"metric":"weight","value":<Value>,"unit":"kg","observed_at":"<ISO time>","external_id":"weight-<yyyy-MM-dd>"}]}
   ```
4. **Get Contents of URL** — same as above.

Automate it ~30 min after you usually weigh in, or add it to your morning routine automation.
Weight mirrors into **Measurements** (source `device`) and flows into your weight trend chart.
Manual weigh-ins logged in the app take precedence in your history (source priority:
manual > device > estimate).

## 3. Shortcut: water (when you log water elsewhere)

Same pattern with `"metric":"water_ml","value":500` — mirrors into Water logs for the day.

## Notes

- **Duplicates are safe** — re-running a shortcut with the same `external_id` returns
  `{"accepted": 0, "duplicates": 1}` and changes nothing.
- **Check it worked:** Settings → Devices & import shows the last ingest time; Progress shows
  steps/weight within seconds.
- **Nothing leaves your network** — Shortcuts talks straight to your HealthOS instance; Apple
  Health data never touches a third party.
- If a sync fails, the shortcut can retry later freely — idempotency keys have you covered.
