import email
import json
import socketserver
import sys
import threading
from email import policy


OUTPUT = sys.argv[1]
WRITE_LOCK = threading.Lock()


class SMTPHandler(socketserver.StreamRequestHandler):
    def send(self, line):
        self.wfile.write((line + "\r\n").encode("ascii"))
        self.wfile.flush()

    def handle(self):
        self.send("220 localhost Lever test SMTP")
        recipients = []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            command = line.split(" ", 1)[0].upper()
            if command in {"EHLO", "HELO"}:
                self.send("250-localhost")
                self.send("250 SIZE 33554432")
            elif command == "MAIL":
                recipients = []
                self.send("250 OK")
            elif command == "RCPT":
                recipients.append(line.split(":", 1)[-1].strip(" <>"))
                self.send("250 OK")
            elif command == "DATA":
                self.send("354 End data with <CR><LF>.<CR><LF>")
                chunks = []
                while True:
                    part = self.rfile.readline()
                    if part in (b".\r\n", b".\n", b""):
                        break
                    if part.startswith(b".."):
                        part = part[1:]
                    chunks.append(part)
                message = email.message_from_bytes(b"".join(chunks), policy=policy.default)
                bodies = []
                for item in message.walk():
                    if item.get_content_maintype() == "multipart":
                        continue
                    try:
                        bodies.append(item.get_content())
                    except Exception:
                        payload = item.get_payload(decode=True) or b""
                        bodies.append(payload.decode("utf-8", "replace"))
                record = {
                    "to": recipients,
                    "subject": str(message.get("Subject", "")),
                    "body": "\n".join(str(body) for body in bodies),
                }
                with WRITE_LOCK:
                    with open(OUTPUT, "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                self.send("250 Stored")
            elif command == "RSET":
                recipients = []
                self.send("250 OK")
            elif command == "NOOP":
                self.send("250 OK")
            elif command == "QUIT":
                self.send("221 Bye")
                return
            else:
                self.send("250 OK")


class SMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


with SMTPServer(("127.0.0.1", 1025), SMTPHandler) as server:
    server.serve_forever()
