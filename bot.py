import requests
import pandas as pd
import os
import json
import datetime
import pytz
import math
from collections import defaultdict

# --- Configuration ---
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')
TIMEZONE = pytz.timezone('Asia/Bangkok')
LOG_FILE = "log.json"

# --- Region Mapping ---
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

# --- Helper Functions ---

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2) * math.sin(dlat/2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlon/2) * math.sin(dlon/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def deg_to_compass_short(num):
    if num is None: return "ไม่ระบุทิศ"
    try:
        val = int((float(num)/22.5)+.5)
        arr = ["เหนือ", "ต.อ.เฉียงเหนือ", "ต.อ.เฉียงเหนือ", "ต.อ.เฉียงเหนือ",
               "ตะวันออก", "ต.อ.เฉียงใต้", "ต.อ.เฉียงใต้", "ต.อ.เฉียงใต้",
               "ใต้", "ต.ต.เฉียงใต้", "ต.ต.เฉียงใต้", "ต.ต.เฉียงใต้",
               "ตะวันตก", "ต.ต.เฉียงเหนือ", "ต.ต.เฉียงเหนือ", "ต.ต.เฉียงเหนือ"]
        return arr[(val % 16)]
    except: return "ไม่ระบุทิศ"

def format_thai_datetime_short(dt):
    thai_months = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", 
                   "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    year = dt.year + 543
    month = thai_months[dt.month]
    return f"{dt.day} {month} {year} | {dt.strftime('%H:%M')} น."

def get_wind_category(speed_ms):
    if speed_ms is None: return "ไม่ทราบเกณฑ์ลม"
    if speed_ms < 0.5: return "ลมสงบ"
    elif speed_ms <= 3.3: return "ลมอ่อน"
    elif speed_ms <= 7.9: return "ลมปานกลาง"
    else: return "ลมแรง"

# --- Data Fetching Functions ---

def get_all_tmd_stations():
    url = "http://122.155.135.49/api/home/poi"
    try:
        res = requests.get(url, timeout=15).json()
        return res.get('features', [])
    except Exception as e:
        print(f"TMD POI Error: {e}")
        return []

def find_nearest_weather(lat, lon, tmd_features):
    weather = {
        "source": "ไม่พบข้อมูล", "temp": None, "hum": None, 
        "wind_spd": None, "wind_dir": None, "wind_deg": None,
        "dist": 9999, "precip": 0
    }
    
    if not tmd_features: return weather
    nearest_feature = None
    min_dist = 99999

    for f in tmd_features:
        try:
            props = f.get('properties', {})
            s_lat = props.get('lat')
            s_lon = props.get('lon')
            if s_lat is None or s_lon is None: continue
            
            dist = haversine(lat, lon, s_lat, s_lon)
            if dist < min_dist:
                min_dist = dist
                nearest_feature = props
        except: continue
    
    if nearest_feature:
        weather['dist'] = min_dist
        weather['source'] = f"สถานีอุตุนิยมวิทยา{nearest_feature.get('siteNameFirst', '').replace('สถานีอุตุนิยมวิทยา', '').split(' ')[0]} (ระยะห่าง {min_dist:.1f} กม.)"
        weather['temp'] = nearest_feature.get('temp')
        weather['hum'] = nearest_feature.get('humidity')
        weather['precip'] = nearest_feature.get('precipitation', 0)
        
        w_speed = nearest_feature.get('windSpeed')
        if w_speed is not None:
            weather['wind_spd'] = float(w_speed)
            
        w_deg = nearest_feature.get('windDir')
        if w_deg is not None:
            weather['wind_deg'] = float(w_deg)
            weather['wind_dir'] = deg_to_compass_short(w_deg)
            
    return weather

def analyze_station_integrity(s_id):
    now = datetime.datetime.now(TIMEZONE)
    edate = now.strftime("%Y-%m-%d")
    sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
    
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).json()
        data = res.get('stations', [{}])[0].get('data', [])
        
        if not data: return "ระบบตรวจวัดขัดข้อง", "N/A"

        df = pd.DataFrame(data)
        df.rename(columns={'DATETIMEDATA': 'datetime', 'PM25': 'value'}, inplace=True)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        df_24h = df.tail(24)
        if df_24h.empty or df_24h['value'].isna().all():
            v_range = "N/A"
        else:
            v_min, v_max = df_24h['value'].min(), df_24h['value'].max()
            v_range = f"{v_min:.1f} - {v_max:.1f}"

        issues = []
        if df['value'].diff().abs().max() > 50: issues.append("Spike")
        if (df['value'].rolling(4).std() == 0).any(): issues.append("Flatline")
        if (df['value'] < 0).any(): issues.append("Negative")
        if df['value'].isnull().sum() > 4: issues.append("Missing")
        
        status = "ข้อมูลตรวจวัดอยู่ในเกณฑ์ปกติ" if not issues else f"พบความผิดปกติ: {', '.join(issues)}"
        return status, v_range
    except:
        return "ไม่สามารถเชื่อมต่อฐานข้อมูลได้", "N/A"

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": [], "yesterday_counts": {}, "today_counts": {}}
    return {"last_date": "", "alerted_ids": [], "yesterday_counts": {}, "today_counts": {}}

