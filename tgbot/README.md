# Culture Music Bot API

Backend handles Culture Music bookings for the website and future Telegram AI bot.

## GET /free-slots

Returns 30-minute availability for a date.

Example:

```http
GET /free-slots?date=2026-05-20
```

Response:

```json
{
  "date": "2026-05-20",
  "slots": [
    { "time": "18:00", "free": true }
  ]
}
```

## POST /book

Creates a booking after re-checking Google Calendar for conflicts.

Example payload for the Telegram AI bot:

```json
{
  "service": "Запись вокала — 1 400 ₽",
  "name": "Иван",
  "date": "2026-05-20",
  "time": "18:00 — 19:00",
  "hours": "1",
  "contact_type": "Telegram",
  "contact": "@username",
  "source": "telegram_ai_bot"
}
```

Successful response:

```json
{
  "ok": true,
  "booking_id": "google-calendar-event-id",
  "message": "Бронь создана"
}
```

If the slot is already taken, the API returns HTTP 409:

```json
{
  "ok": false,
  "error": "slot_taken",
  "message": "Это время уже занято. Выберите другой слот."
}
```

## POST /webhook

Backward-compatible website endpoint. It uses the same internal booking logic as
`POST /book`, including the final calendar conflict check before event creation.

The frontend can keep using `/webhook`; future clients should prefer `/book`.
