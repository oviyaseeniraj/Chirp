import subprocess
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Journalctl Logs</title>
    <style>
        body { background-color: #1e1e1e; color: #ffffff; font-family: monospace; padding: 10px; }
        #terminal { white-space: pre-wrap; word-wrap: break-word; }
    </style>
</head>
<body>
    <div id="terminal"></div>
    <script>
        const terminal = document.getElementById('terminal');
        const evtSource = new EventSource("/stream");
        
        evtSource.onmessage = function(event) {
            terminal.textContent += event.data + '\\n';
            window.scrollTo(0, document.body.scrollHeight);
        };

        evtSource.onerror = function(err) {
            console.error("EventSource failed:", err);
            evtSource.close();
        };
    </script>
</body>
</html>
"""

class LogStreamingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            # Serve the HTML frontend
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
            
        elif self.path == '/stream':
            # Serve the SSE stream from journalctl
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            # Subprocess tailing the systemd journal
            process = subprocess.Popen(
    [
        'journalctl',
        '--follow',
        '--no-pager',
        '-o', 'short-precise',
        '-u', 'chirp-launcher.service',
        '-u', 'chirp_pull_listener.service',
        '-n', '50',
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)
            try:
                for line in iter(process.stdout.readline, ''):
                    # SSE format requires "data: <content>\n\n"
                    clean_line = line.strip().replace('\n', ' ')
                    self.wfile.write(f"data: {clean_line}\n\n".encode('utf-8'))
                    self.wfile.flush()
            except BrokenPipeError:
                pass  # Client disconnected
            finally:
                process.terminate()
        else:
            self.send_response(404)
            self.end_headers()

def main():
    PORT = int(os.getenv("LOG_PORT", "5003"))
    server = HTTPServer(('0.0.0.0', PORT), LogStreamingHandler)
    print(f"Starting logger UI at http://0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down logger.")
        server.server_close()

if __name__ == '__main__':
    main()
    
