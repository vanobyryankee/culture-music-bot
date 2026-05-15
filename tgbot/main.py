import json
import os
from datetime import datetime, timedelta

import pytz
import requests
from flask import Flask, jsonify, request
from google.oauth2 import service_account
from googleapiclient.discovery import build


app = Flask(__name__)

# --- SETTINGS ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "-5288639479")
CALENDAR_ID = "5fac25e58365d554f9eb1e1d0f8d6896cad2d57c4d17bc7de384d584ddf26256@group.calendar.google.com"
TIMEZONE = "Europe/Moscow"
WORK_START = "10:00"
WORK_END = "21:30"
ALLOWED_ORIGINS = {
    "https://culturemusic.ru",
    "https://www.culturemusic.ru",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}


# --- CORS ---
@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/webhook", methods=["OPTIONS"])
@app.route("/free-slots", methods=["OPTIONS"])
@app.route("/book", methods=["OPTIONS"])
def handle_options():
    return "", 200


# --- GOOGLE CALENDAR ---
def get_calendar_service():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        return None
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=creds)


def get_timezone():
    return pytz.timezone(TIMEZONE)


def api_error(status, error, message):
    return jsonify({"ok": False, "error": error, "message": message}), status


def parse_hours(value):
    if value in ("—", "вЂ”", "", None):
        return 1
    return max(1, int(float(str(value).replace(",", "."))))


def parse_booking_window(data):
    tz = get_timezone()
    date_str = str(data.get("date") or "").strip()
    time_str = str(data.get("time") or "").strip()
    hours = parse_hours(data.get("hours", "1"))
    if not date_str or not time_str:
        raise ValueError("missing date or time")

    separator = "—" if "—" in time_str else "-"
    start_text = time_str.split(separator, 1)[0].strip()
    dt_start = tz.localize(datetime.strptime(f"{date_str} {start_text}", "%Y-%m-%d %H:%M"))

    if separator in time_str:
        end_text = time_str.split(separator, 1)[1].strip()
        dt_end = tz.localize(datetime.strptime(f"{date_str} {end_text}", "%Y-%m-%d %H:%M"))
    else:
        dt_end = dt_start + timedelta(hours=hours)

    if dt_end <= dt_start:
        raise ValueError("end must be after start")
    return dt_start, dt_end, hours


def parse_event_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(get_timezone())


def time_ranges_overlap(new_start, new_end, existing_start, existing_end):
    return new_start < existing_end and new_end > existing_start


def list_calendar_events(service, start, end):
    result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return result.get("items", [])


def slot_is_taken(events, start, end):
    for event in events:
        try:
            event_start = parse_event_datetime(event["start"].get("dateTime", event["start"].get("date")))
            event_end = parse_event_datetime(event["end"].get("dateTime", event["end"].get("date")))
            if event_start and event_end and time_ranges_overlap(start, end, event_start, event_end):
                return True
        except Exception:
            continue
    return False


def validate_booking_payload(data):
    required = ("date", "time", "contact")
    if not data or any(not str(data.get(field) or "").strip() for field in required):
        raise ValueError("Не хватает даты, времени или контакта.")


