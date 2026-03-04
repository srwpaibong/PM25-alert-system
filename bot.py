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

def deg_to_compass_thai(num):
    if num is None: return "ไม่ระบุ"
    try:
        val = int((float(num)/22.5)+.5)
        arr = ["ทิศเหนือ", "ทิศตะวันออกเฉียงเหนือ", "ทิศตะวันออกเฉียงเหนือ", "ทิศตะวันออกเฉียงเหนือ",
               "ทิศตะวันออก", "ทิศตะวันออกเฉียงใต้", "ทิศตะวันออกเฉียงใต้", "ทิศตะวันออกเฉียงใต้",
               "ทิศใต้", "ทิศตะวันตกเฉียงใต้", "ทิศตะวันตกเฉียงใต้", "ทิศตะวันตกเฉียงใต้",
               "ทิศตะวันตก", "ทิศตะวันตกเฉียงเหนือ", "ทิศตะวันตกเฉียงเหนือ", "ทิศตะวันตกเฉียงเหนือ"]
        return arr[(val % 16)]
    except: return "ไม่ระบุ"

def is_upwind(target_bearing, wind_deg):
    if wind_deg is None: return False
    diff = abs(target_bearing - wind_deg)
    diff = min(diff, 360 - diff)
    return diff <= 45

def format_thai_datetime(dt):
    """แปลงวันที่เป็นรูปแบบทางการภาษาไทย"""
    thai_months = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", 
                   "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
    year = dt.year + 543
    month = thai_months[dt.month]
    return f"{dt.day} {month} {year} เวลา {dt.strftime('%H:%M')} น."

def get_wind_category(speed_ms):
    """จัดเกณฑ์ความเร็วลม (หน่วย m/s)"""
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
        "dist": 9999
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
        
        # ลมใช้หน่วย m/s ตามค่าดั้งเดิมของ API
        w_speed = nearest_feature.get('windSpeed')
        if w_speed is not None:
            weather['wind_spd'] = float(w_speed)
            
        w_deg = nearest_feature.get('windDir')
        if w_deg is not None:
            weather['wind_deg'] = float(w_deg)
            weather['wind_dir'] = deg_to_compass_thai(w_deg)
            
    return weather

def get_nearest_hotspot(lat, lon, wind_deg):
    """ค้นหาจุดความร้อนย้อนหลัง 3 วัน Limit 5000 ในประเทศไทย"""
    # ใช้ URL Encoded เพื่อป้องกันปัญหาการอ่านอักขระไทยใน Requests
    encoded_thailand = "%E0%B8%A3%E0%B8%B2%E0%B8%8A%E0%B8%AD%E0%B8%B2%E0%B8%93%E0%B8%B2%E0%B8%88%E0%B8%B1%E0%B8%81%E0%B8%A3%E0%B9%84%E0%B8%97%E0%B8%A2"
    url = f"https://api-gateway.gistda.or.th/api/2.0/resources/features/viirs/3days?limit=5000&offset=0&ct_tn={encoded_thailand}"
    headers = {'accept': 'application/json', 'API-Key': GISTDA_KEY}
    
    hotspot_info = {
        "found": False, "dist": 9999, "dir_text": "", "main_landuse": "",
        "is_upwind": False, "nearby_count": 0, "error": False
    }
    landuses = {}
    
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        features = res.get('features', [])
        
        for f in features:
            coords = f.get('geometry', {}).get('coordinates', [])
            if len(coords) < 2: continue
            
            h_lon, h_lat = coords[0], coords[1]
            props = f.get('properties', {})
            
            dist = haversine(lat, lon, h_lat, h_lon)
            
            # พิจารณาเฉพาะจุดที่อยู่ในรัศมี 100 กม.
            if dist <= 100:
                hotspot_info['found'] = True
                hotspot_info['nearby_count'] += 1
                
                lu = props.get('lu_hp_name', 'ไม่ระบุ')
                landuses[lu] = landuses.get(lu, 0) + 1
                
                # หาจุดที่ใกล้ที่สุดเพื่อรายงานทิศทาง
                if dist < hotspot_info['dist']:
                    hotspot_info['dist'] = dist
                    bearing = calculate_bearing(lat, lon, h_lat, h_lon)
                    hotspot_info['dir_text'] = deg_to_compass_thai(bearing)
                    hotspot_info['is_upwind'] = is_upwind(bearing, wind_deg)

        if hotspot_info['found']:
            hotspot_info['main_landuse'] = max(landuses, key=landuses.get)

    except Exception as e:
        print(f"GISTDA API Error: {e}")
        hotspot_info['error'] = True

    return hotspot_info