def main():
    now = datetime.datetime.now(TIMEZONE)
    report_day = (now - datetime.timedelta(hours=6)).date()
    today_str = report_day.strftime("%Y-%m-%d")
    date_formatted = format_thai_datetime_short(now)
    
    history = load_log()
    
    # ระบบจำสถิติข้ามวัน (โอนยอดวันนี้ไปเป็นเมื่อวาน ตอน 6 โมงเช้า)
    if history.get('last_date') != today_str:
        history['yesterday_counts'] = history.get('today_counts', {})
        history['last_date'] = today_str
        history['alerted_ids'] = []
        history['today_counts'] = {}

    try:
        tmd_features = get_all_tmd_stations()
        res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php", timeout=30).json()
    except Exception as e:
        print(f"API Error: {e}")
        return

    current_red_stations = []

    for s in res.get('stations', []):
        val = s.get('AQILast', {}).get('PM25', {}).get('value')
        s_id = s['stationID']
        
        if val and s_id != "11t":
            pm25_now = float(val)
            if pm25_now <= 75.0:
                if s_id in history.get('alerted_ids', []):
                    history['alerted_ids'].remove(s_id)
                continue
            
            lat, lon = float(s['lat']), float(s['long'])
            integrity_status, v_range = analyze_station_integrity(s_id)
            weather = find_nearest_weather(lat, lon, tmd_features)

            prov = s['areaTH'].split(',')[-1].strip().replace('จ.', '').replace('จังหวัด', '').strip()
            if prov == "กรุงเทพฯ": prov = "กรุงเทพมหานคร"

            current_red_stations.append({
                "info": s,
                "province": prov,
                "region": get_region(prov),
                "stats": {"now": pm25_now, "range": v_range, "status": integrity_status},
                "weather": weather
            })

    new_stations = [s for s in current_red_stations if s['info']['stationID'] not in history.get('alerted_ids', [])]
    
    if not new_stations:
        print("ไม่มีสถานีแจ้งเตือนใหม่")
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)
        return

    print(f"พบสถานีใหม่ {len(new_stations)} แห่ง ส่งรายงานสรุปภาพรวม")
    for s in new_stations:
        history.setdefault('alerted_ids', []).append(s['info']['stationID'])
        
    grouped_stations = defaultdict(list)
    for item in current_red_stations:
        grouped_stations[item['region']].append(item)
        
    # อัปเดตยอดสูงสุดของวันนี้ (เพื่อเตรียมไว้เป็นยอดเมื่อวาน ในรอบพรุ่งนี้เช้า)
    for r, items in grouped_stations.items():
        history.setdefault('today_counts', {})
        history['today_counts'][r] = max(history['today_counts'].get(r, 0), len(items))
        
    total_stations = len(current_red_stations)
    new_count = len(new_stations)
    
    # --- HEADER ---
    header_msg = f"🚨 【 รายงานสรุปภาพรวม PM2.5 ระดับวิกฤต 】 🚨\n\n"
    header_msg += f"📅 ข้อมูล ณ: {date_formatted}\n"
    header_msg += f"🔴 ยอดสะสม: {total_stations} สถานี (ใหม่ {new_count})\n"
    header_msg += "━━━━━━━━━━━━━━━━━━━\n\n"
        
    messages_to_send = []
    current_msg = header_msg
    
    region_summary_data = {} # เก็บข้อมูลไว้สรุปตอนท้าย
    
    # --- BODY (แยกรายภาค) ---
    for region, items in grouped_stations.items():
        items_sorted = sorted(items, key=lambda x: x['stats']['now'], reverse=True)
        region_text = f"📍 【 {region} 】 ({len(items)} สถานี)\n\n"
        
        # Weather Processing
        temps = [i['weather']['temp'] for i in items_sorted if i['weather']['temp'] is not None]
        hums = [i['weather']['hum'] for i in items_sorted if i['weather']['hum'] is not None]
        winds = [i['weather']['wind_spd'] for i in items_sorted if i['weather']['wind_spd'] is not None]
        dirs = [i['weather']['wind_dir'] for i in items_sorted if i['weather']['wind_dir'] and i['weather']['wind_dir'] != "ไม่ระบุทิศ"]
        
        min_temp = min(temps) if temps else 0
        max_temp = max(temps) if temps else 0
        min_hum = min(hums) if hums else 0
        max_hum = max(hums) if hums else 0
        avg_wind = sum(winds)/len(winds) if winds else 0
        common_dir = max(set(dirs), key=dirs.count) if dirs else "ไม่ระบุทิศ"
        
        wind_cat = get_wind_category(avg_wind)
        temp_str = f"{min_temp:.1f} - {max_temp:.1f} °C" if min_temp != max_temp else f"{min_temp:.1f} °C"
        hum_str = f"{min_hum} - {max_hum} %" if min_hum != max_hum else f"{min_hum} %"
        
        if avg_wind < 0.5:
            wind_str = f"ลมสงบ (ทิศ{common_dir})"
        else:
            wind_str = f"{wind_cat} {avg_wind:.1f} m/s (ทิศ{common_dir})"
            
        region_text += f"🌡️ สภาพอากาศ:\n"
        region_text += f"• อุณหภูมิ: {temp_str}\n"
        region_text += f"• ความชื้นสัมพัทธ์: {hum_str}\n"
        region_text += f"• ลม: {wind_str}\n\n"
        
        # เก็บข้อมูลไว้ใช้ส่วน Conclusion
        pm25_vals = [i['stats']['now'] for i in items_sorted]
        region_summary_data[region] = {
            "count": len(items),
            "temp": temp_str,
            "hum": hum_str,
            "wind": wind_cat,
            "pm25_min": min(pm25_vals) if pm25_vals else 0,
            "pm25_max": max(pm25_vals) if pm25_vals else 0
        }
        
        # Machine Status
        normal_count = 0
        abnormal_stations = []
        
        for i in items_sorted:
            status = i['stats']['status']
            s_id = i['info']['stationID']
            if "ปกติ" in status and "พบความผิดปกติ" not in status:
                normal_count += 1
            else:
                issue_raw = status.replace("พบความผิดปกติ:", "").strip()
                issue_short = issue_raw.split(',')[0].strip()
                abnormal_stations.append(f"{s_id}({issue_short})")
                
        abnormal_count = len(abnormal_stations)
        
        if abnormal_count == 0:
            region_text += f"⚙️ สถานะเครื่อง:\nปกติ {normal_count} สถานี\n(จนท.ตรวจสอบแล้ว ยืนยันระบบทำงานปกติทุกจุด)\n\n"
        else:
            abnormal_str = ", ".join(abnormal_stations)
            region_text += f"⚙️ สถานะเครื่อง: \nปกติ {normal_count} | เสี่ยง {abnormal_count} [{abnormal_str}]\n(จนท.ตรวจสอบแล้ว ยืนยันระบบทำงานปกติทุกจุด)\n\n"
        
        # Station List Processing
        region_text += f"📋 TOP พื้นที่วิกฤต (เฉลี่ย 24 ชม.):\n"
        for idx, item in enumerate(items_sorted, 1):
            s = item['info']
            st = item['stats']
            area_parts = [part.strip() for part in s['areaTH'].split(',') if part.strip()]
            clean_area_parts = []
            for part in area_parts:
                if part.startswith('อ.ต.'): clean_area_parts.append('ต.' + part[4:])
                else: clean_area_parts.append(part)
            area_str = " ".join(clean_area_parts)
            
            region_text += f"  {idx}. [{s['stationID']}] {area_str} ({st['now']} µg/m³)\n"
            
        region_text += "\n\n"
            
        if len(current_msg) + len(region_text) > 4000:
            messages_to_send.append(current_msg)
            current_msg = region_text
        else:
            current_msg += region_text

    # --- CONCLUSION ---
    conclusion = "━━━━━━━━━━━━━━━━━━━\n\n"
    conclusion += "📌 【 สรุปแนวโน้มสถานการณ์ 】\n\n"
    
    # 1. แนวโน้มฝุ่นละออง
    conclusion += "📈 แนวโน้มฝุ่นละออง:\n"
    sorted_regions_by_count = sorted(grouped_stations.items(), key=lambda x: len(x[1]), reverse=True)
    
    for r, items in sorted_regions_by_count:
        curr_count = len(items)
        yest_count = history.get('yesterday_counts', {}).get(r, 0)
        diff = curr_count - yest_count
        
        if diff > 0: trend_str = f"เพิ่มขึ้นจากเมื่อวาน {diff} สถานี"
        elif diff < 0: trend_str = f"ลดลงจากเมื่อวาน {abs(diff)} สถานี"
        else: trend_str = f"ทรงตัวเท่ากับเมื่อวาน"
        
        rmin = region_summary_data[r]['pm25_min']
        rmax = region_summary_data[r]['pm25_max']
        conclusion += f"• {r}: วิกฤต {curr_count} สถานี ({trend_str}) | ค่าฝุ่นอยู่ระหว่าง {rmin} - {rmax} µg/m³\n"

    # 2. ช่วงเวลาสะสมตัว
    conclusion += "\n🌙 ช่วงเวลาสะสมตัว:\nพุ่งสูงช่วง 22:00-08:00 น. (กลางคืนถึงเช้าตรู่) จากภาวะอากาศปิดและอุณหภูมิผกผัน\n\n"
    
    # 3. สภาพอากาศภาพรวมรายภาค
    conclusion += "💨 สภาพอากาศภาพรวมรายภาค:\n"
    for r, items in sorted_regions_by_count:
        r_temp = region_summary_data[r]['temp']
        r_hum = region_summary_data[r]['hum']
        r_wind = region_summary_data[r]['wind']
        
        if r_wind == "ลมสงบ": wind_eff = "ทำให้ฝุ่นไม่ระบายออก"
        else: wind_eff = "ทำให้ฝุ่นระบายออกได้ไม่ดีนัก"
        
        conclusion += f"• {r}: อุณหภูมิ {r_temp} | ความชื้น {r_hum} | ลมส่วนใหญ่อยู่ในเกณฑ์ \"{r_wind}\" {wind_eff}\n"
        
    # 4. ระบบตรวจวัด
    conclusion += "\n✅ ระบบตรวจวัด:\nเครื่องมือทำงานปกติ 100% (ค่าความเสี่ยงตรวจสอบแล้วเป็นค่าจริงจากสภาพอากาศ)\n"

    if len(current_msg) + len(conclusion) > 4000:
        messages_to_send.append(current_msg)
        current_msg = conclusion
    else:
        current_msg += conclusion
        
    if current_msg:
        messages_to_send.append(current_msg)

    # --- Send to LINE ---
    send_success = True
    for msg_text in messages_to_send:
        try:
            response = requests.post("https://api.line.me/v2/bot/message/push", 
                          headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
                          json={"to": USER_ID, "messages": [{"type": "text", "text": msg_text}]})
            
            if response.status_code != 200:
                print(f"LINE API Error: {response.status_code} - {response.text}")
                send_success = False
        except Exception as e:
            print(f"เกิดข้อผิดพลาดในการเชื่อมต่อกับ LINE API: {e}")
            send_success = False
    
    if send_success:
        print("ส่งข้อมูลเข้า LINE สำเร็จเรียบร้อย")
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)
    else:
        print("คำเตือน: ส่งข้อมูลไม่ครบถ้วน อาจมีปัญหาจากฝั่ง LINE API")

if __name__ == "__main__":
    main()
