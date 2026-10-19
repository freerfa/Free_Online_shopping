"""Generate small valid PNGs for manual upload testing."""
import zlib, struct, os

def png(path, color):
    def ch(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(color) * 4 for _ in range(4))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", ihdr) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))

os.makedirs("/tmp/testpics", exist_ok=True)
png("/tmp/testpics/red.png", (220, 60, 60))
png("/tmp/testpics/blue.png", (60, 90, 220))
png("/tmp/testpics/green.png", (60, 180, 90))
print("pics-ok")