def analyze_station_integrity(s_id):
    """วิเคราะห์ความสมบูรณ์ของข้อมูลย้อนหลัง 48 ชม."""
    now = datetime.datetime.now(TIMEZONE)
    edate = now.strftime("%Y-%m-%d")
    sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
    
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).json()
        data = res.get('stations', [{}])[0].get('data', [])
        
        if not data: return "ระบบตรวจวัดขัดข้อง (ไม่พบข้อมูลย้อนหลัง)", "N/A"

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
        if df['value'].diff().abs().max() > 50: issues.append("Spike (ค่ากระโดดผิดปกติ)")
        if (df['value'].rolling(4).std() == 0).any(): issues.append("Flatline (ค่าค้าง)")
        if (df['value'] < 0).any(): issues.append("Negative (ค่าติดลบ)")
        if df['value'].isnull().sum() > 4: issues.append("Missing (ข้อมูลขาดหายหลายชั่วโมง)")
        
        status = "ข้อมูลตรวจวัดอยู่ในเกณฑ์ปกติ" if not issues else f"พบความผิดปกติ: {', '.join(issues)}"
        return status, v_range
    except:
        return "ไม่สามารถเชื่อมต่อฐานข้อมูลย้อนหลังได้", "N/A"

def analyze_situation(integrity_status):
    """ประเมินเฉพาะสถานะเครื่องตรวจวัด"""
    if "ปกติ" in integrity_status:
        machine_status = "ยืนยันข้อมูลปกติ เบื้องต้นระบบตรวจวัดทำงานสมบูรณ์"
    else:
        # ตัดคำว่า 'พบความผิดปกติ:' ออกเพื่อให้อ่านลื่นขึ้น
        issues = integrity_status.replace("พบความผิดปกติ: ", "")
        machine_status = f"เบื้องต้นข้อมูลตรวจวัดมีความเสี่ยงผิดปกติ ({issues}) รอเจ้าหน้าที่ตรวจสอบยืนยัน"

    return f"• สถานะเครื่องวัด: {machine_status}"

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": []}
    return {"last_date": "", "alerted_ids": []}

def calculate_thai_aqi(pm25):
    if pm25 <= 15.0: xi, xj, ii, ij = 0, 15.0, 0, 25
    elif pm25 <= 25.0: xi, xj, ii, ij = 15.1, 25.0, 26, 50
    elif pm25 <= 37.5: xi, xj, ii, ij = 25.1, 37.5, 51, 100
    elif pm25 <= 75.0: xi, xj, ii, ij = 37.6, 75.0, 101, 200
    else: xi, xj, ii, ij = 75.1, 500.0, 201, 500
    return int(round(((ij - ii) / (xj - xi)) * (pm25 - xi) + ii))