def build_calendar_event(data, start, end, hours):
    service_name = data.get("service", "Услуга не указана")
    client_name = data.get("name", "—")
    contact_type = data.get("contact_type", "")
    contact = data.get("contact", "—")
    source = data.get("source", "website")
    return {
        "summary": f"🎙 {client_name} — {service_name}",
        "description": (
            f"Источник: {source}\n"
            f"Клиент: {client_name}\n"
            f"Услуга: {service_name}\n"
            f"Способ связи: {contact_type}\n"
            f"Контакт: {contact}\n"
            f"Кол-во часов: {hours}\n"
            f"Дата: {data.get('date', '')}\n"
            f"Время: {data.get('time', '')}"
        ),
        "start": {"dateTime": start.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": TIMEZONE},
        "colorId": "1",
    }


def format_telegram_message(data):
    name = data.get("name", "—")
    service_name = data.get("service", "—")
    date = data.get("date", "—")
    time = data.get("time", "—")
    hours = data.get("hours", "—")
    contact_type = data.get("contact_type", "—")
    contact = data.get("contact", "—")
    source = data.get("source", "website")
    try:
        date_fmt = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        date_fmt = date
    return (
        f"🎙 <b>Новая заявка — Culture Music</b>\n\n"
        f"👤 <b>Имя:</b> {name}\n"
        f"📋 <b>Услуга:</b> {service_name}\n"
        f"📅 <b>Дата:</b> {date_fmt}\n"
        f"🕐 <b>Время:</b> {time}\n"
        f"⏱ <b>Часов:</b> {hours}\n"
        f"Источник: {source}\n\n"
        f"💬 <b>{contact_type}:</b> {contact}"
    )


# --- TELEGRAM ---
def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
        return response.ok
    except Exception as exc:
        print(f"Telegram error: {exc}")
        return False


def handle_booking(data, notify=True):
    validate_booking_payload(data)
    start, end, hours = parse_booking_window(data)
    service = get_calendar_service()
    if not service:
        raise RuntimeError("No Google credentials")

    events = list_calendar_events(service, start, end)
    if slot_is_taken(events, start, end):
        return {"taken": True}

    event = build_calendar_event(data, start, end, hours)
    created = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
    if notify:
        send_telegram(format_telegram_message(data))
    print(f"Calendar event created: {created.get('htmlLink')}")
    return {"taken": False, "booking_id": created.get("id", "")}


# --- CREATE EVENT ---
def create_calendar_event(data):
    try:
        result = handle_booking(data, notify=False)
        return not result.get("taken")
    except Exception as exc:
        print(f"Calendar error: {exc}")
        return False


# --- FREE SLOTS ---
@app.route("/free-slots", methods=["GET"])
def free_slots():
    try:
        date_str = request.args.get("date")
        if not date_str:
            return jsonify({"error": "date required"}), 400

        tz = get_timezone()
        day_start = tz.localize(datetime.strptime(f"{date_str} {WORK_START}", "%Y-%m-%d %H:%M"))
        day_end = tz.localize(datetime.strptime(f"{date_str} {WORK_END}", "%Y-%m-%d %H:%M"))
        now = datetime.now(tz)

        all_slots = []
        current = day_start
        while current < day_end:
            all_slots.append(current)
            current += timedelta(minutes=30)

        calendar_service = get_calendar_service()
        events = []
        if calendar_service:
            events = list_calendar_events(calendar_service, day_start, day_end)

        slots = []
        for slot_start in all_slots:
            slot_end = slot_start + timedelta(minutes=30)
            slots.append({
                "time": slot_start.strftime("%H:%M"),
                "free": not slot_is_taken(events, slot_start, slot_end) and slot_start >= now,
            })

        return jsonify({"date": date_str, "slots": slots})

    except Exception as exc:
        print(f"Free slots error: {exc}")
        return jsonify({"error": str(exc)}), 500


# --- BOOKING API ---
@app.route("/book", methods=["POST"])
def book():
    try:
        data = request.get_json(force=True)
        result = handle_booking(data)
        if result.get("taken"):
            return api_error(409, "slot_taken", "Это время уже занято. Выберите другой слот.")
        return jsonify({"ok": True, "booking_id": result.get("booking_id", ""), "message": "Бронь создана"}), 200
    except ValueError:
        return api_error(400, "bad_request", "Не хватает даты, времени или контакта.")
    except Exception as exc:
        print(f"Book error: {exc}")
        return api_error(500, "server_error", "Не удалось создать бронь. Попробуйте позже.")


# --- WEBHOOK ---
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        print(f"Received: {data}")
        result = handle_booking(data)
        if result.get("taken"):
            return api_error(409, "slot_taken", "Это время уже занято. Выберите другой слот.")
        return jsonify({"ok": True, "telegram": True, "calendar": True, "booking_id": result.get("booking_id", "")}), 200
    except ValueError:
        return api_error(400, "bad_request", "Не хватает даты, времени или контакта.")
    except Exception as exc:
        print(f"Webhook error: {exc}")
        return api_error(500, "server_error", "Не удалось создать бронь. Попробуйте позже.")


# --- HEALTH ---
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Culture Music Bot"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
