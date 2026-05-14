import flet as ft
import json
import urllib.request
import urllib.error
import threading
import time

# ===================== 配置 =====================
BEMFA_API = "https://apis.bemfa.com"
UID = "06114339929b461ba9b9ff5b85e8eb0e"

ONENET_URL = "https://iot-api.heclouds.com"
PRODUCT_ID = "H4G3KNU1ha"
DEVICE_NAME = "SMART"
AUTH_TOKEN = "version=2022-05-01&res=products%2FH4G3KNU1ha&et=1810217046&method=sha1&sign=vUDFouL59ehHqk77NcXM3XsWhI0%3D"

# 数据缓存（None表示未获取到数据）
DATA = {"Temp": None, "Hum": None, "relay": False, "led": False, "presence": False, "soil": None}
RUNNING = True


# ===================== HTTP工具 =====================
def http_get(url, headers=None):
    try:
        req = urllib.request.Request(url)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"GET错误: {e}")
        return None


# ===================== 巴法云MQTT控制（核心）=====================
def bemfa_send(topic, msg):
    """通过巴法云HTTP API发布消息到MQTT主题，ESP32实时收到"""
    url = f"{BEMFA_API}/va/sendMessage?uid={UID}&topic={topic}&type=1&msg={msg}"
    result = http_get(url)
    ok = result and result.get("code") == 0
    print(f"[巴法云] topic={topic} msg={msg} {'成功' if ok else '失败'}")
    return ok


def bemfa_getmsg(topic, num=1):
    """获取主题最新消息"""
    url = f"{BEMFA_API}/va/getmsg?uid={UID}&topic={topic}&type=1&num={num}"
    return http_get(url)


# ===================== OneNET查询（只用于显示传感器）=====================
def query_onenet():
    path = f"/thingmodel/query-device-property?product_id={PRODUCT_ID}&device_name={DEVICE_NAME}"
    headers = {"Authorization": AUTH_TOKEN}
    result = http_get(f"{ONENET_URL}{path}", headers)
    if result and result.get("code") == 0:
        for item in result.get("data", []):
            key = item["identifier"]
            val = item["value"]
            if key in DATA:
                if key in ("Temp", "Hum"):
                    try:
                        DATA[key] = float(val) if val is not None else None
                    except (ValueError, TypeError):
                        DATA[key] = None
                elif key == "soil":
                    try:
                        DATA[key] = int(val) if val is not None else None
                    except (ValueError, TypeError):
                        DATA[key] = None
                elif key == "relay":
                    if isinstance(val, str):
                        DATA[key] = val.lower() in ("true", "1", "on")
                    else:
                        DATA[key] = bool(val)
                elif key == "presence":
                    if isinstance(val, str):
                        DATA[key] = val.lower() in ("true", "1")
                    else:
                        DATA[key] = bool(val)
                else:
                    DATA[key] = val
        return True
    return False


# ===================== 后台轮询 =====================
def poll_loop():
    while RUNNING:
        query_onenet()
        result = bemfa_getmsg("relay006", 1)
        if result and result.get("code") == 0:
            msgs = result.get("data", [])
            if msgs:
                last_msg = msgs[0].get("msg", "")
                DATA["relay"] = (last_msg == "on" or last_msg == "1")
        time.sleep(3)


# ===================== 安全格式化工具（修复Bug关键）=====================
def fmt_float(val, fmt=".1f", fallback="--"):
    """安全格式化浮点数 - 修复了字符串类型导致的ValueError"""
    try:
        f = float(val)
        return f"{f:{fmt}}"
    except (ValueError, TypeError):
        return fallback


def in_range(val, lo, hi):
    """安全判断数值是否在范围内"""
    try:
        f = float(val)
        return lo <= f <= hi
    except (ValueError, TypeError):
        return False


# ===================== UI组件 =====================
def sensor_card(icon, icon_color, bg_color, label, value, unit, status, status_color):
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Container(
                    content=ft.Icon(icon, color=icon_color, size=22),
                    bgcolor=bg_color, border_radius=12,
                    width=40, height=40, alignment=ft.alignment.center,
                ),
                ft.Container(
                    content=ft.Text(status, size=12, weight=ft.FontWeight.W_600, color=status_color),
                    bgcolor=ft.Colors.with_opacity(0.1, status_color),
                    border_radius=20, padding=ft.padding.symmetric(horizontal=10, vertical=4),
                ),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([
                ft.Text(value, size=32, weight=ft.FontWeight.BOLD, color="#1a1a2e"),
                ft.Text(unit, size=16, color="#999999") if unit else ft.Container(),
            ], alignment=ft.alignment.bottom_left, spacing=4),
            ft.Text(label, size=14, color="#999999"),
        ], spacing=8),
        bgcolor="white", border_radius=16, padding=16,
        shadow=ft.BoxShadow(spread_radius=0, blur_radius=8,
                          color=ft.Colors.with_opacity(0.06, "black"),
                          offset=ft.Offset(0, 2)),
        expand=True,
    )


