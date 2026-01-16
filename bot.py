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

# --- Mapping: จังหวัด -> รหัสสถานีอุตุฯ (TMD AWS ID) ---
# รวบรวมจากข้อมูล API ที่คุณให้มา + สถานีหลักรายจังหวัด
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
    return diff <= 60 # มุมกว้าง +/- 60 องศา

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
    
    # 1. Try Air4Thai History
    try:
        url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_payload['stationID']}&param=PM25,WS,WD,TEMP,RH&type=hr&limit=1"
        h_res = requests.get(url, timeout=5).json()
        latest = h_res['stations'][0]['data'][-1]
        
        if latest.get('TEMP') and float(latest['TEMP']) > -90: weather['temp'] = float(latest['TEMP'])
        if latest.get('RH'): weather['hum'] = float(latest['RH'])
        if latest.get('WS'): weather['wind_spd'] = float(latest['WS']) * 3.6 # m/s to km/h
        if latest.get('WD'): 
            weather['wind_deg'] = float(latest['WD'])
            weather['wind_dir'] = deg_to_compass_thai(weather['wind_deg'])
    except: pass

    # 2. TMD Fallback (ถ้าไม่มีลมจาก คพ.)
    if weather['wind_deg'] is None:
        # ตัดคำว่า 'จ.' ออก และหาชื่อจังหวัด
        full_province = s_payload['areaTH'].split(',')[-1].strip()
        province_key = full_province.replace('จ.', '').strip()
        
        tmd_id = TMD_PROVINCE_MAP.get(province_key)
        
        if tmd_id:
            url_tmd = f"http://122.155.135.49/api/home/site/{tmd_id}"
            try:
                t_res = requests.get(url_tmd, timeout=10).json()
                item = t_res['data']['items'][0]
                
                raw_dir = item.get('winddirsign', 'N/A')
                thai_dir = WIND_DIR_MAP.get(raw_dir.upper(), raw_dir)
                
                weather['source'] = f"สถานีกรมอุตุฯ จ.{province_key}"
                weather['temp'] = item.get('temp')
                weather['hum'] = item.get('humidity')
                
                # แปลงหน่วยความเร็วลม (ถ้าค่าดูน้อยผิดปกติเหมือน m/s ให้คูณ 3.6)
                w_speed = float(item.get('windspeed', 0))
                if w_speed < 20: w_speed *= 3.6 
                weather['wind_spd'] = w_speed
                
                weather['wind_dir'] = thai_dir
                weather['wind_deg'] = float(item.get('winddir', 0))
            except:
                weather['source'] = f"สถานีกรมอุตุฯ (เชื่อมต่อไม่ได้)"
        else:
            weather['source'] = "ไม่พบสถานีตรวจวัดลมใกล้เคียง"

    return weather

def get_hotspot_data(lat, lon, wind_deg):
    url = "https://api-gateway.gistda.or.th/api/2.0/resources/features/viirs/1day?limit=1000&offset=0&ct_tn=ราชอาณาจักรไทย"
    headers = {'accept': 'application/json', 'API-Key': GISTDA_KEY}
    
    summary = {
        "upwind_total": 0, "nearby_total": 0,
        "landuse": {}, "nearest": 9999, "nearest_dir": "ไม่พบ",
        "scope_msg": ""
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        features = res.get('features', [])
        
        for f in features:
            props = f['properties']
            h_lat, h_lon = props['latitude'], props['longitude']
            dist = haversine(lat, lon, h_lat, h_lon)
            
            if dist <= 50:
                summary['nearby_total'] += 1
                
                if is_upwind(lat, lon, h_lat, h_lon, wind_deg):
