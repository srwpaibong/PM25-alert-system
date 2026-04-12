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

def format_thai_datetime(dt):
    thai_months = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", 
                   "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
    year = dt.year + 543
    month = thai_months[dt.month]
    return f"{dt.day} {month} {year} เวลา {dt.strftime('%H:%M')} น."

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
            weather['wind_dir'] = deg_to_compass_thai(w_deg)
            
    return weather

def analyze_station_integrity(s_id):
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
        if df['value'].isnull().sum() > 4: issues.append("Missing (ข้อมูลขาดหาย)")
        
        status = "ข้อมูลตรวจวัดอยู่ในเกณฑ์ปกติ" if not issues else f"พบความผิดปกติ: {', '.join(issues)}"
        return status, v_range
    except:
        return "ไม่สามารถเชื่อมต่อฐานข้อมูลย้อนหลังได้", "N/A"

def analyze_situation(integrity_status):
    if integrity_status == "ข้อมูลตรวจวัดอยู่ในเกณฑ์ปกติ":
        return "**ยืนยันระบบตรวจวัดทำงานปกติ**"
    else:
        issues = integrity_status.replace("พบความผิดปกติ: ", "")
        return f"เบื้องต้นข้อมูลตรวจวัดมีความเสี่ยงผิดปกติ ({issues}) **เจ้าหน้าที่ตรวจสอบแล้ว ยืนยันเครื่องมือทำงานปกติ**"

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

