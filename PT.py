import os
import threading
import time
import json
import csv
import io
import sys
import urllib.request
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string

# ตั้งค่า MQTT และ Flask
try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[-] ต้องติดตั้ง paho-mqtt")
    sys.exit()

app = Flask(__name__)
SECRET_KEY = "PT_GROUP_FARM_2026"

# โครงสร้างเก็บข้อมูลโรงเรือน
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

# ตั้งค่า Header ป้องกันการ Cache
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    return response

def on_connect(client, userdata, flags, rc, *args):
    if rc == 0:
        print("[*] MQTT Connected!")
        client.subscribe(MQTT_TOPIC_SYNC)
        client.subscribe(MQTT_TOPIC_ALERT)

def on_mqtt_message(client, userdata, msg):
    global houses_data, logs_data
    try:
        raw_data = msg.payload.decode('utf-8')
        payload = json.loads(raw_data)
        if payload.get("secret") == SECRET_KEY:
            house = payload.get("house")
            if house in houses_data:
                if "ip" in payload: houses_data[house]["ip"] = payload["ip"] 
                if "sensors" in payload:
                    houses_data[house]["temp"] = str(payload.get("temp", "--"))
                    houses_data[house]["hum"] = str(payload.get("hum", "--"))
                    houses_data[house]["sensors"] = payload["sensors"]
                if "sensor" in payload and "status" in payload:
                    s = str(payload["sensor"]).strip()
                    st = str(payload["status"]).strip()
                    if s == "Temp": houses_data[house]["temp"] = st
                    elif s == "Hum": houses_data[house]["hum"] = st
                    else:
                        for sensor in houses_data[house]["sensors"]:
                            if sensor["name"] == s: sensor["status"] = st; break
                    
                    time_str = datetime.now().strftime("%H:%M:%S")
                    logs_data.insert(0, {"เวลา": time_str, "โรงเรือน": house, "อุปกรณ์": s, "สถานะ": st})
                    if len(logs_data) > 200: logs_data.pop()
    except Exception as e:
        print(f"[ERROR] on_mqtt_message: {e}")

def mqtt_background_thread():
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect       
    client.on_message = on_mqtt_message
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            client.loop_forever()
        except: time.sleep(5)

@app.route('/api/data')
def api_data(): 
    return jsonify({"houses": houses_data, "logs": logs_data})

HTML_PAGE = """
<!DOCTYPE html>
<html lang="th" data-bs-theme="dark">
<head>
    <title>PT GROUP FARM</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <style>
        .blink-text { animation: blinker 1s linear infinite; }
        @keyframes blinker { 50% { opacity: 0; } }
    </style>
</head>
<body class="bg-dark text-light">
    <div class="container mt-4">
        <h1>🌍 PT GROUP FARM - Dashboard</h1>
        <div class="row" id="dashboard"></div>
        
        <div class="card bg-secondary mt-3 p-3">
            <h5>🕒 ประวัติการแจ้งเตือน (SD Card)</h5>
            <div class="input-group mb-3">
                <select id="houseSelector" class="form-select">
                    <option value="H1">H1</option><option value="H2">H2</option>
                    <option value="H3">H3</option><option value="H4">H4</option>
                </select>
                <button class="btn btn-success" onclick="downloadLogs()">โหลดประวัติจากตู้</button>
            </div>
            
            <div id="fallbackPanel" style="display:none;" class="alert alert-warning">
                <p>ดึงไฟล์จากตู้ไม่ได้ (อยู่นอกวง LAN?) ให้คัดลอกลิงก์ไปเปิดแท็บใหม่เองครับ:</p>
                <input type="text" id="manualLink" class="form-control mb-2" readonly>
                <button class="btn btn-primary btn-sm" onclick="copyLink()">คัดลอกลิงก์</button>
                <input type="file" id="manualFile" class="d-block mt-2" accept=".csv">
            </div>

            <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                <table class="table table-dark table-striped">
                    <thead><tr><th>เวลา</th><th>อุปกรณ์</th><th>สถานะ</th></tr></thead>
                    <tbody id="log-table-body"></tbody>
                </table>
            </div>
        </div>
    </div>
    <script>
        let currentHouses = {};
        
        async function downloadLogs() {
            let house = document.getElementById("houseSelector").value;
            let ip = currentHouses[house]?.ip;
            if(!ip || ip == "") { alert("ยังไม่มี IP ของโรงเรือนนี้"); return; }
            
            try {
                // ทดสอบดึงใน LAN (ด้วย timeout สั้นๆ)
                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), 2000);
                await fetch("http://" + ip + "/api/logs", { signal: controller.signal });
                clearTimeout(timeout);
                window.open("http://" + ip + "/api/logs", "_blank");
            } catch(e) {
                document.getElementById("fallbackPanel").style.display = "block";
                document.getElementById("manualLink").value = "http://" + ip + "/api/logs";
            }
        }

        function copyLink() {
            document.getElementById("manualLink").select();
            document.execCommand("copy");
            alert("คัดลอกแล้ว นำไปวางในแท็บใหม่เพื่อโหลดไฟล์ครับ");
        }

        document.getElementById('manualFile').addEventListener('change', function(e) {
            const file = e.target.files[0];
            const reader = new FileReader();
            reader.onload = function(event) {
                renderLogs(event.target.result);
            };
            reader.readAsText(file);
        });

        function renderLogs(csvText) {
            let tbody = document.getElementById("log-table-body");
            tbody.innerHTML = "";
            let rows = csvText.split('\\n');
            rows.forEach(r => {
                let cols = r.split(',');
                if(cols.length >= 3) {
                    tbody.innerHTML += `<tr><td>${cols[0]}</td><td>${cols[1]}</td><td>${cols[2]}</td></tr>`;
                }
            });
        }

        setInterval(() => {
            fetch('/api/data').then(r=>r.json()).then(d => {
                currentHouses = d.houses;
                let tbody = document.getElementById("log-table-body");
                if (tbody.innerHTML == "") {
                    d.logs.forEach(log => {
                        tbody.innerHTML += `<tr><td>${log.เวลา}</td><td>${log.อุปกรณ์}</td><td>${log.สถานะ}</td></tr>`;
                    });
                }
            });
        }, 2000);
    </script>
</body>
</html>
"""

@app.route('/')
def index(): return render_template_string(HTML_PAGE)

if __name__ == "__main__":
    threading.Thread(target=mqtt_background_thread, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=False)

