import os
import threading
import time
import urllib.request
import json
import csv
import io
import sys
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[-] ยังไม่ได้ติดตั้ง paho-mqtt")
    sys.exit()

app = Flask(__name__)
SECRET_KEY = "PT_GROUP_FARM_2026"

houses_data = { 
    "H1": {"ip": "", "temp": "--", "hum": "--", "sensors": [{"name": f"IN{i:02d}", "status": "รอข้อมูล..."} for i in range(1, 17)], "alerts": {}},
    "H2": {"ip": "", "temp": "--", "hum": "--", "sensors": [{"name": f"IN{i:02d}", "status": "รอข้อมูล..."} for i in range(1, 17)], "alerts": {}},
    "H3": {"ip": "", "temp": "--", "hum": "--", "sensors": [{"name": f"IN{i:02d}", "status": "รอข้อมูล..."} for i in range(1, 17)], "alerts": {}},
    "H4": {"ip": "", "temp": "--", "hum": "--", "sensors": [{"name": f"IN{i:02d}", "status": "รอข้อมูล..."} for i in range(1, 17)], "alerts": {}}
}
logs_data = []

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC_SYNC = "pt_group_farm/+/sync"
MQTT_TOPIC_ALERT = "pt_group_farm/+/alert"

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

def on_mqtt_message(client, userdata, msg):
    try:
        raw_data = msg.payload.decode('utf-8')
        if "sync" in msg.topic:
            pass 
        else:
            print(f"\n[MQTT] Topic: {msg.topic} -> Data: {raw_data}")
            
        payload = json.loads(raw_data)
        if payload.get("secret") == SECRET_KEY:
            house = payload.get("house")
            if house in houses_data:
                if "ip" in payload:
                    houses_data[house]["ip"] = payload["ip"] 
                
                if "sensors" in payload:
                    houses_data[house]["temp"] = str(payload.get("temp", "--"))
                    houses_data[house]["hum"] = str(payload.get("hum", "--"))
                    houses_data[house]["sensors"] = payload["sensors"]
                    
                    for sensor in houses_data[house]["sensors"]:
                        s_name = sensor["name"]
                        if s_name in houses_data[house]["alerts"]:
                            sensor["status"] = houses_data[house]["alerts"][s_name]

                if "sensor" in payload and "status" in payload:
                    s = str(payload["sensor"]).strip()
                    st = str(payload["status"]).strip()
                    
                    if s == "Temp": houses_data[house]["temp"] = st
                    elif s == "Hum": houses_data[house]["hum"] = st
                    else:
                        if "NORMAL" in st.upper() or "ปกติ" in st:
                            if s in houses_data[house]["alerts"]:
                                del houses_data[house]["alerts"][s]
                        else:
                            houses_data[house]["alerts"][s] = st

                        for sensor in houses_data[house]["sensors"]:
                            if sensor["name"] == s:
                                sensor["status"] = st
                                break
                                    
                    if s not in ["Temp", "Hum"] and "NORMAL" not in st.upper():
                        time_str = datetime.now().strftime("%H:%M:%S")
                        logs_data.insert(0, {"เวลา": time_str, "โรงเรือน": house, "อุปกรณ์": s, "สถานะ": st})
                        if len(logs_data) > 100: logs_data.pop()
    except Exception as e:
        pass

def mqtt_background_thread():
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
        
    client.on_message = on_mqtt_message
    print("[*] Cloud System Starting... Connecting to MQTT...")
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            client.subscribe(MQTT_TOPIC_SYNC)
            client.subscribe(MQTT_TOPIC_ALERT)
            print("[*] MQTT Connected! Ready to receive data globally.")
            client.loop_forever()
        except Exception as e:
            print(f"[-] MQTT Connection dropped. Reconnecting in 5s...")
            time.sleep(5)

@app.route('/api/data')
def api_data(): 
    return jsonify({"houses": houses_data, "logs": logs_data[:50]})

