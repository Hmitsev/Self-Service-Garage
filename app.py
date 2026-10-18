import os
import sqlite3
import uuid
import hashlib
from datetime import datetime, date, time, timedelta
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PROFILE_DIR = UPLOAD_DIR / "profiles"
DOC_DIR = UPLOAD_DIR / "documents"
DB_PATH = DATA_DIR / "self_service_garage.db"
BG_PATH = APP_DIR / "garage_background.png"

for folder in (DATA_DIR, UPLOAD_DIR, PROFILE_DIR, DOC_DIR):
    folder.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Вашият сервиз за самообслужване", page_icon="🔧", layout="wide")


def db():
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            email TEXT,
            password_hash TEXT NOT NULL,
            profile_photo TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reservation_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Очаква потвърждение',
            wants_parts INTEGER NOT NULL DEFAULT 0,
            parts_comment TEXT,
            vin TEXT,
            registration_doc TEXT,
            parts_status TEXT,
            admin_note TEXT,
            door_pin TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(reservation_date, start_time),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS technical_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            photo TEXT,
            status TEXT NOT NULL DEFAULT 'Ново',
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        defaults = {
            "youtube_1": "", "youtube_2": "", "youtube_3": "",
            "slot_minutes": "60", "open_hour": "09:00", "close_hour": "18:00",
            "admin_pin_hash": hash_value(os.getenv("ADMIN_PIN", "2468"))
        }
        for key, value in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))


def setting(key, fallback=""):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else fallback


def set_setting(key, value):
    with db() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def save_upload(uploaded, folder: Path, prefix: str):
    if not uploaded:
        return None
    suffix = Path(uploaded.name).suffix.lower() or ".jpg"
    filename = f"{prefix}_{uuid.uuid4().hex}{suffix}"
    target = folder / filename
    target.write_bytes(uploaded.getbuffer())
    return str(target)


def apply_style():
    bg_css = ""
    if BG_PATH.exists():
        import base64
        encoded = base64.b64encode(BG_PATH.read_bytes()).decode()
        bg_css = f"background-image:linear-gradient(rgba(15,0,0,.89),rgba(15,0,0,.92)),url(data:image/png;base64,{encoded});"
    st.markdown(f"""
    <style>
    .stApp {{{bg_css} background-size:cover; background-position:center; background-attachment:fixed;}}
    .block-container {{max-width:1250px; padding-top:1.2rem;}}
    h1,h2,h3,p,label,.stMarkdown {{color:#fff;}}
    [data-testid="stSidebar"] {{background:#170707;}}
    div[data-testid="stMetric"] {{background:rgba(255,255,255,.08);border:1px solid #7c2020;border-radius:14px;padding:12px;}}
    .hero {{padding:22px;border-radius:18px;background:linear-gradient(120deg,rgba(150,0,0,.9),rgba(20,0,0,.82));border:1px solid #e63d3d;margin-bottom:18px;}}
    .notice {{padding:12px 15px;border-left:5px solid #ffcc00;background:rgba(75,55,0,.75);border-radius:8px;color:white;}}
    .card {{padding:16px;border-radius:14px;background:rgba(20,20,20,.82);border:1px solid rgba(255,255,255,.15);}}
    .stButton>button {{border-radius:10px;font-weight:700;}}
    </style>
    """, unsafe_allow_html=True)


def user_by_phone(phone):
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE phone=?", (phone.strip(),)).fetchone()


def available_slots(selected_date):
    start = datetime.combine(selected_date, datetime.strptime(setting("open_hour", "09:00"), "%H:%M").time())
    end = datetime.combine(selected_date, datetime.strptime(setting("close_hour", "18:00"), "%H:%M").time())
    minutes = int(setting("slot_minutes", "60"))
    with db() as conn:
        busy = {r["start_time"] for r in conn.execute(
            "SELECT start_time FROM reservations WHERE reservation_date=? AND status NOT IN ('Отказана','Анулирана')",
            (selected_date.isoformat(),)
        ).fetchall()}
    slots = []
    while start + timedelta(minutes=minutes) <= end:
        value = start.strftime("%H:%M")
        if value not in busy:
            slots.append(value)
        start += timedelta(minutes=minutes)
    return slots


