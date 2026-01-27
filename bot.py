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

# --- Helper Functions: Geometry & Calculation ---

def haversine(lat1, lon1, lat2, lon2):
    """คำนวณระยะทางระหว่าง 2 พิกัด (km)"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2) * math.sin(dlat/2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlon/2) * math.sin(dlon/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def calculate_bearing(lat1, lon1, lat2, lon2):
    """คำนวณทิศทาง (Degree) จากจุด 1 ไปจุด 2"""
    dLon = math.radians(lon2 - lon1)
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)
    y = math.sin(dLon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - \
        math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360

def is_upwind(target_bearing, wind_deg):
    """เช็คว่าเป้าหมายอยู่ต้นลมหรือไม่ (+/- 45 องศา)"""
    if wind_deg is None: return False
    diff = abs(target_bearing - wind_deg)
    diff = min(diff, 360 - diff)
    return diff <= 45

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

# --- Data Fetching Functions ---

def get_tmd_stations_list():
    """ดึงรายชื่อสถานีอุตุฯ ทั้งหมดพร้อมพิกัด"""
    url = "http://122.155.135.49/api/home/poi"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get('result') == 1:
            return res.get('data', [])
    except:
        pass
    return []

def find_nearest_tmd_station(lat, lon, station_list):
    """หาสถานีอุตุฯ ที่ใกล้ที่สุดจากพิกัด"""
    nearest = None
    min_dist = 99999
    
    for s in station_list:
        try:
            s_lat = float(s.get('LAT', 0))
            s_lon = float(s.get('LON', 0))
            if s_lat == 0 or s_lon == 0: continue
            
            dist = haversine(lat, lon, s_lat, s_lon)
            if dist < min_dist:
                min_dist = dist
                nearest = s
        except: continue
        
    return nearest, min_dist

def get_weather_data_smart(lat, lon):
    """ระบบดึงสภาพอากาศแบบฉลาด (Air4Thai -> TMD Nearest)"""
    weather = {
        "source": "ไม่พบข้อมูล", "temp": None, "hum": None, 
        "wind_spd": None, "wind_dir": None, "wind_deg": None,
        "dist": 0
    }
    
    # 1. พยายามหาจาก TMD POI ก่อน (เพราะข้อมูลละเอียดกว่า)
    tmd_stations = get_tmd_stations_list()
    nearest_station, dist = find_nearest_tmd_station(lat, lon, tmd_stations)
    
    if nearest_station:
        aws_id = nearest_station.get('AWSID')
        url = f"http://122.155.135.49/api/home/site/{aws_id}"
        try:
            res = requests.get(url, timeout=10).json()
            # ดึง list ข้อมูลรายชั่วโมง
            items = res.get('data', {}).get('items', [])
            
            if items:
                # เลือกข้อมูลตัวล่าสุดใน list (ปกติ API จะเรียงเวลามาให้แล้ว ตัวท้ายสุดคือล่าสุด)
                # หรือถ้าไม่มีล่าสุด ให้เอาตัวไหนก็ได้ที่มีค่าลม
                valid_item = items[-1] 
                
                # ถ้าตัวล่าสุดไม่มีลม ลองย้อนกลับไปดู 2-3 ชม. ก่อนหน้า
                for item in reversed(items):
                    if item.get('windspeed') is not None:
                        valid_item = item
                        break
                
                weather['source'] = f"สถานีอุตุฯ {nearest_station.get('FNAME', 'ใกล้เคียง')} (ห่าง {dist:.1f} กม.)"
                weather['temp'] = valid_item.get('temp')
                weather['hum'] = valid_item.get('humidity')
                
                w_spd = float(valid_item.get('windspeed', 0))
                # API นี้บางทีส่ง m/s บางที km/h แต่ส่วนใหญ่ถ้าน้อยๆ คือ m/s
                if w_spd < 20: w_spd *= 3.6 
                
                weather['wind_spd'] = w_spd
                weather['wind_deg'] = float(valid_item.get('winddir', 0))
                
                # แปลงทิศอังกฤษเป็นไทย
                raw_dir = valid_item.get('winddirsign', 'N/A')
                # ใช้ฟังก์ชันแปลงองศาเป็นไทยจะแม่นกว่าตัวอักษรย่อ
                weather['wind_dir'] = deg_to_compass_thai(weather['wind_deg'])
                
        except Exception as e:
            print(f"TMD API Error: {e}")

    return weather

def get_nearest_hotspot(lat, lon, wind_deg):
    """หาจุดความร้อนที่ใกล้ที่สุดและวิเคราะห์ผลกระทบ"""
    url = "https://api-gateway.gistda.or.th/api/2.0/resources/features/viirs/1day?limit=1000&offset=0&ct_tn=ราชอาณาจักรไทย"
    headers = {'accept': 'application/json', 'API-Key': GISTDA_KEY}
    
    hotspot_info = {
        "found": False,
        "dist": 9999,
        "dir_text": "",
        "landuse": "",
        "is_upwind": False,
        "bearing": 0
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        features = res.get('features', [])
        
        for f in features:
            props = f['properties']
            h_lat, h_lon = props['latitude'], props['longitude']
            
            # คำนวณระยะทาง
            dist = haversine(lat, lon, h_lat, h_lon)
            
            # หาจุดที่ใกล้ที่สุด (Global Minimum)
            if dist < hotspot_info['dist']:
                hotspot_info['found'] = True
                hotspot_info['dist'] = dist
                hotspot_info['landuse'] = props.get('lu_hp_name', 'ไม่ระบุ')
                
                # คำนวณทิศทางจากสถานีไปหาจุดไฟ
                bearing = calculate_bearing(lat, lon, h_lat, h_lon)
                hotspot_info['bearing'] = bearing
                hotspot_info['dir_text'] = deg_to_compass_thai(bearing)
                
                # เช็คว่าอยู่ต้นลมไหม (ไฟอยู่ทิศเดียวกับที่ลมพัดมา)
                hotspot_info['is_upwind'] = is_upwind(bearing, wind_deg)

    except Exception as e:
        print(f"GISTDA Error: {e}")
        return None

    return hotspot_info

def analyze_situation(pm25_now, pm25_24, wind_spd, h_info, integrity):
    """วิเคราะห์สถานการณ์แบบรวมศูนย์"""
    analysis = ""
    
    # 1. เช็คข้อมูล Integrity
    if "Spike" in integrity: return "⚠️ ข้อมูลผิดปกติ (ค่าพุ่งสูงเฉียบพลัน Spike) ควรตรวจสอบหน้าเครื่อง"
    if "ขาดหาย" in integrity: return "⚠️ ข้อมูลไม่ครบถ้วน (Missing Data)"

    # 2. วิเคราะห์ปัจจัยแวดล้อม
    factors = []
    
    # ลม
    if wind_spd is not None and wind_spd < 4: 
        factors.append("สภาพอากาศปิด/ลมนิ่ง")
    
    # จุดความร้อน
    if h_info['found']:
        if h_info['dist'] < 20:
            factors.append(f"พบจุดความร้อนระยะประชิด ({h_info['dist']:.1f} กม.)")
        elif h_info['is_upwind'] and h_info['dist'] < 100:
            factors.append(f"ลมพัดกลุ่มควันจากระยะ {h_info['dist']:.0f} กม. เข้ามาสะสม")
    
    # สรุปผล
    if pm25_now > 75:
        if factors:
            analysis = f"✅ **สถานการณ์จริง:** ค่าฝุ่นสูงสอดคล้องกับปัจจัย: {', '.join(factors)}"
        else:
            analysis = "⚠️ **เฝ้าระวัง:** ค่าฝุ่นสูงโดยไม่พบปัจจัยแวดล้อมชัดเจน อาจเกิดจากแหล่งกำเนิดเฉพาะจุด (จราจร/โรงงาน)"
            
    return analysis

def calculate_thai_aqi(pm25):
    if pm25 <= 15.0: xi, xj, ii, ij = 0, 15.0, 0, 25
    elif pm25 <= 25.0: xi, xj, ii, ij = 15.1, 25.0, 26, 50
    elif pm25 <= 37.5: xi, xj, ii, ij = 25.1, 37.5, 51, 100
    elif pm25 <= 75.0: xi, xj, ii, ij = 37.6, 75.0, 101, 200
    else: xi, xj, ii, ij = 75.1, 500.0, 201, 500
    return int(round(((ij - ii) / (xj - xi)) * (pm25 - xi) + ii))

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": {}}
    return {"last_date": "", "alerted_ids": {}}

def main():
    now = datetime.datetime.now(TIMEZONE)
    history = load_log()
    today_str = now.strftime("%Y-%m-%d")
    
    if history.get('last_date') != today_str:
        history = {"last_date": today_str, "alerted_ids": {}}

    try:
        res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php", timeout=20).json()
    except:
        return

    red_stations = []

    for s in res.get('stations', []):
        val = s.get('AQILast', {}).get('PM25', {}).get('value')
        s_id = s['stationID']
        
        if val and float(val) > 75.0 and s_id != "11t":
            lat, lon = float(s['lat']), float(s['long'])
            
            # 1. History & Integrity
            edate = now.strftime("%Y-%m-%d")
            sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
            hist_url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
            try:
                h_res = requests.get(hist_url, timeout=10).json()
                data = h_res['stations'][0]['data']
                df = pd.DataFrame(data)
                df['PM25'] = pd.to_numeric(df['PM25'], errors='coerce')
                pm25_now = float(val)
                pm25_24h = df.tail(24)['PM25'].mean()
                v_min, v_max = df['PM25'].min(), df['PM25'].max()
                
                issues = []
                if df['PM25'].diff().abs().max() > 50: issues.append("Spike")
                if (df['PM25'].rolling(4).std() == 0).any(): issues.append("Flatline")
                if df['PM25'].isnull().sum() > 4: issues.append("ขาดหาย > 4ชม.")
                integrity = "✅ ปกติ" if not issues else f"⚠️ {','.join(issues)}"
            except:
                pm25_24h, v_min, v_max = 0, 0, 0
                integrity = "❌ ดึงประวัติไม่ได้"

            # 2. Smart Weather (ดึงจากสถานีใกล้สุด)
            weather = get_weather_data_smart(lat, lon)
            
            # 3. Nearest Hotspot
            h_info = get_nearest_hotspot(lat, lon, weather['wind_deg'])
            
            # 4. Analysis
            w_dir_th = weather['wind_dir'] if weather['wind_dir'] else "ทิศเหนือลม"
            analysis_text = analyze_situation(pm25_now, pm25_24h, weather['wind_spd'], h_info, integrity, w_dir_th)

            red_stations.append({
                "info": s,
                "stats": {"now": pm25_now, "avg24": pm25_24h, "min": v_min, "max": v_max, "status": integrity},
                "weather": weather,
                "hotspot": h_info,
                "analysis": analysis_text
            })

    # เงื่อนไขเดิม: ส่งเฉพาะเมื่อมีสถานีใหม่
    new_stations = [s for s in red_stations if s['info']['stationID'] not in history['alerted_ids']]
    
    if new_stations:
        print(f"พบสถานีใหม่ {len(new_stations)} แห่ง")
        
        # เรียงลำดับ: เอาสถานีใหม่ไว้บนสุด
        display_list = new_stations + [s for s in red_stations if s not in new_stations]
        
        msg = f"📊 *[รายงานเฝ้าระวัง PM2.5 ระดับวิกฤต]*\n⏰ ข้อมูล: {now.strftime('%d %b %H:%M น.')}\n🔴 พื้นที่สีแดง: *{len(red_stations)}* (🆕 เพิ่มใหม่ {len(new_stations)})\n"
        msg += "--------------------------------\n"
        
        for item in display_list:
            s = item['info']
            st = item['stats']
            w = item['weather']
            h = item['hotspot']
            
            # บันทึก Log เฉพาะตัวใหม่
            if s['stationID'] not in history['alerted_ids']:
                history['alerted_ids'][s['stationID']] = now.strftime("%H:%M")
                new_tag = "🆕 "
            else:
                new_tag = ""
            
            # Weather Block
            w_text = f"(แหล่งข้อมูล: {w['source']})\n"
            if w['temp']: w_text += f"• อุณหภูมิ: {w['temp']}°C | ความชื้น: {w['hum']}%\n"
            if w['wind_dir']: w_text += f"• ลม: พัดจาก {w['wind_dir']} | ความเร็ว: {w['wind_spd']:.1f} กม./ชม."
            else: w_text += "• ลม: ไม่มีข้อมูล"

            # Hotspot Block (Nearest Logic)
            if h['found']:
                dist_km = h['dist']
                h_text = f"(จุดที่ใกล้ที่สุด)\n• ระยะห่าง: {dist_km:.1f} กม. ทาง{h['dir_text']}\n• พื้นที่: {h['landuse']}\n"
                if h['is_upwind']: h_text += "• 🌬️ *[อยู่ต้นลม]* ความเสี่ยงสูง"
                else: h_text += "• 💨 *[อยู่ท้ายลม/ข้างลม]* ความเสี่ยงต่ำ"
            else:
                h_text = "• ไม่พบข้อมูลจุดความร้อนในระบบ"

            msg += (f"\n{new_tag}📍 {s['nameTH']} ({s['stationID']})\n"
                    f"จังหวัด: {s['areaTH'].split(',')[-1].strip()}\n\n"
                    f"💨 1. ข้อมูลฝุ่น PM2.5\n"
                    f"• รายชั่วโมง: {st['now']} µg/m³ (🔴 วิกฤต)\n"
                    f"• เฉลี่ย 24 ชม: {st['avg24']:.1f} µg/m³\n"
                    f"• พิสัย 48 ชม: {st['min']} - {st['max']} µg/m³\n"
                    f"• สถานะข้อมูล: {st['status']}\n\n"
                    f"🌦️ 2. ข้อมูลอุตุนิยมวิทยา\n{w_text}\n\n"
                    f"🔥 3. ข้อมูลจุดความร้อน (Hotspot)\n{h_text}\n\n"
                    f"📝 4. ผลการวิเคราะห์\n{item['analysis']}\n"
                    f"================================\n")

        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
                      json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
        
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)
            
    else:
        print("ไม่มีสถานีแดงใหม่ ไม่ส่งรายงาน")

if __name__ == "__main__":
    main()
