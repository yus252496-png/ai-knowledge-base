"""测试 Railway 流式对话 — 通过 captha 识别登录"""
import requests
import json
import time
import base64
import re
from io import BytesIO
from PIL import Image, ImageFilter

BASE = "https://ai-knowledge-base-qtme-production.up.railway.app"
PHONE = "17688939632"
PASSWORD = "123456"

def get_captcha():
    r = requests.get(f"{BASE}/api/auth/captcha", timeout=10)
    data = r.json()
    return data["captcha_id"], data["image"]

def save_captcha(image_b64, filename="captcha.png"):
    header, bdata = image_b64.split(",", 1) if "," in image_b64 else ("", image_b64)
    img = Image.open(BytesIO(base64.b64decode(bdata)))
    img.save(filename)
    return img

def login(phone, password, captcha_id, captcha_code):
    r = requests.post(f"{BASE}/api/auth/login", data={
        "phone": phone,
        "password": password,
        "captcha_id": captcha_id,
        "captcha_code": captcha_code,
    }, timeout=10)
    return r.json()

def try_login():
    """循环获取验证码直到登录成功"""
    for attempt in range(10):
        print(f"\n=== 尝试 {attempt+1} ===")
        cid, cimg = get_captcha()
        img = save_captcha(cimg, "captcha.png")
        print(f"验证码图片已保存到 captcha.png，请查看")

        # 尝试显示图片信息
        print(f"图片尺寸: {img.size}, 模式: {img.mode}")

        # 手动输入验证码
        code = input("请输入4位验证码（从 captcha.png 查看）: ").strip()
        if len(code) != 4 or not code.isdigit():
            print("无效验证码，跳过")
            continue

        result = login(PHONE, PASSWORD, cid, code)
        print(f"登录结果: {json.dumps(result, ensure_ascii=False)}")

        if "token" in result:
            return result["token"]
        elif "locked" in str(result):
            print("账户已锁定，等待...")
            time.sleep(5)
        # 验证码错误，继续循环
    return None

def test_stream(token):
    docs = requests.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {token}"}, timeout=15)
    print(f"\n文档列表 ({docs.status_code}): {docs.json()}")

    print("\n=== 测试流式对话 ===")
    t0 = time.time()
    try:
        resp = requests.post(
            f"{BASE}/api/chat/stream",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"question": "你好，请回复'hello world'", "conversation_id": None},
            stream=True,
            timeout=60,
        )
        print(f"状态码: {resp.status_code}")
        print(f"响应头: {dict(resp.headers)}")
        print(f"\n--- SSE 事件 ---")

        event_count = 0
        first_byte = None
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                now = time.time()
                if first_byte is None:
                    first_byte = now - t0
                t = now - t0
                print(f"[t={t:.1f}s] {line[:300]}")
                if line.startswith("data: "):
                    event_count += 1
                    try:
                        payload = json.loads(line[6:])
                        if payload.get("type") == "done":
                            break
                        if payload.get("type") == "error":
                            print(f"  ** 错误: {payload.get('data')}")
                            break
                    except:
                        pass

        print(f"\n--- 统计 ---")
        print(f"首字节到达: {first_byte:.1f}s" if first_byte else "无数据")
        print(f"事件总数: {event_count}")
        print(f"总耗时: {time.time()-t0:.1f}s")
    except Exception as e:
        print(f"\n异常: {e}")

if __name__ == "__main__":
    token = try_login()
    if token:
        print(f"\n登录成功! token: {token[:30]}...")
        test_stream(token)
    else:
        print("\n登录失败，无法测试")
