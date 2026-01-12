import requests
import pandas as pd
import os
import datetime
import pytz

# --- Configuration ---
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')
API_KEY = os.getenv('AIR4THAI_KEY')
TIMEZONE = pytz.timezone('Asia/Bangkok')

def get_data():
    url = "http://air4thai.com/forweb/getAQI_JSON.php"
    print("1. กำลังดึงข้อมูลจาก Air4Thai...")
    try:
        res = requests.get(url, timeout=30).json()
        stations = res.get('stations', [])
        print(f"พบข้อมูลทั้งหมด {len(stations)} สถานี")
        return stations
    except Exception as e:
        print(f"❌ Error ดึงข้อมูล: {e}")
        return []

def send_line(message):
    print(f"2. กำลังส่งข้อความหา User ID: {USER_ID[:10]}...")
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    payload = {
        "to": USER_ID,
        "messages": [{"type": "text", "text": message}]
    }
    
    response = requests.post(url, headers=headers, json=payload)
    print(f"3. ผลการส่ง LINE (Response): {response.status_code} - {response.text}")
    return response.status_code

def main():
    now = datetime.datetime.now(TIMEZONE)
    print(f"--- เริ่มทำงานเวลา: {now.strftime('%H:%M:%S')} ---")
    
    stations = get_data()
    
    # กรองสถานีที่ไม่ใช่ 11t และไม่ใช่ BKK
    # ทดสอบเบื้องต้น: ดึงสถานีแรกที่เจอมา 1 สถานีเพื่อลองส่ง
    filtered = [s for s in stations if s['stationID'] != "11t" and s.get('stationType', '').lower() != 'bkk']
    
    if filtered:
        target = filtered[0] # เลือกสถานีแรกที่ผ่านการกรอง
        pm25 = target['AQILast']['PM25']['value']
        
        msg = (f"🧪 บอททำงานสำเร็จ!\n"
               f"📍 สถานี: {target['nameTH']}\n"
               f"🗺️ พื้นที่: {target['areaTH']}\n"
               f"💨 PM2.5: {pm25} µg/m³\n"
               f"⏰ เวลา: {now.strftime('%H:%M')} น.")
        
        result = send_line(msg)
        if result == 200:
            print("✅ ส่งข้อความเข้า LINE สำเร็จแล้ว!")
        else:
            print("❌ ส่งไม่สำเร็จ ตรวจสอบ Token หรือ User ID อีกครั้ง")
    else:
        print("❌ ไม่พบสถานีที่ตรงตามเงื่อนไขการกรอง")

if __name__ == "__main__":
    main()