def device_switch(icon, icon_color, bg_color, title, subtitle, value, on_change):
    return ft.Container(
        content=ft.Row([
            ft.Container(
                content=ft.Icon(icon, color=icon_color, size=24),
                bgcolor=bg_color, border_radius=14,
                width=48, height=48, alignment=ft.alignment.center,
            ),
            ft.Column([
                ft.Text(title, size=16, weight=ft.FontWeight.W_600, color="#1a1a2e"),
                ft.Text(subtitle, size=13, color="#aaaaaa"),
            ], spacing=2, expand=True),
            ft.Switch(value=value, on_change=on_change,
                     active_color="#0ea5e9", inactive_thumb_color="#ffffff",
                     inactive_track_color="#e0e0e0"),
        ], alignment=ft.MainAxisAlignment.START),
        bgcolor="white", border_radius=16, padding=16,
        shadow=ft.BoxShadow(spread_radius=0, blur_radius=6,
                          color=ft.Colors.with_opacity(0.04, "black"),
                          offset=ft.Offset(0, 2)),
    )


# ===================== 页面 =====================
def home_page(page, refresh_fn):
    temp_val = fmt_float(DATA['Temp'])
    hum_val = fmt_float(DATA['Hum'])
    temp_status = "正常" if in_range(DATA['Temp'], 15, 35) else "异常" if DATA['Temp'] is not None else "--"
    hum_status = "正常" if in_range(DATA['Hum'], 20, 80) else "异常" if DATA['Hum'] is not None else "--"
    pres_status = "触发" if DATA['presence'] else "正常"
    relay_status = "在家" if DATA['relay'] else "离家"

    return ft.Column([
        ft.Row([
            ft.Column([
                ft.Text("智能家居", size=28, weight=ft.FontWeight.BOLD, color="#1a1a2e"),
                ft.Row([
                    ft.Container(width=8, height=8, bgcolor="#4CAF50", border_radius=4),
                    ft.Text("设备在线", size=14, weight=ft.FontWeight.W_600, color="#4CAF50"),
                ], spacing=6),
            ], expand=True),
            ft.IconButton(
                icon=ft.Icons.REFRESH, icon_color="#666666", icon_size=22,
                on_click=lambda _: refresh_fn(), bgcolor="white", width=40, height=40,
            ),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),

        ft.Row([
            sensor_card(ft.Icons.THERMOSTAT, "#f97316", "#fff7ed", "温度", temp_val, "°C",
                       temp_status, "#4CAF50" if temp_status == "正常" else "#f44336" if temp_status == "异常" else "#999999"),
            sensor_card(ft.Icons.WATER_DROP, "#3b82f6", "#eff6ff", "湿度", hum_val, "%",
                       hum_status, "#4CAF50" if hum_status == "正常" else "#f44336" if hum_status == "异常" else "#999999"),
        ], spacing=12),

        ft.Row([
            sensor_card(ft.Icons.DIRECTIONS_WALK, "#8b5cf6", "#f5f3ff", "人体感应",
                       "有人" if DATA['presence'] else "无人", "", pres_status,
                       "#f59e0b" if DATA['presence'] else "#4CAF50"),
            sensor_card(ft.Icons.POWER_SETTINGS_NEW, "#0ea5e9", "#f0f9ff", "继电器",
                       "吸合" if DATA['relay'] else "断开", "", relay_status,
                       "#4CAF50" if DATA['relay'] else "#999999"),
        ], spacing=12),

        ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.LIGHTBULB, color="#f44336", size=24),
                    bgcolor="#fef2f2", border_radius=14,
                    width=48, height=48, alignment=ft.alignment.center,
                ),
                ft.Column([
                    ft.Text("报警灯", size=16, weight=ft.FontWeight.W_600, color="#1a1a2e"),
                    ft.Text("LED状态", size=13, color="#aaaaaa"),
                ], spacing=2, expand=True),
                ft.Text("开" if DATA['led'] else "关", size=14, color="#999999"),
            ]),
            bgcolor="white", border_radius=16, padding=16,
        ),
    ], spacing=12, scroll=ft.ScrollMode.AUTO)