def main():
    now = datetime.datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")
    date_formatted = format_thai_datetime(now)
    
    history = load_log()
    if history.get('last_date') != today_str:
        history = {"last_date": today_str, "alerted_ids": []}

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
        
        if val and float(val) > 75.0 and s_id != "11t":
            lat, lon = float(s['lat']), float(s['long'])
            pm25_now = float(val)
            
            integrity_status, v_range = analyze_station_integrity(s_id)
            weather = find_nearest_weather(lat, lon, tmd_features)
            h_info = get_nearest_hotspot(lat, lon, weather['wind_deg'])
            
            analysis = analyze_situation(integrity_status)

            current_red_stations.append({
                "info": s,
                "stats": {"now": pm25_now, "range": v_range, "status": integrity_status},
                "weather": weather,
                "hotspot": h_info,
                "analysis": analysis
            })

    new_stations = [s for s in current_red_stations if s['info']['stationID'] not in history['alerted_ids']]
    
    if new_stations:
        print(f"พบสถานีใหม่ {len(new_stations)} แห่ง")
        for s in new_stations:
            history['alerted_ids'].append(s['info']['stationID'])
            
        header_msg = f"📊 [รายงานการติดตามระบบเฝ้าระวัง PM2.5]\n⏰ ข้อมูล ณ วันที่: {date_formatted}\n🔴 พื้นที่เฝ้าระวังระดับวิกฤต: {len(current_red_stations)} สถานี (แจ้งเตือนใหม่ {len(new_stations)})\n"
        header_msg += "--------------------------------\n"
        
        display_list = new_stations + [s for s in current_red_stations if s not in new_stations]
        
        messages_to_send = []
        current_msg = header_msg
        
        for item in display_list:
            s = item['info']
            st = item['stats']
            w = item['weather']
            h = item['hotspot']
            
            new_tag = "🆕 " if s['stationID'] in [n['info']['stationID'] for n in new_stations] else ""
            aqi = calculate_thai_aqi(st['now'])
            
            sections = []

            # 1. PM2.5 Block
            pm25_text = (f"💨 1. ข้อมูลฝุ่น PM2.5\n"
                         f"• Range (AVG.24 hr): {st['range']} µg/m³\n"
                         f"• Current Data (AVG.1 hr): {st['now']} µg/m³\n"
                         f"• AQI: {aqi}\n"
                         f"• Status: {st['status']}")
            sections.append(pm25_text)

            # 2. Weather Block
            w_text = f"🌦️ 2. ข้อมูลอุตุนิยมวิทยาเบื้องต้น\n(แหล่งข้อมูล: {w['source']})\n"
            if w['temp']: w_text += f"• อุณหภูมิ: {w['temp']}°C | ความชื้น: {w['hum']}%\n"
            if w['wind_dir']: 
                wind_cat = get_wind_category(w['wind_spd'])
                w_text += f"• ทิศทางลม: พัดจาก{w['wind_dir']}\n• ความเร็วลม: {wind_cat} ({w['wind_spd']:.1f} m/s)"
            else: w_text += "• ข้อมูลลม: ไม่พบข้อมูลอุตุนิยมวิทยาในพื้นที่ใกล้เคียง"
            sections.append(w_text)

            # 3. Hotspot Block (เพิ่มเฉพาะเมื่อเจอจุดความร้อนเท่านั้น)
            if h.get('found') and not h.get('error'):
                h_text = (f"🔥 3. ข้อมูลจุดความร้อนสะสม (ข้อมูลจาก GISTDA)\n"
                          f"• พบจุดความร้อนจำนวน: {h['nearby_count']} จุด (ในรัศมี 100 กม.)\n"
                          f"• จุดที่ใกล้ที่สุด: ห่าง {h['dist']:.1f} กม. ทาง{h['dir_text']}\n"
                          f"• พื้นที่การเกิดหลัก: {h['main_landuse']}\n")
                if h['is_upwind']: h_text += "• ทิศทางควัน: [อยู่ต้นลม] ความเสี่ยงสูง"
                else: h_text += "• ทิศทางควัน: [อยู่ท้ายลม/ข้างลม] ความเสี่ยงต่ำ"
                
                sections.append(h_text)
                next_section_num = 4
            else:
                # ถ้าไม่เจอจุดความร้อน หรือ API ขัดข้อง ให้ข้ามข้อ 3 ไปเลย
                next_section_num = 3

            # 4. Analysis Block (เลขหัวข้อปรับเปลี่ยนอัตโนมัติ)
            analysis_text = f"📝 {next_section_num}. ประเมินสถานการณ์เบื้องต้น\n{item['analysis']}"
            sections.append(analysis_text)

            # รวมเนื้อหา
            item_text = (f"\n{new_tag}📍 {s['nameTH']} ({s['stationID']})\n"
                         f"จังหวัด: {s['areaTH'].split(',')[-1].strip()}\n\n" +
                         "\n\n".join(sections) +
                         "\n================================\n")
            
            if len(current_msg) + len(item_text) > 4000:
                messages_to_send.append(current_msg)
                current_msg = item_text
            else:
                current_msg += item_text

        if current_msg:
            messages_to_send.append(current_msg)

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
    else:
        print("ไม่มีสถานีแจ้งเตือนใหม่")

if __name__ == "__main__":
    main()
