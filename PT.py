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

def on_connect(client, userdata, flags, rc, *args):
    if rc == 0:
        print("[*] MQTT Connected! Ready to receive data globally.")
        client.subscribe(MQTT_TOPIC_SYNC)
        client.subscribe(MQTT_TOPIC_ALERT)
    else:
        print(f"[-] MQTT Connection failed with code {rc}")

def on_disconnect(client, userdata, rc, *args):
    print(f"[-] MQTT Disconnected! (Code: {rc}) Reconnecting...")

def on_mqtt_message(client, userdata, msg):
    global houses_data, logs_data
    try:
        raw_data = msg.payload.decode('utf-8')
        
        if "sync" not in msg.topic:
            print(f"\n[MQTT ALERT] Topic: {msg.topic} -> Data: {raw_data}")
            
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
                                    
                    if s not in ["Temp", "Hum"]:
                        time_str = datetime.now().strftime("%H:%M:%S")
                        logs_data.insert(0, {"เวลา": time_str, "โรงเรือน": house, "อุปกรณ์": s, "สถานะ": st})
                        if len(logs_data) > 100: logs_data.pop()
    except Exception as e:
        print(f"[ERROR] on_mqtt_message: {e}")

def mqtt_background_thread():
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
        
    client.on_connect = on_connect       
    client.on_disconnect = on_disconnect 
    client.on_message = on_mqtt_message
    
    print("[*] Cloud System Starting... Connecting to MQTT...")
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            client.loop_forever()
        except Exception as e:
            print(f"[-] MQTT Network Error: {e}. Retrying in 5s...")
            time.sleep(5)