def register_view():
    st.subheader("Бърза регистрация")
    st.caption("След сканиране на QR/баркода клиентът попада директно тук.")
    with st.form("register_form"):
        c1, c2 = st.columns(2)
        first = c1.text_input("Име *")
        last = c2.text_input("Фамилия *")
        phone = c1.text_input("Телефон *")
        email = c2.text_input("Имейл")
        password = c1.text_input("Парола *", type="password")
        password2 = c2.text_input("Повтори паролата *", type="password")
        camera = st.camera_input("Направи профилна снимка на място")
        upload = st.file_uploader("или качи снимка", type=["jpg", "jpeg", "png"])
        submitted = st.form_submit_button("Създай профил", use_container_width=True)
    if submitted:
        if not all([first.strip(), last.strip(), phone.strip(), password]):
            st.error("Попълни всички задължителни полета.")
        elif password != password2:
            st.error("Паролите не съвпадат.")
        elif user_by_phone(phone):
            st.error("Вече има профил с този телефон.")
        else:
            photo = save_upload(camera or upload, PROFILE_DIR, "profile")
            with db() as conn:
                cur = conn.execute("INSERT INTO users(first_name,last_name,phone,email,password_hash,profile_photo,created_at) VALUES(?,?,?,?,?,?,?)",
                    (first.strip(), last.strip(), phone.strip(), email.strip(), hash_value(password), photo, datetime.now().isoformat(timespec="seconds")))
                uid = cur.lastrowid
            st.session_state.user_id = uid
            st.session_state.role = "client"
            st.success("Профилът е създаден.")
            st.rerun()


def login_view():
    st.subheader("Вход")
    tab_client, tab_admin = st.tabs(["Клиент", "Администратор"])
    with tab_client:
        phone = st.text_input("Телефон", key="login_phone")
        password = st.text_input("Парола", type="password", key="login_pass")
        if st.button("Вход като клиент", use_container_width=True):
            user = user_by_phone(phone)
            if user and user["password_hash"] == hash_value(password):
                st.session_state.user_id = user["id"]
                st.session_state.role = "client"
                st.rerun()
            st.error("Невалиден телефон или парола.")
    with tab_admin:
        pin = st.text_input("Администраторски PIN", type="password")
        if st.button("Вход в админ панела", use_container_width=True):
            if hash_value(pin) == setting("admin_pin_hash"):
                st.session_state.role = "admin"
                st.rerun()
            st.error("Невалиден администраторски PIN.")


def video_section():
    st.subheader("Запознаване със сервиза")
    labels = ["Как работи сервизът", "Безопасност", "Работа с подемника"]
    cols = st.columns(3)
    for i, col in enumerate(cols, 1):
        with col:
            url = setting(f"youtube_{i}")
            st.markdown(f"**{labels[i-1]}**")
            if url:
                st.video(url)
            else:
                st.info("Видеото ще бъде добавено от администратора.")


