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
BOT_TOKEN   = os.environ.get("BOT_TOKEN")
CHAT_ID     = os.environ.get("CHAT_ID", "-5288639479")
CALENDAR_ID = "5fac25e58365d554f9eb1e1d0f8d6896cad2d57c4d17bc7de384d584ddf26256@group.calendar.google.com"
TIMEZONE    = "Europe/Moscow"
WORK_START  = "10:00"
WORK_END    = "21:30"

# --- CORS ---
@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route("/webhook",    methods=["OPTIONS"])
@app.route("/free-slots", methods=["OPTIONS"])
def handle_options():
    return '', 200

# --- GOOGLE CALENDAR ---
def get_calendar_service():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        return None
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=creds)

# --- TELEGRAM ---
def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
        return r.ok
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# --- CREATE EVENT ---
def create_calendar_event(data):
    try:
        service = get_calendar_service()
        if not service:
            print("No Google credentials")
            return False

        tz       = pytz.timezone(TIMEZONE)
        date_str = data.get("date", "")
        time_str = data.get("time", "10:00")
        hours    = int(data.get("hours", "1") if data.get("hours", "1") not in ("—", "", None) else "1")

        try:
            dt_start = tz.localize(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))
        except:
            dt_start = tz.localize(datetime.now().replace(second=0, microsecond=0))

        dt_end       = dt_start + timedelta(hours=hours)
        service_name = data.get("service", "Услуга не указана")
        client_name  = data.get("name", "—")
        contact_type = data.get("contact_type", "")
        contact      = data.get("contact", "—")

        event = {
            "summary": f"🎙 {client_name} — {service_name}",
            "description": (
                f"Клиент: {client_name}\n"
                f"Услуга: {service_name}\n"
                f"Способ связи: {contact_type}\n"
                f"Контакт: {contact}\n"
                f"Кол-во часов: {hours}"
            ),
            "start": {"dateTime": dt_start.isoformat(), "timeZone": TIMEZONE},
            "end":   {"dateTime": dt_end.isoformat(),   "timeZone": TIMEZONE},
            "colorId": "1",
        }

        created = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        print(f"Calendar event created: {created.get('htmlLink')}")
        return True

    except Exception as e:
        print(f"Calendar error: {e}")
        return False

# --- FREE SLOTS ---
@app.route("/free-slots", methods=["GET"])
def free_slots():
    try:
        date_str = request.args.get("date")
        if not date_str:
            return jsonify({"error": "date required"}), 400

        tz        = pytz.timezone(TIMEZONE)
        day_start = tz.localize(datetime.strptime(f"{date_str} {WORK_START}", "%Y-%m-%d %H:%M"))
        day_end   = tz.localize(datetime.strptime(f"{date_str} {WORK_END}",   "%Y-%m-%d %H:%M"))
        now       = datetime.now(tz)

        # Генерируем слоты по 30 минут
        all_slots = []
        cur = day_start
        while cur < day_end:
            all_slots.append(cur)
            cur += timedelta(minutes=30)

        # Получаем события из календаря
        cal_service = get_calendar_service()
        events = []
        if cal_service:
            result = cal_service.events().list(
                calendarId=CALENDAR_ID,
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            events = result.get("items", [])

        def is_busy(slot_start):
            slot_end = slot_start + timedelta(minutes=30)
            for ev in events:
                try:
                    ev_start = datetime.fromisoformat(ev["start"].get("dateTime", ev["start"].get("date"))).astimezone(tz)
                    ev_end   = datetime.fromisoformat(ev["end"].get("dateTime",   ev["end"].get("date"))).astimezone(tz)
                    if slot_start < ev_end and slot_end > ev_start:
                        return True
                except:
                    continue
            return False

        slots = []
        for s in all_slots:
            slots.append({
                "time": s.strftime("%H:%M"),
                "free": not is_busy(s) and s >= now
            })

        return jsonify({"date": date_str, "slots": slots})

    except Exception as e:
        print(f"Free slots error: {e}")
        return jsonify({"error": str(e)}), 500

# --- WEBHOOK ---
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No data"}), 400

        print(f"Received: {data}")

        name         = data.get("name", "—")
        service_name = data.get("service", "—")
        date         = data.get("date", "—")
        time         = data.get("time", "—")
        hours        = data.get("hours", "—")
        contact_type = data.get("contact_type", "—")
        contact      = data.get("contact", "—")

        try:
            date_fmt = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
        except:
            date_fmt = date

        msg = (
            f"🎙 <b>Новая заявка — Culture Music</b>\n\n"
            f"👤 <b>Имя:</b> {name}\n"
            f"📋 <b>Услуга:</b> {service_name}\n"
            f"📅 <b>Дата:</b> {date_fmt}\n"
            f"🕐 <b>Время:</b> {time}\n"
            f"⏱ <b>Часов:</b> {hours}\n\n"
            f"💬 <b>{contact_type}:</b> {contact}"
        )

        tg_ok  = send_telegram(msg)
        cal_ok = create_calendar_event(data)

        return jsonify({"ok": True, "telegram": tg_ok, "calendar": cal_ok}), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# --- HEALTH ---
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Culture Music Bot"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
