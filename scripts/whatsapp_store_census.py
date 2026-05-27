#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from whatsapp_web_scanner import CdpConnection, find_whatsapp_page

DEFAULT_STORES = (
    ("model-storage", "message"),
    ("model-storage", "message-history"),
    ("model-storage", "peer-message"),
    ("model-storage", "message-info"),
    ("model-storage", "message-association"),
    ("model-storage", "chat"),
    ("model-storage", "contact"),
    ("model-storage", "group-metadata"),
    ("fts-storage", "fts-v3-index"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect WhatsApp Web IndexedDB stores for available message fields."
    )
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9223")
    parser.add_argument("--sample-rows", type=int, default=20)
    parser.add_argument("--output", default="")
    return parser.parse_args()


def census_expression(sample_rows: int) -> str:
    targets = json.dumps(DEFAULT_STORES)
    return f"""
(async()=>{{
  const targets = {targets};
  const sampleRows = {max(int(sample_rows), 1)};
  const openDb = (name) => new Promise((resolve, reject) => {{
    const req = indexedDB.open(name);
    req.onerror = () => reject(req.error || new Error('open failed '+name));
    req.onsuccess = () => resolve(req.result);
  }});
  const safeStringify = (value) => {{
    const seen = new WeakSet();
    return JSON.stringify(value, (key, val) => {{
      if (typeof val === 'bigint') return String(val);
      if (val instanceof ArrayBuffer) {{
        const bytes = Array.from(new Uint8Array(val).slice(0, 24));
        return {{kind:'ArrayBuffer', len: val.byteLength, hex: bytes.map(b => b.toString(16).padStart(2,'0')).join('')}};
      }}
      if (val && typeof val === 'object') {{
        if (seen.has(val)) return '[Circular]';
        seen.add(val);
      }}
      return val;
    }});
  }};
  const readRows = (db, storeName) => new Promise((resolve) => {{
    if (!Array.from(db.objectStoreNames).includes(storeName)) {{
      return resolve({{exists:false, count:null, rows:[]}});
    }}
    const rows=[];
    let count=null;
    const tx=db.transaction(storeName,'readonly');
    const store=tx.objectStore(storeName);
    const countReq=store.count();
    countReq.onsuccess=()=>{{ count=countReq.result || 0; }};
    const req=store.openCursor(null,'prev');
    req.onerror=()=>resolve({{exists:true,count,rows,error:String(req.error)}});
    req.onsuccess=()=>{{
      const cursor=req.result;
      if (!cursor || rows.length>=sampleRows) return resolve({{exists:true,count,rows}});
      const value=cursor.value;
      let text='';
      try {{ text=safeStringify(value) || ''; }} catch(e) {{ text=String(value); }}
      const strings = Array.from(new Set((text.match(/[A-Za-z0-9][^"\\\\]{{8,}}/g)||[])
        .filter(s => !/^https?:/.test(s))
        .slice(0,30)));
      const keys = value && typeof value === 'object' ? Object.keys(value).slice(0,80) : [];
      rows.push({{key:String(cursor.key), keys, size:text.length, strings}});
      cursor.continue();
    }};
  }});
  const out=[];
  for (const [dbName, storeName] of targets) {{
    try {{
      const db=await openDb(dbName);
      const info=await readRows(db, storeName);
      db.close();
      out.push({{dbName, storeName, ...info}});
    }} catch(e) {{
      out.push({{dbName, storeName, error:String(e)}});
    }}
  }}
  return out;
}})()
"""


def main() -> int:
    args = parse_args()
    page = find_whatsapp_page(args.cdp_url)
    with CdpConnection(page.websocket_url, timeout=30) as conn:
        result = conn.command(
            "Runtime.evaluate",
            {
                "expression": census_expression(args.sample_rows),
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
    if result.get("exceptionDetails"):
        print(json.dumps(result["exceptionDetails"], indent=2), file=sys.stderr)
        return 1
    value = result.get("result", {}).get("value") or []
    if args.output:
        Path(args.output).expanduser().write_text(json.dumps(value, indent=2))
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