# 🟢 ไอเดียโค้ดไฮบริด: ลองใช้ "โค้ดพิเศษดึงในวง LAN" ก่อน ถ้าไม่ได้ค่อยสลับโหมด
@app.route('/api/sd_logs')
def get_sd_logs():
    house = request.args.get('house')
    if house not in houses_data or not houses_data[house]["ip"]:
        return jsonify({"status": "error", "message": "ยังไม่ได้รับ IP จากตู้คอนโทรล (รอสักครู่)"})
    
    ip = houses_data[house]["ip"]
    if ip == "0.0.0.0" or ip == "":
        return jsonify({"status": "error", "message": "ตู้คอนโทรลยังไม่ได้ต่อ Wi-Fi"})

    try:
        # 1. พยายามใช้ "โค้ดพิเศษ" โหลดไฟล์ตรงๆ ภายในเวลา 3 วินาที (ทำงาน 100% ถ้าอยู่วง LAN เดียวกัน)
        req = urllib.request.Request(f"http://{ip}/api/logs", method="GET")
        with urllib.request.urlopen(req, timeout=3) as response:
            csv_data = response.read().decode('utf-8')
            
        parsed_logs = []
        reader = csv.reader(io.StringIO(csv_data))
        next(reader, None) 
        for row in reader:
            if len(row) >= 3:
                parsed_logs.insert(0, {
                    "เวลา": row[0].strip(),
                    "อุปกรณ์": row[1].strip(),
                    "สถานะ": row[2].strip()
                })
        return jsonify({"status": "ok", "logs": parsed_logs})
    except Exception as e:
        # 2. ถ้ารันบน Render (Cloud) มันจะเข้า Error ตรงนี้ทันที
        # เราส่งสถานะ fallback กลับไป เพื่อให้หน้าเว็บเปลี่ยนไปแสดง "ปุ่มคัดลอกลิงก์" แทน
        return jsonify({"status": "fallback", "ip": ip})

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
                <h5 class="mb-0 text-light">🕒 การแจ้งเตือนล่าสุด (ทั้งระบบ)</h5>
                <div class="d-flex gap-2 align-items-center">
                    <button class="btn btn-sm btn-outline-success fw-bold" onclick="openSDModal()">
                        📂 ดูประวัติทั้งหมดจาก SD Card
                    </button>
                    <select id="filterHouse" class="form-select form-select-sm w-auto bg-dark text-white border-secondary">
                        <option value="ทั้งหมด">ทุกโรงเรือน</option>
                        <option value="H1">H1</option>
                        <option value="H2">H2</option>
                        <option value="H3">H3</option>
                        <option value="H4">H4</option>
                    </select>
                    <select id="filterDevice" class="form-select form-select-sm w-auto bg-dark text-white border-secondary">
                        <option value="ทั้งหมด">ทุกอุปกรณ์</option>
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

    <div class="modal fade" id="sdLogModal" tabindex="-1">
        <div class="modal-dialog modal-xl">
            <div class="modal-content bg-dark text-white border-secondary">
                <div class="modal-header border-secondary" style="background-color: #1f2937;">
                    <h5 class="modal-title text-success">📂 ประวัติจาก SD Card (โรงเรือน: <span id="sdLogHouseName"></span>)</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body p-3">
                    
                    <div class="d-flex gap-2 mb-3 align-items-center flex-wrap" style="background: #1a1a1a; padding: 10px; border-radius: 8px; border: 1px solid #444;">
                        <label class="text-info fw-bold small">กรองอุปกรณ์:</label>
                        <select id="modalDeviceFilter" class="form-select form-select-sm w-auto bg-dark text-white border-secondary">
                            <option value="ทั้งหมด">ทุกอุปกรณ์</option>
                        </select>
                        <span id="sdModalStatus" class="text-warning small fw-bold ms-auto"></span>
                    </div>

                    <div id="fallbackUi" style="display: none;" class="alert alert-warning p-2 text-start mb-3 border-warning">
                        <strong>⚠️ พบการเชื่อมต่อผ่าน Cloud (หรืออยู่นอกวง LAN)</strong> Chrome บล็อกการเปิดแท็บอัตโนมัติ<br>
                        <span class="text-dark fw-bold">วิธีดึงข้อมูล (ทำครั้งเดียวผ่าน 100%):</span>
                        <div class="input-group input-group-sm my-2 w-75">
                            <span class="input-group-text bg-warning text-dark fw-bold">1. คัดลอกลิงก์ตู้</span>
                            <input type="text" id="manualUrl" class="form-control bg-light text-dark fw-bold" readonly>
                            <button class="btn btn-dark fw-bold" onclick="copyUrl()">คัดลอก</button>
                        </div>
                        <div class="mb-1 text-dark">2. เปิดแท็บใหม่ กด <b>Paste & Go (วางและไป)</b> เพื่อโหลดไฟล์ลงเครื่อง</div>
                        <div class="d-flex align-items-center text-dark">
                            3. นำเข้าไฟล์ที่ได้มาใส่ตรงนี้ ➡️ <input type="file" id="csvFileInput" accept=".csv" class="form-control form-control-sm w-auto ms-2 border-secondary bg-dark text-white">
                        </div>
                    </div>

                    <div class="table-responsive" style="max-height: 500px; overflow-y: auto;">
                        <table class="table table-dark table-hover table-striped mb-0 text-center">
                            <thead style="position: sticky; top: 0; z-index: 1;">
                                <tr><th>วัน/เวลา</th><th>อุปกรณ์</th><th>สถานะ</th></tr>
                            </thead>
                            <tbody id="sd-log-table-body">
                                <tr><td colspan='3' class='py-5 text-muted'>กำลังตรวจสอบเครือข่ายวง LAN...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentSdLogs = [];

        function openSDModal() {
            let house = document.getElementById("filterHouse").value;
            if (house === "ทั้งหมด") {
                alert("⚠️ กรุณาเลือกชื่อโรงเรือน (H1-H4) ที่ช่องตัวกรองหน้าเว็บก่อนครับ");
                return;
            }
            
            document.getElementById("sdLogHouseName").innerText = house;
            document.getElementById("sdModalStatus").innerText = "พยายามดึงข้อมูลอัตโนมัติในวง LAN...";
            document.getElementById("sdModalStatus").className = "ms-auto text-warning small fw-bold blink-text";
            document.getElementById("sd-log-table-body").innerHTML = "<tr><td colspan='3' class='py-5 text-warning'>กำลังเชื่อมต่อตู้ ESP32... ⏳</td></tr>";
            document.getElementById("fallbackUi").style.display = "none";
            document.getElementById("csvFileInput").value = "";
            
            var sdModal = new bootstrap.Modal(document.getElementById('sdLogModal'));
            sdModal.show();

            // 1. ยิงไปให้ Python ใช้โค้ดพิเศษดึง
            fetch('/api/sd_logs?house=' + house)
            .then(res => res.json())
            .then(data => {
                document.getElementById("sdModalStatus").classList.remove("blink-text");
                
                if (data.status === "ok") {
                    // 🟢 โค้ดพิเศษทำงานสำเร็จ (แสดงว่ารัน Local อยู่ในวง LAN)
                    currentSdLogs = data.logs;
                    updateFilterAndRender();
                    document.getElementById("sdModalStatus").innerText = `✅ ดึงข้อมูลวง LAN สำเร็จ!`;
                    document.getElementById("sdModalStatus").className = "ms-auto text-success small fw-bold";
                } 
                else if (data.status === "fallback") {
                    
                    document.getElementById("sdModalStatus").innerText = "พบ ESP32 ในวง LAN";
                    document.getElementById("sdModalStatus").className = "ms-auto text-success small fw-bold";
                    document.getElementById("sd-log-table-body").innerHTML =
                        `
                        <tr>
                            <td colspan="3" class="py-4">
                                <a href="http://${data.ip}/api/logs"
                                   target="_blank"
                                   class="btn btn-success btn-lg">
                                   📂 ดาวน์โหลดไฟล์จาก ESP32
                                </a>
                            </td>
                        </tr>
                        `;
                } 
                else {
                    document.getElementById("sdModalStatus").innerText = "❌ ขัดข้อง";
                    document.getElementById("sdModalStatus").className = "ms-auto text-danger small fw-bold";
                    document.getElementById("sd-log-table-body").innerHTML = `<tr><td colspan='3' class='text-danger py-4'>❌ ${data.message}</td></tr>`;
                }
            })
            .catch(err => {
                document.getElementById("sdModalStatus").classList.remove("blink-text");
                document.getElementById("sdModalStatus").innerText = "❌ เซิร์ฟเวอร์ไม่ตอบสนอง";
            });
        }

        // ฟังก์ชันเมื่อกดปุ่มคัดลอก
        function copyUrl() {
            var copyText = document.getElementById("manualUrl");
            copyText.select();
            document.execCommand("copy");
            alert("คัดลอกลิงก์สำเร็จ! เปิดแท็บใหม่แล้วกด วางและไป (Paste and Go) ได้เลยครับ");
        }

        // ฟังก์ชันเมื่อกดปุ่มนำเข้าไฟล์ CSV (โหมด Fallback)
        document.getElementById('csvFileInput').addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (!file) return;

            document.getElementById('sdModalStatus').innerText = "กำลังแปลงข้อมูล...";
            const reader = new FileReader();
            reader.onload = function(event) {
                const text = event.target.result;
                const lines = text.split('\\n');
                currentSdLogs = [];
                
                for (let i = 1; i < lines.length; i++) {
                    const row = lines[i].trim();
                    if (!row) continue;
                    const cols = row.split(',');
                    if (cols.length >= 3) {
                        currentSdLogs.push({
                            "เวลา": cols[0].trim(),
                            "อุปกรณ์": cols[1].trim(),
                            "สถานะ": cols[2].trim()
                        });
                    }
                }
                
                updateFilterAndRender();
                document.getElementById('sdModalStatus').className = "text-success small fw-bold ms-auto";
                document.getElementById('sdModalStatus').innerText = `✅ นำเข้าไฟล์สำเร็จ`;
            };
            reader.readAsText(file);
        });

        function updateFilterAndRender() {
            let uniqueDevices = new Set();
            currentSdLogs.forEach(log => uniqueDevices.add(log.อุปกรณ์));
            
            let filterHtml = '<option value="ทั้งหมด">ทุกอุปกรณ์</option>';
            Array.from(uniqueDevices).sort().forEach(dev => {
                filterHtml += `<option value="${dev}">${dev}</option>`;
            });
            document.getElementById('modalDeviceFilter').innerHTML = filterHtml;
            
            renderSDTable();
        }

        function renderSDTable() {
            const filterDev = document.getElementById('modalDeviceFilter').value;
            let html = '';
            let count = 0;

            const reversedData = [...currentSdLogs].reverse();
            reversedData.forEach(log => {
                if (filterDev === "ทั้งหมด" || log.อุปกรณ์ === filterDev) {
                    count++;
                    let stStr = log.สถานะ.toUpperCase();
                    let statusColor = "text-success";
                    if (stStr.includes("ERROR") || stStr.includes("TRIGGER") || stStr.includes("HIGH") || stStr.includes("LOW")) {
                        statusColor = "text-danger";
                    } else if (log.อุปกรณ์ === "SYSTEM") {
                        statusColor = "text-warning";
                    }
                    html += `<tr><td>${log.เวลา}</td><td>${log.อุปกรณ์}</td><td class="${statusColor} fw-bold">${log.สถานะ}</td></tr>`;
                }
            });

            if (count === 0) {
                html = "<tr><td colspan='3' class='py-5 text-warning'>ไม่พบข้อมูล</td></tr>";
            }
            document.getElementById('sd-log-table-body').innerHTML = html;
        }

        document.getElementById('modalDeviceFilter').addEventListener('change', renderSDTable);

        function updateData() {
            let spinner = document.getElementById("loadingSpinner");
            let clock = document.getElementById("liveClock");
            spinner.style.display = "inline-block";
            
            fetch('/api/data?t=' + Date.now()).then(res => res.json()).then(data => {
                setTimeout(() => {
                    spinner.style.display = "none";
                    clock.className = "badge bg-success fs-6";
                    clock.innerText = "🟢 ออนไลน์: " + new Date().toLocaleTimeString();
                }, 200);

                let uniqueNames = new Set(); 

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
                        uniqueNames.add(sensor.name); 
                        
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
                
                let filterDevice = document.getElementById("filterDevice");
                let currentSelection = filterDevice.value;
                let optionsHtml = '<option value="ทั้งหมด">ทุกอุปกรณ์</option>';
                Array.from(uniqueNames).sort().forEach(name => {
                    let selected = (name === currentSelection) ? "selected" : "";
                    optionsHtml += `<option value="${name}" ${selected}>${name}</option>`;
                });
                if (filterDevice.innerHTML !== optionsHtml) filterDevice.innerHTML = optionsHtml;

                let tbody = document.getElementById("log-table-body");
                let filterHouse = document.getElementById("filterHouse").value;
                let rowsHtml = ""; let count = 0;
                
                if (data.logs.length === 0) {
                    rowsHtml = "<tr><td colspan='4' class='text-muted py-4'>💡 ระบบปกติ ยังไม่มีการแจ้งเตือน</td></tr>";
                } else {
                    data.logs.forEach(log => {
                        let matchHouse = (filterHouse === "ทั้งหมด" || log.โรงเรือน === filterHouse);
                        let matchDevice = (currentSelection === "ทั้งหมด" || log.อุปกรณ์ === currentSelection);
                        
                        if (matchHouse && matchDevice) {
                            count++;
                            let stStr = log.สถานะ.toUpperCase();
                            let statusColor = (stStr.includes("ERROR") || stStr.includes("TRIGGER")) ? "text-danger" : "text-success";
                            rowsHtml += `<tr><td>${log.เวลา}</td><td>${log.โรงเรือน}</td><td>${log.อุปกรณ์}</td><td class="${statusColor} fw-bold">${log.สถานะ}</td></tr>`;
                        }
                    });
                    if (count === 0) rowsHtml = "<tr><td colspan='4' class='text-muted py-4'>🔍 ไม่พบข้อมูลที่ตรงกับตัวกรอง</td></tr>";
                }
                tbody.innerHTML = rowsHtml;
            }).catch(err => {
                spinner.style.display = "none";
                clock.className = "badge bg-danger fs-6 blink-text";
                clock.innerText = "🔴 ขาดการเชื่อมต่อกับ Server!";
            });
        }
        
        document.getElementById("filterHouse").addEventListener("change", updateData);
        document.getElementById("filterDevice").addEventListener("change", updateData);
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
