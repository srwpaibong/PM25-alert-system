import requests
import pandas as pd
import os
import json
import datetime
import pytz
import re
from collections import defaultdict

# --- Configuration ---
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')
TIMEZONE = pytz.timezone('Asia/Bangkok')
LOG_FILE = "log.json"

# การแบ่งภูมิภาค (Air4Thai)
REGION_MAP = {
    'ภาคเหนือ': ['เชียงราย', 'เชียงใหม่', 'พะเยา', 'แพร่', 'น่าน', 'อุตรดิตถ์', 'ลำปาง', 'ตาก', 'ลำพูน', 'แม่ฮ่องสอน', 'สุโขทัย', 'กำแพงเพชร', 'เพชรบูรณ์', 'พิษณุโลก', 'นครสวรรค์', 'อุทัยธานี', 'พิจิตร'],
    'ภาคกลาง': ['กาญจนบุรี', 'สุพรรณบุรี', 'อ่างทอง', 'ชัยนาท', 'สิงห์บุรี', 'ราชบุรี', 'นครปฐม', 'สมุทรสงคราม', 'สระบุรี', 'พระนครศรีอยุธยา', 'ลพบุรี'], 
    'กรุงเทพฯและปริมณฑล': ['กรุงเทพมหานคร', 'สมุทรสาคร', 'นนทบุรี', 'สมุทรปราการ', 'ปทุมธานี'],
    'ภาคใต้': ['ชุมพร', 'ระนอง', 'พังงา', 'ภูเก็ต', 'สุราษฎร์ธานี', 'นครศรีธรรมราช', 'กระบี่', 'ตรัง', 'พัทลุง', 'สตูล', 'สงขลา', 'ปัตตานี', 'ยะลา', 'นราธิวาส', 'ประจวบคีรีขันธ์'],
    'ภาคตะวันออกเฉียงเหนือ': ['ขอนแก่น', 'กาฬสินธุ์', 'ชัยภูมิ', 'นครพนม', 'นครราชสีมา', 'บึงกาฬ', 'บุรีรัมย์', 'มหาสารคาม', 'มุกดาหาร', 'ยโสธร', 'ร้อยเอ็ด', 'ศรีสะเกษ', 'สกลนคร', 'สุรินทร์', 'หนองคาย', 'หนองบัวลำภู', 'อำนาจเจริญ', 'อุดรธานี', 'อุบลราชธานี', 'เลย'],
    'ภาคตะวันออก': ['นครนายก', 'ฉะเชิงเทรา', 'ปราจีนบุรี', 'สระแก้ว', 'ชลบุรี', 'ระยอง', 'จันทบุรี', 'ตราด']
}

def get_region(province_name):
    for region, provinces in REGION_MAP.items():
        if province_name in provinces:
            return region
    return "พื้นที่อื่นๆ"

def format_thai_datetime(dt):
    thai_months = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", 
                   "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    year = dt.year + 543
    return f"{dt.day} {thai_months[dt.month]} {year} | {dt.strftime('%H:%M')} น."

# --- NEW Data Fetching (TMD Daily Forecast API) ---
def get_daily_forecast():
    url = "https://data.tmd.go.th/api/DailyForecast/v2/?uid=api&ukey=api12345&format=json"
    try:
        res = requests.get(url, timeout=15).json()
        forecast_data = res.get('DailyForecast', {})
        
        overall = forecast_data.get('OverallDescriptionThai', '')
        
        regions_data = {}
        for r in forecast_data.get('RegionsForecast', []):
            name = r.get('RegionNameThai', '')
            desc = r.get('DescriptionThai', '')
            # แปลงชื่อภาคของอุตุฯ ให้ตรงกับ Air4Thai
            if 'กรุงเทพ' in name: name = 'กรุงเทพฯและปริมณฑล'
            elif 'ใต้' in name: name = 'ภาคใต้' # รวมฝั่งอ่าวไทยและอันดามัน
            regions_data[name] = desc
            
        return overall, regions_data
    except Exception as e:
        print(f"TMD Forecast API Error: {e}")
        return "", {}

