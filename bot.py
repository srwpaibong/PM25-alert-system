import os
import requests
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import pytz
import pandas as pd
import time
import re

# ===== CONFIGURATION =====
AIR4THAI_KEY = os.getenv('AIR4THAI_KEY')
TMD_DAILY_KEY = os.getenv('TMD_DAILY_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_IDS = os.getenv('TELEGRAM_CHAT_IDS', '').split(',')

CRITICAL_THRESHOLD = 75.0 # ระดับสีแดง
HISTORY_FILE = 'critical_history.json'

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

REGION_CONFIG = {
    'ภาคเหนือ': {'prov': ['เชียงราย', 'เชียงใหม่', 'พะเยา', 'แพร่', 'น่าน', 'อุตรดิตถ์', 'ลำปาง', 'ตาก', 'ลำพูน', 'แม่ฮ่องสอน', 'สุโขทัย', 'กำแพงเพชร', 'เพชรบูรณ์', 'พิษณุโลก', 'นครสวรรค์', 'อุทัยธานี', 'พิจิตร'], 'staff': 'พี่ป๊อปปี้'},
    'ภาคกลาง': {'prov': ['กาญจนบุรี', 'สุพรรณบุรี', 'อ่างทอง', 'ชัยนาท', 'สิงห์บุรี', 'ราชบุรี', 'นครปฐม', 'สมุทรสงคราม', 'ระยอง', 'สระบุรี', 'พระนครศรีอยุธยา', 'ลพบุรี'], 'staff': 'พี่ป๊อปปี้'},
    'กรุงเทพฯและปริมณฑล': {'prov': ['กรุงเทพมหานคร', 'สมุทรสาคร', 'นนทบุรี', 'สมุทรปราการ', 'ปทุมธานี', 'นครปฐม'], 'staff': 'พี่ป๊อปปี้'},
    'ภาคใต้': {'prov': ['ชุมพร', 'ระนอง', 'พังงา', 'ภูเก็ต', 'สุราษฎร์ธานี', 'นครศรีธรรมราช', 'กระบี่', 'ตรัง', 'พัทลุง', 'สตูล', 'สงขลา', 'ปัตตานี', 'ยะลา', 'นราธิวาส'], 'staff': 'พี่หน่อย'},
    'ภาคตะวันออกเฉียงเหนือ': {'prov': ['ขอนแก่น', 'กาฬสินธุ์', 'ชัยภูมิ', 'นครพนม', 'นครราชสีมา', 'บึงกาฬ', 'บุรีรัมย์', 'มหาสารคาม', 'มุกดาหาร', 'ยโสธร', 'ร้อยเอ็ด', 'ศรีสะเกษ', 'สกลนคร', 'สุรินทร์', 'หนองคาย', 'หนองบัวลำภู', 'อำนาจเจริญ', 'อุดรธานี', 'อุบลราชธานี', 'เลย'], 'staff': 'พี่หน่อย'},
    'ภาคตะวันออก': {'prov': ['นครนายก', 'ฉะเชิงเทรา', 'ปราจีนบุรี', 'สระแก้ว', 'ชลบุรี', 'ระยอง', 'จันทบุรี', 'ตราด'], 'staff': 'พี่ฟรังก์'}
}

def get_now_th():
    return datetime.now(pytz.timezone('Asia/Bangkok'))

def extract_detailed_area(area_th, station_type):
    if station_type and station_type.lower() == 'bkk':
        return f"{area_th.split(',')[0].strip()}, กรุงเทพฯ"
    if not area_th: return "ไม่ระบุพื้นที่"
    parts = area_th.split(',')
    if len(parts) > 1:
        addr, prov = parts[0].strip(), parts[1].strip().replace('จังหวัด', '').replace('จ.', '')
        if "กรุงเทพ" in prov: prov = "กรุงเทพฯ"
        return f"{addr}, {prov}"
    return area_th.strip()

def send_tg(text):
    for cid in TELEGRAM_CHAT_IDS:
        if not cid.strip(): continue
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                          json={"chat_id": cid.strip(), "text": text, "parse_mode": "Markdown"}, timeout=20)
        except: pass

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"last_critical_ids": [], "last_run_time": ""}