HTML_PAGE = """
<!DOCTYPE html>
<html lang="th" data-bs-theme="dark">
<head>
    <title>PT GROUP FARM - Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .card { box-shadow: 0 4px 8px rgba(0,0,0,0.4); border-radius: 12px; overflow: hidden; }
        .card-header { border-top-left-radius: 12px !important; border-top-right-radius: 12px !important; }
        .sensor-row { padding: 8px 0; border-bottom: 1px solid #333; }
        .sensor-row:last-child { border-bottom: none; }
        .blink-text { animation: blinker 1s linear infinite; }
        @keyframes blinker { 50% { opacity: 0; } }
    </style>
</head>
<body>
    <div class="container mt-4">
        <div class="text-center mb-4">
            <h1 style="color: #FFDF00; font-weight: bold; margin-bottom: 0;">🌍 PT GROUP FARM</h1>
            <h5 class="text-secondary mt-1">Global Monitor Dashboard (Online)</h5>
            <div class="d-flex justify-content-center align-items-center gap-2 mt-2">
                <div id="loadingSpinner" class="spinner-border text-success spinner-border-sm" role="status" style="display: none;"></div>
                <span class="badge bg-secondary fs-6" id="liveClock">รอการเชื่อมต่อระบบ...</span>
            </div>
        </div>
        
        <div class="row">
            {% for house in ["H1", "H2", "H3", "H4"] %}
            <div class="col-md-6 col-lg-3 mb-4">
                <div class="card text-bg-dark border-secondary h-100 flex-column d-flex">
                    <div class="card-header fw-bold d-flex justify-content-between align-items-center" style="background-color: #1f2937;">
                        <h5 class="mb-0 text-info">📊 โรงเรือน {{ house }}</h5>
                        <span id="{{ house }}_StatusDot" style="height: 10px; width: 10px; background-color: red; border-radius: 50%; display: inline-block;"></span>
                    </div>
                    <div class="card-body flex-grow-1">
                        <h5 class="text-warning mb-1">🌡️ อุณหภูมิ: <span id="{{ house }}_Temp">รอข้อมูล...</span> °C</h5>
                        <h5 class="text-info mb-3">💧 ความชื้น: <span id="{{ house }}_Hum">รอข้อมูล...</span> %</h5>
                        <hr class="border-secondary">
                        
                        {% for s_idx in range(16) %}
                        <div class="d-flex justify-content-between sensor-row">
                            <span id="{{ house }}_name_{{ s_idx }}">⚙️ IN{{ "%02d" % (s_idx+1) }}</span>
                            <span id="{{ house }}_status_{{ s_idx }}" class="fw-bold text-muted">รอข้อมูล...</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>

        <div class="card text-bg-dark border-secondary mt-2 mb-5">
            <div class="card-header fw-bold d-flex flex-wrap justify-content-between align-items-center gap-2" style="background-color: #1f2937;">
                <h5 class="mb-0 text-light">🕒 การแจ้งเตือนล่าสุด (เฉพาะ ERROR)</h5>
                <div class="d-flex gap-2 align-items-center">
                    
                    <div class="dropdown d-inline-block">
                        <button class="btn btn-sm btn-outline-secondary fw-bold dropdown-toggle" type="button" data-bs-toggle="dropdown">
                            📂 โหลดประวัติ SD Card (ผ่าน LAN)
                        </button>
                        <ul class="dropdown-menu dropdown-menu-dark">
                            <li><a class="dropdown-item" href="#" onclick="downloadCSV('H1')">โหลดของโรงเรือน H1</a></li>
                            <li><a class="dropdown-item" href="#" onclick="downloadCSV('H2')">โหลดของโรงเรือน H2</a></li>
                            <li><a class="dropdown-item" href="#" onclick="downloadCSV('H3')">โหลดของโรงเรือน H3</a></li>
                            <li><a class="dropdown-item" href="#" onclick="downloadCSV('H4')">โหลดของโรงเรือน H4</a></li>
                        </ul>
                    </div>

                    <select id="filterHouse" class="form-select form-select-sm w-auto bg-dark text-white border-secondary">
                        <option value="ทั้งหมด">ทุกโรงเรือน</option>
                        <option value="H1">H1</option>
                        <option value="H2">H2</option>
                        <option value="H3">H3</option>
                        <option value="H4">H4</option>
                    </select>
                </div>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                    <table class="table table-dark table-hover table-striped mb-0 text-center">
                        <thead style="position: sticky; top: 0; z-index: 1;">
                            <tr><th>เวลา</th><th>โรงเรือน</th><th>อุปกรณ์</th><th>สถานะ</th></tr>
                        </thead>
                        <tbody id="log-table-body"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        // ตัวแปรสำหรับเก็บข้อมูล IP ล่าสุดของแต่ละตู้
        let latestHousesData = {};

        function updateData() {
            let spinner = document.getElementById("loadingSpinner");
            let clock = document.getElementById("liveClock");
            spinner.style.display = "inline-block";
            
            fetch('/api/data?t=' + Date.now()).then(res => res.json()).then(data => {
                latestHousesData = data.houses; // อัปเดตข้อมูลตู้เพื่อนำ IP ไปใช้งานตอนโหลดไฟล์
                
                setTimeout(() => {
                    spinner.style.display = "none";
                    clock.className = "badge bg-success fs-6";
                    clock.innerText = "🟢 ออนไลน์: " + new Date().toLocaleTimeString();
                }, 200);

                for (const [house, hData] of Object.entries(data.houses)) {
                    let elTemp = document.getElementById(house + "_Temp");
                    let elHum = document.getElementById(house + "_Hum");
                    let dot = document.getElementById(house + "_StatusDot");
                    
                    if(hData.temp !== "--" && hData.temp !== "") {
                        if(dot) dot.style.backgroundColor = "#00ff00"; 
                    } else {
                        if(dot) dot.style.backgroundColor = "red";
                    }

                    if(elTemp && elTemp.innerText !== hData.temp) elTemp.innerText = hData.temp;
                    if(elHum && elHum.innerText !== hData.hum) elHum.innerText = hData.hum;

                    hData.sensors.forEach((sensor, idx) => {
                        let nameEl = document.getElementById(house + "_name_" + idx);
                        let statusEl = document.getElementById(house + "_status_" + idx);
                        
                        if(nameEl && nameEl.innerText !== "⚙️ " + sensor.name) nameEl.innerText = "⚙️ " + sensor.name;
                        
                        if(statusEl) {
                            if (statusEl.innerText !== sensor.status) statusEl.innerText = sensor.status;
                            let stStr = sensor.status.toUpperCase();
                            
                            if(stStr.includes("ERROR") || stStr.includes("TRIGGER") || stStr.includes("HIGH") || stStr.includes("LOW")) {
                                statusEl.className = "fw-bold text-danger blink-text"; 
                            } else if(stStr.includes("NORMAL")) {
                                statusEl.className = "fw-bold text-success"; 
                            } else {
                                statusEl.className = "fw-bold text-muted"; 
                            }
                        }
                    });
                }
                
                let tbody = document.getElementById("log-table-body");
                let filterHouse = document.getElementById("filterHouse").value;
                let rowsHtml = ""; let count = 0;
                
                if (data.logs.length === 0) {
                    rowsHtml = "<tr><td colspan='4' class='text-muted py-4'>💡 ระบบปกติ ยังไม่มีการแจ้งเตือน ERROR</td></tr>";
                } else {
                    data.logs.forEach(log => {
                        let matchHouse = (filterHouse === "ทั้งหมด" || log.โรงเรือน === filterHouse);
                        if (matchHouse) {
                            count++;
                            let stStr = log.สถานะ.toUpperCase();
                            let statusColor = (stStr.includes("ERROR") || stStr.includes("TRIGGER")) ? "text-danger" : "text-success";
                            rowsHtml += `<tr><td>${log.เวลา}</td><td>${log.โรงเรือน}</td><td>${log.อุปกรณ์}</td><td class="${statusColor} fw-bold">${log.สถานะ}</td></tr>`;
                        }
                    });
                    if (count === 0) rowsHtml = "<tr><td colspan='4' class='text-muted py-4'>🔍 ไม่พบข้อมูล</td></tr>";
                }
                tbody.innerHTML = rowsHtml;
            }).catch(err => {
                spinner.style.display = "none";
                clock.className = "badge bg-danger fs-6 blink-text";
                clock.innerText = "🔴 ขาดการเชื่อมต่อกับ Server!";
            });
        }
        
        // ฟังก์ชันสำหรับเปิดแท็บใหม่ วิ่งตรงไปหาตู้ ESP32 ตาม IP ที่ได้จาก MQTT
        function downloadCSV(house) {
            let houseData = latestHousesData[house];
            
            if (!houseData || !houseData.ip || houseData.ip === "") {
                alert("⚠️ ยังไม่ได้รับ IP ของโรงเรือน " + house + " กรุณารอให้ตู้ส่งข้อมูลเข้าระบบสักครู่ครับ");
                return;
            }
            
            if (houseData.ip === "0.0.0.0") {
                alert("⚠️ ตู้คอนโทรล " + house + " ยังไม่ได้เชื่อมต่อ Wi-Fi ครับ");
                return;
            }

            let confirmMsg = "กำลังเชื่อมต่อไปที่ตู้ " + house + " (IP: " + houseData.ip + ")\\n\\nคุณเชื่อมต่อ Wi-Fi วงเดียวกันกับที่ฟาร์มนาคำอยู่ใช่ไหม?";
            if (confirm(confirmMsg)) {
                window.open("http://" + houseData.ip + "/api/logs", "_blank");
            }
        }
        
        document.getElementById("filterHouse").addEventListener("change", updateData);
        setInterval(updateData, 1000); 
        updateData();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

if __name__ == "__main__":
    threading.Thread(target=mqtt_background_thread, daemon=True).start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
