"""Tests for scripts/p4k_reader.py using small hand-built archives in the Data.p4k layout."""

import io
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import p4k_reader  # noqa: E402

try:
    import zstandard
except ImportError:  # the reader needs it only for zstd entries
    zstandard = None


def build_p4k(entries, junk_before_cd=b"", prefix=b""):
    """entries: list of (name, data, method, encrypted). Writes ZIP64 fields for every entry."""
    out = io.BytesIO()
    out.write(prefix)
    central = []
    for name, data, method, encrypted in entries:
        if method == 100:
            payload = zstandard.ZstdCompressor().compress(data)
        elif method == 8:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            payload = c.compress(data) + c.flush()
        else:
            payload = data
        offset = out.tell() - len(prefix)
        raw_name = name.encode()
        out.write(struct.pack("<4s5H3I2H", b"PK\x03\x04", 45, 0, method, 0, 0, zlib.crc32(data),
                              len(payload), len(data), len(raw_name), 0))
        out.write(raw_name)
        out.write(payload)
        zip64 = struct.pack("<HH3Q", 0x0001, 24, len(data), len(payload), offset)
        # CIG's extra data: the encryption flag is byte 168 of the whole extra block
        # (after the 28-byte ZIP64 field and this field's 4-byte header).
        cig_payload = bytes(168 - 28 - 4) + (b"\x01" if encrypted else b"\x00") + bytes(7)
        cig = struct.pack("<HH", 0x5000, len(cig_payload)) + cig_payload
        extra = zip64 + cig
        central.append(struct.pack("<4s6H3I5H2I", b"PK\x01\x02", 45, 45, 0, method, 0, 0, zlib.crc32(data),
                                   0xFFFFFFFF, 0xFFFFFFFF, len(raw_name), len(extra), 0, 0, 0, 0, 0xFFFFFFFF)
                       + raw_name + extra)
    cd_offset = out.tell() - len(prefix)
    cd = junk_before_cd + b"".join(central)
    out.write(cd)
    eocd64_at = out.tell() - len(prefix)
    out.write(struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, len(entries), len(entries),
                          len(cd), cd_offset))
    out.write(struct.pack("<4sIQI", b"PK\x06\x07", 0, eocd64_at, 1))
    out.write(struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0))
    return out.getvalue()


class P4KReaderTests(unittest.TestCase):
    def write(self, blob):
        path = Path(tempfile.mkdtemp()) / "Data.p4k"
        path.write_bytes(blob)
        return path

    @unittest.skipIf(zstandard is None, "zstandard not installed")
    def test_reads_zstd_zip64_entry_with_junk_before_directory(self):
        ini = "﻿Frontend_PU_Version=4.10\r\nitem_Name=Bracer\r\n".encode("utf-8") * 500
        path = self.write(build_p4k([
            ("Data\\Objects\\thing.xml", b"<x/>", 0, False),
            ("Data\\Localization\\english\\global.ini", ini, 100, False),
        ], junk_before_cd=b"\x00" * 37))
        p4k = p4k_reader.P4KFile(path)
        entry = p4k.find("Data/Localization/english/global.ini")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.file_size, len(ini))
        self.assertEqual(p4k.read(entry), ini)
        self.assertEqual(p4k.read("data/objects/THING.xml"), b"<x/>")

    def test_deflate_and_prepended_data(self):
        data = b"hello world " * 100
        path = self.write(build_p4k([("a/b.txt", data, 8, False)], prefix=b"PREPENDED" * 10))
        self.assertEqual(p4k_reader.P4KFile(path).read("a/b.txt"), data)

    def test_encrypted_entries_are_refused(self):
        path = self.write(build_p4k([("secret.bin", b"abc", 0, True)]))
        with self.assertRaises(ValueError):
            p4k_reader.P4KFile(path).read("secret.bin")

    def test_reads_archive_written_by_zipfile(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
            with z.open("Data/Localization/english/global.ini", "w", force_zip64=True) as f:
                f.write(b"key=value\r\n" * 1000)
            z.writestr("other.txt", "x")
        path = self.write(buf.getvalue())
        self.assertEqual(p4k_reader.P4KFile(path).read("Data/Localization/english/global.ini"),
                         b"key=value\r\n" * 1000)

    def test_missing_entry(self):
        path = self.write(build_p4k([("a.txt", b"a", 0, False)]))
        p4k = p4k_reader.P4KFile(path)
        self.assertIsNone(p4k.find("nope.txt"))
        with self.assertRaises(FileNotFoundError):
            p4k.read("nope.txt")

    def test_not_an_archive(self):
        with self.assertRaises(ValueError):
            p4k_reader.P4KFile(self.write(b"not a zip at all"))


if __name__ == "__main__":
    unittest.main()