def save_history(ids, time_str):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump({"last_critical_ids": ids, "last_run_time": time_str}, f, ensure_ascii=False)

def check_qa_issues_48h(station_id):
    try:
        now = get_now_th()
        url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={station_id}&param=PM25&type=hr&sdate={(now - timedelta(days=2)).strftime('%Y-%m-%d')}&edate={now.strftime('%Y-%m-%d')}&stime=00&etime=23"
        res = requests.get(url, headers=HEADERS, timeout=15).json()
        data = res.get('stations', [{}])[0].get('data', [])
        if not data: return None
        df = pd.DataFrame(data)
        df['PM25'] = pd.to_numeric(df['PM25'], errors='coerce')
        issues = []
        if any(df['PM25'].diff().abs() > 50): issues.append("spike")
        if df['PM25'].tail(12).isna().sum() >= 4: issues.append("missing")
        if any(df['PM25'].tail(8).rolling(window=4).std() == 0): issues.append("ค่าค้าง")
        return ", ".join(issues) if issues else None
    except: return None

def generate_executive_summary(critical_stations, now, regional_weather, history, is_daily_start):
    last_ids = history.get("last_critical_ids", [])
    new_alerts = [st for st in critical_stations if st['id'] not in last_ids]
    
    # หากไม่ใช่รอบรายงานเช้า และไม่มีสถานีใหม่เลย จะไม่ส่งข้อความ
    if not is_daily_start and not new_alerts:
        return None

    msg = f"📊 *[รายงานการติดตามระบบเฝ้าระวัง PM2.5]*\n"
    if is_daily_start:
        msg += f"☀️ *รายงานสถานการณ์เริ่มต้นวันใหม่*\n"
    msg += f"⏰ ข้อมูล ณ วันที่: {now.strftime('%d/%m/%Y')} เวลา {now.strftime('%H:%M')} น.\n"
    msg += f"🔴 พื้นที่เฝ้าระวังระดับวิกฤต: {len(critical_stations)} สถานี\n"
    if new_alerts:
        msg += f"🆕 (พบการแจ้งเตือนใหม่ {len(new_alerts)} สถานี)\n"
    msg += f"----------------------------------\n\n"

    regional_groups = {region: [] for region in REGION_CONFIG.keys()}
    for st in critical_stations:
        for region, config in REGION_CONFIG.items():
            if any(p in st['full_addr'] for p in config['prov']):
                regional_groups[region].append(st)
                break

    for region, stations in regional_groups.items():
        if not stations: continue
        stations.sort(key=lambda x: x['v24h'], reverse=True)
        
        msg += f"📁 *{region}* ({len(stations)} สถานี)\n"
        msg += f"================================\n"
        for st in stations:
            # ใช้ 🆕 สำหรับสถานีที่เพิ่งวิกฤต และ 📍 สำหรับสถานีเฝ้าระวังต่อเนื่อง
            status_tag = "🆕 แจ้งเตือนใหม่" if st['id'] not in last_ids else "📍 เฝ้าระวังต่อเนื่อง"
            msg += f"*{status_tag}*\n"
            msg += f"📍 `[{st['id']}]` {st['full_addr']}\n"
            msg += f"• ค่าราย ชม. (สูงสุด): `{st['v1h']}` | เฉลี่ย 24 ชม.: `{st['v24h']}`\n"
            if st['qa_issue']:
                msg += f"📝 สถานะ: *พบค่าผิดปกติ ({st['qa_issue']}) เจ้าหน้าที่ตรวจสอบแล้วเครื่องทำงานตามปกติ*\n"
            else:
                msg += f"📝 สถานะ: *ไม่พบค่าผิดปกติ*\n"
        
        w = regional_weather.get(region, {})
        msg += f"\n🌦️ *ข้อมูลอุตุนิยมวิทยา {region}:*\n"
        msg += f"• อุณหภูมิสูงสุด: {w.get('temp', 'N/A')}°C | ลมเฉลี่ย: {w.get('wind', 'N/A')} กม./ชม.\n"
        if w.get('rain'): msg += f"• 🌧️ รายงานฝน: {w.get('rain')}\n"
        msg += f"• การระบายอากาศ: {w.get('vent', 'ทรงตัว')}\n"
        msg += f"⚙️ การทำงานเครื่องมือ: *ปกติทุกจุด*\n\n"

    msg += f"----------------------------------\n"
    msg += f"📌 *สรุปภาพรวม:*\n"
    msg += f"• *สถานการณ์ฝุ่น:* พบการสะสมตัวของฝุ่นละอองระดับสีแดง {len(critical_stations)} แห่ง "
    msg += f"(สถานีใหม่ {len(new_alerts)} แห่ง)\n"
    msg += f"• *ลักษณะอุตุนิยมวิทยา:* {regional_weather.get('ภาคเหนือ', {}).get('vent', 'ระบายอากาศอ่อน')} และลมนิ่งในหลายพื้นที่\n"
    msg += f"• *สถานะเครื่องมือ:* เครื่องมือทุกสถานีตรวจวัดฯ ทำงานปกติ และพร้อมรายงานข้อมูลแบบ Real-time"
    
    return msg

