import requests
import pandas as pd
import os
import json
import datetime
import pytz
import math
import time

# --- Configuration ---
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')
GISTDA_KEY = os.getenv('GISTDA_API_KEY')
TIMEZONE = pytz.timezone('Asia/Bangkok')
LOG_FILE = "log.json"

# --- Mapping: จังหวัด -> รหัสสถานีอุตุฯ (TMD AWS ID) ---
TMD_PROVINCE_MAP = {
    # ภาคเหนือ
    "เชียงราย": 1005, "เชียงใหม่": 1023, "น่าน": 1011, "พะเยา": 1017,
    "แพร่": 1014, "แม่ฮ่องสอน": 3, "ลำปาง": 16, "ลำพูน": 10,
    "อุตรดิตถ์": 1035, "สุโขทัย": 1010, "พิษณุโลก": 38, "พิจิตร": 1033,
    "เพชรบูรณ์": 1040, "ตาก": 17, "กำแพงเพชร": 1031,
    # ภาคตะวันออกเฉียงเหนือ
    "หนองคาย": 1034, "เลย": 48, "อุดรธานี": 35, "นครพนม": 46,
    "สกลนคร": 1046, "หนองบัวลำภู": 79, "ขอนแก่น": 37, "กาฬสินธุ์": 1051,
    "มุกดาหาร": 43, "ชัยภูมิ": 1050, "มหาสารคาม": 40, "ร้อยเอ็ด": 1052,
    "ยโสธร": 1053, "อำนาจเจริญ": 1054, "อุบลราชธานี": 73, "ศรีสะเกษ": 70,
    "สุรินทร์": 69, "บุรีรัมย์": 67, "นครราชสีมา": 1055,
    # ภาคกลาง
    "นครสวรรค์": 27, "อุทัยธานี": 1032, "ชัยนาท": 25, "ลพบุรี": 1038,
    "สิงห์บุรี": 1038, "อ่างทอง": 1036, "สระบุรี": 1037, "พระนครศรีอยุธยา": 1036,
    "อยุธยา": 1036, "สุพรรณบุรี": 1030, "นครปฐม": 28, "ปทุมธานี": 1003,
    "นนทบุรี": 1003, "สมุทรปราการ": 1001, "กรุงเทพฯ": 1001, "กรุงเทพมหานคร": 1001,
    # ภาคตะวันออก
    "นครนายก": 1003, "ปราจีนบุรี": 1069, "สระแก้ว": 1066, "ฉะเชิงเทรา": 34,
    "ชลบุรี": 44, "ระยอง": 58, "จันทบุรี": 41, "ตราด": 39,
    # ภาคตะวันตก
    "กาญจนบุรี": 1062, "ราชบุรี": 32, "เพชรบุรี": 1072, "ประจวบคีรีขันธ์": 1073,
    # ภาคใต้
    "ชุมพร": 60, "ระนอง": 59, "สุราษฎร์ธานี": 91, "พังงา": 61,
    "ภูเก็ต": 68, "กระบี่": 1087, "นครศรีธรรมราช": 90, "ตรัง": 64,
    "พัทลุง": 82, "สตูล": 63, "สงขลา": 53, "ปัตตานี": 3936,
    "ยะลา": 3932, "นราธิวาส": 3906
}

# --- Thai Wind Direction Mapping ---
WIND_DIR_MAP = {
    "N": "ทิศเหนือ", "NNE": "ทิศตะวันออกเฉียงเหนือ", "NE": "ทิศตะวันออกเฉียงเหนือ", "ENE": "ทิศตะวันออกเฉียงเหนือ",
    "E": "ทิศตะวันออก", "ESE": "ทิศตะวันออกเฉียงใต้", "SE": "ทิศตะวันออกเฉียงใต้", "SSE": "ทิศตะวันออกเฉียงใต้",
    "S": "ทิศใต้", "SSW": "ทิศตะวันตกเฉียงใต้", "SW": "ทิศตะวันตกเฉียงใต้", "WSW": "ทิศตะวันตกเฉียงใต้",
    "W": "ทิศตะวันตก", "WNW": "ทิศตะวันตกเฉียงเหนือ", "NW": "ทิศตะวันตกเฉียงเหนือ", "NNW": "ทิศตะวันตกเฉียงเหนือ",
    "C": "ลมสงบ", "CALM": "ลมสงบ"
}

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

