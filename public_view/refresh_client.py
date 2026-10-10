"""Request the fixed snapshot operation over a local Unix socket."""
import http.client
import json
import socket


def refresh(socket_path):
    connection = http.client.HTTPConnection("localhost", timeout=115)
    try:
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(115)
        connection.sock.connect(str(socket_path))
        connection.request("POST", "/refresh", body=b"")
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()
