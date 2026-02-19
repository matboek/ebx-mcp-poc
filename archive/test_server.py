#!/usr/bin/env python3
"""
Simple test script to verify the MCP server responds correctly.
Sends a simple MCP initialize request to the server.
"""

import subprocess
import json
import sys

# Start the server process
process = subprocess.Popen(
    [sys.executable, 'server.py'],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=0
)

# Send an initialize request (MCP protocol)
initialize_request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {
            "name": "test-client",
            "version": "1.0.0"
        }
    }
}

try:
    # Send the request
    print("Sending initialize request...")
    process.stdin.write(json.dumps(initialize_request) + '\n')
    process.stdin.flush()
    
    # Read response (with timeout)
    import select
    if select.select([process.stdout], [], [], 5)[0]:
        response = process.stdout.readline()
        print("Server response:")
        print(json.dumps(json.loads(response), indent=2))
        print("\n✅ Server is working correctly!")
    else:
        print("⚠️  No response from server (timeout)")
        
except Exception as e:
    print(f"❌ Error: {e}")
finally:
    process.terminate()
    process.wait()
