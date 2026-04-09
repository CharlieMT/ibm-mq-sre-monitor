# ==============================================================================
# Copyright (c) 2026 Kyndryl. All rights reserved.
# PROPRIETARY AND CONFIDENTIAL
# ==============================================================================

import http.server
import socketserver
import json
import os
import urllib.parse
import logging
import subprocess
import re

PORT = 8080
CONFIG_DIRS = ["mq_checks_config/queues", "mq_checks_config/channels"]
STATE_FILE = "mq_checks_config/current_state.json"
LOG_FILE = "mq_logs/mq_monitor.log" # Upewnij się, że ta ścieżka zgadza się z Twoim Daemonem!

for d in CONFIG_DIRS:
    os.makedirs(d, exist_ok=True)

def get_system_qms():
    """Fetches Queue Managers from OS (dspmq) and existing JSON configs."""
    qms = set()
    
    # 1. Próba pobrania prawdziwych menedżerów z systemu (IBM MQ)
    try:
        result = subprocess.run(['dspmq'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        if result.returncode == 0:
            found = re.findall(r'QMNAME\(([^)]+)\)', result.stdout)
            qms.update(found)
    except Exception as e:
        logging.warning(f"dspmq not available, falling back to JSON configs: {e}")

    # 2. Próba pobrania menedżerów z zapisanych plików JSON (Fallback)
    for d in CONFIG_DIRS:
        if os.path.exists(d):
            for filename in os.listdir(d):
                if filename.endswith(".json"):
                    try:
                        with open(os.path.join(d, filename), 'r') as f:
                            rule = json.load(f)
                            if 'queue_manager' in rule:
                                qms.add(rule['queue_manager'])
                    except:
                        pass
                        
    # 3. Jeśli system jest całkowicie pusty i nie ma jeszcze plików JSON
    # Zwracamy pustą listę (lub jeden pusty element, by nie zepsuć HTML'a)
    return sorted(list(qms)) if qms else [""]

# --- HTML TEMPLATE (Pure HTML + CSS + JS) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SRE MQ Dashboard</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1e1e2e; color: #cdd6f4; margin: 0; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: #313244; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
        h1 {{ color: #89b4fa; border-bottom: 2px solid #45475a; padding-bottom: 10px; margin-top: 0; display: flex; justify-content: space-between; align-items: center; }}
        .live-indicator {{ font-size: 12px; color: #a6e3a1; border: 1px solid #a6e3a1; padding: 4px 8px; border-radius: 20px; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} 100% {{ opacity: 1; }} }}
        
        .tab {{ overflow: hidden; border-bottom: 1px solid #45475a; margin-bottom: 20px; display: flex; }}
        .tab button {{ background-color: inherit; color: #a6adc8; border: none; outline: none; cursor: pointer; padding: 14px 24px; transition: 0.3s; font-size: 16px; font-weight: bold; border-radius: 8px 8px 0 0; }}
        .tab button:hover {{ background-color: #45475a; color: #cdd6f4; }}
        .tab button.active {{ background-color: #89b4fa; color: #11111b; }}
        .tabcontent {{ display: none; animation: fadeEffect 0.5s; }}
        @keyframes fadeEffect {{ from {{opacity: 0;}} to {{opacity: 1;}} }}

        .filters {{ display: flex; gap: 15px; margin-bottom: 20px; background: #181825; padding: 15px; border-radius: 8px; align-items: center; flex-wrap: wrap; }}
        .filters label {{ color: #a6e3a1; font-weight: bold; font-size: 14px; margin-right: 5px; }}
        .filters select, .filters input[type="text"] {{ padding: 8px; background: #45475a; color: #cdd6f4; border: 1px solid #585b70; border-radius: 4px; outline: none; min-width: 150px; font-size: 14px; }}
        .search-container {{ margin-left: auto; display: flex; align-items: center; }}
        .search-container input[type="text"] {{ min-width: 250px; }}

        table {{ width: 100%; border-collapse: collapse; font-size: 14px; background: #181825; border-radius: 8px; overflow: hidden; margin-bottom: 20px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #313244; }}
        th {{ background-color: #11111b; color: #fab387; }}
        tr:hover {{ background-color: #313244; }}
        
        .log-viewer {{ background: #11111b; color: #a6e3a1; font-family: monospace; padding: 15px; border-radius: 8px; height: 500px; overflow-y: auto; white-space: pre-wrap; font-size: 13px; border: 1px solid #45475a; }}
        .timestamp {{ color: #89b4fa; font-weight: bold; margin-bottom: 10px; }}
        
        form.rule-form {{ background: #181825; padding: 20px; border-radius: 8px; display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }}
        .form-group {{ display: flex; flex-direction: column; }}
        .form-group.full-width {{ grid-column: span 2; }}
        form label {{ margin-bottom: 5px; color: #f38ba8; font-weight: bold; font-size: 13px; }}
        form input, form select {{ padding: 10px; background: #45475a; color: #cdd6f4; border: 1px solid #585b70; border-radius: 4px; outline: none; }}
        
        .checkbox-group {{ display: flex; flex-direction: row; align-items: center; gap: 20px; background: #313244; padding: 15px; border-radius: 8px; }}
        .checkbox-label {{ display: flex; align-items: center; cursor: pointer; color: #a6e3a1; font-size: 14px; margin: 0; }}
        .checkbox-label input[type="checkbox"] {{ width: 20px; height: 20px; margin-right: 10px; accent-color: #89b4fa; }}

        .btn-submit {{ grid-column: span 2; background-color: #89b4fa; color: #11111b; padding: 12px; border: none; border-radius: 5px; font-weight: bold; cursor: pointer; font-size: 16px; margin-top: 10px; }}
        .btn-submit.modify {{ background-color: #f9e2af; }}
        .btn-delete {{ background-color: #f38ba8; color: #11111b; border: none; padding: 6px 10px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 12px; margin-left: 5px;}}
        .btn-edit {{ background-color: #89b4fa; color: #11111b; border: none; padding: 6px 10px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 12px; }}

        .message {{ padding: 12px; border-radius: 5px; margin-bottom: 15px; font-weight: bold; }}
        .success {{ background-color: #a6e3a1; color: #11111b; }}
        .error {{ background-color: #f38ba8; color: #11111b; }}
        .action-form {{ margin: 0; padding: 0; display: inline; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>
            📡 MQ SRE Control Center
            <span class="live-indicator" id="connStatus">🟢 Connected</span>
        </h1>
        
        {message}

        <div class="tab">
            <button class="tablinks" onclick="openTab(event, 'Dashboard')" id="tabDashboard">📊 Rules Config</button>
            <button class="tablinks" onclick="openTab(event, 'LiveMetrics')" id="tabLive">⚡ Live Values</button>
            <button class="tablinks" onclick="openTab(event, 'SystemLogs')" id="tabLogs">📜 System Logs</button>
            <button class="tablinks" onclick="openTab(event, 'AddRule')" id="tabAdd">➕ Add Rule</button>
            <button class="tablinks" onclick="openTab(event, 'ModifyRule')" id="tabModify">✏️ Modify Rule</button>
        </div>

        <div id="Dashboard" class="tabcontent">
            <div class="filters">
                <div>
                    <label>Queue Manager:</label>
                    <select id="filterQM" onchange="filterTable()">
                        <option value="ALL">All Managers</option>
                        {qm_filter_options}
                    </select>
                </div>
                <div>
                    <label>Object Type:</label>
                    <select id="filterType" onchange="filterTable()">
                        <option value="ALL">All Types</option>
                        <option value="QUEUE">QUEUE</option>
                        <option value="CHANNEL">CHANNEL</option>
                    </select>
                </div>
                <div class="search-container">
                    <label>🔍 Search:</label>
                    <input type="text" id="filterName" onkeyup="filterTable()" placeholder="Type object name...">
                </div>
            </div>

            <table id="rulesTable">
                <thead>
                    <tr><th>QM</th><th>Type</th><th>Object Name</th><th>Attribute</th><th>Rule</th><th>Severity</th><th>Status</th><th>Actions</th></tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>

        <div id="LiveMetrics" class="tabcontent" style="display:none;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <p id="lastUpdatedMetric" style="color: #a6adc8; margin: 0; font-family: monospace;">Last Daemon Update: Fetching...</p>
                <button type="button" onclick="fetchMetrics()" style="background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; border-radius: 4px; padding: 5px 15px; cursor: pointer; font-weight: bold; transition: 0.2s;">
                    ↻ Refresh Now
                </button>
            </div>
            <table id="liveTable">
                <thead>
                    <tr><th>Queue Manager</th><th>Object Name</th><th>Attribute Checked</th><th>Last Value Read</th><th>Status</th></tr>
                </thead>
                <tbody id="liveTableBody">
                    <tr><td colspan='5'>Waiting for daemon data...</td></tr>
                </tbody>
            </table>
        </div>

        <div id="SystemLogs" class="tabcontent" style="display:none;">
            <div class="timestamp">Auto-refreshing every 3 seconds...</div>
            <div class="log-viewer" id="logViewer">Fetching logs...</div>
        </div>

        <div id="AddRule" class="tabcontent">
            <h2 style="color: #a6e3a1;">Create New Monitor Rule</h2>
            <form class="rule-form" method="POST" action="/add_rule">
                <input type="hidden" name="action_type" value="ADD">
                <div class="form-group"><label>Queue Manager:</label><select name="q_mgr" required>{qm_system_options}</select></div>
                <div class="form-group"><label>Object Type:</label><select name="obj_type"><option value="QUEUE">QUEUE</option><option value="CHANNEL">CHANNEL</option></select></div>
                <div class="form-group full-width"><label>Object Name:</label><input type="text" name="obj_name" required></div>
                <div class="form-group"><label>Attribute:</label><input type="text" name="check_type" required></div>
                <div class="form-group"><label>Operator:</label><select name="operator"><option value=">">></option><option value="<"><</option><option value=">=">>=</option><option value="<="><=</option><option value="==">==</option><option value="!=">!=</option></select></div>
                <div class="form-group"><label>Threshold:</label><input type="text" name="threshold" required></div>
                <div class="form-group"><label>ITSM Severity:</label><select name="severity"><option value="info" selected>INFO</option><option value="warning">WARNING</option><option value="minor">MINOR</option><option value="major">MAJOR</option><option value="critical">CRITICAL</option></select></div>
                <div class="form-group"><label>Check Interval (s):</label><input type="number" name="interval" value="60" min="10" required></div>
                <div class="form-group full-width"><label>Incident Template:</label><select name="incident_template" id="add_incident_template" onchange="applyTemplate(this.value, 'add_')">{template_options}</select></div>
                <div class="form-group"><label>Knowledge Base (EHI):</label><input type="text" name="ehi" id="add_ehi"></div>
                <div class="form-group"><label>Level 1 Support:</label><input type="text" name="first_line" id="add_first_line"></div>
                <div class="form-group"><label>Level 2 Support:</label><input type="text" name="second_line" id="add_second_line"></div>
                <div class="form-group full-width checkbox-group"><label class="checkbox-label"><input type="checkbox" name="enable_check" checked> Enable Monitoring</label><label class="checkbox-label"><input type="checkbox" name="enable_alert" checked> Enable ITSM Alerts</label></div>
                <div style="display: flex; gap: 15px; margin-top: 10px;">
                    <button type="submit" class="btn-submit" style="flex: 4;">➕ Add New Rule</button>
                    <button type="reset" style="flex: 1; background-color: #45475a; color: #f38ba8; border: 1px solid #585b70; border-radius: 4px; padding: 10px; cursor: pointer; font-weight: bold; transition: 0.2s;">🗑️ Clear Form</button>
                </div>
            </form>
        </div>

        <div id="ModifyRule" class="tabcontent">
            <h2 style="color: #f9e2af;">Modify Existing Rule</h2>
            <form class="rule-form" method="POST" action="/modify_rule">
                <input type="hidden" name="action_type" value="MODIFY">
                <input type="hidden" name="original_filepath" id="mod_orig_filepath">
                <div class="form-group full-width">
                    <label style="color: #f9e2af; font-size: 15px;">🔍 Select a rule to modify:</label>
                    <select name="rule_select" id="mod_rule_select" onchange="loadRuleIntoForm(this.value)" required>
                        <option value="" disabled selected>-- Select an existing rule --</option>
                        {rule_dropdown_options}
                    </select>
                </div>
                <div class="form-group"><label>Queue Manager:</label><select name="q_mgr" id="mod_qm" required>{qm_system_options}</select></div>
                <div class="form-group"><label>Object Type:</label><select name="obj_type" id="mod_type"><option value="QUEUE">QUEUE</option><option value="CHANNEL">CHANNEL</option></select></div>
                <div class="form-group full-width"><label>Object Name:</label><input type="text" name="obj_name" id="mod_name" required></div>
                <div class="form-group"><label>Attribute:</label><input type="text" name="check_type" id="mod_attr" required></div>
                <div class="form-group"><label>Operator:</label><select name="operator" id="mod_op"><option value=">">></option><option value="<"><</option><option value=">=">>=</option><option value="<="><=</option><option value="==">==</option><option value="!=">!=</option></select></div>
                <div class="form-group"><label>Threshold:</label><input type="text" name="threshold" id="mod_thr" required></div>
                <div class="form-group"><label>ITSM Severity:</label><select name="severity" id="mod_sev"><option value="info" selected>INFO</option><option value="warning">WARNING</option><option value="minor">MINOR</option><option value="major">MAJOR</option><option value="critical">CRITICAL</option></select></div>
                <div class="form-group"><label>Check Interval (s):</label><input type="number" name="interval" id="mod_int" min="10" required></div>
                <div class="form-group full-width"><label>Incident Template:</label><select name="incident_template" id="mod_incident_template" onchange="applyTemplate(this.value, 'mod_')">{template_options}</select></div>
                <div class="form-group"><label>Knowledge Base (EHI):</label><input type="text" name="ehi" id="mod_ehi"></div>
                <div class="form-group"><label>Level 1 Support:</label><input type="text" name="first_line" id="mod_first_line"></div>
                <div class="form-group"><label>Level 2 Support:</label><input type="text" name="second_line" id="mod_second_line"></div>
                <div class="form-group full-width checkbox-group"><label class="checkbox-label"><input type="checkbox" name="enable_check" id="mod_chk"> Enable Monitoring</label><label class="checkbox-label"><input type="checkbox" name="enable_alert" id="mod_alrt"> Enable ITSM Alerts</label></div>
                <div style="display: flex; gap: 15px; margin-top: 10px;">
                    <button type="submit" class="btn-submit modify" style="flex: 4;">💾 Save Modifications</button>
                    <button type="reset" onclick="document.getElementById('mod_rule_select').value='';" style="flex: 1; background-color: #45475a; color: #f38ba8; border: 1px solid #585b70; border-radius: 4px; padding: 10px; cursor: pointer; font-weight: bold; transition: 0.2s;">🗑️ Clear Form</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        const rulesDatabase = {rules_json_data};
        const incidentTemplates = {templates_json};
        let activeTab = 'Dashboard';

        function openTab(evt, tabName) {{
            activeTab = tabName;
            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tabcontent");
            for (i = 0; i < tabcontent.length; i++) {{ tabcontent[i].style.display = "none"; }}
            tablinks = document.getElementsByClassName("tablinks");
            for (i = 0; i < tablinks.length; i++) {{ tablinks[i].className = tablinks[i].className.replace(" active", ""); }}
            document.getElementById(tabName).style.display = "block";
            if(evt) evt.currentTarget.className += " active";
            
            // Trigger immediate fetch if switching to live tabs
            if(tabName === 'LiveMetrics') fetchMetrics();
            if(tabName === 'SystemLogs') fetchLogs();
        }}
        
        document.getElementById("tabDashboard").click();

        function filterTable() {{
            var filterQM = document.getElementById("filterQM").value.toUpperCase();
            var filterType = document.getElementById("filterType").value.toUpperCase();
            var filterName = document.getElementById("filterName").value.toUpperCase();
            var table = document.getElementById("rulesTable");
            var tr = table.getElementsByTagName("tr");
            for (var i = 1; i < tr.length; i++) {{ 
                var tdQM = tr[i].getAttribute("data-qm");
                var tdType = tr[i].getAttribute("data-type");
                var tdName = tr[i].getAttribute("data-name"); 
                if (tdQM && tdType && tdName) {{
                    var showQM = (filterQM === "ALL" || tdQM === filterQM);
                    var showType = (filterType === "ALL" || tdType === filterType);
                    var showName = (filterName === "" || tdName.includes(filterName));
                    tr[i].style.display = (showQM && showType && showName) ? "" : "none";
                }}
            }}
        }}

        function loadRuleIntoForm(filepath) {{
            if (!filepath || !rulesDatabase[filepath]) return;
            var rule = rulesDatabase[filepath];
            document.getElementById("mod_orig_filepath").value = filepath;
            document.getElementById("mod_qm").value = rule.queue_manager || "";
            document.getElementById("mod_type").value = filepath.includes("/queues/") ? "QUEUE" : "CHANNEL";
            document.getElementById("mod_name").value = rule.object_name || "";
            document.getElementById("mod_attr").value = rule.check_type || "";
            document.getElementById("mod_op").value = rule.operator || ">";
            document.getElementById("mod_thr").value = rule.threshold || "";
            document.getElementById("mod_sev").value = rule.alert_severity || "major";
            document.getElementById("mod_int").value = rule.interval || 60;
            document.getElementById("mod_chk").checked = rule.enable_check !== false;
            document.getElementById("mod_alrt").checked = rule.enable_alert !== false;
            document.getElementById("mod_ehi").value = rule.ehi || "";
            document.getElementById("mod_first_line").value = rule.first_line || "";
            document.getElementById("mod_second_line").value = rule.second_line || "";
        }}

        function loadEditForm(btn) {{
            var tr = btn.closest('tr');
            var filepath = tr.getAttribute('data-filepath');
            document.getElementById("mod_rule_select").value = filepath;
            loadRuleIntoForm(filepath);
            document.getElementById("tabModify").click();
        }}

        function applyTemplate(templateName, prefix) {{
            if(templateName && incidentTemplates[templateName]) {{
                document.getElementById(prefix + 'ehi').value = incidentTemplates[templateName].ehi || '';
                document.getElementById(prefix + 'first_line').value = incidentTemplates[templateName].first_line || '';
                document.getElementById(prefix + 'second_line').value = incidentTemplates[templateName].second_line || '';
            }}
        }}

        // --- AJAX: LIVE FETCHING SYSTEM ---
        
        function updateStatus(isOnline) {{
            const el = document.getElementById('connStatus');
            if(isOnline) {{
                el.innerText = '🟢 Live Sync Active';
                el.style.color = '#a6e3a1'; el.style.borderColor = '#a6e3a1';
            }} else {{
                el.innerText = '🔴 Connection Lost';
                el.style.color = '#f38ba8'; el.style.borderColor = '#f38ba8';
            }}
        }}

        async function fetchMetrics() {{
            if(activeTab !== 'LiveMetrics') return;
            try {{
                const response = await fetch('/api/state');
                if(!response.ok) throw new Error('API Error');
                const data = await response.json();
                
                document.getElementById('lastUpdatedMetric').innerText = 'Last Daemon Update: ' + (data.last_updated || 'Unknown');
                
                const tbody = document.getElementById('liveTableBody');
                if(data.data && data.data.length > 0) {{
                    let html = '';
                    data.data.forEach(row => {{
                        let statusColor = '#f38ba8'; // Default red (Error/Alert)
                        if (row.status === 'OK') statusColor = '#a6e3a1'; // Green
                        else if (row.status === 'PAUSED') statusColor = '#a6adc8'; // Gray
                        else if (row.status === 'STANDBY') statusColor = '#f9e2af'; // Yellow
                        
                        // TUTAJ JEST POPRAWKA: Podwójne klamry dla zmiennych JS
                        let objDisplay = row.obj_type ? `[${{row.obj_type}}] ${{row.obj_name || '-'}}` : row.obj_name || '-';
                        
                        html += `<tr><td>${{row.q_mgr || '-'}}</td><td>${{objDisplay}}</td><td>${{row.check_type || '-'}}</td><td style="font-weight: bold; font-size: 16px;">${{row.value !== undefined ? row.value : '-'}}</td><td style="color: ${{statusColor}}; font-weight: bold;">${{row.status || '-'}}</td></tr>`;
                    }});
                    tbody.innerHTML = html;
                }} else {{
                    tbody.innerHTML = "<tr><td colspan='5'>No live data collected yet. Is the daemon running?</td></tr>";
                }}
                updateStatus(true);
            }} catch(e) {{
                updateStatus(false);
                document.getElementById('liveTableBody').innerHTML = "<tr><td colspan='5' style='color:#f38ba8;'>Error fetching state file.</td></tr>";
            }}
        }}

        async function fetchLogs() {{
            if(activeTab !== 'SystemLogs') return;
            try {{
                const response = await fetch('/api/logs');
                if(!response.ok) throw new Error('API Error');
                const text = await response.text();
                const viewer = document.getElementById('logViewer');
                
                // Only scroll to bottom if user is already at the bottom (don't force scroll if they are reading up)
                const isScrolledToBottom = viewer.scrollHeight - viewer.clientHeight <= viewer.scrollTop + 50;
                
                viewer.innerText = text || "Log file is empty or missing.";
                
                if(isScrolledToBottom) {{
                    viewer.scrollTop = viewer.scrollHeight;
                }}
                updateStatus(true);
            }} catch(e) {{
                updateStatus(false);
                document.getElementById('logViewer').innerText = "Failed to read log file.";
            }}
        }}

        // Set interval to fetch data according to tick rate defined in app_config (assuming it's in seconds, we convert to milliseconds)
        //Set interval for fetching logs every 3 seconds (can be adjusted as needed)
        const METRICS_INTERVAL = {tick_rate} * 1000;
        setInterval(fetchMetrics, METRICS_INTERVAL);

        const LOGS_INTERVAL = 3000;
        setInterval(fetchLogs, LOGS_INTERVAL);

        fetchMetrics();
        fetchLogs();
    </script>
</body>
</html>
"""

class SREDashboardHandler(http.server.BaseHTTPRequestHandler):
    
    def _read_existing_rules(self):
        rows = ""
        rule_dropdown_options = ""
        unique_qms = set()
        system_qms = get_system_qms()
        rules_dict = {}
        
        # Read incident templates
        incident_templates_dict = {}
        template_options = '<option value="">-- Select Incident Template --</option>'
        try:
            if os.path.exists('incident_templates.json'):
                with open('incident_templates.json', 'r') as f:
                    incident_templates_dict = json.load(f)
                    for template_name in incident_templates_dict:
                        template_options += f'<option value="{template_name}">{template_name}</option>'
        except Exception as e:
            logging.warning(f"Error reading incident_templates.json: {e}")
        
        for folder in CONFIG_DIRS:
            obj_type = "QUEUE" if "queues" in folder else "CHANNEL"
            if os.path.exists(folder):
                for filename in os.listdir(folder):
                    if filename.endswith(".json"):
                        filepath = os.path.join(folder, filename)
                        try:
                            with open(filepath, 'r') as f:
                                rule = json.load(f)
                                rules_dict[filepath] = rule
                                
                                qm = rule.get('queue_manager', '-')
                                obj_name = rule.get('object_name', '-')
                                attr = rule.get('check_type', '-')
                                op = rule.get('operator', '')
                                thr = rule.get('threshold', '')
                                sev = rule.get('alert_severity', '-').upper()
                                
                                is_enabled = rule.get('enable_check', True)
                                is_alerting = rule.get('enable_alert', True)
                                
                                if not is_enabled:
                                    status_badge = "<span style='color: #f38ba8; font-weight: bold;'>⏸️ PAUSED</span>"
                                elif not is_alerting:
                                    status_badge = "<span style='color: #fab387; font-weight: bold;'>▶️ RUNNING (🔕 Muted)</span>"
                                else:
                                    status_badge = "<span style='color: #a6e3a1; font-weight: bold;'>▶️ RUNNING & 🔔 ALERTING</span>"
                                
                                unique_qms.add(qm)
                                rule_dropdown_options += f'<option value="{filepath}">[{qm}] {obj_type} - {obj_name}</option>'
                                
                                actions = f"""
                                <button type="button" class="btn-edit" onclick="loadEditForm(this)">✏️ Edit</button>
                                <form class="action-form" method="POST" action="/delete_rule" onsubmit="return confirm('Are you sure you want to delete {obj_name}?');">
                                    <input type="hidden" name="filepath" value="{filepath}">
                                    <button type="submit" class="btn-delete">🗑️ Delete</button>
                                </form>
                                """
                                
                                rows += f"<tr data-qm='{qm.upper()}' data-type='{obj_type}' data-name='{obj_name.upper()}' data-filepath='{filepath}'><td>{qm}</td><td>{obj_type}</td><td>{obj_name}</td><td>{attr}</td><td>{op} {thr}</td><td>{sev}</td><td>{status_badge}</td><td style='white-space: nowrap;'>{actions}</td></tr>"
                        except Exception as e:
                            logging.error(f"Error reading {filepath}: {e}")
                            
        if not rows:
            rows = "<tr><td colspan='8' style='text-align: center;'>No rules defined yet.</td></tr>"
            
        qm_filter_options = "".join([f'<option value="{qm.upper()}">{qm}</option>' for qm in sorted(list(unique_qms)) if qm != '-'])
        qm_system_options = "".join([f'<option value="{qm}">{qm}</option>' for qm in system_qms])
        rules_json_data = json.dumps(rules_dict)
        templates_json = json.dumps(incident_templates_dict)
            
        return rows, qm_filter_options, qm_system_options, rule_dropdown_options, rules_json_data, templates_json, template_options

    def do_GET(self):
        # --- NEW: API ENDPOINTS FOR LIVE METRICS & LOGS ---
        if self.path == "/api/state":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            try:
                if os.path.exists(STATE_FILE):
                    with open(STATE_FILE, 'r') as f:
                        state_data = f.read()
                        self.wfile.write(state_data.encode("utf-8"))
                else:
                    self.wfile.write(b'{"last_updated": "No file found", "data": []}')
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                
        elif self.path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            try:
                if os.path.exists(LOG_FILE):
                    # Zwraca tylko 100 ostatnich linii, żeby nie zawiesić przeglądarki przy gigabajtowych logach
                    with open(LOG_FILE, 'r') as f:
                        lines = f.readlines()
                        last_lines = lines[-100:]
                        self.wfile.write("".join(last_lines).encode("utf-8"))
                else:
                    self.wfile.write(b"Log file not found at " + LOG_FILE.encode("utf-8"))
            except Exception as e:
                self.wfile.write(str(e).encode("utf-8"))
                
        # --- STANDARD HTML VIEW ---
        elif self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            tick_rate = 15  # Wartość domyślna
            try:
                if os.path.exists('app_config.conf'):
                    with open('app_config.conf', 'r') as f:
                        for line in f:
                            if line.strip().startswith('tick_rate'):
                                # Radzi sobie z formatami: "tick_rate = 5", "tick_rate=10", "tick_rate = 15s"
                                val = line.split('=')[1].strip().replace('s', '')
                                tick_rate = int(val)
                                break
            except Exception as e:
                pass  # Jeśli coś pójdzie nie tak, po prostu użyje domyślnego 5
            table_rows, qm_filter_options, qm_system_options, rule_dropdown_options, rules_json_data, templates_json, template_options = self._read_existing_rules()
            html = HTML_TEMPLATE.format(message="", table_rows=table_rows, qm_filter_options=qm_filter_options, qm_system_options=qm_system_options, rule_dropdown_options=rule_dropdown_options, rules_json_data=rules_json_data, templates_json=templates_json, template_options=template_options, tick_rate=tick_rate)
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_error(404, "Page not found")

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        data = urllib.parse.parse_qs(post_data)
        msg = ""
        
        if self.path in ["/add_rule", "/modify_rule"]:
            try:
                action_type = data.get('action_type', [''])[0]
                original_filepath = data.get('original_filepath', [''])[0]
                q_mgr = data.get('q_mgr', [''])[0].strip()
                obj_type = data.get('obj_type', [''])[0]
                obj_name = data.get('obj_name', [''])[0].strip()
                check_type = data.get('check_type', [''])[0].strip().upper()
                operator = data.get('operator', [''])[0]
                threshold = data.get('threshold', [''])[0].strip()
                severity = data.get('severity', ['major'])[0].strip().lower()
                interval = int(data.get('interval', ['60'])[0].strip())
                enable_check = 'enable_check' in data
                enable_alert = 'enable_alert' in data
                # Extract ITSM fields
                ehi = data.get('ehi', [''])[0].strip()
                first_line = data.get('first_line', [''])[0].strip()
                second_line = data.get('second_line', [''])[0].strip()
                parsed_threshold = int(threshold) if threshold.isdigit() else threshold
                
                new_rule = {"queue_manager": q_mgr, "object_type": obj_type, "object_name": obj_name, "check_type": check_type, "operator": operator, "threshold": parsed_threshold, "alert_severity": severity, "enable_alert": enable_alert, "enable_check": enable_check, "interval": interval, "ehi": ehi, "first_line": first_line, "second_line": second_line}
                folder = "mq_checks_config/queues" if obj_type == "QUEUE" else "mq_checks_config/channels"
                new_filepath = os.path.join(folder, f"{obj_name.replace('/', '_')}.json")
                
                if action_type == "ADD" and os.path.exists(new_filepath):
                    msg = f'<div class="message error">❌ Error: Rule for "{obj_name}" already exists!</div>'
                else:
                    if action_type == "MODIFY" and original_filepath and os.path.exists(original_filepath) and original_filepath != new_filepath:
                        os.remove(original_filepath)
                    with open(new_filepath, 'w') as f:
                        json.dump(new_rule, f, indent=4)
                    msg = f'<div class="message success">✅ Success! Rule {obj_name} saved.</div>'
            except Exception as e:
                msg = f'<div class="message error">❌ Error saving rule: {str(e)}</div>'
                
        elif self.path == "/delete_rule":
            try:
                filepath = data.get('filepath', [''])[0]
                if os.path.exists(filepath):
                    os.remove(filepath)
                    msg = f'<div class="message success">🗑️ Success! Rule deleted.</div>'
            except Exception as e:
                msg = f'<div class="message error">❌ Error deleting rule: {str(e)}</div>'

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        table_rows, qm_filter_options, qm_system_options, rule_dropdown_options, rules_json_data, templates_json, template_options = self._read_existing_rules()
        html = HTML_TEMPLATE.format(message=msg, table_rows=table_rows, qm_filter_options=qm_filter_options, qm_system_options=qm_system_options, rule_dropdown_options=rule_dropdown_options, rules_json_data=rules_json_data, templates_json=templates_json, template_options=template_options)
        self.wfile.write(html.encode("utf-8"))

if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), SREDashboardHandler) as httpd:
        print(f"🚀 Native SRE Web GUI started on port {PORT}!")
        print(f"Open in browser: http://localhost:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")