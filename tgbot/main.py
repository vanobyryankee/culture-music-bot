import os
import json
import requests
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "-5288639479")
CALENDAR_ID = "5fac25e58365d554f9eb1e1d0f8d6896cad2d57c4d17bc7de384d584ddf26256@group.calendar.google.com"
TIMEZONE = "Europe/Moscow"

# --- TELEGRAM ---
def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.ok
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# --- GOOGLE CALENDAR ---
def create_calendar_event(data):
    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if not creds_json:
            print("No Google credentials")
            return False

        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        service = build("calendar", "v3", credentials=creds)

        # Парсим дату и время из заявки
        date_str = data.get("date", "")      # формат: YYYY-MM-DD
        time_str = data.get("time", "10:00") # формат: HH:MM
        hours = int(data.get("hours", "1") if data.get("hours", "1") != "—" else "1")

        tz = pytz.timezone(TIMEZONE)

        try:
            dt_start = tz.localize(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))
        except:
            dt_start = tz.localize(datetime.now().replace(second=0, microsecond=0))

        dt_end = dt_start + timedelta(hours=hours)

        service_name = data.get("service", "Услуга не указана")
        client_name = data.get("name", "—")
        contact_type = data.get("contact_type", "")
        contact = data.get("contact", "—")

        event = {
            "summary": f"🎙 {client_name} — {service_name}",
            "description": (
                f"Клиент: {client_name}\n"
                f"Услуга: {service_name}\n"
                f"Способ связи: {contact_type}\n"
                f"Контакт: {contact}\n"
                f"Кол-во часов: {hours}"
            ),
            "start": {
                "dateTime": dt_start.isoformat(),
                "timeZone": TIMEZONE,
            },
            "end": {
                "dateTime": dt_end.isoformat(),
                "timeZone": TIMEZONE,
            },
            "colorId": "1",  # синий
        }

        created = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        print(f"Calendar event created: {created.get('htmlLink')}")
        return True

    except Exception as e:
        print(f"Calendar error: {e}")
        return False

# --- WEBHOOK ENDPOINT ---
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No data"}), 400

        print(f"Received: {data}")

        service = data.get("service", "—")
        name = data.get("name", "—")
        date = data.get("date", "—")
        time = data.get("time", "—")
        hours = data.get("hours", "—")
        contact_type = data.get("contact_type", "—")
        contact = data.get("contact", "—")

        # Форматируем дату для Telegram
        try:
            date_fmt = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
        except:
            date_fmt = date

        # Красивое сообщение в Telegram
        msg = (
            f"🎙 <b>Новая заявка — Culture Music</b>\n\n"
            f"👤 <b>Имя:</b> {name}\n"
            f"📋 <b>Услуга:</b> {service}\n"
            f"📅 <b>Дата:</b> {date_fmt}\n"
            f"🕐 <b>Время:</b> {time}\n"
            f"⏱ <b>Часов:</b> {hours}\n\n"
            f"💬 <b>{contact_type}:</b> {contact}"
        )

        tg_ok = send_telegram(msg)
        cal_ok = create_calendar_event(data)

        return jsonify({
            "ok": True,
            "telegram": tg_ok,
            "calendar": cal_ok
        }), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# --- HEALTH CHECK ---
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Culture Music Bot"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
