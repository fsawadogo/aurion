# Gemini Vision-Clip Probe

**Endpoint:** `POST /api/v1/admin/probe/vision-clip`

A synchronous, admin-only diagnostic that exercises the configured
`vision_clip` provider end-to-end (default Gemini 2.5 Pro) against a
small operator-supplied MP4. Use it to verify a real provider round
trip — auth, transport, prompt boundary, response parsing — without
running a full clinical session.

---

## When to use it

* **Before any new `vision_clip` provider configuration change.** Run
  the probe against the new config; if it returns 200 with
  `success=true`, you can flip the AppConfig key with confidence.
* **Before the eval team kicks off a Phase 2 clip-mode run.** A 5 KB
  probe verifies the full path is working without burning a real
  session on a misconfigured key.
* **After a dev secret rotation.** Confirms `GOOGLE_AI_API_KEY` (or
  the OpenAI/Anthropic equivalent if `vision_clip` is set to a
  fallback) reached the container's environment.
* **As a CI smoke step** (manual trigger) after each `vision_clip`
  provider PR.

---

## What it does

1. Accepts an MP4 multipart upload (≤ 5 MB).
2. Writes the bytes to S3 under `probe/<probe_id>.mp4` so the
   provider's `get_object` path is exercised end-to-end.
3. Resolves the provider through the SAME registry call that Stage 2
   dispatch uses (`get_vision_provider_for_kind("clip", …)`).
4. Times the provider's `caption_clip` invocation with a wall-clock
   timer.
5. **Always** deletes the temp S3 object in a finally-block.
6. Emits a `vision_clip_probed` audit event (success or failure).
7. Returns a structured diagnostic. **Never re-raises** — even auth
   failures come back as a 200 with `success=false`.

---

## What it does NOT do

* Persist the clip beyond the provider call.
* Persist the caption.
* Create or touch any session row.
* Run the descriptive-mode prompt the eval team is comparing — it
  uses the same prompt as a real call, but the test card has no
  clinical content so the model's output is meaningless beyond
  "the path works".

---

## Invocation

### Local (LocalStack)

LocalStack S3 works for the put/delete; the provider call itself
**will fail** because dev shells typically don't carry a real
`GOOGLE_AI_API_KEY`. The probe surfaces that as
`error_type=ProviderError, error_message=~"GOOGLE_AI_API_KEY not
configured"`. Use this invocation to verify the route + auth + S3
+ audit path:

```bash
curl -X POST http://localhost:8080/api/v1/admin/probe/vision-clip \
  -H "Authorization: Bearer ADMIN:$(uuidgen)" \
  -F clip=@backend/tests/fixtures/probe_clip.mp4 \
  | jq '.'
```

### Dev cloud (real Gemini)

The dev cluster has `GOOGLE_AI_API_KEY` in Secrets Manager. This
invocation runs end-to-end against real Gemini:

```bash
curl -X POST https://api.dev.aurionclinical.com/api/v1/admin/probe/vision-clip \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -F clip=@backend/tests/fixtures/probe_clip.mp4 \
  | jq '.'
```

`$ADMIN_JWT` is a Cognito access token for a user with the ADMIN
group. Pull one from the web portal's session storage, or mint one
via the Cognito hosted UI.

### Probing a fallback provider

To exercise the OpenAI midpoint-still path (P1-2) without flipping
the live AppConfig:

```bash
curl -X POST http://localhost:8080/api/v1/admin/probe/vision-clip \
  -H "Authorization: Bearer ADMIN:$(uuidgen)" \
  -F provider_override=openai \
  -F clip=@backend/tests/fixtures/probe_clip.mp4 \
  | jq '.'
```

Valid `provider_override` values are the `VisionProviderKey` enum
values: `gemini`, `openai`, `anthropic`.

---

## Reading the response