def calculate_bearing(lat1, lon1, lat2, lon2):
    dLon = math.radians(lon2 - lon1)
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)
    y = math.sin(dLon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - \
        math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360

def is_upwind(station_lat, station_lon, hotspot_lat, hotspot_lon, wind_deg):
    if wind_deg is None: return True
    target_bearing = calculate_bearing(station_lat, station_lon, hotspot_lat, hotspot_lon)
    diff = abs(target_bearing - wind_deg)
    diff = min(diff, 360 - diff)
    return diff <= 60

def deg_to_compass_thai(num):
    if num is None: return "ไม่ระบุ"
    val = int((num/22.5)+.5)
    arr = ["ทิศเหนือ", "ทิศตะวันออกเฉียงเหนือ", "ทิศตะวันออกเฉียงเหนือ", "ทิศตะวันออกเฉียงเหนือ",
           "ทิศตะวันออก", "ทิศตะวันออกเฉียงใต้", "ทิศตะวันออกเฉียงใต้", "ทิศตะวันออกเฉียงใต้",
           "ทิศใต้", "ทิศตะวันตกเฉียงใต้", "ทิศตะวันตกเฉียงใต้", "ทิศตะวันตกเฉียงใต้",
           "ทิศตะวันตก", "ทิศตะวันตกเฉียงเหนือ", "ทิศตะวันตกเฉียงเหนือ", "ทิศตะวันตกเฉียงเหนือ"]
    return arr[(val % 16)]

# --- Data Fetching ---
def get_weather_data(s_payload, lat, lon):
    weather = {
        "source": "สถานี คพ.", "temp": None, "hum": None, 
        "wind_spd": None, "wind_dir": None, "wind_deg": None
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # 1. Try Air4Thai
    try:
        url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_payload['stationID']}&param=PM25,WS,WD,TEMP,RH&type=hr&limit=1"
        h_res = requests.get(url, headers=headers, timeout=5).json()
        if 'stations' in h_res and len(h_res['stations']) > 0:
            latest = h_res['stations'][0]['data'][-1]
            if latest.get('TEMP') and float(latest['TEMP']) > -90: weather['temp'] = float(latest['TEMP'])
            if latest.get('RH'): weather['hum'] = float(latest['RH'])
            if latest.get('WS'): weather['wind_spd'] = float(latest['WS']) * 3.6
            if latest.get('WD'): 
                weather['wind_deg'] = float(latest['WD'])
                weather['wind_dir'] = deg_to_compass_thai(weather['wind_deg'])
    except:
        pass

    # 2. TMD Fallback (with Retry)
    if weather['wind_deg'] is None:
        try:
            full_province = s_payload['areaTH'].split(',')[-1].strip()
            province_key = full_province.replace('จ.', '').strip()
            tmd_id = TMD_PROVINCE_MAP.get(province_key)
            
            if tmd_id:
                url_tmd = f"http://122.155.135.49/api/home/site/{tmd_id}"
                
                # Retry Logic: ลอง 3 ครั้ง ถ้าพลาด
                t_res = None
                for attempt in range(3):
                    try:
                        resp = requests.get(url_tmd, headers=headers, timeout=20) # เพิ่ม Timeout เป็น 20s
                        if resp.status_code == 200:
                            t_res = resp.json()
                            break
                    except Exception as e:
                        print(f"Attempt {attempt+1} failed for {province_key}: {e}")
                        time.sleep(2) # รอ 2 วินาทีก่อนลองใหม่

                if t_res and 'data' in t_res and 'items' in t_res['data'] and len(t_res['data']['items']) > 0:
                    item = t_res['data']['items'][0]
                    
                    raw_dir = item.get('winddirsign', 'N/A')
                    thai_dir = WIND_DIR_MAP.get(raw_dir.upper(), raw_dir)
                    
                    weather['source'] = f"สถานีกรมอุตุฯ จ.{province_key}"
                    weather['temp'] = item.get('temp')
                    weather['hum'] = item.get('humidity')
                    
                    w_speed = float(item.get('windspeed', 0))
                    if w_speed < 20: w_speed *= 3.6 
                    weather['wind_spd'] = w_speed
                    
                    weather['wind_dir'] = thai_dir
                    weather['wind_deg'] = float(item.get('winddir', 0))
                else:
                    weather['source'] = f"สถานีกรมอุตุฯ จ.{province_key} (ไม่มีข้อมูล)"
            else:
                weather['source'] = "ไม่พบสถานีตรวจวัดลมใกล้เคียง"
        except Exception as e:
            print(f"TMD Error ({province_key}): {e}")
            weather['source'] = "สถานีกรมอุตุฯ (เชื่อมต่อไม่ได้)"

    return weather

def get_hotspot_data(lat, lon, wind_deg):
    url = "https://api-gateway.gistda.or.th/api/2.0/resources/features/viirs/1day?limit=1000&offset=0&ct_tn=ราชอาณาจักรไทย"
    headers = {'accept': 'application/json', 'API-Key': GISTDA_KEY}
    
    summary = {
        "upwind_total": 0, "nearby_total": 0,
        "landuse": {}, "nearest": 9999, "nearest_dir": "ไม่พบ",
        "scope_msg": "", "report_count": 0
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        features = res.get('features', [])
        
        for f in features:
            props = f['properties']
            h_lat, h_lon = props['latitude'], props['longitude']
            dist = haversine(lat, lon, h_lat, h_lon)
            
            if dist <= 50:
                summary['nearby_total'] += 1
                
                if is_upwind(lat, lon, h_lat, h_lon, wind_deg):
                    summary['upwind_total'] += 1
                    lu = props.get('lu_hp_name', 'ไม่ระบุ')
                    summary['landuse'][lu] = summary['landuse'].get(lu, 0) + 1
                
                if dist < summary['nearest']:
                    summary['nearest'] = dist
                    b = calculate_bearing(lat, lon, h_lat, h_lon)
                    summary['nearest_dir'] = deg_to_compass_thai(b)

        if summary['upwind_total'] > 0:
            summary['scope_msg'] = "(รัศมี 50 กม. จากทิศที่ลมพัดมา)"
            summary['report_count'] = summary['upwind_total']
        elif summary['nearby_total'] > 0:
            summary['scope_msg'] = "(รัศมี 50 กม. รอบทิศทาง - ไม่ตรงทิศลม)"
            summary['report_count'] = summary['nearby_total']
        else:
            summary['scope_msg'] = "(รัศมี 50 กม. รอบทิศทาง)"
            summary['report_count'] = 0

    except Exception as e:
        print(f"GISTDA Error: {e}")
        return None

    return summary

def analyze_situation(pm25_now, pm25_24, wind_spd, hotspot_data, integrity, wind_dir_thai):
    analysis = ""
    hotspot_count = hotspot_data['report_count'] if hotspot_data else 0
    
    if "Spike" in integrity: return "⚠️ ข้อมูลมีความผิดปกติ (ค่าพุ่งสูงเฉียบพลัน Spike) ควรตรวจสอบเซนเซอร์"
    if "ขาดหาย" in integrity: return "⚠️ ข้อมูลไม่ครบถ้วน (Missing Data)"

    factors = []
    if wind_spd is not None and wind_spd < 5: factors.append("สภาพอากาศปิด/ลมนิ่ง")
    if hotspot_count > 5: factors.append("พบจุดความร้อนสะสมจำนวนมาก")
    
    if pm25_now > 75:
        if hotspot_count > 0 and "ลมนิ่ง" in str(factors):
            analysis = "✅ **สถานการณ์จริง:** ค่าฝุ่นสูงวิกฤตสอดคล้องกับสภาพอากาศปิดและมีจุดความร้อนในพื้นที่"
        elif hotspot_data and hotspot_data['upwind_total'] > 0:
            analysis = f"✅ **สถานการณ์จริง:** ลมพัดพาฝุ่นจากการเผาไหม้ทาง{wind_dir_thai}เข้ามาสะสม"
        elif "ลมนิ่ง" in str(factors):
            analysis = "⚠️ **เฝ้าระวัง:** ไม่พบจุดเผาใกล้เคียง แต่ค่าฝุ่นสูงจากสภาพอากาศปิด (อาจเป็นฝุ่นสะสม)"
        else:
            analysis = "⚠️ **เฝ้าระวัง:** ค่าฝุ่นสูงโดยไม่พบปัจจัยแวดล้อมชัดเจน อาจเกิดจากแหล่งกำเนิดเฉพาะจุด"
            
    return analysis

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": []}
    return {"last_date": "", "alerted_ids": []}

def main():
    now = datetime.datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")
    
    # 1. โหลด Log เก่า
    history = load_log()
    
    # ถ้าขึ้นวันใหม่ ให้รีเซ็ตประวัติการแจ้งเตือน
    if history.get('last_date') != today_str:
        history = {"last_date": today_str, "alerted_ids": []}

    try:
        res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php", timeout=30).json()
    except:
        print("API Error")
        return

    current_red_stations = []

    # 2. รวบรวมสถานีแดงทั้งหมดในตอนนี้
    for s in res.get('stations', []):
        val = s.get('AQILast', {}).get('PM25', {}).get('value')
        s_id = s['stationID']
        
        if val and float(val) > 75.1 and s_id != "11t":
            lat, lon = float(s['lat']), float(s['long'])
            
            # --- ดึงข้อมูลเชิงลึก (History / Weather / Hotspot) ---
            # (ทำเหมือนเดิมแต่ย้ายมาไว้ตรงนี้)
            edate = now.strftime("%Y-%m-%d")
            sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
            hist_url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
            try:
                h_res = requests.get(hist_url, timeout=10).json()
                if 'stations' in h_res and len(h_res['stations']) > 0:
                    data = h_res['stations'][0]['data']
                    df = pd.DataFrame(data)
                    df['PM25'] = pd.to_numeric(df['PM25'], errors='coerce')
                    pm25_now, pm25_24h = float(val), df.tail(24)['PM25'].mean()
                    v_min, v_max = df['PM25'].min(), df['PM25'].max()
                    
                    issues = []
                    if df['PM25'].diff().abs().max() > 50: issues.append("Spike")
                    if (df['PM25'].rolling(4).std() == 0).any(): issues.append("Flatline")
                    if df['PM25'].isnull().sum() > 4: issues.append("ขาดหาย > 4ชม.")
                    integrity = "✅ ปกติ" if not issues else f"⚠️ {','.join(issues)}"
                else: raise ValueError("Empty")
            except:
                pm25_24h, v_min, v_max, integrity = 0, 0, 0, "❌ ดึงประวัติไม่ได้"

            weather = get_weather_data(s, lat, lon)
            hotspot = get_hotspot_data(lat, lon, weather['wind_deg'])
            w_dir_th = weather['wind_dir'] if weather['wind_dir'] else "ทิศเหนือลม"
            analysis_text = analyze_situation(pm25_now, pm25_24h, weather['wind_spd'], hotspot, integrity, w_dir_th)

            current_red_stations.append({
                "info": s,
                "stats": {"now": pm25_now, "avg24": pm25_24h, "min": v_min, "max": v_max, "status": integrity},
                "weather": weather,
                "hotspot": hotspot,
                "analysis": analysis_text
            })

    # 3. คัดกรอง: หาเฉพาะสถานีใหม่ที่ยังไม่เคยแจ้งเตือนวันนี้
    new_stations = [s for s in current_red_stations if s['info']['stationID'] not in history['alerted_ids']]
    
    # 4. เงื่อนไขการส่ง: ส่งเฉพาะเมื่อมีสถานีใหม่ (new_stations > 0)
    if new_stations:
        print(f"พบสถานีใหม่ {len(new_stations)} แห่ง ส่งรายงาน...")
        
        # อัปเดต Log ทันที
        for s in new_stations:
            history['alerted_ids'].append(s['info']['stationID'])
        
        # สร้างข้อความ (รวมทุกสถานีแดงปัจจุบัน เพื่อให้เห็นภาพรวม แต่แจ้งเตือนเพราะมีของใหม่)
        msg = f"📊 *[รายงานเฝ้าระวัง PM2.5 ระดับวิกฤต]*\n⏰ ข้อมูล: {now.strftime('%d %b %H:%M น.')}\n🔴 พื้นที่สีแดง: *{len(current_red_stations)}* (🆕 เพิ่มใหม่ {len(new_stations)})\n"
        msg += "--------------------------------\n"
        
        # จัดลำดับ: เอาของใหม่ขึ้นก่อน
        # แยก list เป็น [ใหม่] + [เก่า]
        display_list = new_stations + [s for s in current_red_stations if s not in new_stations]
        
        for item in display_list:
            s = item['info']
            st = item['stats']
            w = item['weather']
            h = item['hotspot']
            
            # สัญลักษณ์บอกว่าอันไหนใหม่
            new_tag = "🆕 " if s['stationID'] in [n['info']['stationID'] for n in new_stations] else ""
            
            w_text = f"*(แหล่งข้อมูล: {w['source']})*\n"
            if w['temp']: w_text += f"• *อุณหภูมิ:* {w['temp']}°C | *ความชื้น:* {w['hum']}%\n"
            if w['wind_dir']: w_text += f"• *ลม:* พัดจาก *{w['wind_dir']}* | *ความเร็ว:* {w['wind_spd']:.1f} กม./ชม."
            else: w_text += "• *ลม:* ไม่มีข้อมูล"

            h_text = ""
            if h and h['report_count'] > 0:
                top_lu = max(h['landuse'], key=h['landuse'].get) if h['landuse'] else "-"
                h_text = (f"*{h['scope_msg']}*\n"
                          f"• *พบทั้งหมด:* {h['report_count']} จุด (สะสม 24ชม.)\n"
                          f"• *พื้นที่หลัก:* {top_lu} ({h['landuse'].get(top_lu,0)})\n"
                          f"• *ระยะใกล้สุด:* {h['nearest']:.1f} กม. ทาง*{h['nearest_dir']}*")
            else:
                h_text = "• ไม่พบจุดความร้อนในรัศมี 50 กม."

            msg += (f"\n{new_tag}📍 *{s['nameTH']} ({s['stationID']})*\n"
                    f"จังหวัด: {s['areaTH'].split(',')[-1].strip()}\n\n"
                    f"💨 *1. ข้อมูลฝุ่น PM2.5*\n"
                    f"• *รายชั่วโมง:* {st['now']} µg/m³ (🔴 วิกฤต)\n"
                    f"• *เฉลี่ย 24 ชม:* {st['avg24']:.1f} µg/m³\n"
                    f"• *พิสัย 48 ชม:* {st['min']} - {st['max']} µg/m³\n"
                    f"• *สถานะข้อมูล:* {st['status']}\n\n"
                    f"🌦️ *2. ข้อมูลอุตุนิยมวิทยา*\n{w_text}\n\n"
                    f"🔥 *3. ข้อมูลจุดความร้อน (Hotspot)*\n{h_text}\n\n"
                    f"📝 *4. ผลการวิเคราะห์*\n{item['analysis']}\n"
                    f"================================\n")

        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
                      json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
        
        # บันทึกไฟล์ Log
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)
            
    else:
        print("ไม่มีสถานีแดงใหม่ ไม่ส่งรายงาน")

if __name__ == "__main__":
    main()