def new_reservation(user_id):
    st.subheader("Запази час")
    selected = st.date_input("Избери дата", min_value=date.today(), value=date.today() + timedelta(days=1))
    slots = available_slots(selected)
    if not slots:
        st.warning("Няма свободни часове за избраната дата.")
        return
    chosen = st.selectbox("Свободен начален час", slots)
    st.markdown('<div class="notice">Ако желаете части, заявката трябва да бъде подадена минимум 1 ден преди резервирания час.</div>', unsafe_allow_html=True)
    if st.button("Продължи към потвърждение", type="primary"):
        st.session_state.pending_slot = (selected.isoformat(), chosen)
    if "pending_slot" in st.session_state:
        day_value, time_value = st.session_state.pending_slot
        st.info(f"Избран час: {day_value} в {time_value}")
        wants = st.radio("Желаете ли да закупите части предварително?", ["Не, само резервация", "Да, желая части"])
        parts_comment = vin = doc_path = None
        valid_parts = True
        if wants.startswith("Да"):
            reservation_dt = datetime.combine(date.fromisoformat(day_value), datetime.strptime(time_value, "%H:%M").time())
            if reservation_dt < datetime.now() + timedelta(days=1):
                st.error("За заявка с части избери час, който е поне 1 ден напред.")
                valid_parts = False
            parts_comment = st.text_area("Какви части желаете? *", placeholder="Напр. масло, маслен филтър, предни накладки...")
            vin = st.text_input("Номер на рама (VIN) *", max_chars=17).upper().strip()
            doc_camera = st.camera_input("Снимай талона")
            doc_upload = st.file_uploader("или качи снимка на талона", type=["jpg", "jpeg", "png", "pdf"])
            if doc_camera or doc_upload:
                doc_path = save_upload(doc_camera or doc_upload, DOC_DIR, "talon")
        if st.button("Потвърди и изпрати заявката", use_container_width=True, disabled=not valid_parts):
            wants_parts = wants.startswith("Да")
            if wants_parts and (not parts_comment or len(vin) != 17):
                st.error("За заявка за части са задължителни описание и 17-символен VIN.")
            else:
                minutes = int(setting("slot_minutes", "60"))
                end_time = (datetime.strptime(time_value, "%H:%M") + timedelta(minutes=minutes)).strftime("%H:%M")
                try:
                    with db() as conn:
                        conn.execute("""INSERT INTO reservations(user_id,reservation_date,start_time,end_time,wants_parts,parts_comment,vin,registration_doc,parts_status,created_at)
                                      VALUES(?,?,?,?,?,?,?,?,?,?)""",
                                     (user_id, day_value, time_value, end_time, int(wants_parts), parts_comment, vin, doc_path,
                                      "Очаква преглед" if wants_parts else None, datetime.now().isoformat(timespec="seconds")))
                    del st.session_state.pending_slot
                    st.success("Заявката е изпратена. Очаква потвърждение от администратор и PIN за достъп.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Този час току-що е зает. Избери друг свободен час.")


def history(user_id):
    st.subheader("История на резервациите")
    with db() as conn:
        rows = conn.execute("SELECT * FROM reservations WHERE user_id=? ORDER BY reservation_date DESC,start_time DESC", (user_id,)).fetchall()
    if not rows:
        st.info("Все още няма резервации.")
    for r in rows:
        icon = "✅" if r["status"] == "Потвърдена" else "⏳"
        with st.expander(f"{icon} {r['reservation_date']} • {r['start_time']} • {r['status']}"):
            st.write("**Заявка за части:**", "Да" if r["wants_parts"] else "Не")
            if r["parts_status"]: st.write("**Статус части:**", r["parts_status"])
            if r["admin_note"]: st.write("**Отговор от сервиза:**", r["admin_note"])
            if r["door_pin"]: st.success(f"PIN за вход: {r['door_pin']}")


def technical_issue(user_id):
    st.subheader("Технически проблем")
    with st.form("issue_form"):
        category = st.selectbox("Категория", ["Подемник", "Инструменти", "Врата / smart lock", "Осветление", "Друго"])
        description = st.text_area("Опиши проблема *")
        photo = st.camera_input("Снимай проблема")
        submit = st.form_submit_button("Изпрати сигнал", use_container_width=True)
    if submit:
        if not description.strip():
            st.error("Добави описание.")
        else:
            path = save_upload(photo, DOC_DIR, "issue")
            with db() as conn:
                conn.execute("INSERT INTO technical_issues(user_id,category,description,photo,created_at) VALUES(?,?,?,?,?)",
                             (user_id, category, description.strip(), path, datetime.now().isoformat(timespec="seconds")))
            st.success("Сигналът е изпратен към администратора.")


