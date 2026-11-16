# API and integrations

## REST API

Fieldnote has a REST API for reading and writing notes, notebooks and tags. API access is included with Plus and Team plans and is not available on Free. Create a personal access token under Settings, then Developer. Tokens are shown once, can be scoped to read-only or read-write, and can be revoked at any time.

## Rate limits

The API allows 120 requests per minute per token on Plus and 600 requests per minute per token on Team. When you exceed the limit the API returns HTTP 429 with a Retry-After header that says how many seconds to wait. Bulk endpoints accept up to 100 notes per request, which is the most efficient way to import large amounts of data.

## Webhooks

Team workspaces can register up to 20 webhooks that fire when notes are created, updated or deleted. Each delivery is signed with an HMAC-SHA256 signature in the X-Fieldnote-Signature header so your server can verify it came from Fieldnote. Failed deliveries are retried with exponential backoff for up to 24 hours.

## Integrations

Built-in integrations connect Fieldnote with Slack (share notes into channels and save messages as notes), Google Calendar (create meeting notes from events) and Zapier. Integrations are enabled under Settings, then Integrations. On Team plans, admins can restrict which integrations members are allowed to enable.
