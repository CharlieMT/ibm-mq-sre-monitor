#!/bin/bash

echo "🔍 Initialization: Checking Python environment..."

SELECTED_PYTHON=""

# Helper function: checks if the given command has Python >= 3.8
check_version() {
    local cmd=$1
    # Check if command exists and is executable
    if command -v "$cmd" >/dev/null 2>&1; then
        # Use Python's internal sys.version_info for a bulletproof check
        if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
            return 0 # Success: version is OK
        fi
    fi
    return 1 # Error: command not found or version is too old (e.g., 2.7 or 3.6)
}

# STEP 1: Check the default system commands first
# We check 'python3' and 'python' to respect the OS default behavior
for default_cmd in "python3" "python"; do
    if check_version "$default_cmd"; then
        SELECTED_PYTHON="$default_cmd"
        echo "✅ Default '$default_cmd' meets the requirements."
        break
    fi
done

# STEP 2: If defaults fail, scan common system directories
if [ -z "$SELECTED_PYTHON" ]; then
    echo "⚠️ Default commands are too old or missing. Scanning system directories..."
    
    # Define common paths where Python might be installed (package managers or compiled)
    SEARCH_PATHS="/usr/bin/python* /usr/local/bin/python* /opt/python*/bin/python*"
    
    # We use regex 'python[0-9]+\.[0-9]+$' to match any future version (e.g., python3.12, python4.1)
    # We use 'sort -V -r' (Version reverse) to test the newest installed versions first
    AVAILABLE_PYTHONS=$(ls $SEARCH_PATHS 2>/dev/null | grep -E 'python[0-9]+\.[0-9]+$' | sort -V -r)
    
    for py_path in $AVAILABLE_PYTHONS; do
        # We pass the absolute path to check_version (e.g., /usr/local/bin/python3.12)
        if check_version "$py_path"; then
            SELECTED_PYTHON="$py_path"
            echo "✅ Found a suitable alternative: $SELECTED_PYTHON"
            break
        fi
    done
fi

# STEP 3: Final validation
if [ -z "$SELECTED_PYTHON" ]; then
    echo "❌ CRITICAL ENVIRONMENT ERROR: No compatible Python version found!"
    echo "Python >= 3.8 is required. Please install a newer version."
    exit 1
fi

# Extract the exact version number for the startup log
EXACT_VERSION=$($SELECTED_PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')

echo "🚀 Starting SRE Daemon using $SELECTED_PYTHON (Version: $EXACT_VERSION)..."
echo "------------------------------------------------------------"

# Execute the main application using the selected Python interpreter
$SELECTED_PYTHON src/main.py