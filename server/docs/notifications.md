# Gen4 robot notifications

Gen4 robots send `robots.notify` separately from ordinary status updates. This
includes messages about scheduled cleaning starts, off-base/low-battery failures,
localization failures and unreachable zones. Some routine-related messages are
intentionally absent from `state.show.errors`.

The server accepts these requests, saves the notification, and replies with the
original request ID, `code: 200` and an empty body. A successful response means
the notification is stored, not that a user has seen it. A database failure returns
500 without publishing an event.

## Robot protocol

For example, a robot request may contain:

```json
{
  "type": "request",
  "id": "example-request-id",
  "to": {"service": "robots.notify"},
  "body": {
    "message_code": "nav_floorplan_zone_unreachable",
    "payload": {"zone_name": "Kitchen"}
  }
}
```

The robot identity comes from its connection, never from the request body.
Request IDs and message codes must be non-blank strings of at most 128 characters.
An omitted or null payload is accepted; otherwise it must be a JSON object of at
most 16 KiB when encoded by the server's JSON encoder. Invalid input receives 400
(413 for an oversized payload). Unknown message codes and contextual payload
fields are retained so clients can handle newer firmware.

Retries with the same request ID from the same robot receive 200 without another
record or event, including concurrent retries. The same code under a new request
ID is a separate notification. Deduplication does not assume that matching codes
or text represent the same occurrence.

## Live events

Both `/api/events` and the originating robot's `/api/robot/<serial>/connect`
stream publish a **named** SSE event after the database commit:

```text
event: notification
data: {"id":1,"robot":"example-robot","message_code":"nav_floorplan_zone_unreachable","payload":{"zone_name":"Kitchen"},"received_at":"2026-10-18T12:00:00Z"}

```

Existing unnamed robot events and `event: robots` inventory updates are unchanged.
Browser clients opt in using `addEventListener('notification', ...)`. The event
data has the same shape as a history item. Notification IDs are globally unique,
monotonically increasing database integers; `received_at` is the server's UTC
receipt time, not a timestamp asserted by the robot. Concurrent deliveries can
arrive out of ID order.

SSE is best-effort: the existing bounded client queues can drop older frames, and
events are not replayed using `Last-Event-ID`. Clients listening to both streams
should deduplicate by notification ID. For reconnect recovery, subscribe and
buffer events first, then fetch history until a previously known ID is reached,
merging by ID. Fetching history periodically also recovers dropped frames.

## Notification history

`GET /api/robot/<serial>/notifications?limit=50&before=123`

```json
{
  "notifications": [
    {
      "id": 122,
      "robot": "example-robot",
      "message_code": "routine_cleaning_start_low_battery_error",
      "payload": null,
      "received_at": "2026-10-18T12:00:00Z"
    }
  ],
  "next_before": null
}
```

Results are newest-first and scoped to the requested robot. `limit` defaults to
50 and accepts 1–100. `before` is an exclusive, positive signed 64-bit ID cursor;
omit it for the newest page. When `next_before` is non-null, pass that value as
`before` for the next page. New arrivals do not shift already-paginated records.
Malformed or repeated pagination values receive 400; an unknown robot receives
404. Known robots with no history return an empty list. History is available even
when the robot is offline and survives server restarts. Records have no automatic
expiration or read/unread state in this version.

## Installation and validation

The Alembic revision `c84f7e239a10` follows `5fe01baecb7b` and adds the notification
table, request deduplication constraint and robot/history index. Use the normal
deployment migration step (`alembic upgrade head` from `server/`). Downgrading this
revision deletes notification history; robot, map and run tables are unchanged.

With the server dependencies installed, run from `server/`:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

The tests use synthetic requests, temporary SQLite databases and local sockets;
no robot is contacted. They exercise acknowledgement framing, persistence,
deduplication, SSE scoping, validation, failure handling, history pagination and
migration upgrade/downgrade.

This is the backend notification foundation. It does not add browser toasts,
mobile push delivery, or an iOS notification screen. `robots.error_codes` remains
an ordinary forwarded robot event; it is not converted into a second notification.
The existing `/api/log` endpoints continue to serve server logs.
