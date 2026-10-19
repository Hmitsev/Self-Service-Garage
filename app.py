import os
import uuid
import hashlib
import base64
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path

import psycopg2
from psycopg2 import IntegrityError
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
import streamlit as st

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PROFILE_DIR = UPLOAD_DIR / "profiles"
DOC_DIR = UPLOAD_DIR / "documents"
CLIENT_BG = APP_DIR / "Designer (25).png"
ADMIN_BG = APP_DIR / "Designer (26).png"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

for folder in (DATA_DIR, UPLOAD_DIR, PROFILE_DIR, DOC_DIR):
    folder.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Сервиз за самообслужване", page_icon="🔧", layout="wide")

if not DATABASE_URL:
    st.error("Липсва DATABASE_URL в Render Environment.")
    st.stop()

@st.cache_resource
def get_pool():
    return ThreadedConnectionPool(1, 8, dsn=DATABASE_URL, sslmode="require")

@contextmanager
def db():
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

def fetchone(query, params=()):
    with db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()

def fetchall(query, params=()):
    with db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()

def execute(query, params=(), returning=False):
    with db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone() if returning else None

def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def init_db():
    statements = [
        """CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE, email TEXT, password_hash TEXT NOT NULL,
            profile_photo TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS reservations (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reservation_date DATE NOT NULL, start_time TIME NOT NULL, end_time TIME NOT NULL,
            status TEXT NOT NULL DEFAULT 'Очаква потвърждение', wants_parts BOOLEAN NOT NULL DEFAULT FALSE,
            parts_comment TEXT, vin TEXT, registration_doc TEXT, parts_status TEXT,
            admin_note TEXT, door_pin TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(reservation_date, start_time)
        )""",
        """CREATE TABLE IF NOT EXISTS technical_issues (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            category TEXT NOT NULL, description TEXT NOT NULL, photo TEXT,
            status TEXT NOT NULL DEFAULT 'Ново', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_reservation_day ON reservations(reservation_date, start_time)",
        "CREATE INDEX IF NOT EXISTS idx_reservation_user ON reservations(user_id)",
    ]
    with db() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
            defaults = {
                "youtube_1": "", "youtube_2": "", "youtube_3": "",
                "slot_minutes": "60", "open_hour": "09:00", "close_hour": "18:00",
                "admin_pin_hash": hash_value(os.getenv("ADMIN_PIN", "2468")),
            }
            for key, value in defaults.items():
                cur.execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO NOTHING", (key, value))

def setting(key, fallback=""):
    row = fetchone("SELECT value FROM settings WHERE key=%s", (key,))
    return row["value"] if row else fallback

def set_setting(key, value):
    execute("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (key, str(value)))

def save_upload(uploaded, folder, prefix):
    if not uploaded:
        return None
    suffix = Path(uploaded.name).suffix.lower() or ".jpg"
    target = folder / f"{prefix}_{uuid.uuid4().hex}{suffix}"
    target.write_bytes(uploaded.getbuffer())
    return str(target)

def apply_style():
    background_file = ADMIN_BG if st.session_state.get("role") == "admin" else CLIENT_BG
    bg_css = ""
    if background_file.exists():
        encoded = base64.b64encode(background_file.read_bytes()).decode()
        bg_css = f"background-image:linear-gradient(rgba(15,0,0,.86),rgba(15,0,0,.90)),url(data:image/png;base64,{encoded});"
    st.markdown(f"""
    <style>
    .stApp {{{bg_css} background-size:cover;background-position:center;background-attachment:fixed;}}
    .block-container {{max-width:1250px;padding-top:1.2rem;}}
    h1,h2,h3,p,label,.stMarkdown {{color:#fff;}}
    [data-testid="stSidebar"] {{background:#170707;}}
    div[data-testid="stMetric"] {{background:rgba(255,255,255,.08);border:1px solid #7c2020;border-radius:14px;padding:12px;}}
    .hero {{padding:22px;border-radius:18px;background:linear-gradient(120deg,rgba(150,0,0,.9),rgba(20,0,0,.82));border:1px solid #e63d3d;margin-bottom:18px;}}
    .notice {{padding:12px 15px;border-left:5px solid #ffcc00;background:rgba(75,55,0,.75);border-radius:8px;color:white;}}
    .slot-free {{padding:11px;text-align:center;border-radius:10px;background:#14532d;border:1px solid #22c55e;color:white;font-weight:700;margin-bottom:6px;}}
    .slot-busy {{padding:11px;text-align:center;border-radius:10px;background:#7f1d1d;border:1px solid #ef4444;color:white;font-weight:700;margin-bottom:6px;}}
    .stButton>button {{border-radius:10px;font-weight:700;}}
    </style>""", unsafe_allow_html=True)

def user_by_phone(phone):
    return fetchone("SELECT * FROM users WHERE phone=%s", (phone.strip(),))

def day_slots(selected_date):
    start = datetime.combine(selected_date, datetime.strptime(setting("open_hour", "09:00"), "%H:%M").time())
    end = datetime.combine(selected_date, datetime.strptime(setting("close_hour", "18:00"), "%H:%M").time())
    minutes = int(setting("slot_minutes", "60"))
    rows = fetchall("SELECT start_time FROM reservations WHERE reservation_date=%s AND status NOT IN ('Отказана','Анулирана')", (selected_date,))
    busy = {row["start_time"].strftime("%H:%M") for row in rows}
    slots = []
    while start + timedelta(minutes=minutes) <= end:
        slot_time = start.strftime("%H:%M")
        slots.append({"time": slot_time, "is_busy": slot_time in busy})
        start += timedelta(minutes=minutes)
    return slots

def register_view():
    st.subheader("Бърза регистрация")
    st.caption("След сканиране на QR/баркода клиентът попада директно тук.")
    with st.form("register_form"):
        c1, c2 = st.columns(2)
        first = c1.text_input("Име *"); last = c2.text_input("Фамилия *")
        phone = c1.text_input("Телефон *"); email = c2.text_input("Имейл")
        password = c1.text_input("Парола *", type="password")
        password2 = c2.text_input("Повтори паролата *", type="password")
        camera = st.camera_input("Направи профилна снимка на място")
        upload = st.file_uploader("или качи снимка", type=["jpg", "jpeg", "png"])
        submitted = st.form_submit_button("Създай профил", use_container_width=True)
    if submitted:
        if not all([first.strip(), last.strip(), phone.strip(), password]): st.error("Попълни всички задължителни полета.")
        elif password != password2: st.error("Паролите не съвпадат.")
        elif user_by_phone(phone): st.error("Вече има профил с този телефон.")
        else:
            photo = save_upload(camera or upload, PROFILE_DIR, "profile")
            row = execute("""INSERT INTO users(first_name,last_name,phone,email,password_hash,profile_photo)
                           VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
                          (first.strip(), last.strip(), phone.strip(), email.strip(), hash_value(password), photo), True)
            st.session_state.user_id = row["id"]; st.session_state.role = "client"; st.rerun()

def login_view():
    st.subheader("Вход")
    tab_client, tab_admin = st.tabs(["Клиент", "Администратор"])
    with tab_client:
        phone = st.text_input("Телефон", key="login_phone")
        password = st.text_input("Парола", type="password", key="login_pass")
        if st.button("Вход като клиент", use_container_width=True):
            user = user_by_phone(phone)
            if user and user["password_hash"] == hash_value(password):
                st.session_state.user_id = user["id"]; st.session_state.role = "client"; st.rerun()
            st.error("Невалиден телефон или парола.")
    with tab_admin:
        pin = st.text_input("Администраторски PIN", type="password")
        if st.button("Вход в админ панела", use_container_width=True):
            if hash_value(pin) == setting("admin_pin_hash"):
                st.session_state.role = "admin"; st.rerun()
            st.error("Невалиден администраторски PIN.")

def video_section():
    st.subheader("Запознаване със сервиза")

    videos = [
        {
            "title": "Как работи сервизът",
            "setting_key": "youtube_1",
            "description": "Кратко представяне на сервиза и начина на използване.",
        },
        {
            "title": "Безопасност",
            "setting_key": "youtube_2",
            "description": "Основни правила за безопасна работа в сервиза.",
        },
        {
            "title": "Работа с подемника",
            "setting_key": "youtube_3",
            "description": "Инструкции за правилна и безопасна работа с подемника.",
        },
    ]

    columns = st.columns(3)

    for column, video in zip(columns, videos):
        with column:
            st.markdown(f"### {video['title']}")

            url = setting(video["setting_key"], "").strip()

            if url:
                st.video(url)
            else:
                st.info("Видеото ще бъде добавено от администратора.")
                st.caption(video["description"])

def new_reservation(user_id):
    st.subheader("Визуален календар за резервации")
    selected = st.date_input("Избери дата", min_value=date.today(), value=date.today() + timedelta(days=1))
    slots = day_slots(selected); st.caption("🟢 Свободен час    🔴 Зает час")
    free_slots = [s["time"] for s in slots if not s["is_busy"]]
    for start_index in range(0, len(slots), 4):
        for col, slot in zip(st.columns(4), slots[start_index:start_index + 4]):
            css = "slot-busy" if slot["is_busy"] else "slot-free"
            label = "ЗАЕТ" if slot["is_busy"] else "СВОБОДЕН"
            col.markdown(f'<div class="{css}">{slot["time"]}<br>{label}</div>', unsafe_allow_html=True)
    if not free_slots:
        st.warning("За избраната дата няма свободни часове."); return
    chosen = st.selectbox("Избери свободен час", free_slots)
    st.markdown('<div class="notice">Заявка за части се подава минимум 1 ден предварително.</div>', unsafe_allow_html=True)
    if st.button("Продължи към потвърждение", type="primary", use_container_width=True):
        st.session_state.pending_slot = (selected.isoformat(), chosen)
    if "pending_slot" not in st.session_state: return
    day_value, time_value = st.session_state.pending_slot
    st.info(f"Избран час: {day_value} в {time_value}")
    wants = st.radio("Желаете ли да закупите части предварително?", ["Не, само резервация", "Да, желая части"])
    parts_comment = vin = doc_path = None; valid_parts = True
    if wants.startswith("Да"):
        reservation_dt = datetime.combine(date.fromisoformat(day_value), datetime.strptime(time_value, "%H:%M").time())
        if reservation_dt < datetime.now() + timedelta(days=1):
            st.error("За заявка с части избери час поне 1 ден напред."); valid_parts = False
        parts_comment = st.text_area("Какви части желаете? *")
        vin = st.text_input("Номер на рама (VIN) *", max_chars=17).upper().strip()
        doc_camera = st.camera_input("Снимай талона")
        doc_upload = st.file_uploader("или качи талона", type=["jpg", "jpeg", "png", "pdf"])
        if doc_camera or doc_upload: doc_path = save_upload(doc_camera or doc_upload, DOC_DIR, "talon")
    if st.button("Потвърди и изпрати заявката", use_container_width=True, disabled=not valid_parts):
        wants_parts = wants.startswith("Да")
        if wants_parts and (not parts_comment or not vin or len(vin) != 17):
            st.error("Задължителни са описание и 17-символен VIN."); return
        minutes = int(setting("slot_minutes", "60"))
        end_time = (datetime.strptime(time_value, "%H:%M") + timedelta(minutes=minutes)).time()
        try:
            execute("""INSERT INTO reservations(user_id,reservation_date,start_time,end_time,wants_parts,parts_comment,vin,registration_doc,parts_status)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (user_id, date.fromisoformat(day_value), datetime.strptime(time_value, "%H:%M").time(), end_time,
                     wants_parts, parts_comment, vin, doc_path, "Очаква преглед" if wants_parts else None))
            del st.session_state.pending_slot; st.success("Заявката е изпратена."); st.rerun()
        except IntegrityError:
            st.error("Този час току-що е зает. Избери друг."); st.rerun()

def history(user_id):
    st.subheader("История на резервациите")
    rows = fetchall("SELECT * FROM reservations WHERE user_id=%s ORDER BY reservation_date DESC,start_time DESC", (user_id,))
    if not rows: st.info("Все още няма резервации.")
    for r in rows:
        day_text = r["reservation_date"].isoformat(); time_text = r["start_time"].strftime("%H:%M")
        with st.expander(f"{'✅' if r['status']=='Потвърдена' else '⏳'} {day_text} • {time_text} • {r['status']}"):
            st.write("**Заявка за части:**", "Да" if r["wants_parts"] else "Не")
            if r["parts_status"]: st.write("**Статус части:**", r["parts_status"])
            if r["admin_note"]: st.write("**Отговор:**", r["admin_note"])
            if r["door_pin"]: st.success(f"PIN за вход: {r['door_pin']}")

def technical_issue(user_id):
    st.subheader("Технически проблем")
    with st.form("issue_form"):
        category = st.selectbox("Категория", ["Подемник", "Инструменти", "Врата / smart lock", "Осветление", "Друго"])
        description = st.text_area("Опиши проблема *"); photo = st.camera_input("Снимай проблема")
        submit = st.form_submit_button("Изпрати сигнал", use_container_width=True)
    if submit:
        if not description.strip(): st.error("Добави описание.")
        else:
            execute("INSERT INTO technical_issues(user_id,category,description,photo) VALUES(%s,%s,%s,%s)",
                    (user_id, category, description.strip(), save_upload(photo, DOC_DIR, "issue")))
            st.success("Сигналът е изпратен.")

def client_panel():
    user = fetchone("SELECT * FROM users WHERE id=%s", (st.session_state.user_id,))
    st.markdown(f'<div class="hero"><h1>Сервиз за самообслужване</h1><p>Здравей, {user["first_name"]}.</p></div>', unsafe_allow_html=True)
    with st.sidebar:
        if user["profile_photo"] and Path(user["profile_photo"]).exists(): st.image(user["profile_photo"], width=110)
        st.write(f"**{user['first_name']} {user['last_name']}**")
        page = st.radio("Меню", ["Начало", "Запази час", "Моите резервации", "Технически проблем", "Моят профил"])
        if st.button("Изход"): st.session_state.clear(); st.rerun()
    if page == "Начало": video_section()
    elif page == "Запази час": new_reservation(user["id"])
    elif page == "Моите резервации": history(user["id"])
    elif page == "Технически проблем": technical_issue(user["id"])
    else:
        st.subheader("Моят профил"); st.write(f"**Име:** {user['first_name']} {user['last_name']}"); st.write(f"**Телефон:** {user['phone']}"); st.write(f"**Имейл:** {user['email'] or '—'}")

def admin_reservations():
    st.subheader("Мониторинг на резервациите")
    statuses = ["Очаква потвърждение", "Потвърдена", "Отказана", "Завършена"]
    status_filter = st.multiselect("Статус", statuses, default=statuses[:2])
    rows = fetchall("""SELECT r.*,u.first_name,u.last_name,u.phone FROM reservations r
                     JOIN users u ON u.id=r.user_id ORDER BY r.reservation_date,r.start_time""")
    rows = [r for r in rows if not status_filter or r["status"] in status_filter]
    if not rows: st.info("Няма резервации.")
    part_statuses = ["—", "Очаква преглед", "Можем да подготвим", "Не можем да подготвим", "Подготвени"]
    for r in rows:
        day_text = r["reservation_date"].isoformat(); time_text = r["start_time"].strftime("%H:%M")
        with st.expander(f"#{r['id']} • {day_text} {time_text} • {r['first_name']} {r['last_name']} • {r['status']}"):
            c1,c2 = st.columns([2,1])
            with c1:
                st.write(f"Телефон: {r['phone']}"); st.write("Части:", "Да" if r["wants_parts"] else "Не")
                if r["wants_parts"]: st.write("VIN:", r["vin"]); st.write("Заявка:", r["parts_comment"])
            with c2:
                new_status = st.selectbox("Статус резервация", statuses, index=statuses.index(r["status"]), key=f"s_{r['id']}")
                current_parts = r["parts_status"] if r["parts_status"] in part_statuses else "—"
                parts_status = st.selectbox("Статус части", part_statuses, index=part_statuses.index(current_parts), key=f"p_{r['id']}")
                note = st.text_area("Отговор към клиента", value=r["admin_note"] or "", key=f"n_{r['id']}")
                door_pin = st.text_input("PIN за smart lock", value=r["door_pin"] or "", key=f"pin_{r['id']}")
                if st.button("Запази промените", key=f"save_{r['id']}", use_container_width=True):
                    execute("UPDATE reservations SET status=%s,parts_status=%s,admin_note=%s,door_pin=%s WHERE id=%s",
                            (new_status, None if parts_status=="—" else parts_status, note, door_pin, r["id"]))
                    st.rerun()

def admin_panel():
    st.markdown('<div class="hero"><h1>Админ панел • Сервиз за самообслужване</h1></div>', unsafe_allow_html=True)
    with st.sidebar:
        page = st.radio("Админ меню", ["Табло", "Резервации", "Технически сигнали", "Видео съдържание", "Настройки"])
        if st.button("Изход"): st.session_state.clear(); st.rerun()
    if page == "Табло":
        pending = fetchone("SELECT COUNT(*) AS c FROM reservations WHERE status='Очаква потвърждение'")["c"]
        parts = fetchone("SELECT COUNT(*) AS c FROM reservations WHERE wants_parts=TRUE AND parts_status='Очаква преглед'")["c"]
        issues = fetchone("SELECT COUNT(*) AS c FROM technical_issues WHERE status='Ново'")["c"]
        users = fetchone("SELECT COUNT(*) AS c FROM users")["c"]
        for col,label,value in zip(st.columns(4), ["Чакащи резервации","Заявки за части","Нови сигнали","Клиенти"], [pending,parts,issues,users]): col.metric(label,value)
    elif page == "Резервации": admin_reservations()
    elif page == "Технически сигнали":
        rows = fetchall("""SELECT t.*,u.first_name,u.last_name FROM technical_issues t JOIN users u ON u.id=t.user_id ORDER BY t.id DESC""")
        for r in rows:
            with st.expander(f"#{r['id']} • {r['category']} • {r['first_name']} {r['last_name']} • {r['status']}"):
                st.write(r["description"])
                new = st.selectbox("Статус", ["Ново", "В работа", "Решено"], index=["Ново", "В работа", "Решено"].index(r["status"]), key=f"is_{r['id']}")
                if st.button("Обнови", key=f"iu_{r['id']}"): execute("UPDATE technical_issues SET status=%s WHERE id=%s", (new,r["id"])); st.rerun()
    elif page == "Видео съдържание":
        with st.form("videos"):
            urls = [st.text_input(f"Видео {i}", value=setting(f"youtube_{i}")) for i in range(1,4)]
            if st.form_submit_button("Запази видеата", use_container_width=True):
                for i,url in enumerate(urls,1): set_setting(f"youtube_{i}",url.strip())
                st.success("Видеата са обновени.")
    else:
        with st.form("settings_form"):
            opening = st.text_input("Отваряне", value=setting("open_hour")); closing = st.text_input("Затваряне", value=setting("close_hour"))
            duration = st.number_input("Слот (минути)", 30, 240, int(setting("slot_minutes")), 30)
            new_pin = st.text_input("Нов администраторски PIN", type="password")
            if st.form_submit_button("Запази настройки"):
                datetime.strptime(opening,"%H:%M"); datetime.strptime(closing,"%H:%M")
                set_setting("open_hour",opening); set_setting("close_hour",closing); set_setting("slot_minutes",duration)
                if new_pin: set_setting("admin_pin_hash",hash_value(new_pin))
                st.success("Настройките са запазени.")

try:
    init_db()
except Exception as exc:
    st.error("Неуспешна връзка с Neon. Провери DATABASE_URL в Render.")
    st.code(str(exc))
    st.stop()

apply_style()
if "role" not in st.session_state:
    st.markdown('<div class="hero"><h1>Сервиз за самообслужване</h1><p>Резервация, безопасност, части и достъп в едно приложение.</p></div>', unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["Създай профил", "Вход"])
    with tab1: register_view()
    with tab2: login_view()
elif st.session_state.role == "client": client_panel()
else: admin_panel()
