import requests
import pandas as pd
import os
import json
import datetime
import pytz
import math

# --- Configuration ---
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')
GISTDA_KEY = os.getenv('GISTDA_API_KEY')
TIMEZONE = pytz.timezone('Asia/Bangkok')
LOG_FILE = "log.json"

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
    """แปลงองศาลม (0-360) เป็นชื่อทิศภาษาไทย"""
    if num is None: return "ไม่ระบุ"
    val = int((num/22.5)+.5)
    arr = [
        "ทิศเหนือ", "ทิศตะวันออกเฉียงเหนือ", "ทิศตะวันออกเฉียงเหนือ", "ทิศตะวันออกเฉียงเหนือ",
        "ทิศตะวันออก", "ทิศตะวันออกเฉียงใต้", "ทิศตะวันออกเฉียงใต้", "ทิศตะวันออกเฉียงใต้",
        "ทิศใต้", "ทิศตะวันตกเฉียงใต้", "ทิศตะวันตกเฉียงใต้", "ทิศตะวันตกเฉียงใต้",
        "ทิศตะวันตก", "ทิศตะวันตกเฉียงเหนือ", "ทิศตะวันตกเฉียงเหนือ", "ทิศตะวันตกเฉียงเหนือ"
    ]
    return arr[(val % 16)]

# --- Data Fetching ---

def get_weather_data(s_payload, lat, lon):
    weather = {
        "source": "สถานี คพ.",
        "temp": None, "hum": None, "wind_spd": None, "wind_dir": None, "wind_deg": None
    }
    
    # 1. Try Air4Thai
    try:
        url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_payload['stationID']}&param=PM25,WS,WD,TEMP,RH&type=hr&limit=1"
        h_res = requests.get(url, timeout=10).json()
        latest = h_res['stations'][0]['data'][-1]
        
        if latest.get('TEMP') and float(latest['TEMP']) > -90: weather['temp'] = float(latest['TEMP'])
        if latest.get('RH'): weather['hum'] = float(latest['RH'])
        if latest.get('WS'): weather['wind_spd'] = float(latest['WS']) * 3.6 # m/s to km/h
        if latest.get('WD'): 
            weather['wind_deg'] = float(latest['WD'])
            weather['wind_dir'] = deg_to_compass_thai(weather['wind_deg'])
    except: pass

    # 2. Try TMD (Mockup: Default to closest station if PCD fails)
    if weather['temp'] is None:
        tmd_id = 1034 
        url_tmd = f"http://122.155.135.49/api/home/site/{tmd_id}"
        try:
            t_res = requests.get(url_tmd, timeout=10).json()
            item = t_res['data']['items'][0]
            
            # แปลงชื่อทิศอังกฤษ -> ไทย
            raw_dir = item.get('winddirsign', 'N/A')
            thai_dir = WIND_DIR_MAP.get(raw_dir.upper(), raw_dir)
            
            weather = {
                "source": f"สถานีกรมอุตุฯ (AWS {tmd_id})",
                "temp": item.get('temp'),
                "hum": item.get('humidity'),
                "wind_spd": item.get('windspeed'),
                "wind_dir": thai_dir,
                "wind_deg": item.get('winddir')
            }
        except:
            weather['source'] = "ไม่พบข้อมูลอากาศ"

    return weather

def get_hotspot_data(lat, lon, wind_deg):
    url = "https://api-gateway.gistda.or.th/api/2.0/resources/features/viirs/1day?limit=1000&offset=0&ct_tn=ราชอาณาจักรไทย"
    headers = {'accept': 'application/json', 'API-Key': GISTDA_KEY}
    
    hotspot_summary = {"total": 0, "landuse": {}, "nearest": 9999, "nearest_dir": ""}
    
    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        features = res.get('features', [])
        
        for f in features:
            props = f['properties']
            h_lat, h_lon = props['latitude'], props['longitude']
            
            dist = haversine(lat, lon, h_lat, h_lon)
            if dist <= 50:
                if is_upwind(lat, lon, h_lat, h_lon, wind_deg):
                    hotspot_summary['total'] += 1
                    lu = props.get('lu_hp_name', 'ไม่ระบุ')
                    hotspot_summary['landuse'][lu] = hotspot_summary['landuse'].get(lu, 0) + 1
                    
                    if dist < hotspot_summary['nearest']:
                        hotspot_summary['nearest'] = dist
                        # หาว่าจุดไฟอยู่ทิศไหนของสถานี (แปลงเป็นไทย)
                        b = calculate_bearing(lat, lon, h_lat, h_lon)
                        hotspot_summary['nearest_dir'] = deg_to_compass_thai(b)
    except Exception as e:
        print(f"GISTDA Error: {e}")
        return None

    return hotspot_summary

