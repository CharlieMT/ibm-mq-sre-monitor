# 🚂 IBM MQ SRE Monitor (Daemon)

A robust, production-grade Python daemon for monitoring IBM MQ infrastructure (Queues and Channels). Built with Site Reliability Engineering (SRE) principles in mind, it utilizes the native `runmqsc` CLI to fetch real-time metrics. It features an asynchronous event-loop scheduler, strict separation of configuration from code, fail-safe error handling, and advanced log rotation with GZIP compression.

## ✨ Key Features

* **Asynchronous Task Scheduler:** Uses an internal event loop based on a global `tick_rate`. Each queue and channel is evaluated independently according to its own custom `interval` defined in its JSON config, preventing check-blocking and time drift.
* **`conf.d` Style Architecture:** Monitors are defined in modular JSON files split into `queues/` and `channels/` directories, allowing easy management by multiple teams.
* **In-Memory Efficiency:** Configurations are loaded into RAM at startup. The main loop performs zero unnecessary disk I/O.
* **Production-Grade Logging:** Built-in `RotatingFileHandler` prevents log exhaustion by capping active log size and automatically compressing (`.gz`) older archives.
* **Fail-Safe & Honest Metrics:** Intelligently parses `runmqsc` outputs. It safely ignores informational messages (e.g., `AMQ8409I`), explicitly detects missing CLI tools or authorization errors (e.g., user not in the `mqm` group), and suspends alerts for unreachable objects rather than reporting false '0' or 'UNKNOWN' values.
* **Systemd Ready:** Easily deployable as a background background service with auto-restart capabilities.

## 📂 Directory Structure

```text
mq_app_bash/
├── start_monitor.sh           # Main entry point (Bash wrapper)
├── app_config.conf            # Global application settings (Tick rate, Paths)
├── src/                       # Core Python logic
│   ├── main.py                # Main daemon event loop & logger setup
│   ├── config_parser.py       # Parses .conf and .json files
│   └── mq_connector.py        # Subprocess wrapper & intelligent MQ CLI parser
├── mq_checks_config/          # conf.d directory for checks
│   ├── queues/                # JSON configs for Queue Depth
│   └── channels/              # JSON configs for Channel Status
└── mq_logs/                   # Automatically generated rotating logs (.log & .gz)

📋 Prerequisites

    Python 3.8+ installed on the host machine (required for modern subprocess and logging features).

    IBM MQ Server or Client installed (runmqsc must be available in the system $PATH).

    Permissions: The Linux user executing this script MUST be a member of the mqm group (or have equivalent MQ administrative rights) to successfully execute the commands.

🚀 Installation & Setup

    Clone the repository:
    Bash

    git clone https://github.com/CharlieMT/ibm-mq-sre-monitor.git
    cd ibm-mq-sre-monitor

    Make the wrapper script executable:
    Bash

    chmod +x start_monitor.sh

    Adjust global behavior in app_config.conf:
    Ini, TOML

    # Base resolution of the event loop (e.g., 5s, 10s)
    tick_rate = 5s

    # Directories for MQ check configurations
    queues_dir = mq_checks_config/queues
    channels_dir = mq_checks_config/channels

    # Logging configuration
    log_dir = mq_logs
    log_file = mq_monitor.log
    log_level = INFO
    log_max_size = 20MB
    log_backup_count = 5

## ⚙️ Adding Monitors (Universal Rule Engine)

This SRE Daemon features a powerful **Universal Rule Engine**. Instead of hardcoding specific checks, the daemon can dynamically query **any attribute** from IBM MQ objects and evaluate it using standard mathematical operators.

To add a monitor, place a `.json` file into the `mq_checks_config/queues/` or `mq_checks_config/channels/` directory.

*(Note: Use the `.disable` extension, e.g., `my_queue.json.disable`, to completely exclude a file from being loaded into memory without deleting it).*

### Supported Rule Parameters:
* **`check_type`**: Any valid IBM MQ attribute returned by `runmqsc` (e.g., `CURDEPTH`, `STATUS`, `IPPROCS`, `MAXDEPTH`, `MSGDLVSQ`).
* **`operator`**: The comparison operator. Supported values: `>`, `<`, `>=`, `<=`, `==`, `!=`.
* **`threshold`**: The value to compare against. Can be an integer (e.g., `100`) or a string (e.g., `"RUNNING"`).
* **`alert_severity`**: The ITSM incident level triggered upon failure. Valid options: `info`, `warning`, `minor`, `major`, `critical`.
* **`interval`**: How often (in seconds) this specific object should be checked.

### Example 1: Queue Depth Alert (Numeric Comparison)
Triggers a 'critical' incident if the queue depth exceeds 500 messages.
```json
{
    "queue_manager": "QM1",
    "object_name": "PROD.PAYMENTS.IN",
    "check_type": "CURDEPTH",
    "operator": ">",
    "threshold": 500,
    "alert_severity": "critical",
    "enable_alert": true,
    "enable_check": true,
    "interval": 30
}

