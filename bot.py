import os

def main():
    print("--- ระบบเริ่มทำงานแล้ว ---")
    line_token = os.getenv('LINE_ACCESS_TOKEN')
    user_id = os.getenv('LINE_USER_ID')
    
    if line_token:
        print(f"พบ Token: {line_token[:5]}...")
    else:
        print("❌ ไม่พบ LINE_ACCESS_TOKEN ใน Secrets")
        
    if user_id:
        print(f"พบ User ID: {user_id}")
    else:
        print("❌ ไม่พบ LINE_USER_ID ใน Secrets")
    print("--- จบการทดสอบเบื้องต้น ---")

if __name__ == "__main__":
    main()
