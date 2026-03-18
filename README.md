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

    Python 3.x installed on the host machine.

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

⚙️ Adding Monitors

To add a new Queue or Channel, drop a .json file into the respective directory. Note the interval field, which dictates how often (in seconds) this specific object should be checked.
(Note: A script restart is required to load new configurations into memory).

Example Queue Config (mq_checks_config/queues/local_test.json):
JSON

[
  {
    "queue_manager": "QM1",
    "object_name": "LOCAL.QUEUE.TEST",
    "check_type": "CURDEPTH",
    "max_threshold": 100,
    "enable_alert": true,
    "interval": 15
  }
]

Example Channel Config (mq_checks_config/channels/to_qm2.json):
JSON

[
  {
    "queue_manager": "QM1",
    "object_name": "TO.QM2",
    "check_type": "STATUS",
    "max_threshold": "RUNNING",
    "enable_alert": true,
    "interval": 60
  }
]

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