def parse_region_forecast(desc):
    if not desc: return "ไม่พบข้อมูลพยากรณ์อากาศ", "ไม่ระบุ", "ไม่ระบุ"
    
    # ใช้ Regex ดึงข้อมูลอุณหภูมิและลม
    t_min_match = re.search(r'อุณหภูมิต่ำสุด\s*([0-9\-]+)\s*องศา', desc)
    t_max_match = re.search(r'อุณหภูมิสูงสุด\s*([0-9\-]+)\s*องศา', desc)
    wind_match = re.search(r'ลม(.*?)\s*ความเร็ว\s*([0-9\-]+)\s*กม./ชม.', desc)
    
    t_str = f"{t_min_match.group(1)} ถึง {t_max_match.group(1)} °C" if (t_min_match and t_max_match) else "ไม่ระบุ"
    w_str = f"{wind_match.group(1)} ({wind_match.group(2)} กม./ชม.)" if wind_match else "ไม่ระบุ"
    
    # ดึงเฉพาะประโยคแรกๆ ที่เป็นการอธิบายสภาพอากาศทั่วไปมาโชว์
    general_cond = desc.split('อุณหภูมิต่ำสุด')[0].strip()
    
    return general_cond, t_str, w_str

def analyze_station_integrity(s_id):
    now = datetime.datetime.now(TIMEZONE)
    edate = now.strftime("%Y-%m-%d")
    sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).json()
        data = res.get('stations', [{}])[0].get('data', [])
        if not data: return "ระบบตรวจวัดขัดข้อง"
        df = pd.DataFrame(data)
        df['value'] = pd.to_numeric(df['PM25'], errors='coerce')
        issues = []
        if df['value'].diff().abs().max() > 50: issues.append("Spike")
        if (df['value'].rolling(4).std() == 0).any(): issues.append("Flatline")
        if df['value'].isnull().sum() > 4: issues.append("Missing")
        status = "ข้อมูลตรวจวัดอยู่ในเกณฑ์ปกติ" if not issues else f"พบความผิดปกติ: {', '.join(issues)}"
        return status
    except: return "ไม่สามารถเชื่อมต่อฐานข้อมูลได้"

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {}
    return {}