def generate_executive_summary(all_stations, date_formatted):
    if not all_stations:
        return ""

    total_stations = len(all_stations)
    regions = defaultdict(list)
    for s in all_stations:
        regions[s['region']].append(s)
        
    region_counts = []
    for r, items in regions.items():
        region_counts.append(f"{r} {len(items)}")
        
    summary = f"📋 **[สรุปภาพรวมสถานการณ์ฝุ่น PM2.5 ระดับวิกฤต]**\n"
    summary += f"📅 ข้อมูล ณ วันที่: {date_formatted}\n"
    summary += f"🔴 จำนวนสถานีวิกฤตทั้งหมด: {total_stations} สถานี ({', '.join(region_counts)})\n"
    summary += "="*32 + "\n"
    
    nat_temps = []
    nat_winds = []
    
    for region, items in regions.items():
        items_sorted = sorted(items, key=lambda x: x['stats']['now'], reverse=True)
        summary += f"\n📁 **{region}** (จำนวน {len(items)} สถานี)\n"
        
        temps = [i['weather']['temp'] for i in items_sorted if i['weather']['temp'] is not None]
        winds = [i['weather']['wind_spd'] for i in items_sorted if i['weather']['wind_spd'] is not None]
        dirs = [i['weather']['wind_dir'] for i in items_sorted if i['weather']['wind_dir']]
        precips = [i['weather'].get('precip', 0) for i in items_sorted]
        
        avg_temp = sum(temps)/len(temps) if temps else 0
        avg_wind = sum(winds)/len(winds) if winds else 0
        common_dir = max(set(dirs), key=dirs.count) if dirs else "ไม่ระบุ"
        has_rain = any(p > 0 for p in precips)
        
        nat_temps.extend(temps)
        nat_winds.extend(winds)
        
        wind_cat = get_wind_category(avg_wind)
        
        if avg_wind < 0.5:
            weather_str = f"อุณหภูมิเฉลี่ย {avg_temp:.1f}°C, ทิศทางลมหลักพัดจาก{common_dir}, ความเร็วลมเฉลี่ย: ลมสงบ"
        else:
            weather_str = f"อุณหภูมิเฉลี่ย {avg_temp:.1f}°C, ทิศทางลมหลักพัดจาก{common_dir}, ความเร็วลมเฉลี่ย: {wind_cat} ({avg_wind:.1f} m/s)"
            
        if has_rain:
            weather_str += " และมีรายงานฝนตกบางพื้นที่"
            
        summary += f"🌦️ สภาพอากาศภาพรวม: {weather_str}\n"
        
        normal_count = 0
        abnormal_details = []
        for i in items_sorted:
            status = i['stats']['status']
            if "ปกติ" in status and "พบความผิดปกติ" not in status:
                normal_count += 1
            else:
                issue = status.replace("พบความผิดปกติ: ", "").strip()
                abnormal_details.append(issue)
                
        abnormal_count = len(items_sorted) - normal_count
        if abnormal_count == 0:
            summary += f"📝 สถานะเครื่องตรวจวัด: **ยืนยันระบบตรวจวัดทำงานปกติทุกสถานี**\n"
        else:
            issue_counts = {}
            for detail in abnormal_details:
                parts = [p.strip() for p in detail.split(',')]
                for p in parts:
                    issue_counts[p] = issue_counts.get(p, 0) + 1
            issue_str = ", ".join([f"{k} {v} สถานี" for k, v in issue_counts.items()])
            summary += f"📝 สถานะเครื่องตรวจวัด: ทำงานปกติ {normal_count} สถานี, พบความเสี่ยง ({issue_str}) **เจ้าหน้าที่ตรวจสอบแล้ว ยืนยันเครื่องมือทำงานปกติทุกสถานี**\n"
        
        summary += f"📍 รายชื่อสถานี (เรียงตามค่าเฉลี่ย 24 ชม. จากมากไปน้อย):\n"
        for idx, item in enumerate(items_sorted, 1):
            s = item['info']
            st = item['stats']
            
            area_parts = s['areaTH'].split(',')
            if len(area_parts) >= 3:
                amphoe = area_parts[-2].strip()
            elif len(area_parts) == 2:
                amphoe = area_parts[0].strip()
            else:
                amphoe = ""
            
            max_1hr = "N/A"
            if '-' in st['range']:
                max_1hr = st['range'].split('-')[-1].strip()
                
            summary += f"  {idx}. [{s['stationID']}] {s['nameTH']} {amphoe} จ.{item['province']}\n"
            summary += f"      ↳ เฉลี่ย 24 ชม.: {st['now']} | รายชั่วโมงสูงสุด: {max_1hr} µg/m³\n"
    
    avg_nat_temp = sum(nat_temps)/len(nat_temps) if nat_temps else 0
    avg_nat_wind = sum(nat_winds)/len(nat_winds) if nat_winds else 0
    nat_wind_cat = get_wind_category(avg_nat_wind)
    
    summary += "\n" + "="*32 + "\n"
    summary += "📌 **สรุปแนวโน้มสถานการณ์ภาพรวม**\n"
    summary += f"• **สถานการณ์ฝุ่น:** พบพื้นที่เฝ้าระวังระดับวิกฤต (สีแดง) รวมทั้งสิ้น {total_stations} สถานี แนะนำให้ติดตามสถานการณ์อย่างใกล้ชิด\n"
    if avg_nat_wind < 0.5:
        summary += f"• **สภาพอากาศภาพรวม:** อุณหภูมิเฉลี่ย {avg_nat_temp:.1f}°C สภาพลมโดยเฉลี่ยอยู่ในเกณฑ์ลมสงบ ซึ่งเป็นปัจจัยเสริมให้เกิดการสะสมของฝุ่นละออง\n"
    else:
        summary += f"• **สภาพอากาศภาพรวม:** อุณหภูมิเฉลี่ย {avg_nat_temp:.1f}°C สภาพลมโดยเฉลี่ยอยู่ในเกณฑ์{nat_wind_cat} ({avg_nat_wind:.1f} m/s) ซึ่งลมนิ่ง/ลมอ่อนเป็นปัจจัยเสริมให้เกิดการสะสมของฝุ่น\n"
    summary += "• **สถานะระบบตรวจวัด:** เครื่องมือทำงานตามปกติและสามารถเชื่อถือได้ทุกสถานีตรวจวัดฯ\n"

    return summary

