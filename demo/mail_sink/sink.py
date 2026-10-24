"""
The test mail server (docs/WORKFLOWS_PHASE8.md, proposal 8): a development tool that receives mail and never forwards it.

It speaks just enough SMTP to accept a message (HELO/EHLO, MAIL, RCPT, DATA, RSET, NOOP, QUIT), saves each message
as a file, and lists the messages on a small page. It is written with Python's standard socket library, because the
stock tool for this was removed in Python 3.12. Nothing to install.

    python3 demo/mail_sink/sink.py                       SMTP on 8025, the page on http://localhost:8026
    python3 demo/mail_sink/sink.py --folder /some/where  where the messages are kept (default: demo/output/mail)

Point the mail settings at host localhost, port 8025.
"""
import argparse
import html
import socketserver
import threading
import time
from email import message_from_bytes, policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_FOLDER = Path(__file__).resolve().parents[1] / "output" / "mail"
_save_lock = threading.Lock()


def save_message(folder: Path, data: bytes) -> Path:
    """Keeps one message as a numbered .eml file and returns its path."""
    folder.mkdir(parents=True, exist_ok=True)
    with _save_lock:
        path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{len(list(folder.glob('*.eml'))) + 1:04d}.eml"
        path.write_bytes(data)
    return path


class SmtpSession(socketserver.StreamRequestHandler):
    """One connection: answers the commands and collects the text between DATA and the lone full stop."""
    folder = DEFAULT_FOLDER

    def reply(self, text: str) -> None:
        self.wfile.write((text + "\r\n").encode())
        self.wfile.flush()

    def handle(self) -> None:
        self.reply("220 AutoApp test mail server")
        sender, recipients = "", []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            command = line.decode(errors="replace").strip()
            word = command.upper()
            if word.startswith(("EHLO", "HELO")):
                self.reply("250 localhost")
            elif word.startswith("MAIL FROM"):
                sender, recipients = command[9:].lstrip(": "), []
                self.reply("250 OK")
            elif word.startswith("RCPT TO"):
                recipients.append(command[7:].lstrip(": "))
                self.reply("250 OK")
            elif word == "DATA":
                self.reply("354 End data with a full stop on a line of its own")
                save_message(self.folder, self.read_data(sender, recipients))
                self.reply("250 OK, kept")
            elif word == "QUIT":
                self.reply("221 Bye")
                return
            elif word in ("RSET", "NOOP"):
                self.reply("250 OK")
            else:
                self.reply("502 Not understood by the test mail server")

    def read_data(self, sender: str, recipients: list) -> bytes:
        lines = [f"X-Envelope-From: {sender}".encode(), f"X-Envelope-To: {', '.join(recipients)}".encode()]
        while True:
            line = self.rfile.readline().rstrip(b"\r\n")
            if line == b".":
                return b"\r\n".join(lines) + b"\r\n"
            lines.append(line[1:] if line.startswith(b"..") else line)     # a leading ".." stands for "."


class SmtpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def read_messages(folder: Path) -> list:
    """The saved messages, newest first, as (file name, from, to, subject, body)."""
    found = []
    for path in sorted(folder.glob("*.eml"), reverse=True):
        message = message_from_bytes(path.read_bytes(), policy=policy.default)
        body = message.get_body(preferencelist=("plain",))
        found.append((path.name, message["From"], message["To"], message["Subject"], body.get_content() if body else ""))
    return found


def page(folder: Path) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(str(sender))}</td><td>{html.escape(str(to))}</td>"
        f"<td>{html.escape(str(subject))}</td><td><pre>{html.escape(body)}</pre></td></tr>"
        for name, sender, to, subject, body in read_messages(folder))
    return ("<!doctype html><meta charset=utf-8><title>Test mail</title><h1>Test mail server</h1>"
            "<p>Everything AutoApp sent here. Nothing is forwarded.</p><table border=1 cellpadding=6>"
            f"<tr><th>File</th><th>From</th><th>To</th><th>Subject</th><th>Message</th></tr>{rows}</table>")


def page_handler(folder: Path):
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            body = page(folder).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Page


def serve(folder: Path, smtp_port: int, page_port: int) -> tuple:
    """Starts both servers in threads and returns them (the tests use this with port 0 to be given a free one)."""
    session = type("Session", (SmtpSession,), {"folder": folder})
    smtp = SmtpServer(("127.0.0.1", smtp_port), session)
    web = ThreadingHTTPServer(("127.0.0.1", page_port), page_handler(folder))
    for server in (smtp, web):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return smtp, web


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoApp test mail server")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--smtp-port", type=int, default=8025)
    parser.add_argument("--page-port", type=int, default=8026)
    args = parser.parse_args()
    serve(args.folder, args.smtp_port, args.page_port)
    print(f"Test mail server: SMTP on {args.smtp_port}, messages at http://localhost:{args.page_port}, kept in {args.folder}")
    threading.Event().wait()