def analyze_situation(pm25_now, pm25_24, wind_spd, hotspot_count, integrity, wind_dir_thai):
    """วิเคราะห์สถานการณ์เป็นภาษาไทย"""
    analysis = ""
    
    if "Spike" in integrity: return "⚠️ ข้อมูลมีความผิดปกติ (ค่าพุ่งสูงเฉียบพลัน Spike) ควรตรวจสอบเซนเซอร์ก่อนเชื่อถือข้อมูล"
    if "ขาดหาย" in integrity: return "⚠️ ข้อมูลไม่ครบถ้วน (Missing Data) อาจทำให้การประเมินคลาดเคลื่อน"

    factors = []
    if wind_spd is not None and wind_spd < 5: factors.append("สภาพอากาศปิด/ลมนิ่ง")
    if hotspot_count and hotspot_count > 5: factors.append(f"จุดความร้อนหนาแน่นใน{wind_dir_thai} (ต้นลม)")
    
    if pm25_now > 75:
        if "จุดความร้อน" in str(factors) and "ลมนิ่ง" in str(factors):
            analysis = "✅ **สถานการณ์จริง:** ค่าฝุ่นสูงวิกฤตสอดคล้องกับสภาพอากาศปิดและการเผาในพื้นที่ต้นลม"
        elif "จุดความร้อน" in str(factors):
            analysis = f"✅ **สถานการณ์จริง:** ลมพัดพาฝุ่นจากการเผาไหม้ทาง{wind_dir_thai}เข้ามาสะสมในพื้นที่"
        elif "ลมนิ่ง" in str(factors):
            analysis = "⚠️ **เฝ้าระวัง:** ไม่พบจุดเผาใกล้เคียง แต่ค่าฝุ่นสูงจากสภาพอากาศปิด (อาจเป็นฝุ่นสะสมหรือควันข้ามแดน)"
        else:
            analysis = "⚠️ **เฝ้าระวัง:** ค่าฝุ่นสูงโดยไม่พบปัจจัยแวดล้อมชัดเจน อาจเกิดจากแหล่งกำเนิดเฉพาะจุด"
            
    return analysis

def main():
    now = datetime.datetime.now(TIMEZONE)
    res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php").json()
    red_stations = []

    for s in res.get('stations', []):
        val = s.get('AQILast', {}).get('PM25', {}).get('value')
        s_id = s['stationID']
        
        if val and float(val) > 75.0 and s_id != "11t":
            lat, lon = float(s['lat']), float(s['long'])
            
            # History & Stats
            edate = now.strftime("%Y-%m-%d")
            sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
            hist_url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
            
            try:
                h_res = requests.get(hist_url, timeout=15).json()
                data = h_res['stations'][0]['data']
                df = pd.DataFrame(data)
                df['PM25'] = pd.to_numeric(df['PM25'], errors='coerce')
                
                issues = []
                if df['PM25'].diff().abs().max() > 50: issues.append("Spike")
                if (df['PM25'].rolling(4).std() == 0).any(): issues.append("Flatline")
                if df['PM25'].isnull().sum() > 4: issues.append("ขาดหาย > 4ชม.")
                integrity = "✅ ปกติ" if not issues else f"⚠️ {','.join(issues)}"
                
                pm25_now = float(val)
                pm25_24h = df.tail(24)['PM25'].mean()
                v_min, v_max = df['PM25'].min(), df['PM25'].max()
            except:
                pm25_24h, v_min, v_max = 0, 0, 0
                integrity = "❌ ดึงประวัติไม่ได้"

            weather = get_weather_data(s, lat, lon)
            hotspot = get_hotspot_data(lat, lon, weather['wind_deg'])
            
            # ส่งทิศลมไทยเข้าฟังก์ชันวิเคราะห์ด้วย
            w_dir_th = weather['wind_dir'] if weather['wind_dir'] else "ทิศเหนือลม"
            analysis_text = analyze_situation(pm25_now, pm25_24h, weather['wind_spd'], hotspot['total'] if hotspot else 0, integrity, w_dir_th)

            red_stations.append({
                "info": s,
                "stats": {"now": pm25_now, "avg24": pm25_24h, "min": v_min, "max": v_max, "status": integrity},
                "weather": weather,
                "hotspot": hotspot,
                "analysis": analysis_text
            })

    if red_stations:
        msg = f"📊 *[รายงานเฝ้าระวัง PM2.5 ระดับวิกฤต]*\n⏰ ข้อมูลประจำวันที่: {now.strftime('%d %b เวลา %H:%M น.')}\n🔴 พบพื้นที่สีแดงจำนวน: *{len(red_stations)} สถานี*\n"
        msg += "--------------------------------\n"
        
        for item in red_stations:
            s = item['info']
            st = item['stats']
            w = item['weather']
            h = item['hotspot']
            
            w_text = f"*(แหล่งข้อมูล: {w['source']})*\n"
            if w['temp']: w_text += f"• *อุณหภูมิ:* {w['temp']}°C | *ความชื้น:* {w['hum']}%\n"
            if w['wind_dir']: w_text += f"• *ลม:* พัดจาก *{w['wind_dir']}* | *ความเร็ว:* {w['wind_spd']:.1f} กม./ชม."
            else: w_text += "• *ลม:* ไม่มีข้อมูล"

            if h and h['total'] > 0:
                top_lu = max(h['landuse'], key=h['landuse'].get) if h['landuse'] else "-"
                h_text = (f"*(รัศมี 50 กม. จากทิศที่ลมพัดมา)*\n"
                          f"• *พบทั้งหมด:* {h['total']} จุด\n"
                          f"• *พื้นที่หลัก:* {top_lu} ({h['landuse'].get(top_lu,0)})\n"
                          f"• *ระยะใกล้สุด:* {h['nearest']:.1f} กม. ทาง*{h['nearest_dir']}*")
            else:
                h_text = "• ไม่พบจุดความร้อนในทิศเหนือลม (รัศมี 50 กม.)"

            msg += (f"\n📍 *{s['nameTH']} ({s['stationID']})*\n"
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
        print("ส่งรายงานเรียบร้อย")

if __name__ == "__main__":
    main()
