"""
Read single files out of Star Citizen's Data.p4k without unpacking the archive.

Data.p4k is a ZIP64 archive with a few twists:
  * entries are usually compressed with zstd, stored as ZIP compression method 100;
  * the central directory may start with bytes that are not an entry header, so entries are
    located by their signature instead of assuming the directory starts with one;
  * CIG adds its own extra fields, including a flag for encrypted entries (localization files
    are not encrypted, and encrypted entries are refused rather than read as garbage).

Only what scripts/update_stock.py needs is implemented: list/find entries and read one.

    p4k = P4KFile("C:/.../StarCitizen/LIVE/Data.p4k")
    entry = p4k.find("Data/Localization/english/global.ini")
    data = p4k.read(entry)

Dependency: zstandard (pip install zstandard).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

METHOD_STORED = 0
METHOD_DEFLATE = 8
METHOD_ZSTD = 100

SIG_CENTRAL = b"PK\x01\x02"
SIG_LOCAL = b"PK\x03\x04"
SIG_EOCD = b"PK\x05\x06"
SIG_EOCD64 = b"PK\x06\x06"
SIG_EOCD64_LOCATOR = b"PK\x06\x07"

CENTRAL_HEADER = struct.Struct("<4s6H3I5H2I")   # 46 bytes
LOCAL_HEADER = struct.Struct("<4s5H3I2H")       # 30 bytes
EOCD = struct.Struct("<4s4H2IH")                # 22 bytes
EOCD64 = struct.Struct("<4sQ2H2I4Q")            # 56 bytes
EOCD64_LOCATOR = struct.Struct("<4sIQI")        # 20 bytes

ZIP64_EXTRA = 0x0001
CIG_ENCRYPTION_FLAG_OFFSET = 168  # byte inside CIG's extra data that is non-zero for encrypted entries
MAX_COMMENT = 0xFFFF


@dataclass
class P4KEntry:
    filename: str
    method: int
    compressed_size: int
    file_size: int
    header_offset: int
    encrypted: bool


class P4KFile:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._base, self._cd_offset, self._cd_size = self._locate_central_directory()
        self._entries: list[P4KEntry] | None = None

    # -- archive structure -------------------------------------------------

    def _locate_central_directory(self) -> tuple[int, int, int]:
        """Return (base offset, central directory offset, central directory size)."""
        size = self.path.stat().st_size
        with self.path.open("rb") as f:
            tail_len = min(size, EOCD.size + MAX_COMMENT + EOCD64_LOCATOR.size)
            f.seek(size - tail_len)
            tail = f.read(tail_len)
            pos = tail.rfind(SIG_EOCD)
            if pos < 0:
                raise ValueError(f"{self.path} is not a ZIP/P4K archive (no end-of-directory record)")
            _, _, _, _, _, cd_size, cd_offset, _ = EOCD.unpack_from(tail, pos)
            eocd_at = size - tail_len + pos

            # ZIP64: a locator just before the classic record points at the 64-bit record.
            loc_at = eocd_at - EOCD64_LOCATOR.size
            if loc_at >= 0:
                f.seek(loc_at)
                loc = f.read(EOCD64_LOCATOR.size)
                if loc[:4] == SIG_EOCD64_LOCATOR:
                    _, _, eocd64_offset, _ = EOCD64_LOCATOR.unpack(loc)
                    # The locator's offset ignores any prepended data; the record normally sits
                    # right before the locator, so try that position too.
                    for candidate in (eocd64_offset, loc_at - EOCD64.size):
                        f.seek(candidate)
                        rec = f.read(EOCD64.size)
                        if rec[:4] == SIG_EOCD64:
                            break
                    else:
                        raise ValueError("ZIP64 end-of-directory record not found")
                    fields = EOCD64.unpack(rec)
                    cd_size, cd_offset = fields[8], fields[9]
                    eocd_at = candidate

            # Data prepended to the archive shifts every stored offset by the same amount.
            base = eocd_at - cd_size - cd_offset
            return base, cd_offset, cd_size

    def _read_entries(self) -> list[P4KEntry]:
        with self.path.open("rb") as f:
            f.seek(self._base + self._cd_offset)
            cd = f.read(self._cd_size)

        entries = []
        pos = cd.find(SIG_CENTRAL)
        while pos >= 0 and pos + CENTRAL_HEADER.size <= len(cd) and cd[pos:pos + 4] == SIG_CENTRAL:
            (_, _, _, flags, method, _, _, _, csize, usize,
             name_len, extra_len, comment_len, _, _, _, offset) = CENTRAL_HEADER.unpack_from(cd, pos)
            start = pos + CENTRAL_HEADER.size
            name = cd[start:start + name_len].decode("utf-8" if flags & 0x800 else "cp437", "replace")
            extra = cd[start + name_len:start + name_len + extra_len]
            usize, csize, offset = _apply_zip64(extra, usize, csize, offset)
            encrypted = len(extra) > CIG_ENCRYPTION_FLAG_OFFSET and extra[CIG_ENCRYPTION_FLAG_OFFSET] != 0
            entries.append(P4KEntry(name, method, csize, usize, offset, encrypted))
            pos = start + name_len + extra_len + comment_len
        if not entries:
            raise ValueError(f"No entries found in {self.path}")
        return entries

    # -- public API ----------------------------------------------------------

    @property
    def entries(self) -> list[P4KEntry]:
        if self._entries is None:
            self._entries = self._read_entries()
        return self._entries

    def find(self, path: str) -> P4KEntry | None:
        """Case-insensitive lookup; forward or back slashes both work."""
        wanted = path.replace("\\", "/").lower()
        for entry in self.entries:
            if entry.filename.replace("\\", "/").lower() == wanted:
                return entry
        return None

    def read(self, entry: P4KEntry | str) -> bytes:
        if isinstance(entry, str):
            found = self.find(entry)
            if found is None:
                raise FileNotFoundError(f"{entry} is not in {self.path}")
            entry = found
        if entry.encrypted:
            raise ValueError(f"{entry.filename} is encrypted; this reader only handles unencrypted entries")

        with self.path.open("rb") as f:
            f.seek(self._base + entry.header_offset)
            header = f.read(LOCAL_HEADER.size)
            if header[:4] != SIG_LOCAL:
                raise ValueError(f"Bad local header for {entry.filename}")
            name_len, extra_len = LOCAL_HEADER.unpack(header)[9:11]
            f.seek(name_len + extra_len, 1)
            raw = f.read(entry.compressed_size)

        if entry.method == METHOD_STORED:
            data = raw
        elif entry.method == METHOD_DEFLATE:
            data = zlib.decompress(raw, -15)
        elif entry.method == METHOD_ZSTD:
            try:
                import zstandard
            except ImportError as e:
                raise ImportError("zstandard is required: pip install zstandard") from e
            data = zstandard.ZstdDecompressor().decompress(raw, max_output_size=max(entry.file_size, 1))
        else:
            raise ValueError(f"Unsupported compression method {entry.method} for {entry.filename}")

        if len(data) != entry.file_size:
            raise ValueError(f"{entry.filename}: expected {entry.file_size} bytes, got {len(data)}")
        return data


def _apply_zip64(extra: bytes, usize: int, csize: int, offset: int) -> tuple[int, int, int]:
    """Replace 0xFFFFFFFF placeholders with the 64-bit values from the ZIP64 extra field."""
    pos = 0
    while pos + 4 <= len(extra):
        tag, size = struct.unpack_from("<HH", extra, pos)
        if tag == ZIP64_EXTRA:
            values = list(struct.unpack_from(f"<{size // 8}Q", extra, pos + 4))
            # Values appear only for fields that overflowed, in this fixed order.
            if usize == 0xFFFFFFFF and values:
                usize = values.pop(0)
            if csize == 0xFFFFFFFF and values:
                csize = values.pop(0)
            if offset == 0xFFFFFFFF and values:
                offset = values.pop(0)
            break
        pos += 4 + size
    return usize, csize, offset
