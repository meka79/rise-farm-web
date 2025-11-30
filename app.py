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
st.set_page_config(page_title="Rise Farm (Cloud V40)", layout="wide", page_icon="☁️")
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

# --- DATA YÖNETİMİ ---
@st.cache_data(ttl=10)
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
            
        cols = ["Adet", "Birim_Fiyat", "Toplam_Deger", "Toplam_TL"]
        for c in cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        
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
    
    # HESAPLAMA DÜZELTME (GARANTİ)
    # 1 GB = 100.000.000 Coin = 360 TL
    # (Coin / 100_000_000) * 360
    
    gb_miktari = toplam_coin / 100000000.0
    toplam_tl = gb_miktari * GB_FIYATI_TL
    
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
                st.markdown("---")
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
            m_cat = mc1.selectbox("Kategori", list(ITEM_DB.keys()), key="mc")
            m_subs = list(ITEM_DB[m_cat].keys())
            m_sub = m_subs[0]
            if len(m_subs) > 1: m_sub = mc2.selectbox("Bölüm", m_subs, key="ms")
            m_items = list(ITEM_DB[m_cat][m_sub].keys()) + ["Diğer"]
            m_item = st.selectbox("Eşya", m_items, key="mi")
            def_price = 0
            fin_name = m_item
            if m_item == "Diğer" or m_cat == "Craft (Üretim)": fin_name = st.text_input("Adı", key="mni")
            else: def_price = ITEM_DB[m_cat][m_sub][m_item]
            with st.form("manual"):
                c1, c2, c3 = st.columns(3)
                mt = c1.date_input("Tarih", datetime.date.today(), key="md")
                mq = c2.number_input("Adet", min_value=1, value=1, key="mq")
                mp = c3.text_input("Fiyat", value=format_price(def_price), key="mp")
                mn = st.text_area("Not", key="mn")
                if st.form_submit_button("Kaydet"):
                    real_p = parse_price(mp)
                    if fin_name:
                        save_entry_cloud(CURRENT_USER, mt, m_cat, m_sub, fin_name, mq, real_p, mn)
                        st.success("Kaydedildi")
                    else: st.error("İsim girin")

    # --- SAYFA: PİYASA AYARLARI ---
    elif sayfa == "⚙️ Piyasa Ayarları":
        st.title("⚙️ Piyasa Ayarları")
        with st.expander("📤 Eski Fiyat Dosyasını Yükle (market_prices.json)", expanded=False):
            uploaded_file = st.file_uploader("Dosya Seç", type="json")
            if uploaded_file:
                if st.button("Fiyatları İçe Aktar"):
                    if upload_json_prices(uploaded_file):
                        st.success("Fiyatlar yüklendi!"); st.rerun()
                    else: st.error("Hata oluştu.")
        st.markdown("---")
        with st.container(border=True):
            e_cat = st.selectbox("Kategori", list(ITEM_DB.keys()))
            if e_cat == "Craft (Üretim)": st.warning("Manuel kategori.")
            else:
                e_sub = st.selectbox("Bölüm", list(ITEM_DB[e_cat].keys()))
                with st.form("prices"):
                    new_prices = {}
                    items = ITEM_DB[e_cat][e_sub]
                    item_l = list(items.items())
                    for i in range(0, len(item_l), 3):
                        chunk = item_l[i:i+3]
                        cols = st.columns(3)
                        for j, (nm, pr) in enumerate(chunk):
                            with cols[j]:
                                if nm == "Treasure Token": new_prices[nm] = pr; continue
                                new_prices[nm] = parse_price(st.text_input(nm, value=format_price(pr), key=f"p_{nm}"))
                    if "Treasure Token" in items:
                        new_prices["Treasure Token"] = items["Treasure Token"]
                        st.info(f"Treasure Token: {format_price(items['Treasure Token'])}")
                    if st.form_submit_button("Güncelle"):
                        if "Royal Chest" in new_prices:
                            new_prices["Treasure Token"] = int(new_prices["Royal Chest"] / 9)
                        ITEM_DB[e_cat][e_sub] = new_prices
                        if save_prices_cloud(ITEM_DB): st.success("Fiyatlar güncellendi!")

    # --- SAYFA: ANALİZ ---
    elif sayfa == "📊 Analiz & Defter":
        st.title("📊 Analiz")
        df = get_data_cached(CURRENT_USER)
        
        df_filtered = pd.DataFrame()
        if not df.empty: df_filtered = df.copy()
        
        if not df.empty:
            with st.expander("🔍 Filtrele", expanded=True):
                c1, c2, c3 = st.columns(3)
                opts = ["Tüm Zamanlar", "Bugün", "Son 7 Gün", "Bu Ay"]
                if PERIOD_DB: opts += [f"👑 {p}" for p in PERIOD_DB]
                d_fil = c1.selectbox("Dönem", opts)
                cat_fil = c2.multiselect("Kategori", df["Kategori"].unique())
                av_sub = df["Alt_Kategori"].unique()
                if cat_fil: av_sub = df[df["Kategori"].isin(cat_fil)]["Alt_Kategori"].unique()
                sub_fil = c3.multiselect("Bölüm", av_sub)
                
                act_p = None
                if d_fil == "Bugün": df_filtered = df_filtered[df_filtered["Tarih"] == pd.Timestamp.today().normalize()]
                elif d_fil == "Son 7 Gün": df_filtered = df_filtered[df_filtered["Tarih"] >= (pd.Timestamp.today() - timedelta(days=7))]
                elif d_fil == "Bu Ay": 
                    t = pd.Timestamp.today()
                    df_filtered = df_filtered[(df_filtered["Tarih"].dt.month == t.month) & (df_filtered["Tarih"].dt.year == t.year)]
                elif d_fil.startswith("👑"):
                    pn = d_fil.replace("👑 ", "")
                    if pn in PERIOD_DB:
                        act_p = pn
                        s = pd.to_datetime(PERIOD_DB[pn]["start"])
                        e = pd.to_datetime(PERIOD_DB[pn]["end"])
                        df_filtered = df_filtered[(df_filtered["Tarih"] >= s) & (df_filtered["Tarih"] <= e)]
                if cat_fil: df_filtered = df_filtered[df_filtered["Kategori"].isin(cat_fil)]
                if sub_fil: df_filtered = df_filtered[df_filtered["Alt_Kategori"].isin(sub_fil)]
            
            if act_p:
                rem = (pd.to_datetime(PERIOD_DB[act_p]["end"]).date() - datetime.date.today()).days
                st.info(f"👑 **{act_p}** | Kalan: {max(0, rem)} gün")
            
            tot_c = df_filtered["Toplam_Deger"].sum()
            tot_tl = df_filtered["Toplam_TL"].sum()
            c1, c2 = st.columns(2)
            c1.metric("💰 Kazanç", format_m(tot_c))
            c2.metric("🇹🇷 Değer", f"{tot_tl:,.0f} TL")
            
            st.markdown("---")
            t1, t2, t3 = st.tabs(["📅 Günlük", "📊 Özet", "🛠️ Geçmiş"])
            
            with t1:
                col_ozet, col_detay = st.columns([1, 1.5])
                ds = df_filtered.groupby(df_filtered["Tarih"].dt.date)[["Toplam_Deger", "Toplam_TL"]].sum().reset_index().sort_values("Tarih", ascending=False)
                ds["Coin"] = ds["Toplam_Deger"].apply(lambda x: f"{x/1000000:.2f}m")
                ds["TL"] = ds["Toplam_TL"].apply(lambda x: f"{x:.0f} TL")
                col_ozet.dataframe(ds[["Tarih", "Coin", "TL"]], use_container_width=True, hide_index=True)
                
                if not ds.empty:
                    sel_d = col_detay.selectbox("Detay Tarihi:", ds["Tarih"], format_func=lambda x: x.strftime("%d.%m"))
                    dd = df[df["Tarih"].dt.date == sel_d]
                    subs = dd["Alt_Kategori"].unique()
                    for s in subs:
                        sd = dd[dd["Alt_Kategori"] == s]
                        stotal = sd["Toplam_Deger"].sum()
                        grp = sd.groupby(["Eşya", "Birim_Fiyat"]).agg({"Adet":"sum", "Toplam_Deger":"sum"}).reset_index()
                        grp["Birim"] = grp["Birim_Fiyat"].apply(format_price)
                        grp["Top"] = grp["Toplam_Deger"].apply(format_price)
                        with col_detay.expander(f"{s} | {format_price(stotal)}"):
                            st.dataframe(grp[["Eşya", "Adet", "Birim", "Top"]], use_container_width=True, hide_index=True)

            with t2:
                c_i, c_p = st.columns([1.5, 1])
                if not df_filtered.empty:
                    item_s = df_filtered.groupby(["Alt_Kategori", "Eşya"]).agg({"Adet":"sum", "Toplam_Deger":"sum"}).reset_index().sort_values("Toplam_Deger", ascending=False)
                    item_s["Gelir"] = item_s["Toplam_Deger"].apply(format_price)
                    c_i.dataframe(item_s[["Alt_Kategori", "Eşya", "Adet", "Gelir"]], use_container_width=True, hide_index=True)
                    cat_s = df_filtered.groupby("Alt_Kategori")["Toplam_Deger"].sum().reset_index()
                    cat_s["%"] = (cat_s["Toplam_Deger"] / cat_s["Toplam_Deger"].sum() * 100).map('{:.1f}%'.format)
                    c_p.dataframe(cat_s[["Alt_Kategori", "%"]], use_container_width=True, hide_index=True)
            
            with t3:
                df_show = df_filtered.sort_values("Tarih", ascending=False)
                st.dataframe(df_show, use_container_width=True)
                col_del1, col_del2 = st.columns([3, 1])
                with col_del1:
                    delete_options = df_show.apply(lambda x: f"{x.name} | {x['Tarih'].strftime('%d.%m')} - {x['Eşya']} ({x['Adet']} ad.)", axis=1)
                    sel_rec = st.selectbox("İşlem Seç:", delete_options, index=None, placeholder="Kayıt seç...")
                if sel_rec:
                    idx = int(sel_rec.split(" | ")[0])
                    rec = df.loc[idx]
                    b1, b2 = st.columns(2)
                    if b1.button("🗑️ Sil", type="primary"):
                        if delete_row_by_ui_index(df_filtered, idx): st.success("Silindi!"); st.rerun()
                        else: st.error("Hata.")
                    if b2.button("✏️ Düzenle"):
                        st.session_state['edit_mode'] = True; st.session_state['edit_idx'] = idx
                    if st.session_state.get('edit_mode') and st.session_state.get('edit_idx') == idx:
                        with st.form("edit_form"):
                            e_tarih = st.date_input("Tarih", rec["Tarih"])
                            e_adet = st.number_input("Adet", value=int(rec["Adet"]), min_value=1)
                            e_fiyat = st.number_input("Birim Fiyat", value=int(rec["Birim_Fiyat"]), step=1000)
                            e_not = st.text_area("Not", value=str(rec["Notlar"]))
                            if st.form_submit_button("💾 Güncelle"):
                                new_d = {'Tarih': e_tarih, 'Adet': e_adet, 'Birim_Fiyat': e_fiyat, 'Notlar': e_not}
                                if update_row_by_ui_index(df_filtered, idx, new_d):
                                    del st.session_state['edit_mode']; del st.session_state['edit_idx']
                                    st.success("Güncellendi!"); st.rerun()
                                else: st.error("Hata.")
                with st.expander("🗑️ Veri Tabanı Temizliği"):
                    if st.button("TÜM KAYITLARIMI SİL"):
                        if clear_user_data(CURRENT_USER): st.success("Temizlendi."); st.rerun()
        else:
            st.info("Kayıt yok.")