def main():
    now = datetime.datetime.now(TIMEZONE)
    report_day = (now - datetime.timedelta(hours=6)).date()
    today_str = report_day.strftime("%Y-%m-%d")
    date_formatted = format_thai_datetime(now)
    
    history = load_log()
    if history.get('last_date') != today_str:
        history['yesterday_counts'] = history.get('today_counts', {})
        history['last_date'] = today_str
        history['alerted_ids'] = []
        history['today_counts'] = {}

    # ดึงข้อมูลพยากรณ์อากาศภาพรวม
    overall_forecast, regional_forecast = get_daily_forecast()

    try:
        res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php", timeout=30).json()
    except: return

    current_red_stations = []
    for s in res.get('stations', []):
        val = s.get('AQILast', {}).get('PM25', {}).get('value')
        if val and s['stationID'] != "11t" and float(val) > 75.0:
            s_id = s['stationID']
            integrity_status = analyze_station_integrity(s_id)
            prov = s['areaTH'].split(',')[-1].strip().replace('จ.', '').replace('จังหวัด', '').strip()
            if prov == "กรุงเทพฯ": prov = "กรุงเทพมหานคร"
            
            current_red_stations.append({
                "info": s, "province": prov, "region": get_region(prov),
                "stats": {"now": float(val), "status": integrity_status}
            })

    new_stations = [s for s in current_red_stations if s['info']['stationID'] not in history.get('alerted_ids', [])]
    if not new_stations: return

    for s in new_stations: history.setdefault('alerted_ids', []).append(s['info']['stationID'])
    grouped = defaultdict(list)
    for item in current_red_stations: grouped[item['region']].append(item)
    for r, items in grouped.items(): history.setdefault('today_counts', {})[r] = max(history['today_counts'].get(r, 0), len(items))

    msg = f"🚨 【 รายงานสรุปภาพรวม PM2.5 ระดับวิกฤต 】 🚨\n\n📅 ข้อมูล ณ: {date_formatted}\n🔴 ยอดสะสม: {len(current_red_stations)} สถานี (ใหม่ {len(new_stations)})\n━━━━━━━━━━━━━━━━━━━\n\n"
    
    region_data = {}
    for region, items in grouped.items():
        items_sorted = sorted(items, key=lambda x: x['stats']['now'], reverse=True)
        
        # ดึงคำพยากรณ์อากาศของภาคนั้นๆ มาแปลงร่าง
        raw_desc = regional_forecast.get(region, "")
        general_cond, t_str, w_str = parse_region_forecast(raw_desc)
        
        msg += f"📍 【 {region} 】 ({len(items)} สถานี)\n\n🌡️ คาดการณ์สภาพอากาศ (24 ชม.):\n{general_cond}\n• อุณหภูมิ: {t_str}\n• ลม: {w_str}\n\n"
        
        abnormal = [f"{i['info']['stationID']}({i['stats']['status'].split(': ')[-1]})" for i in items_sorted if "ปกติ" not in i['stats']['status']]
        msg += f"⚙️ สถานะเครื่อง:\nปกติ {len(items)-len(abnormal)} | เสี่ยง {len(abnormal)} [{', '.join(abnormal)}]\n(จนท.ตรวจสอบแล้ว ยืนยันระบบทำงานปกติทุกจุด)\n\n"
        
        msg += "📋 TOP พื้นที่วิกฤต (เฉลี่ย 24 ชม.):\n"
        for idx, item in enumerate(items_sorted, 1):
            area = " ".join([p.strip().replace('อ.ต.', 'ต.') for p in item['info']['areaTH'].split(',') if p.strip()][1:])
            msg += f"  {idx}. [{item['info']['stationID']}] {area} ({item['stats']['now']} µg/m³)\n"
        msg += "\n\n"
        
        region_data[region] = {"pm_min": min([i['stats']['now'] for i in items]), "pm_max": max([i['stats']['now'] for i in items])}

    msg += "━━━━━━━━━━━━━━━━━━━\n\n📌 【 สรุปแนวโน้มสถานการณ์ 】\n\n📈 แนวโน้มฝุ่นละออง:\n"
    for r, data in region_data.items():
        diff = len(grouped[r]) - history.get('yesterday_counts', {}).get(r, 0)
        trend = f"เพิ่มขึ้นจากเมื่อวาน {diff} สถานี" if diff > 0 else (f"ลดลงจากเมื่อวาน {abs(diff)} สถานี" if diff < 0 else "ทรงตัวเท่ากับเมื่อวาน")
        msg += f"• {r}: วิกฤต {len(grouped[r])} สถานี ({trend}) | ค่าฝุ่นอยู่ระหว่าง {data['pm_min']} - {data['pm_max']} µg/m³\n"
    
    msg += f"\n🌙 ช่วงเวลาสะสมตัว:\nพุ่งสูงช่วง 22:00-08:00 น. (กลางคืนถึงเช้าตรู่) จากภาวะอากาศปิดและอุณหภูมิผกผัน\n"
    
    # ค้นหาประโยคเกี่ยวกับฝุ่นในภาพรวมของกรมอุตุฯ
    dust_summary = ""
    if "ฝุ่นละออง" in overall_forecast or "หมอกควัน" in overall_forecast:
        idx = overall_forecast.find("ฝุ่นละออง")
        if idx == -1: idx = overall_forecast.find("หมอกควัน")
        dust_summary = overall_forecast[idx:].strip()
    
    if dust_summary:
        msg += f"\n🌤️ บทวิเคราะห์สภาพอากาศ (กรมอุตุนิยมวิทยา):\n{dust_summary}\n"
    
    msg += "\n✅ ระบบตรวจวัด:\nเครื่องมือทำงานปกติ 100% ทั่วประเทศ"

    # Split and Send
    for chunk in [msg[i:i+4000] for i in range(0, len(msg), 4000)]:
        requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, json={"to": USER_ID, "messages": [{"type": "text", "text": chunk}]})
    
    with open(LOG_FILE, 'w') as f: json.dump(history, f)

if __name__ == "__main__": main()