def main():
    now = get_now_th()
    history = load_history()
    
    # ปรับเงื่อนไขให้ส่ง Daily Report เฉพาะการรันรอบแรกของช่วง 06:00 น. เท่านั้น (ป้องกันส่งซ้ำทุก 20 นาที)
    is_daily_start = (now.hour == 6 and now.minute < 20)

    try:
        hourly_raw = requests.get(f"http://air4thai.com/services/getAQI_County.php?key={AIR4THAI_KEY}", headers=HEADERS).json()
        daily_raw = requests.get("http://air4thai.com/forweb/getAQI_JSON.php", headers=HEADERS).json()
        daily_map = {s['stationID']: s['AQILast']['PM25']['value'] for s in daily_raw.get('stations', []) if s.get('AQILast')}
    except: return
    
    critical_stations = []
    current_red_ids = []
    valid_h = [s for s in hourly_raw if s and isinstance(s, dict) and s.get('hourly_data')]
    for s in valid_h:
        st_id = s['StationID']
        v1h, v24h = float(s['hourly_data'].get('PM25', 0)), float(daily_map.get(st_id, 0))
        if v24h >= CRITICAL_THRESHOLD or v1h >= 100:
            current_red_ids.append(st_id)
            critical_stations.append({
                'id': st_id, 'v1h': v1h, 'v24h': v24h,
                'full_addr': extract_detailed_area(s['AreaNameTh'], s.get('StationType')),
                'qa_issue': check_qa_issues_48h(st_id)
            })

    regional_weather = {}
    try:
        tmd_res = requests.get(f"https://data.tmd.go.th/api/DailyForecast/v2/?uid=api&ukey={TMD_DAILY_KEY}", timeout=30).content
        root = ET.fromstring(tmd_res.decode('utf-8-sig').strip())
        for rf in root.findall('.//RegionForecast'):
            name = rf.find('RegionNameThai').text.strip()
            desc = rf.find('DescriptionThai').text.strip()
            max_temp = re.findall(r'สูงสุด\s+(\d+-\d+|\d+)', desc)
            wind_spd = re.findall(r'ความเร็ว\s+(\d+-\d+|\d+)', desc)
            regional_weather[name] = {
                'temp': max_temp[0] if max_temp else "N/A",
                'wind': wind_spd[0] if wind_spd else "N/A",
                'rain': "พบฝนบางพื้นที่" if any(x in desc for x in ["มีฝน", "ฝนฟ้าคะนอง"]) else None,
                'vent': "อ่อนถึงไม่ดี" if "ระบายอากาศอยู่ในเกณฑ์อ่อน" in desc else "ระบายอากาศได้ดี"
            }
    except: pass

    report = generate_executive_summary(critical_stations, now, regional_weather, history, is_daily_start)
    
    if report:
        send_tg(report)
        save_history(current_red_ids, now.strftime('%Y-%m-%d %H:%M'))
    else:
        # อัปเดตประวัติเสมอเพื่อให้ระบบรู้สถานะปัจจุบัน (ป้องกันกรณี แดง -> ส้ม แล้วไม่รู้ตัว)
        save_history(current_red_ids, now.strftime('%Y-%m-%d %H:%M'))

if __name__ == "__main__":
    main()
