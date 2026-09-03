# Jellyfin Media Auditor

Local Ubuntu service which discovers movies through Jellyfin, audits per-stream audio languages (via metadata and faster-whisper AI sampling), maintains controlled Jellyfin **Tags** (`CZ Audio`, `EN Audio`, `OTHER Audio`), and automatically downloads and synchronizes sidecar subtitles. SQLite is the authoritative state store; Jellyfin is the inventory source and projection target.

---

## Controlled Audio Tags

The auditor strictly manages three application-controlled Jellyfin Tags:
- `CZ Audio` — Assigned if movie contains at least one Czech audio stream (`cs`).
- `EN Audio` — Assigned if movie contains at least one English audio stream (`en`).
- `OTHER Audio` — Assigned if movie contains at least one confidently identified audio stream in any language other than Czech or English.

> [!IMPORTANT]
> The system **only** modifies these three controlled tags. All other user-defined tags (e.g., `Action`, `Drama`, `Favourite`) or provider keywords are preserved intact. No Jellyfin Collections are used.

---

## Configuration & Environment Variables

Create `.env` in the working directory (or `/etc/jellyfin-media-auditor/env`):

```bash
# /opt/foxfinauto/.env
JELLYFIN_API_KEY="your-jellyfin-api-key"
JELLYFIN_WEBHOOK_TOKEN="secret-auditor-webhook-token"

# Optional OpenSubtitles credentials (if subtitles automation is enabled)
OPENSUBTITLES_API_KEY=""
OPENSUBTITLES_USERNAME=""
OPENSUBTITLES_PASSWORD=""
```

`config.yaml` manages local runtime settings:

```yaml
jellyfin:
  url: "http://192.168.1.2:1234"
  api_key: "${JELLYFIN_API_KEY}"
  user_id: "{USER_ID}"
  webhook_token: "${JELLYFIN_WEBHOOK_TOKEN}"
media:
  jellyfin_root: "/foxfin/movies"
  worker_root: "/foxfin/movies"
libraries:
  - name: "Movies"
    jellyfin_id: "{ID}"
scanner:
  interval_minutes: 60
  worker_poll_seconds: 5
  max_attempts: 5
audio_detection:
  confidence_threshold: 0.75
  initial_sample_count: 3
  fallback_sample_count: 6
  sample_duration_seconds: 30
subtitles:
  enabled: false
```

---

## Running Locally & Testing

1. **Run Unit Tests**:
   ```bash
   PYTHONPATH=. .venv/bin/pytest
   ```

2. **Run Worker & Webhook API Server**:
   ```bash
   AUDITOR_CONFIG=config.yaml .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8787
   ```

3. **Run Streamlit Dashboard UI**:
   ```bash
   AUDITOR_CONFIG=config.yaml .venv/bin/streamlit run ui/dashboard.py --server.address 0.0.0.0 --server.port 8501
   ```

4. **Run one controlled subtitle test** (does not enable the global subtitle worker setting):
   ```bash
   AUDITOR_CONFIG=config.yaml .venv/bin/python -m app.subtitle_test --item-id <JELLYFIN_ITEM_ID>
   ```
   This command may download subtitles for only the specified movie. Verify the `.cs.srt` / `.en.srt` sidecars, Jellyfin refresh, and dashboard status before setting `subtitles.enabled: true`.

---

## Daemon & Webhook Setup

### Systemd Services

Systemd unit files are located in `systemd/`:
- `jellyfin-media-auditor.service` (Worker and FastAPI Webhook on port 8787)
- `jellyfin-media-auditor-ui.service` (Streamlit UI Dashboard on port 8501)

To install and start:

```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jellyfin-media-auditor jellyfin-media-auditor-ui
```

Check status and logs:
```bash
sudo systemctl status jellyfin-media-auditor jellyfin-media-auditor-ui
sudo journalctl -u jellyfin-media-auditor -f
```

---

## Jellyfin Webhook Integration

To process newly added movies instantly:

1. Open Jellyfin Server Dashboard -> **Plugins** -> **Webhook**.
2. Add a new Webhook destination:
   - **Webhook URL**: `http://<your-server-ip>:8787/webhook/jellyfin`
   - **HTTP Header**: `X-Auditor-Token: secret-auditor-webhook-token` (matching `JELLYFIN_WEBHOOK_TOKEN` in `.env`)
   - **Notification Type**: Enable `ItemAdded`.
   - **Item Type**: Enable `Movie`.
3. Save the webhook rule.

When Jellyfin adds a new movie, the webhook receives the item ID and enqueues it for immediate processing.

---

## Streamlit UI Features

Access the dashboard at `http://<your-server-ip>:8501`:
- **Overview Metrics**: Total movies, queued, processing, processed, unsure, errors, and audio tag breakdowns (`CZ Audio`, `EN Audio`, `OTHER Audio`).
- **Filterable Movie List**: Filter by library name or processing status.
- **Movie Inspector**: View stream breakdown (codec, channels, metadata language, detected language, confidence score, detection method).
- **Manual Overrides**: Assign custom language overrides per audio stream if needed.
- **Reprocessing & Manual Queue**: Trigger re-audits or queue movies by Jellyfin item ID directly.