```json
{
  "probe_id": "a1b2c3d4e5f6...",
  "provider_used": "gemini",
  "model_id": "gemini-2.5-pro",
  "latency_ms": 1842,
  "success": true,
  "caption": {
    "frame_id": "probe_seg_a1b2c3d4_clip",
    "session_id": "00000000-0000-0000-0000-000000000000",
    "timestamp_ms": 1000,
    "audio_anchor_id": "probe_seg_a1b2c3d4",
    "provider_used": "gemini",
    "visual_description": "A solid blue test pattern...",
    "confidence": "low",
    "confidence_reason": "No clinically relevant content visible.",
    "integration_status": "ENRICHES",
    "evidence_kind": "clip",
    "duration_ms": 2000,
    "degraded_to_frame": false
  },
  "error_type": null,
  "error_message": null,
  "raw_response_excerpt": null,
  "clip_metadata": {
    "size_bytes": 5033,
    "duration_ms": 0,
    "content_type": "video/mp4"
  }
}
```

### Success fields

| Field | Meaning |
|---|---|
| `success: true` | Provider returned a valid `FrameCaption`. |
| `caption.confidence: "low"` | Expected for the test fixture (no clinical content). |
| `caption.evidence_kind: "clip"` | Native video understanding worked. |
| `caption.degraded_to_frame: false` | Provider accepted the clip natively (Gemini). `true` means a still was extracted from the midpoint (OpenAI/Anthropic fallback path). |
| `latency_ms` | Wall-clock around the provider call. Gemini production targets ~2–4 s for a 2-s clip; flag if > 8 s. |
| `model_id` | The model constant from the provider implementation. |

### Failure types

| `error_type` | Likely cause | Action |
|---|---|---|
| `ProviderError` + message containing `"not configured"` | `GOOGLE_AI_API_KEY` missing in Secrets Manager or container env | Verify the secret is set; redeploy the dev service. |
| `ProviderError` + message containing `"401"` / `"403"` / `"authentication"` | Key is set but invalid or rotated | Rotate the key, push to Secrets Manager, force a deployment to pick up the new value. |
| `ProviderError` + message containing `"429"` / `"quota"` | Rate-limit / quota exhausted | Wait, or bump the dev project's quota in Google Cloud Console. |
| `ProviderError` + message containing `"shape"` / `"key"` / `"missing"` | SDK / API response shape changed under us | Check the Gemini changelog. The provider impl needs an update. |
| `S3UploadError` | Dev S3 / LocalStack misconfigured | Check the `FRAMES_BUCKET` env var; check the IAM role's KMS perms. |
| `TimeoutError` | Provider call exceeded the 120-s `httpx` budget in the Gemini impl | Network issue, or Gemini is degraded. Retry. |

`error_message` is **scrubbed of API keys** before it crosses the
wire — `AIza…`, `sk-…`, `sk-ant-…`, `AKIA…`, `?key=…`, and `Bearer
…` patterns are replaced with `***REDACTED***`.

---

## Cost

Each probe call against Gemini 2.5 Pro on a 2-s clip costs
approximately **$0.01 USD**. Probe liberally during dev rollout;
don't bake the probe into a high-frequency cron without rate
limiting.

---

## Audit trail

Every probe call emits a single `vision_clip_probed` row to
DynamoDB with:

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "event_type": "vision_clip_probed",
  "provider": "gemini",
  "success": true,
  "latency_ms": 1842
}
```

Failures additionally carry `"error_type"`. The synthetic session id
keeps probe rows out of any real session's history; query the audit
table for `event_type=vision_clip_probed` to see all historical
probes.

---

## Regenerating the fixture clip

See `backend/tests/fixtures/README.md`. The recipe is:

```bash
ffmpeg -f lavfi -i "color=c=blue:s=320x240:d=2" \
       -c:v libx264 -pix_fmt yuv420p -tune zerolatency \
       -an -y backend/tests/fixtures/probe_clip.mp4
```

The committed fixture is ~5 KB, 2.0 s, H.264, no audio.
