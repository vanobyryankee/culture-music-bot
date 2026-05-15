from __future__ import annotations

from datetime import datetime

import pytest

import main


class FakeEvents:
    def __init__(self, events=None):
        self.events = events or []
        self.inserted = []

    def list(self, **kwargs):
        self.last_list_kwargs = kwargs
        return self

    def insert(self, **kwargs):
        self.last_insert_kwargs = kwargs
        self.inserted.append(kwargs["body"])
        return self

    def execute(self):
        if self.inserted:
            return {"id": "evt_123", "htmlLink": "https://calendar.example/event"}
        return {"items": self.events}


class FakeCalendarService:
    def __init__(self, events=None):
        self._events = FakeEvents(events)

    def events(self):
        return self._events


@pytest.fixture()
def client(monkeypatch):
    main.app.config.update(TESTING=True)
    monkeypatch.setattr(main, "send_telegram", lambda text: True)
    return main.app.test_client()


def payload(**overrides):
    data = {
        "service": "Запись вокала — 1 400 ₽",
        "name": "Иван",
        "date": "2026-05-20",
        "time": "18:00 — 19:00",
        "hours": "1",
        "contact_type": "Telegram",
        "contact": "@username",
        "source": "website",
    }
    data.update(overrides)
    return data


def test_time_ranges_touching_edges_do_not_overlap():
    tz = main.get_timezone()
    existing_start = tz.localize(datetime(2026, 5, 20, 18, 0))
    existing_end = tz.localize(datetime(2026, 5, 20, 19, 0))
    new_start = tz.localize(datetime(2026, 5, 20, 19, 0))
    new_end = tz.localize(datetime(2026, 5, 20, 20, 0))

    assert not main.time_ranges_overlap(new_start, new_end, existing_start, existing_end)


def test_time_ranges_partial_overlap_conflicts():
    tz = main.get_timezone()
    existing_start = tz.localize(datetime(2026, 5, 20, 18, 0))
    existing_end = tz.localize(datetime(2026, 5, 20, 19, 0))
    new_start = tz.localize(datetime(2026, 5, 20, 18, 30))
    new_end = tz.localize(datetime(2026, 5, 20, 19, 30))

    assert main.time_ranges_overlap(new_start, new_end, existing_start, existing_end)


def test_book_creates_calendar_event_with_source(client, monkeypatch):
    fake_service = FakeCalendarService()
    monkeypatch.setattr(main, "get_calendar_service", lambda: fake_service)

    response = client.post("/book", json=payload(source="telegram_ai_bot"))

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert response.get_json()["booking_id"] == "evt_123"
    assert len(fake_service.events().inserted) == 1
    event = fake_service.events().inserted[0]
    assert "Источник: telegram_ai_bot" in event["description"]
    assert event["start"]["dateTime"].startswith("2026-05-20T18:00:00")
    assert event["end"]["dateTime"].startswith("2026-05-20T19:00:00")


def test_book_rejects_taken_slot(client, monkeypatch):
    busy_event = {
        "start": {"dateTime": "2026-05-20T18:30:00+03:00"},
        "end": {"dateTime": "2026-05-20T19:30:00+03:00"},
    }
    fake_service = FakeCalendarService([busy_event])
    monkeypatch.setattr(main, "get_calendar_service", lambda: fake_service)

    response = client.post("/book", json=payload())

    assert response.status_code == 409
    assert response.get_json()["error"] == "slot_taken"
    assert fake_service.events().inserted == []


def test_book_rejects_bad_request(client):
    response = client.post("/book", json=payload(contact=""))

    assert response.status_code == 400
    assert response.get_json()["error"] == "bad_request"


def test_webhook_uses_same_booking_logic(client, monkeypatch):
    fake_service = FakeCalendarService()
    monkeypatch.setattr(main, "get_calendar_service", lambda: fake_service)

    response = client.post("/webhook", json=payload())

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert len(fake_service.events().inserted) == 1
