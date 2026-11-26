/**
 * Zero-dependency pure-JS ZIP archive writer (STORE method + UTF-8 filename flag).
 * Ideal for already-compressed media (JPEG/PNG/WebP/MP4/WebM): fast, low memory,
 * and supports Chinese paths like "横版/photo_watermarked.jpg" cleanly across OSes.
 */

const CRC32_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) {
      c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
    }
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) {
    crc = CRC32_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime(date = new Date()) {
  const year = Math.max(1980, date.getFullYear());
  const dosDate = ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  const dosTime = (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1);
  return { dosDate, dosTime };
}

export class ZipBuilder {
  constructor() {
    this._entries = [];
    this._encoder = new TextEncoder();
  }

  /**
   * Add a file entry (e.g. path = "横版/img_watermarked.jpg", data = Uint8Array | Blob).
   */
  async addFile(path, data) {
    const cleanPath = String(path).replace(/^\/+/, "").replace(/\\/g, "/");
    let bytes;
    if (data instanceof Uint8Array) {
      bytes = data;
    } else if (data instanceof Blob) {
      bytes = new Uint8Array(await data.arrayBuffer());
    } else if (data instanceof ArrayBuffer) {
      bytes = new Uint8Array(data);
    } else {
      throw new TypeError("Unsupported data type for ZipBuilder.addFile");
    }

    this._entries.push({
      nameBytes: this._encoder.encode(cleanPath),
      data: bytes,
      crc: crc32(bytes),
      ...dosDateTime(),
    });
  }

  /**
   * Build and return the final ZIP Blob.
   */
  buildBlob() {
    const localParts = [];
    const centralParts = [];
    let offset = 0;

    for (const entry of this._entries) {
      const nameLen = entry.nameBytes.length;
      const size = entry.data.length;

      // Local File Header (30 bytes + filename)
      const localHeader = new ArrayBuffer(30);
      const lv = new DataView(localHeader);
      lv.setUint32(0, 0x04034b50, true); // Local file header signature
      lv.setUint16(4, 20, true);         // Version needed (2.0)
      lv.setUint16(6, 0x0800, true);     // General purpose bit 11 = UTF-8 filenames
      lv.setUint16(8, 0, true);          // Compression method: 0 (STORE)
      lv.setUint16(10, entry.dosTime, true);
      lv.setUint16(12, entry.dosDate, true);
      lv.setUint32(14, entry.crc, true);
      lv.setUint32(18, size, true);      // Compressed size
      lv.setUint32(22, size, true);      // Uncompressed size
      lv.setUint16(26, nameLen, true);
      lv.setUint16(28, 0, true);         // Extra field length

      localParts.push(new Uint8Array(localHeader), entry.nameBytes, entry.data);

      // Central Directory File Header (46 bytes + filename)
      const centralHeader = new ArrayBuffer(46);
      const cv = new DataView(centralHeader);
      cv.setUint32(0, 0x02014b50, true); // Central directory signature
      cv.setUint16(4, 20, true);         // Version made by
      cv.setUint16(6, 20, true);         // Version needed
      cv.setUint16(8, 0x0800, true);     // UTF-8 flag
      cv.setUint16(10, 0, true);         // Method: STORE
      cv.setUint16(12, entry.dosTime, true);
      cv.setUint16(14, entry.dosDate, true);
      cv.setUint32(16, entry.crc, true);
      cv.setUint32(20, size, true);
      cv.setUint32(24, size, true);
      cv.setUint16(28, nameLen, true);
      cv.setUint16(30, 0, true);         // Extra length
      cv.setUint16(32, 0, true);         // Comment length
      cv.setUint16(34, 0, true);         // Disk number start
      cv.setUint16(36, 0, true);         // Internal file attrs
      cv.setUint32(38, 0, true);         // External file attrs
      cv.setUint32(42, offset, true);    // Relative offset of local header

      centralParts.push(new Uint8Array(centralHeader), entry.nameBytes);
      offset += 30 + nameLen + size;
    }

    let centralSize = 0;
    for (const part of centralParts) centralSize += part.length;

    // End of Central Directory Record (22 bytes)
    const eocd = new ArrayBuffer(22);
    const ev = new DataView(eocd);
    ev.setUint32(0, 0x06054b50, true);
    ev.setUint16(4, 0, true);
    ev.setUint16(6, 0, true);
    ev.setUint16(8, this._entries.length, true);
    ev.setUint16(10, this._entries.length, true);
    ev.setUint32(12, centralSize, true);
    ev.setUint32(16, offset, true);
    ev.setUint16(20, 0, true);

    return new Blob([...localParts, ...centralParts, new Uint8Array(eocd)], {
      type: "application/zip",
    });
  }
}