def client_panel():
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id=?", (st.session_state.user_id,)).fetchone()
    st.markdown(f'<div class="hero"><h1>Вашият сервиз за самообслужване</h1><p>Здравей, {user["first_name"]}. Ремонтирай сам, безопасно и в резервиран час.</p></div>', unsafe_allow_html=True)
    with st.sidebar:
        if user["profile_photo"] and Path(user["profile_photo"]).exists(): st.image(user["profile_photo"], width=110)
        st.write(f"**{user['first_name']} {user['last_name']}**")
        page = st.radio("Меню", ["Начало", "Запази час", "Моите резервации", "Технически проблем", "Моят профил"])
        if st.button("Изход"):
            st.session_state.clear(); st.rerun()
    if page == "Начало":
        video_section()
        st.markdown("### Бързи действия")
        c1,c2,c3 = st.columns(3)
        c1.info("📅 Резервирай свободен ден и час")
        c2.info("🛒 Заяви части поне 1 ден предварително")
        c3.info("🔐 Получи PIN след потвърждение")
    elif page == "Запази час": new_reservation(user["id"])
    elif page == "Моите резервации": history(user["id"])
    elif page == "Технически проблем": technical_issue(user["id"])
    else:
        st.subheader("Моят профил")
        st.write(f"**Име:** {user['first_name']} {user['last_name']}")
        st.write(f"**Телефон:** {user['phone']}")
        st.write(f"**Имейл:** {user['email'] or '—'}")


def admin_reservations():
    st.subheader("Мониторинг на резервациите")
    status_filter = st.multiselect("Статус", ["Очаква потвърждение", "Потвърдена", "Отказана", "Завършена"], default=["Очаква потвърждение", "Потвърдена"])
    with db() as conn:
        query = """SELECT r.*,u.first_name,u.last_name,u.phone FROM reservations r JOIN users u ON u.id=r.user_id"""
        rows = conn.execute(query + " ORDER BY r.reservation_date,r.start_time").fetchall()
    rows = [r for r in rows if not status_filter or r["status"] in status_filter]
    if not rows: st.info("Няма резервации за избрания филтър.")
    for r in rows:
        title = f"#{r['id']} • {r['reservation_date']} {r['start_time']} • {r['first_name']} {r['last_name']} • {r['status']}"
        with st.expander(title):
            c1,c2 = st.columns([2,1])
            with c1:
                st.write(f"Телефон: {r['phone']}")
                st.write("Части:", "Да" if r["wants_parts"] else "Не")
                if r["wants_parts"]:
                    st.write("VIN:", r["vin"])
                    st.write("Заявка:", r["parts_comment"])
                    if r["registration_doc"] and Path(r["registration_doc"]).exists():
                        try: st.image(r["registration_doc"], width=420)
                        except Exception: st.write("Качен е документ към заявката.")
            with c2:
                new_status = st.selectbox("Статус резервация", ["Очаква потвърждение", "Потвърдена", "Отказана", "Завършена"], index=["Очаква потвърждение", "Потвърдена", "Отказана", "Завършена"].index(r["status"]), key=f"s_{r['id']}")
                parts_status = st.selectbox("Статус части", ["—", "Очаква преглед", "Можем да подготвим", "Не можем да подготвим", "Подготвени"], index=(["—", "Очаква преглед", "Можем да подготвим", "Не можем да подготвим", "Подготвени"].index(r["parts_status"]) if r["parts_status"] in ["—", "Очаква преглед", "Можем да подготвим", "Не можем да подготвим", "Подготвени"] else 0), key=f"p_{r['id']}")
                note = st.text_area("Отговор към клиента", value=r["admin_note"] or "", key=f"n_{r['id']}")
                door_pin = st.text_input("PIN за smart lock", value=r["door_pin"] or "", max_chars=10, key=f"pin_{r['id']}")
                if st.button("Запази промените", key=f"save_{r['id']}", use_container_width=True):
                    with db() as conn:
                        conn.execute("UPDATE reservations SET status=?,parts_status=?,admin_note=?,door_pin=? WHERE id=?",
                                     (new_status, None if parts_status == "—" else parts_status, note, door_pin, r["id"]))
                    st.success("Промените са запазени.")
                    st.rerun()


