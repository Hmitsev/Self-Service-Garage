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
import time

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
@st.cache_resource
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
        "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS parts_offer TEXT",
        "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS customer_parts_decision TEXT",
        "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS customer_parts_comment TEXT",
        "ALTER TABLE reservations ADD COLUMN IF NOT EXISTS customer_parts_responded_at TIMESTAMPTZ",
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
@st.cache_data
def get_bg_css(background_file):

    if not background_file.exists():
        return ""

    encoded = base64.b64encode(
        background_file.read_bytes()
    ).decode()

    return (
        "background-image:"
        "linear-gradient(rgba(15,0,0,.86),rgba(15,0,0,.90)),"
        f"url(data:image/png;base64,{encoded});"
    )


def apply_style():
    background_file = ADMIN_BG if st.session_state.get("role") == "admin" else CLIENT_BG
    bg_css = get_bg_css(background_file)
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

    /* Client navigation buttons */
    div[data-testid="stHorizontalBlock"] .stButton > button {{
        width:100%; min-height:54px; border-radius:14px;
        border:1px solid #ff4242;
        background:linear-gradient(135deg,#720000,#d01010 55%,#8b0000);
        color:white; font-weight:800;
        box-shadow:0 8px 20px rgba(180,0,0,.28);
    }}
    div[data-testid="stHorizontalBlock"] .stButton > button:hover {{
        border-color:#ff8585;
        background:linear-gradient(135deg,#970000,#ef2424 55%,#a00000);
        color:white; transform:translateY(-1px);
    }}
    div[data-testid="stHorizontalBlock"] .stButton > button[kind="primary"] {{
        border-color:#43e47c;
        background:linear-gradient(135deg,#086b30,#16a34a 55%,#08732f);
        color:white;
        box-shadow:0 8px 22px rgba(22,163,74,.38);
    }}
    </style>""", unsafe_allow_html=True)

def user_by_phone(phone):
    return fetchone("SELECT * FROM users WHERE phone=%s", (phone.strip(),))

def day_slots(selected_date):
    open_dt = datetime.combine(
        selected_date,
        datetime.strptime(setting("open_hour", "09:00"), "%H:%M").time(),
    )
    close_dt = datetime.combine(
        selected_date,
        datetime.strptime(setting("close_hour", "18:00"), "%H:%M").time(),
    )
    minutes = int(setting("slot_minutes", "60"))
    rows = fetchall(
        """SELECT start_time,end_time FROM reservations
           WHERE reservation_date=%s
             AND status NOT IN ('Отказана','Анулирана')""",
        (selected_date,),
    )

    reservations = [
        (
            datetime.combine(selected_date, row["start_time"]),
            datetime.combine(selected_date, row["end_time"]),
        )
        for row in rows
    ]

    slots = []
    current = open_dt
    while current + timedelta(minutes=minutes) <= close_dt:
        slot_end = current + timedelta(minutes=minutes)
        is_busy = any(
            current < reserved_end and slot_end > reserved_start
            for reserved_start, reserved_end in reservations
        )
        slots.append({"time": current.strftime("%H:%M"), "is_busy": is_busy})
        current = slot_end
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
        submitted = st.form_submit_button("Създай профил", use_container_width=True)
    if submitted:
        if not all([first.strip(), last.strip(), phone.strip(), password]): st.error("Попълни всички задължителни полета.")
        elif password != password2: st.error("Паролите не съвпадат.")
        elif user_by_phone(phone): st.error("Вече има профил с този телефон.")
        else:
            row = execute("""
            INSERT INTO users(
                first_name,last_name,phone,email,
                password_hash,profile_photo
            )
            VALUES(%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                first.strip(),
                last.strip(),
                phone.strip(),
                email.strip(),
                hash_value(password),
                None
            ), True)
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
    selected = st.date_input(
        "Избери дата",
        min_value=date.today(),
        value=date.today() + timedelta(days=1),
    )

    slots = day_slots(selected)
    st.caption("🟢 Свободен час    🔴 Зает час")
    free_slots = [slot["time"] for slot in slots if not slot["is_busy"]]

    for start_index in range(0, len(slots), 4):
        for col, slot in zip(st.columns(4), slots[start_index:start_index + 4]):
            css = "slot-busy" if slot["is_busy"] else "slot-free"
            label = "ЗАЕТ" if slot["is_busy"] else "СВОБОДЕН"
            col.markdown(
                f'<div class="{css}">{slot["time"]}<br>{label}</div>',
                unsafe_allow_html=True,
            )

    if not free_slots:
        st.warning("За избраната дата няма свободни часове.")
        return

    slot_minutes = int(setting("slot_minutes", "60"))
    start_value = st.selectbox("Начален час", free_slots)
    start_index = next(i for i, slot in enumerate(slots) if slot["time"] == start_value)

    consecutive_free = 0
    for slot in slots[start_index:]:
        if slot["is_busy"]:
            break
        consecutive_free += 1

    duration_options = list(range(1, consecutive_free + 1))
    duration_slots = st.selectbox(
        "Продължителност",
        duration_options,
        format_func=lambda value: f"{value} час" if value == 1 else f"{value} часа",
    )

    start_dt = datetime.combine(
        selected,
        datetime.strptime(start_value, "%H:%M").time(),
    )
    end_dt = start_dt + timedelta(minutes=slot_minutes * duration_slots)
    end_value = end_dt.strftime("%H:%M")

    st.info(
        f"Избран период: {selected.isoformat()} от {start_value} до {end_value} "
        f"({duration_slots} {'час' if duration_slots == 1 else 'часа'})"
    )
    st.markdown(
        '<div class="notice">Заявка за части се подава минимум 1 ден предварително.</div>',
        unsafe_allow_html=True,
    )

    if st.button("Продължи към потвърждение", type="primary", use_container_width=True):
        st.session_state.pending_slot = (
            selected.isoformat(),
            start_value,
            end_value,
            duration_slots,
        )

    if "pending_slot" not in st.session_state:
        return

    day_value, pending_start, pending_end, pending_duration = st.session_state.pending_slot
    st.success(
        f"Период за потвърждение: {day_value} от {pending_start} до {pending_end} "
        f"({pending_duration} {'час' if pending_duration == 1 else 'часа'})"
    )

    wants = st.radio(
        "Желаете ли да закупите части предварително?",
        ["Не, само резервация", "Да, желая части"],
    )
    parts_comment = vin = doc_path = None
    valid_parts = True

    if wants.startswith("Да"):
        reservation_dt = datetime.combine(
            date.fromisoformat(day_value),
            datetime.strptime(pending_start, "%H:%M").time(),
        )
        if reservation_dt < datetime.now() + timedelta(days=1):
            st.error("За заявка с части избери период поне 1 ден напред.")
            valid_parts = False
        parts_comment = st.text_area("Какви части желаете? *")
        vin = st.text_input("Номер на рама (VIN) *", max_chars=17).upper().strip()
        add_registration_doc = st.checkbox(
            "📷 Добави снимка на талона"
        )
        
        doc_camera = None
        doc_upload = None
        doc_path = None
        
        if add_registration_doc:
        
            st.info(
                "Снимайте талона хоризонтално, така че полето (E) с VIN да се вижда ясно."
            )
        
            document_source = st.radio(
                "Как желаете да добавите талона?",
                ["Снимай с камера", "Качи готов файл"],
                horizontal=True,
                key="registration_document_source",
            )
        
            if document_source == "Снимай с камера":
        
                st.image(
                    APP_DIR / "vin_example.jpg",
                    caption="Пример как трябва да бъде сниман талонът",
                    use_container_width=True,
                )
        
                doc_camera = st.camera_input(
                    "Снимай талона",
                    key="registration_doc_camera",
                )
        
            else:
        
                doc_upload = st.file_uploader(
                    "Качи снимка или PDF на талона",
                    type=["jpg", "jpeg", "png", "pdf"],
                    key="registration_doc_upload",
                )
        
            document_file = doc_camera or doc_upload
        
            if document_file:
        
                doc_path = save_upload(
                    document_file,
                    DOC_DIR,
                    "talon",
                )
        
                st.success(
                    "Талонът е приложен успешно."
                )

    if st.button(
        "Потвърди и изпрати заявката",
        use_container_width=True,
        disabled=not valid_parts,
    ):
        wants_parts = wants.startswith("Да")
        if wants_parts and (not parts_comment or not vin or len(vin) != 17):
            st.error("Задължителни са описание и 17-символен VIN.")
            return

        reservation_date = date.fromisoformat(day_value)
        start_time_db = datetime.strptime(pending_start, "%H:%M").time()
        end_time_db = datetime.strptime(pending_end, "%H:%M").time()

        overlap = fetchone(
            """SELECT id FROM reservations
               WHERE reservation_date=%s
                 AND status NOT IN ('Отказана','Анулирана')
                 AND start_time < %s
                 AND end_time > %s
               LIMIT 1""",
            (reservation_date, end_time_db, start_time_db),
        )
        if overlap:
            st.error("Избраният период вече съдържа зает час. Избери друг период.")
            st.session_state.pop("pending_slot", None)
            st.rerun()

        try:
            execute(
                """INSERT INTO reservations(
                       user_id,reservation_date,start_time,end_time,wants_parts,
                       parts_comment,vin,registration_doc,parts_status
                   ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    user_id,
                    reservation_date,
                    start_time_db,
                    end_time_db,
                    wants_parts,
                    parts_comment,
                    vin,
                    doc_path,
                    "Очаква преглед" if wants_parts else None,
                ),
            )
            st.session_state.pop("pending_slot", None)
            st.session_state.client_flash = (
                f"Потвърдено: резервацията е изпратена за {day_value}, "
                f"от {pending_start} до {pending_end}."
            )
            st.rerun()
        except IntegrityError:
            st.error("Началният час току-що е резервиран. Избери друг период.")
            st.session_state.pop("pending_slot", None)
            st.rerun()

def history(user_id):
    st.subheader("История на резервациите")
    rows=fetchall("SELECT * FROM reservations WHERE user_id=%s ORDER BY reservation_date DESC,start_time DESC",(user_id,))
    if not rows: st.info("Все още няма резервации."); return
    for r in rows:
        day=r["reservation_date"].isoformat()
        start_hour=r["start_time"].strftime("%H:%M")
        end_hour=r["end_time"].strftime("%H:%M")
        with st.expander(f"{day} • {start_hour}–{end_hour} • {r['status']}"):
            st.write("**Заявка за части:**","Да" if r["wants_parts"] else "Не")
            if r["parts_status"]: st.write("**Статус части:**",r["parts_status"])
            if r.get("parts_offer"): st.info(r["parts_offer"])
            if r["admin_note"]: st.write("**Съобщение от сервиза:**",r["admin_note"])
            if r["door_pin"]: st.success(f"PIN за вход: {r['door_pin']}")
            if r.get("customer_parts_decision"):
                st.write("**Вашето решение:**",r["customer_parts_decision"])
                if r.get("customer_parts_comment"): st.write("**Вашият избор:**",r["customer_parts_comment"])
            elif r["wants_parts"] and r["parts_status"]=="Можем да подготвим" and r.get("parts_offer"):
                decision=st.radio("Изберете решение",["Избери","Искам","Отказвам"],key=f"dec_{r['id']}")
                comment=""
                if decision=="Искам":
                    comment=st.text_area("Кой вариант желаете? *",placeholder="Например: Искам диск 1 – 50 евро.",key=f"com_{r['id']}")
                elif decision=="Отказвам":
                    comment=st.text_area("Коментар (по желание)",key=f"com_{r['id']}")
                if st.button("Потвърди избора",key=f"confirm_{r['id']}",use_container_width=True):
                    if decision=="Избери": st.error("Изберете Искам или Отказвам.")
                    elif decision=="Искам" and not comment.strip(): st.error("Напишете кой вариант желаете.")
                    else:
                        ps="Клиентът потвърди" if decision=="Искам" else "Клиентът отказа"
                        execute("""UPDATE reservations SET customer_parts_decision=%s,customer_parts_comment=%s,
                                   customer_parts_responded_at=NOW(),parts_status=%s WHERE id=%s AND user_id=%s""",
                                (decision,comment.strip() or None,ps,r["id"],user_id))
                        if decision == "Искам":
                            st.session_state.client_flash = f"Потвърдено: приехте предложението за части. Избран вариант: {comment.strip()}"
                        else:
                            st.session_state.client_flash = "Потвърдено: отказахте предложението за части."
                        st.rerun()

def technical_issue(user_id):

    st.subheader("Технически проблем")

    with st.form("issue_form"):

        category = st.selectbox(
            "Категория",
            [
                "Подемник",
                "Инструменти",
                "Врата / smart lock",
                "Осветление",
                "Друго",
            ],
        )

        description = st.text_area(
            "Опиши проблема *"
        )

        add_photo = st.toggle(
            "📷 Добави снимка към сигнала"
        )

        photo = None

        if add_photo:
            photo = st.camera_input(
                "Снимай проблема"
            )

        submit = st.form_submit_button(
            "Изпрати сигнал",
            use_container_width=True,
        )

    if submit:

        if not description.strip():
            st.error("Добави описание.")

        else:
            execute(
                "INSERT INTO technical_issues(user_id,category,description,photo) VALUES(%s,%s,%s,%s)",
                (
                    user_id,
                    category,
                    description.strip(),
                    save_upload(photo, DOC_DIR, "issue"),
                ),
            )

            st.success("Сигналът е изпратен.")

def client_panel():
    user = fetchone("SELECT * FROM users WHERE id=%s", (st.session_state.user_id,))

    if "client_page" not in st.session_state:
        st.session_state.client_page = "Начало"

    st.markdown('<div class="hero">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.image(APP_DIR / "Designer (27).jpg")
    st.markdown(
        f"<p style='text-align:center;color:white;'>Здравей, {user['first_name']}.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    nav_items = [
        ("🏠 Начало", "Начало"),
        ("📅 Запази час", "Запази час"),
        ("🧾 Моите резервации", "Моите резервации"),
        ("🛠 Технически проблем", "Технически проблем"),
    ]
    nav_columns = st.columns(4)
    for column, (label, page_name) in zip(nav_columns, nav_items):
        with column:
            if st.button(
                label,
                key=f"client_nav_{page_name}",
                use_container_width=True,
                type="primary" if st.session_state.client_page == page_name else "secondary",
            ):
                st.session_state.client_page = page_name
                st.rerun()

    with st.sidebar:
        st.write(f"**{user['first_name']} {user['last_name']}**")
        if st.button("🏠 Начало", key="sidebar_home", use_container_width=True):
            st.session_state.client_page = "Начало"
            st.rerun()
        if st.button("👤 Моят профил", key="sidebar_profile", use_container_width=True):
            st.session_state.client_page = "Моят профил"
            st.rerun()
        if st.button("Изход", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    if st.session_state.get("client_flash"):
        st.success(st.session_state.pop("client_flash"))

    page = st.session_state.client_page
    st.markdown("---")
    if page == "Начало":
        video_section()
    elif page == "Запази час":
        new_reservation(user["id"])
    elif page == "Моите резервации":
        history(user["id"])
    elif page == "Технически проблем":
        technical_issue(user["id"])
    else:
        st.subheader("Моят профил")
        st.write(f"**Име:** {user['first_name']} {user['last_name']}")
        st.write(f"**Телефон:** {user['phone']}")
        st.write(f"**Имейл:** {user['email'] or '—'}")

def admin_reservations():
    st.subheader("Мониторинг на резервациите")
    statuses=["Очаква потвърждение","Потвърдена","Отказана","Завършена"]
    selected=st.multiselect("Статус",statuses,default=statuses[:2])
    rows=fetchall("""SELECT r.*,u.first_name,u.last_name,u.phone FROM reservations r
                     JOIN users u ON u.id=r.user_id
                     WHERE r.status NOT IN ('Завършена','Отказана')
                     ORDER BY r.reservation_date,r.start_time""")
    rows=[r for r in rows if not selected or r["status"] in selected]
    part_statuses=["—","Очаква преглед","Можем да подготвим","Не можем да подготвим","Клиентът потвърди","Клиентът отказа","Подготвени"]
    for r in rows:
        day=r["reservation_date"].isoformat()
        start_hour=r["start_time"].strftime("%H:%M")
        end_hour=r["end_time"].strftime("%H:%M")
        with st.expander(f"#{r['id']} • {day} {start_hour}–{end_hour} • {r['first_name']} {r['last_name']} • {r['status']}"):
            st.write(f"**Телефон:** {r['phone']}"); st.write("**Части:**","Да" if r["wants_parts"] else "Не")
            if r["wants_parts"]:
                st.write("**VIN:**",r["vin"] or "—"); st.write("**Заявка:**",r["parts_comment"] or "—")
            if r.get("customer_parts_decision"):
                st.success(f"Решение на клиента: {r['customer_parts_decision']}")
                st.write("**Избор/коментар:**",r.get("customer_parts_comment") or "—")
            c1,c2=st.columns(2)
            ns=c1.selectbox("Статус резервация",statuses,index=statuses.index(r["status"]),key=f"s_{r['id']}")
            cur=r["parts_status"] if r["parts_status"] in part_statuses else "—"
            ps=c2.selectbox("Статус части",part_statuses,index=part_statuses.index(cur),key=f"p_{r['id']}")
            offer=st.text_area("Предложение за части",value=r.get("parts_offer") or "",placeholder="Диск 1 – 50 евро\nДиск 2 – 40 евро",key=f"off_{r['id']}",disabled=not r["wants_parts"])
            note=st.text_area("Съобщение към клиента",value=r["admin_note"] or "",key=f"n_{r['id']}")
            pin=st.text_input("PIN",value=r["door_pin"] or "",key=f"pin_{r['id']}")
            if st.button("Запази промените",key=f"save_{r['id']}",use_container_width=True):
                if ps=="Можем да подготвим" and not offer.strip(): st.error("Добавете предложение за части.")
                else:
                    execute("UPDATE reservations SET status=%s,parts_status=%s,parts_offer=%s,admin_note=%s,door_pin=%s WHERE id=%s",
                            (ns,None if ps=="—" else ps,offer.strip() or None,note.strip() or None,pin.strip() or None,r["id"]))
                    st.session_state.admin_flash = (
                        f"Потвърдено: резервация #{r['id']} е обновена. "
                        f"Статус: {ns}. Статус части: {ps}."
                    )
                    st.rerun()


def admin_archive():
    st.subheader("Архив")
    a,b=st.columns(2); d1=a.date_input("От",date.today()-timedelta(days=90)); d2=b.date_input("До",date.today())
    rows=fetchall("""SELECT r.*,u.first_name,u.last_name,u.phone FROM reservations r JOIN users u ON u.id=r.user_id
                   WHERE reservation_date BETWEEN %s AND %s AND status IN ('Завършена','Отказана') ORDER BY reservation_date DESC,start_time DESC""",(d1,d2))
    st.metric("Архивирани",len(rows))
    for r in rows:
        with st.expander(
            f"{r['status']} • {r['reservation_date']} "
            f"{r['start_time'].strftime('%H:%M')}–{r['end_time'].strftime('%H:%M')} • "
            f"{r['first_name']} {r['last_name']}"
        ):
            st.write("**Телефон:**",r["phone"]); st.write("**Оферта:**",r.get("parts_offer") or "—"); st.write("**Решение:**",r.get("customer_parts_decision") or "—"); st.write("**Коментар:**",r.get("customer_parts_comment") or "—")


    st.markdown("### Решени технически сигнали")
    solved_issues = fetchall("""SELECT t.*,u.first_name,u.last_name FROM technical_issues t
                              JOIN users u ON u.id=t.user_id
                              WHERE t.status='Решено'
                              ORDER BY t.id DESC""")
    if not solved_issues:
        st.info("Няма решени технически сигнали.")
    for issue in solved_issues:
        with st.expander(f"Решено • #{issue['id']} • {issue['category']} • {issue['first_name']} {issue['last_name']}"):
            st.write(issue["description"])
            st.caption(f"Създадено: {issue['created_at'].strftime('%d.%m.%Y %H:%M')}")


def admin_statistics():
    st.subheader("Статистика")
    a,b=st.columns(2); d1=a.date_input("Период от",date.today()-timedelta(days=30),key="sf"); d2=b.date_input("Период до",date.today(),key="st")
    q=fetchone("""SELECT COUNT(*) total,COUNT(*) FILTER(WHERE status='Потвърдена') confirmed,
      COUNT(*) FILTER(WHERE status='Завършена') completed,COUNT(*) FILTER(WHERE status='Отказана') cancelled,
      COUNT(*) FILTER(WHERE wants_parts) parts,COUNT(*) FILTER(WHERE customer_parts_decision='Искам') accepted
      FROM reservations WHERE reservation_date BETWEEN %s AND %s""",(d1,d2))
    cols=st.columns(6)
    for col,label,key in zip(cols,["Общо","Потвърдени","Завършени","Отказани","С части","Приети оферти"],["total","confirmed","completed","cancelled","parts","accepted"]): col.metric(label,int(q[key] or 0))
    daily=fetchall("SELECT reservation_date,COUNT(*) total FROM reservations WHERE reservation_date BETWEEN %s AND %s GROUP BY reservation_date ORDER BY reservation_date",(d1,d2))
    if daily: st.line_chart({r["reservation_date"].isoformat():int(r["total"]) for r in daily})

def admin_panel():
    # Browser timer triggers a rerun every 240000 ms (4 minutes).
    st.components.v1.html(
        """
        <script>
        setTimeout(function() {
            window.parent.location.reload();
        }, 240000);
        </script>
        """,
        height=0,
    )

    st.markdown('<div class="hero">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.image(APP_DIR / "Designer (27).jpg")
    st.markdown(
        "<p style='text-align:center;color:white;'>Административен панел</p>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    with st.sidebar:
        page = st.radio(
            "Админ меню",
            ["Табло", "Резервации", "Архив", "Статистика", "Технически сигнали", "Видео съдържание", "Настройки"],
        )
        st.caption("🔄 Автоматично обновяване на всеки 4 минути")
        if st.button("Изход"):
            st.session_state.clear()
            st.rerun()

    if st.session_state.get("admin_flash"):
        st.success(st.session_state.pop("admin_flash"))

    if page == "Табло":
        pending = fetchone("SELECT COUNT(*) AS c FROM reservations WHERE status='Очаква потвърждение'")["c"]
        parts = fetchone("""SELECT COUNT(*) AS c FROM reservations
                          WHERE wants_parts=TRUE
                            AND status NOT IN ('Завършена','Отказана')
                            AND parts_status IN ('Очаква преглед','Можем да подготвим','Клиентът потвърди')""")["c"]
        issues = fetchone("SELECT COUNT(*) AS c FROM technical_issues WHERE status='Ново'")["c"]
        users = fetchone("SELECT COUNT(*) AS c FROM users")["c"]
        for col,label,value in zip(
            st.columns(4),
            ["Чакащи резервации","Заявки за части","Нови сигнали","Клиенти"],
            [pending,parts,issues,users],
        ):
            col.metric(label,value)
    elif page == "Резервации":
        admin_reservations()
    elif page == "Архив":
        admin_archive()
    elif page == "Статистика":
        admin_statistics()
    elif page == "Технически сигнали":
        rows = fetchall("""SELECT t.*,u.first_name,u.last_name FROM technical_issues t
                         JOIN users u ON u.id=t.user_id
                         WHERE t.status<>'Решено'
                         ORDER BY t.id DESC""")
        if not rows:
            st.info("Няма активни технически сигнали.")
        for r in rows:
            with st.expander(f"#{r['id']} • {r['category']} • {r['first_name']} {r['last_name']} • {r['status']}"):
                st.write(r["description"])
                status_options = ["Ново", "В работа", "Решено"]
                new = st.selectbox(
                    "Статус",
                    status_options,
                    index=status_options.index(r["status"]),
                    key=f"is_{r['id']}",
                )
                if st.button("Обнови", key=f"iu_{r['id']}"):
                    execute("UPDATE technical_issues SET status=%s WHERE id=%s", (new,r["id"]))
                    if new == "Решено":
                        st.session_state.admin_flash = f"Потвърдено: сигнал #{r['id']} е решен и преместен в Архив."
                    else:
                        st.session_state.admin_flash = f"Потвърдено: сигнал #{r['id']} е със статус „{new}“."
                    st.rerun()
    elif page == "Видео съдържание":
        with st.form("videos"):
            urls = [st.text_input(f"Видео {i}", value=setting(f"youtube_{i}")) for i in range(1,4)]
            if st.form_submit_button("Запази видеата", use_container_width=True):
                for i,url in enumerate(urls,1):
                    set_setting(f"youtube_{i}",url.strip())
                st.success("Потвърдено: видеата са обновени.")
    else:
        with st.form("settings_form"):
            opening = st.text_input("Отваряне", value=setting("open_hour"))
            closing = st.text_input("Затваряне", value=setting("close_hour"))
            duration = st.number_input("Слот (минути)", 30, 240, int(setting("slot_minutes")), 30)
            new_pin = st.text_input("Нов администраторски PIN", type="password")
            if st.form_submit_button("Запази настройки"):
                datetime.strptime(opening,"%H:%M")
                datetime.strptime(closing,"%H:%M")
                set_setting("open_hour",opening)
                set_setting("close_hour",closing)
                set_setting("slot_minutes",duration)
                if new_pin:
                    set_setting("admin_pin_hash",hash_value(new_pin))
                st.success("Потвърдено: настройките са запазени.")

try:
    init_db()
except Exception as exc:
    st.error("Неуспешна връзка с Neon. Провери DATABASE_URL в Render.")
    st.code(str(exc))
    st.stop()

apply_style()

if "role" not in st.session_state:

    st.markdown('<div class="hero">', unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 2, 1])

    with c2:
        st.image(APP_DIR / "Designer (27).jpg")

    st.markdown(
        "<p style='text-align:center;color:white;font-size:18px;'>"
        "Резервация • Части • Достъп • Самообслужване"
        "</p>",
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["Създай профил", "Вход"])

    with tab1:
        register_view()

    with tab2:
        login_view()

elif st.session_state.role == "client":
    client_panel()

else:
    admin_panel()