def control_page(page, refresh_fn):
    def show_snack(text, success=True):
        sb = ft.SnackBar(content=ft.Text(text), bgcolor="#4CAF50" if success else "#f44336")
        page.overlay.append(sb)
        sb.open = True
        page.update()

    def toggle_relay(e):
        next_val = e.control.value
        ok = bemfa_send("relay006", "on" if next_val else "off")
        if ok:
            DATA["relay"] = next_val
            show_snack(f"继电器已{'打开' if next_val else '关闭'}", True)
        else:
            e.control.value = not next_val
            show_snack("控制失败", False)
        page.update()

    return ft.Column([
        ft.Text("设备控制", size=24, weight=ft.FontWeight.BOLD, color="#1a1a2e"),
        ft.Text("通过巴法云MQTT实时控制ESP32", size=14, color="#999999"),

        device_switch(
            ft.Icons.POWER_SETTINGS_NEW, "#0ea5e9", "#f0f9ff",
            "在家模式", "relay006 - MQTT实时下发", DATA["relay"], toggle_relay
        ),

        ft.Container(
            content=ft.Column([
                ft.Text("裴相智", size=14, weight=ft.FontWeight.W_600, color="#1a1a2e"),
                ft.Text("郑州大学物理学院测控技术与仪器", size=12, color="#0ea5e9"),
                ft.Text("原此行，终抵群星！！！！", size=12, color="#888888"),
            ], spacing=4),
            bgcolor="white", border_radius=16, padding=16,
        ),
    ], spacing=12, scroll=ft.ScrollMode.AUTO)


def profile_page():
    def menu_item(icon, icon_color, bg_color, label, desc):
        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Icon(icon, color=icon_color, size=22),
                    bgcolor=bg_color, border_radius=12,
                    width=40, height=40, alignment=ft.alignment.center,
                ),
                ft.Column([
                    ft.Text(label, size=15, weight=ft.FontWeight.W_500, color="#1a1a2e"),
                    ft.Text(desc, size=12, color="#aaaaaa"),
                ], spacing=2, expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, color="#cccccc", size=18),
            ]),
            bgcolor="white", border_radius=0, padding=14,
        )

    return ft.Column([
        ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.PERSON, color="white", size=32),
                    bgcolor="#0ea5e9", border_radius=100,
                    width=56, height=56, alignment=ft.alignment.center,
                ),
                ft.Column([
                    ft.Text("管理员", size=18, weight=ft.FontWeight.BOLD, color="#1a1a2e"),
                    ft.Text("巴法云MQTT直连", size=14, color="#999999"),
                ], spacing=4),
            ], spacing=16),
            bgcolor="white", border_radius=16, padding=20,
        ),

        ft.Text("控制通道", size=13, weight=ft.FontWeight.W_600, color="#999999"),
        ft.Container(
            content=ft.Column([
                menu_item(ft.Icons.CLOUD, "#0ea5e9", "#f0f9ff", "巴法云MQTT", "apis.bemfa.com - 直接下发"),
                ft.Divider(height=1, color="#f1f5f9"),
                menu_item(ft.Icons.STORAGE, "#8b5cf6", "#f5f3ff", "OneNET数据", "只用于读取传感器数值"),
            ]),
            bgcolor="white", border_radius=16,
        ),

        ft.Text("系统", size=13, weight=ft.FontWeight.W_600, color="#999999"),
        ft.Container(
            content=menu_item(ft.Icons.INFO, "#64748b", "#f1f5f9", "关于", "Smart Home v2.0 巴法云MQTT版"),
            bgcolor="white", border_radius=16,
        ),
    ], spacing=12, scroll=ft.ScrollMode.AUTO)


# ===================== 主程序 =====================
def main(page: ft.Page):
    page.title = "智能家居"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = "#f8fafc"
    page.padding = 16
    page.window.width = 400
    page.window.height = 700

    poll_thread = threading.Thread(target=poll_loop, daemon=True)
    poll_thread.start()

    def refresh():
        build_view()
        page.update()

    content = ft.Container(expand=True)

    def build_view():
        tab = page.client_storage.get("current_tab") or "home"
        if tab == "home":
            content.content = home_page(page, refresh)
        elif tab == "control":
            content.content = control_page(page, refresh)
        elif tab == "profile":
            content.content = profile_page()
        else:
            content.content = home_page(page, refresh)

    def on_nav_change(e):
        index = e.control.selected_index
        tabs = ["home", "control", "profile"]
        tab_key = tabs[min(index, 2)]
        page.client_storage.set("current_tab", tab_key)
        build_view()
        page.update()

    nav_bar = ft.NavigationBar(
        selected_index=0, on_change=on_nav_change, bgcolor="white",
        indicator_color=ft.Colors.with_opacity(0.1, "#0ea5e9"),
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.HOME_OUTLINED, selected_icon=ft.Icons.HOME, label="首页"),
            ft.NavigationBarDestination(icon=ft.Icons.BAR_CHART, selected_icon=ft.Icons.BAR_CHART, label="控制"),
            ft.NavigationBarDestination(icon=ft.Icons.TOGGLE_ON_OUTLINED, selected_icon=ft.Icons.TOGGLE_ON, label="管理员"),
            ft.NavigationBarDestination(icon=ft.Icons.PERSON_OUTLINE, selected_icon=ft.Icons.PERSON, label="我的"),
        ],
    )

    build_view()

    page.add(
        ft.Column([content, nav_bar], expand=True, spacing=0)
    )


if __name__ == "__main__":
    ft.app(target=main, view=ft.AppView.FLET_APP)