def admin_panel():
    st.markdown('<div class="hero"><h1>Админ панел • Сервиз за самообслужване</h1><p>Контрол на резервации, части, съдържание и достъп.</p></div>', unsafe_allow_html=True)
    with st.sidebar:
        page = st.radio("Админ меню", ["Табло", "Резервации", "Технически сигнали", "Видео съдържание", "Настройки"])
        if st.button("Изход"):
            st.session_state.clear(); st.rerun()
    if page == "Табло":
        with db() as conn:
            pending = conn.execute("SELECT COUNT(*) c FROM reservations WHERE status='Очаква потвърждение'").fetchone()["c"]
            parts = conn.execute("SELECT COUNT(*) c FROM reservations WHERE wants_parts=1 AND parts_status='Очаква преглед'").fetchone()["c"]
            issues = conn.execute("SELECT COUNT(*) c FROM technical_issues WHERE status='Ново'").fetchone()["c"]
            users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        cols = st.columns(4)
        for col,label,value in zip(cols,["Чакащи резервации","Заявки за части","Нови сигнали","Клиенти"],[pending,parts,issues,users]): col.metric(label,value)
    elif page == "Резервации": admin_reservations()
    elif page == "Технически сигнали":
        st.subheader("Технически сигнали")
        with db() as conn:
            rows = conn.execute("SELECT t.*,u.first_name,u.last_name FROM technical_issues t JOIN users u ON u.id=t.user_id ORDER BY t.id DESC").fetchall()
        for r in rows:
            with st.expander(f"#{r['id']} • {r['category']} • {r['first_name']} {r['last_name']} • {r['status']}"):
                st.write(r["description"])
                if r["photo"] and Path(r["photo"]).exists(): st.image(r["photo"], width=450)
                new = st.selectbox("Статус", ["Ново", "В работа", "Решено"], index=["Ново", "В работа", "Решено"].index(r["status"]), key=f"is_{r['id']}")
                if st.button("Обнови", key=f"iu_{r['id']}"):
                    with db() as conn: conn.execute("UPDATE technical_issues SET status=? WHERE id=?", (new,r["id"]))
                    st.rerun()
    elif page == "Видео съдържание":
        st.subheader("YouTube видеа на началната страница")
        st.caption("Постави пълен публичен или unlisted YouTube линк. Видеото се показва директно в клиентския панел.")
        with st.form("videos"):
            urls = [st.text_input(f"Видео {i}", value=setting(f"youtube_{i}")) for i in range(1,4)]
            if st.form_submit_button("Запази видеата", use_container_width=True):
                for i,url in enumerate(urls,1): set_setting(f"youtube_{i}",url.strip())
                st.success("Видеата са обновени.")
    else:
        st.subheader("Работно време и сигурност")
        with st.form("settings_form"):
            c1,c2,c3 = st.columns(3)
            opening = c1.text_input("Отваряне", value=setting("open_hour"))
            closing = c2.text_input("Затваряне", value=setting("close_hour"))
            duration = c3.number_input("Продължителност на слот (минути)", min_value=30, max_value=240, step=30, value=int(setting("slot_minutes")))
            new_pin = st.text_input("Нов администраторски PIN (остави празно без промяна)", type="password")
            if st.form_submit_button("Запази настройки", use_container_width=True):
                try:
                    datetime.strptime(opening,"%H:%M"); datetime.strptime(closing,"%H:%M")
                    set_setting("open_hour",opening); set_setting("close_hour",closing); set_setting("slot_minutes",duration)
                    if new_pin: set_setting("admin_pin_hash",hash_value(new_pin))
                    st.success("Настройките са запазени.")
                except ValueError: st.error("Часът трябва да е във формат HH:MM.")


init_db()
apply_style()
if "role" not in st.session_state:
    st.markdown('<div class="hero"><h1>Вашият сервиз за самообслужване</h1><p>Резервация, безопасност, части и достъп в едно приложение.</p></div>', unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["Създай профил", "Вход"])
    with tab1: register_view()
    with tab2: login_view()
elif st.session_state.role == "client":
    client_panel()
else:
    admin_panel()