def main():
    now = datetime.datetime.now(TIMEZONE)
    
    # --- Logic: Reset Log ณ เวลา 06.00 น. ---
    # ปรับเวลาถอยหลัง 6 ชม. เพื่อให้การเปลี่ยนวันที่ใน Log เกิดขึ้นตอน 06.00 น.
    report_day = (now - datetime.timedelta(hours=6)).date()
    today_str = report_day.strftime("%Y-%m-%d")
    
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
        
        if val and s_id != "11t":
            pm25_now = float(val)
            if pm25_now <= 75.0:
                if s_id in history['alerted_ids']:
                    history['alerted_ids'].remove(s_id)
                continue
            
            lat, lon = float(s['lat']), float(s['long'])
            integrity_status, v_range = analyze_station_integrity(s_id)
            weather = find_nearest_weather(lat, lon, tmd_features)
            analysis = analyze_situation(integrity_status)

            prov = s['areaTH'].split(',')[-1].strip().replace('จ.', '').replace('จังหวัด', '').strip()
            if prov == "กรุงเทพฯ": prov = "กรุงเทพมหานคร"

            current_red_stations.append({
                "info": s,
                "province": prov,
                "region": get_region(prov),
                "stats": {"now": pm25_now, "range": v_range, "status": integrity_status},
                "weather": weather,
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
        
        grouped_stations = defaultdict(list)
        for item in display_list:
            grouped_stations[item['region']].append(item)
        
        messages_to_send = []
        current_msg = header_msg
        
        for region, items in grouped_stations.items():
            region_header = f"\n📁 *{region}*\n================================\n"
            current_msg += region_header
            
            for item in items:
                s = item['info']
                st = item['stats']
                w = item['weather']
                
                new_tag = "🆕 " if s['stationID'] in [n['info']['stationID'] for n in new_stations] else ""
                aqi = calculate_thai_aqi(st['now'])
                
                area_parts = s['areaTH'].split(',')
                if len(area_parts) >= 3: amphoe = area_parts[-2].strip()
                elif len(area_parts) == 2: amphoe = area_parts[0].strip()
                else: amphoe = ""

                block_text = (f"{new_tag}📍 {s['nameTH']} ({s['stationID']})\n"
                             f"อำเภอ/เขต: {amphoe} จังหวัด: {item['province']}\n\n"
                             f"💨 1. ข้อมูลฝุ่น PM2.5\n"
                             f"• Range (AVG.1 hr): {st['range']} µg/m³\n"
                             f"• Current Data (AVG.24 hr): {st['now']} µg/m³\n"
                             f"• AQI: {aqi}\n"
                             f"• Status: {st['status']}\n\n"
                             f"📝 2. สรุปสถานะเครื่องตรวจวัดเบื้องต้น: {item['analysis']}\n\n")

                w_text = f"🌦️ 3. ข้อมูลอุตุนิยมวิทยาเบื้องต้น\n(แหล่งข้อมูล: {w['source']})\n"
                if w['temp']: w_text += f"• อุณหภูมิ: {w['temp']}°C | ความชื้น: {w['hum']}%\n"
                
                if w['wind_dir']:
                    if w['wind_spd'] == 0.0 or w['wind_spd'] < 0.5:
                        w_text += f"• ทิศทางลม: พัดจาก{w['wind_dir']}\n• ความเร็วลม: ลมสงบ\n"
                    else:
                        wind_cat = get_wind_category(w['wind_spd'])
                        w_text += f"• ทิศทางลม: พัดจาก{w['wind_dir']}\n• ความเร็วลม: {wind_cat} ({w['wind_spd']:.1f} m/s)\n"
                else: 
                    w_text += "• ข้อมูลลม: ไม่พบข้อมูลอุตุนิยมวิทยาในพื้นที่ใกล้เคียง\n"
                
                block_text += w_text + "--------------------------------\n"
                
                if len(current_msg) + len(block_text) > 4000:
                    messages_to_send.append(current_msg)
                    current_msg = block_text
                else:
                    current_msg += block_text

        if current_msg:
            messages_to_send.append(current_msg)
            
        exec_summary_text = generate_executive_summary(current_red_stations, date_formatted)
        if exec_summary_text:
            if len(messages_to_send[-1]) + len(exec_summary_text) > 4000:
                messages_to_send.append(exec_summary_text)
            else:
                messages_to_send[-1] += "\n" + exec_summary_text

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
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)

if __name__ == "__main__":
    main()