Example 2: Channel Status Alert (String Comparison)

Triggers a 'major' incident if the channel drops out of the RUNNING state.
JSON

{
    "queue_manager": "QM1",
    "object_name": "TO.QM2",
    "check_type": "STATUS",
    "operator": "!=",
    "threshold": "RUNNING",
    "alert_severity": "major",
    "enable_alert": true,
    "enable_check": true,
    "interval": 60
}

Example 3: Application Disconnect Alert

Triggers a 'minor' incident if the number of connected applications (IPPROCS) drops below 1.
JSON

{
    "queue_manager": "QM1",
    "object_name": "APP.LISTENER.QUEUE",
    "check_type": "IPPROCS",
    "operator": "<",
    "threshold": 1,
    "alert_severity": "minor",
    "enable_alert": true,
    "enable_check": true,
    "interval": 120
}

🏃‍♂️ Usage

Run interactively (for testing):
Bash

./start_monitor.sh

View the logs in real-time:
Bash

tail -f mq_logs/mq_monitor.log

🛠️ Systemd Integration (Production Autostart)

To ensure the daemon starts automatically on system boot and restarts on failure, configure it as a systemd service.

    Create a new service file:
    Bash

    sudo nano /etc/systemd/system/mq-monitor.service

    Add the following configuration (adjust User and paths to match your environment):
    Ini, TOML

    [Unit]
    Description=IBM MQ SRE Monitor Daemon
    After=network.target

    [Service]
    Type=simple
    # IMPORTANT: This user must be in the 'mqm' group
    User=charlie
    WorkingDirectory=/"PATH TO APP DIRECTORY"/mq_app_bash
    ExecStart=/usr/bin/python3 /"PATH TO APP DIRECTORY"/mq_app_bash/src/main.py
    Restart=on-failure
    RestartSec=10

    [Install]
    WantedBy=multi-user.target

    Enable and start the service:
    Bash

    sudo systemctl daemon-reload
    sudo systemctl enable mq-monitor.service
    sudo systemctl start mq-monitor.service

    Check status:
    Bash

    sudo systemctl status mq-monitor.service

    ## 🚨 Maximo ITSM Integration (Stateful Alerts)

This SRE Daemon includes a fully integrated, stateful Alert Manager designed for IBM Maximo. It is built to prevent "alert fatigue" by tracking active incidents in memory and automatically resolving them (`status: closed`) when MQ metrics return to normal.

### 🧠 Smart Features
* **State Recovery:** On startup, the daemon queries the Maximo API for currently open alerts to reconstruct its internal state. This prevents duplicate tickets if the daemon service is restarted.
* **Circuit Breaker (Fail-Safe):** If the Maximo API becomes unreachable (e.g., DNS failure, network outage), the daemon intelligently suspends new alert creation to prevent blind firing. It will continue to monitor MQ locally and log errors safely until the connection is restored.
* **Auto-Incident Creation:** Major and critical MQ failures automatically include the `auto_create: True` flag, immediately escalating the issue to the 1st-line support (Operation Center) without manual intervention.

### ⚙️ Configuration & Security

**🛑 IMPORTANT:** Never commit your production API keys to the Git repository!

The application uses a secure template system for credentials. To enable Maximo alerts:

1. Copy the provided template file to create your local configuration:
   ```bash
   cp app_config.conf.template app_config.conf

    Open app_config.conf and configure the [Alerts] section:
    Ini, TOML

    [Alerts]
    # Master switch to enable/disable Maximo integration (boolean)
    global_alerts_enable = true

    # Maximo API Endpoint for your environment
    api_url = [https://alerts-api.yourcompany.internal/api/v1/alerts](https://alerts-api.yourcompany.internal/api/v1/alerts)

    # Your dedicated authentication key
    api_key = YOUR_SECURE_API_KEY_HERE