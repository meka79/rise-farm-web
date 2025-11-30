import streamlit as st
import pandas as pd
import datetime
from datetime import timedelta
import gspread
from google.oauth2.service_account import Credentials
import json
import time
import plotly.express as px

# --- AYARLAR ---
st.set_page_config(page_title="Rise Farm (Cloud V42)", layout="wide", page_icon="☁️")
GB_FIYATI_TL = 360.0

# --- AUTH & BAĞLANTI ---
@st.cache_resource
def get_google_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(st.secrets["gcp_service_account"]["json_content"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open("rise_farm_db")

# --- SHEET BAŞLATUCU ---
def init_sheets():
    sh = get_google_sheet()
    try: sh.worksheet("Logs")
    except: 
        ws = sh.add_worksheet("Logs", 1000, 11)
        ws.append_row(["Sahip", "Tarih", "Kategori", "Alt_Kategori", "Eşya", "Adet", "Birim_Fiyat", "Toplam_Deger", "Toplam_TL", "Notlar"])
    
    try: sh.worksheet("Prices")
    except: sh.add_worksheet("Prices", 1000, 3)
    
    try: sh.worksheet("Periods")
    except: 
        ws = sh.add_worksheet("Periods", 100, 4)
        ws.append_row(["Sahip", "Donem_Adi", "Baslangic", "Bitis"])
    return sh

# --- YARDIMCI FONKSİYONLAR ---
def parse_price(value_str):
    if isinstance(value_str, (int, float)): return int(value_str)
    s = str(value_str).lower().strip().replace(',', '.')
    multiplier = 1
    if s.endswith('k'): multiplier = 1_000; s = s[:-1]
    elif s.endswith('m'): multiplier = 1_000_000; s = s[:-1]
    try: return int(float(s) * multiplier)
    except: return 0

def format_price(value):
    try: val = float(value)
    except: return str(value)
    if val >= 1_000_000: return f"{val/1_000_000:g}m"
    elif val >= 1_000: return f"{val/1_000:g}k"
    return str(int(val))

def format_m(deger):
    return f"{deger/1_000_000:.2f} m"

# --- DATA YÖNETİMİ (AKILLI OKUMA) ---
@st.cache_data(ttl=5)
def get_data_cached(username):
    try:
        sh = get_google_sheet()
        ws = sh.worksheet("Logs")
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        if df.empty: return pd.DataFrame(columns=["Sahip", "Tarih", "Kategori", "Alt_Kategori", "Eşya", "Adet", "Birim_Fiyat", "Toplam_Deger", "Toplam_TL", "Notlar"])
        
        if "Sahip" in df.columns:
            df = df[df["Sahip"] == username]
        else:
            return pd.DataFrame()
            
        # --- HATA DÜZELTME BURADA ---
        # Türkçe Google Sheets virgül (,) kullanır, Python nokta (.) ister.
        # Virgülü silmek yerine NOKTAYA çeviriyoruz.
        
        def clean_number(x):
            s = str(x).strip()
            # Eğer sadece virgül varsa (örn: 172,8) onu noktaya çevir
            if ',' in s and '.' not in s:
                s = s.replace(',', '.')
            # Eğer hem nokta hem virgül varsa (örn: 1.200,50) binlik noktasını sil, virgülü nokta yap
            elif ',' in s and '.' in s:
                s = s.replace('.', '').replace(',', '.')
            return pd.to_numeric(s, errors='coerce')

        cols = ["Adet", "Birim_Fiyat", "Toplam_Deger", "Toplam_TL"]
        for c in cols:
            if c in df.columns:
                df[c] = df[c].apply(clean_number).fillna(0)
        
        if "Tarih" in df.columns:
            df["Tarih"] = pd.to_datetime(df["Tarih"], errors='coerce')
            
        return df
    except: return pd.DataFrame()

def clear_cache():
    st.cache_data.clear()

def save_entry_cloud(username, tarih, kategori, alt_kategori, esya, adet, fiyat, notlar):
    sh = get_google_sheet()
    ws = sh.worksheet("Logs")
    
    toplam_coin = adet * fiyat
    
    # HESAPLAMA
    toplam_tl = (toplam_coin / 100_000_000.0) * GB_FIYATI_TL
    
    tarih_str = tarih.strftime("%Y-%m-%d")
    row = [username, tarih_str, kategori, alt_kategori, esya, adet, fiyat, toplam_coin, toplam_tl, notlar]
    ws.append_row(row)
    clear_cache()
    return True

# --- SİLME VE GÜNCELLEME ---
def delete_row_by_ui_index(df_user, ui_index):
    sh = get_google_sheet()
    ws = sh.worksheet("Logs")
    all_values = ws.get_all_values()
    
    target_row = df_user.loc[ui_index]
    target_date = str(target_row['Tarih'].strftime('%Y-%m-%d')) if pd.notnull(target_row['Tarih']) else ""
    
    row_to_del = -1
    for i, row in enumerate(all_values):
        if i == 0: continue
        if (len(row) > 5 and 
            str(row[0]) == str(target_row['Sahip']) and 
            str(row[1]) == target_date and
            str(row[4]) == str(target_row['Eşya']) and
            str(row[5]) == str(target_row['Adet'])):
            row_to_del = i + 1
            break
            
    if row_to_del != -1:
        ws.delete_rows(row_to_del)
        clear_cache()
        return True
    return False

def update_row_by_ui_index(df_user, ui_index, new_data):
    if delete_row_by_ui_index(df_user, ui_index):
        old = df_user.loc[ui_index]
        save_entry_cloud(
            old['Sahip'],
            new_data['Tarih'],
            old['Kategori'],
            old['Alt_Kategori'],
            old['Eşya'],
            new_data['Adet'],
            new_data['Birim_Fiyat'],
            new_data['Notlar']
        )
        return True
    return False

def clear_user_data(username):
    sh = get_google_sheet()
    ws = sh.worksheet("Logs")
    all_values = ws.get_all_values()
    keep = [all_values[0]] + [row for row in all_values[1:] if str(row[0]) != username]
    ws.clear()
    ws.append_rows(keep)
    clear_cache()
    return True

# --- FİYAT YÖNETİMİ ---
BASE_DB = {
    "Gathering (Toplama)": {
        "Woodcutting (Odunculuk)": {"Oak Wood": 12000, "Pine Wood": 15000, "Aspen Wood": 20000, "Birch Wood": 25000, "🌟 Holywood": 1400000, "🌟 Firefly Wood": 600000, "🌟 Soulsage": 700000},
        "Mining (Madencilik)": {"Copper Ore": 10000, "Iron Ore": 20000, "Titanium Ore": 50000, "Gold Ore": 80000, "🌟 Silver Dust": 150000, "🌟 Gold Dust": 250000},
        "Quarrying (Taşçılık)": {"Rough Stone": 5000, "Marble": 15000, "Granite": 25000, "🌟 Sphere of Fire": 300000, "🌟 Sphere of Water": 300000, "🌟 Sphere of Air": 300000, "🌟 Poison Essence": 400000},
        "Archaeology (Arkeoloji)": {"Crude Amber": 30000, "Crude Amethyst": 30000, "Crude Emerald": 30000, "Crude Ruby": 30000, "Crude Sapphire": 30000, "Crude Topaz": 30000, "🌟 Rare Obsidian": 1500000},
        "Fishing (Balıkçılık)": {"Fish": 5000, "Lobster": 25000, "🌟 Pearl": 500000, "🌟 Golden Fish": 2000000},
        "Harvesting (Çiftçilik)": {"Carrot": 1000, "Corn": 1500, "Cotton Fiber": 8000, "Potato": 2000, "Tomato": 2500, "Asparagus": 3000, "Mushroom": 3500, "Garlic": 4000, "Onion": 2500, "Grape": 3000, "Lemon": 3500, "Pepper": 4000, "Zucchini": 2500},
        "Skinning (Dericilik)": {"Meat": 500, "Stag Hide": 2000, "Boar Hide": 4000, "Tiger Hide": 8000, "Bear Hide": 12000, "Zebra Hide": 3000, "Wolf Hide": 5000, "Leopard Hide": 10000, "Elephant Hide": 15000},
        "Herbalism (Bitkicilik)": {"Cranberry": 3000, "Sage": 5000, "Valerian": 7000, "Vervain": 9000}
    },
    "Etkinlikler": {
        "Crystals (Kristaller)": {"Green Crystal": 100000, "Yellow Crystal": 200000, "Red Crystal": 300000, "Onyx Crystal": 500000},
        "Chests (Kutular)": {"Treasure Token": 500000, "Gold Chest": 3000000, "Royal Chest": 5000000, "Golden Jade": 10000000, "Celestial Chest": 15000000}
    },
    "Droplar (Mob & Boss)": {
        "Genel Liste": {"Skill Book": 1000000, "Epic Upgrade Scroll": 3000000, "Unique Upgrade Scroll": 15000000, "Relic Upgrade Scroll": 5000000, "Epic Weapon Shard": 500000}
    },
    "Craft (Üretim)": {"Manuel Giriş": {}},
    "Upgrade (Basma)": {"Genel": {"Basılmış (+7) İtem": 50000000, "Basılmış (+8) İtem": 500000000, "Yanan İtem (Gider)": 0}}
}

@st.cache_data(ttl=300)
def get_prices_cloud():
    active_db = BASE_DB.copy()
    try:
        sh = get_google_sheet()
        ws = sh.worksheet("Prices")
        records = ws.get_all_records()
        price_map = {str(r['Item']): int(r['Price']) for r in records}
        for cat in active_db:
            for sub in active_db[cat]:
                for item in active_db[cat][sub]:
                    if item in price_map:
                        active_db[cat][sub][item] = price_map[item]
        return active_db
    except: return active_db

def save_prices_cloud(current_db):
    sh = get_google_sheet()
    ws = sh.worksheet("Prices")
    ws.clear()
    ws.append_row(["Item", "Price"])
    rows = []
    for cat in current_db:
        for sub in current_db[cat]:
            for item, price in current_db[cat][sub].items():
                rows.append([item, price])
    ws.append_rows(rows)
    clear_cache()
    return True

def upload_json_prices(json_file):
    try:
        data = json.load(json_file)
        current_db = BASE_DB.copy()
        for cat in data:
            if cat in current_db:
                for sub in data[cat]:
                    if sub in current_db[cat]:
                        for item, price in data[cat][sub].items():
                            if item in current_db[cat][sub]:
                                current_db[cat][sub][item] = price
        save_prices_cloud(current_db)
        return True
    except: return False

# --- DÖNEMLER ---
@st.cache_data(ttl=60)
def get_periods_cloud(username):
    try:
        sh = get_google_sheet()
        ws = sh.worksheet("Periods")
        data = ws.get_all_records()
        periods = {}
        for r in data:
            if str(r.get('Sahip')) == username:
                periods[r['Donem_Adi']] = {"start": r['Baslangic'], "end": r['Bitis']}
        return periods
    except: return {}

def save_period_cloud(username, name, start, end):
    sh = get_google_sheet()
    ws = sh.worksheet("Periods")
    ws.append_row([username, name, str(start), str(end)])
    clear_cache()
    return True

def delete_period_cloud(username, name):
    sh = get_google_sheet()
    ws = sh.worksheet("Periods")
    all_data = ws.get_all_records()
    new_data = [d for d in all_data if not (str(d.get('Sahip')) == username and d['Donem_Adi'] == name)]
    ws.clear()
    ws.append_row(["Sahip", "Donem_Adi", "Baslangic", "Bitis"])
    rows = [[d.get('Sahip'), d['Donem_Adi'], d['Baslangic'], d['Bitis']] for d in new_data]
    if rows: ws.append_rows(rows)
    clear_cache()
    return True

# --- LOGIN ---
def check_login():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["username"] = ""

    if not st.session_state["logged_in"]:
        st.markdown("## 🔐 Rise Farm Giriş")
        with st.form("login_form"):
            user = st.text_input("Kullanıcı Adı")
            pwd = st.text_input("Şifre", type="password")
            if st.form_submit_button("Giriş Yap"):
                users_db = st.secrets.get("users", {})
                if user in users_db and users_db[user] == pwd:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = user
                    st.success("Giriş Başarılı!")
                    st.rerun()
                else: st.error("Hatalı kullanıcı adı veya şifre.")
        return False
    return True

# --- ANA UYGULAMA ---
if check_login():
    CURRENT_USER = st.session_state["username"]
    
    st.sidebar.success(f"👤 **{CURRENT_USER}**")
    if st.sidebar.button("Çıkış Yap"):
        st.session_state["logged_in"] = False
        st.rerun()
    
    st.sidebar.markdown("---")
    
    # Yenile Butonu
    if st.sidebar.button("🔄 Verileri Yenile"):
        clear_cache()
        st.rerun()
    
    sh = init_sheets()
    ITEM_DB = get_prices_cloud()
    PERIOD_DB = get_periods_cloud(CURRENT_USER)
    
    st.sidebar.title("Menü")
    sayfa = st.sidebar.radio("Git:", ["📝 Yeni Kayıt Ekle", "⚙️ Piyasa Ayarları", "📊 Analiz & Defter"])
    st.sidebar.markdown("---")
    
    with st.sidebar.expander("👑 Premium Yönetimi", expanded=False):
        new_p_name = st.text_input("Dönem Adı", placeholder="Örn: Kasım Farmı")
        new_p_start = st.date_input("Başlangıç", datetime.date.today())
        if st.button("Dönem Ekle"):
            if new_p_name:
                end_date = new_p_start + timedelta(days=30)
                save_period_cloud(CURRENT_USER, new_p_name, new_p_start, end_date)
                st.success("Eklendi!"); st.rerun()
        if PERIOD_DB:
            st.markdown("---")
            del_p = st.selectbox("Silinecek:", list(PERIOD_DB.keys()), index=None)
            if del_p and st.button("Sil"):
                delete_period_cloud(CURRENT_USER, del_p); st.rerun()

    st.sidebar.info(f"1 GB = **{GB_FIYATI_TL} TL**")

    # --- SAYFA: YENİ KAYIT ---
    if sayfa == "📝 Yeni Kayıt Ekle":
        st.title("📝 Yeni Kayıt (Cloud)")
        tab_toplu, tab_manuel = st.tabs(["📦 Toplu Giriş", "✍️ Manuel Giriş"])
        
        with tab_toplu:
            cats = ["Gathering (Toplama)", "Etkinlikler", "Droplar (Mob & Boss)", "Upgrade (Basma)"]
            c1, c2 = st.columns(2)
            sec_cat = c1.selectbox("Kategori", cats, key="bc")
            alt_kats = list(ITEM_DB[sec_cat].keys())
            if sec_cat == "Gathering (Toplama)":
                desired = ["Woodcutting (Odunculuk)", "Mining (Madencilik)", "Quarrying (Taşçılık)", "Archaeology (Arkeoloji)", "Fishing (Balıkçılık)", "Harvesting (Çiftçilik)", "Skinning (Dericilik)", "Herbalism (Bitkicilik)"]
                alt_kats = [x for x in desired if x in alt_kats] + [x for x in alt_kats if x not in desired]
            sec_sub = alt_kats[0]
            if len(alt_kats) > 1: sec_sub = c2.selectbox("Bölüm", alt_kats, key="bs")
            st.markdown("---")
            d1, d2 = st.columns([1,3])
            tarih = d1.date_input("Tarih", datetime.date.today(), key="bd")
            notlar = d2.text_input("Not", key="bn")
            st.subheader(f"📦 {sec_sub}")
            with st.form("batch"):
                items = ITEM_DB[sec_cat][sec_sub]
                inputs = {}
                item_list = list(items.items())
                for i in range(0, len(item_list), 3):
                    chunk = item_list[i:i+3]
                    cols = st.columns(3)
                    for j, (name, price) in enumerate(chunk):
                        with cols[j]:
                            inputs[name] = st.number_input(f"{name}", min_value=0, step=1, help=f"Piyasa: {format_price(price)}", key=f"q_{name}")
                if st.form_submit_button("💾 Kaydet"):
                    count = 0
                    for nm, qty in inputs.items():
                        if qty > 0:
                            prc = ITEM_DB[sec_cat][sec_sub][nm]
                            save_entry_cloud(CURRENT_USER, tarih, sec_cat, sec_sub, nm, qty, prc, notlar)
                            count += 1
                    if count > 0: st.success(f"{count} kalem eklendi!"); st.toast("Kaydedildi!")
                    else: st.warning("Adet giriniz.")

        with tab_manuel:
            mc1, mc2 = st.columns(2)
            m
