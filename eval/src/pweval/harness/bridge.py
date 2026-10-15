"""沙箱内外的转发，只用标准库（沙箱里用系统的 python3 直接运行这个文件，不导入 t1）。

沙箱断网，只有回环地址；与外面的联系只经挂载进去的 unix socket：

    unix-to-tcp  <sock> <host:port>      沙箱外：socket 上的每个连接转到 TCP（如大模型服务）
    tcp-to-unix  <host:port> <sock>      沙箱内：回环地址上的 TCP 连接转到 socket
    unix-exec    <sock> -- <命令…>        沙箱外：每个连接启动一次命令，连接与命令的 stdin / stdout 对接（MCP 服务）
    stdio-to-unix <sock>                 沙箱内：stdin / stdout 接到 socket（登记为 MCP 服务的命令）

转发只搬运字节，不解析内容。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading


def _pump(read, write, done) -> None:
    try:
        while data := read():
            write(data)
    except OSError:
        pass
    finally:
        done()


def _splice(a: socket.socket, b: socket.socket) -> None:
    def close() -> None:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    threads = [
        threading.Thread(target=_pump, args=(lambda: a.recv(65536), b.sendall, close), daemon=True),
        threading.Thread(target=_pump, args=(lambda: b.recv(65536), a.sendall, close), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    a.close()
    b.close()


def _address(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    return host, int(port)


def _serve(listener: socket.socket, handle) -> None:
    while True:
        conn, _ = listener.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def _unix_listener(path: str) -> socket.socket:
    if os.path.exists(path):
        os.unlink(path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(16)
    return listener


def unix_to_tcp(sock: str, target: str) -> None:
    def handle(conn: socket.socket) -> None:
        _splice(conn, socket.create_connection(_address(target)))

    _serve(_unix_listener(sock), handle)


def tcp_to_unix(listen: str, sock: str) -> None:
    listener = socket.create_server(_address(listen))

    def handle(conn: socket.socket) -> None:
        out = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        out.connect(sock)
        _splice(conn, out)

    _serve(listener, handle)


def unix_exec(sock: str, command: list[str]) -> None:
    def handle(conn: socket.socket) -> None:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        assert proc.stdin is not None and proc.stdout is not None
        stdin, stdout = proc.stdin, proc.stdout

        def to_proc() -> None:
            try:
                while data := conn.recv(65536):
                    stdin.write(data)
                    stdin.flush()
            except OSError:
                pass
            finally:
                try:
                    stdin.close()
                except OSError:
                    pass

        t = threading.Thread(target=to_proc, daemon=True)
        t.start()
        try:
            while data := stdout.read(65536):
                conn.sendall(data)
        except OSError:
            pass
        proc.wait()
        conn.close()

    _serve(_unix_listener(sock), handle)


def stdio_to_unix(sock: str) -> None:
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(sock)
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer

    def to_sock() -> None:
        try:
            while data := stdin.read1(65536):
                conn.sendall(data)
        except OSError:
            pass
        finally:
            try:
                conn.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    threading.Thread(target=to_sock, daemon=True).start()
    while data := conn.recv(65536):
        stdout.write(data)
        stdout.flush()


def main(argv: list[str]) -> int:
    mode, args = argv[0], argv[1:]
    if mode == "unix-to-tcp":
        unix_to_tcp(args[0], args[1])
    elif mode == "tcp-to-unix":
        tcp_to_unix(args[0], args[1])
    elif mode == "unix-exec":
        unix_exec(args[0], args[args.index("--") + 1 :])
    elif mode == "stdio-to-unix":
        stdio_to_unix(args[0])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
