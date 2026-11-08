#!/usr/bin/env python3
"""Offline installer and real smoke test for danieltebs/vtracer OCR Linux bundle.

Usage: python setup_vtracer_ocr.py --bundle FILE.zip --destination DIR

Requires Linux x86_64, Tesseract (deu/eng), cv2 and NumPy. The bundle is
stored in ChatGPT Library /Mindmap_Tools so subsequent ephemeral runtimes can
restore this tool without downloading source or compiling Rust.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET


def run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True, help='Previously verified Linux ZIP bundle')
    parser.add_argument('--destination', type=Path, default=Path.cwd() / 'vtracer_ocr_installed')
    args = parser.parse_args()
    bundle, dest = args.bundle.resolve(), args.destination.resolve()
    status = {'bundle':str(bundle), 'destination':str(dest), 'platform':sys.platform, 'architecture':platform.machine(), 'status':'unavailable'}
    try:
        if sys.platform != 'linux' or platform.machine().lower() not in {'x86_64','amd64'}:
            raise RuntimeError('This bundle works on Linux x86_64 only; Windows/macOS need separate builds')
        if not bundle.is_file():
            raise RuntimeError('ZIP file not found; materialize the Library ZIP first')
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(bundle) as z:
            names = z.namelist()
            for item in z.infolist():
                path=Path(item.filename)
                if path.is_absolute() or '..' in path.parts or item.filename.startswith('/'):
                    raise RuntimeError(f'Unsafe ZIP entry: {item.filename}')
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError('ZIP contains symbolic links: refusing to extract')
            needed={'vtracer','SHA256SUMS','tools/ocr/prepare_text_layer.py','tools/ocr/image_processing.py','BUILD_SHA'}
            if not needed.issubset(names):
                raise RuntimeError(f'Incomplete bundle, missing: {sorted(needed-set(names))}')
            z.extractall(dest)
        exe=dest/'vtracer'
        exe.chmod(exe.stat().st_mode | 0o111)
        parts=(dest/'SHA256SUMS').read_text().strip().split()
        if len(parts)<2 or parts[-1] != 'vtracer':
            raise RuntimeError('Expected SHA256SUMS entry for vtracer at bundle root')
        actual=hashlib.sha256(exe.read_bytes()).hexdigest()
        if actual != parts[0]:
            raise RuntimeError('VTracer executable checksum mismatch')
        help_out=run([str(exe),'--help']).stdout
        if '--text-file' not in help_out:
            raise RuntimeError('Binary lacks --text-file extension')
        if shutil.which('tesseract') is None:
            raise RuntimeError('Tesseract is missing from PATH')
        langs=run(['tesseract','--list-langs']).stdout
        if not {'deu','eng'}.issubset(set(langs.split())):
            raise RuntimeError('Tesseract needs deu and eng language data')
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise RuntimeError('Install opencv-python-headless and numpy in this Python environment') from exc
        sample=dest/'installation_smoke'
        sample.mkdir(exist_ok=True)
        img = np.full((200,640,3),255,dtype=np.uint8)
        cv2.putText(img,'Wald und Baum',(20,100),cv2.FONT_HERSHEY_SIMPLEX,1.8,(0,0,0),3,cv2.LINE_AA)
        cv2.circle(img,(530,138),35,(90,160,210),-1)
        image_path=sample/'example.png'
        if not cv2.imwrite(str(image_path),img):
            raise RuntimeError('Could not save smoke-test PNG')
        script=dest/'tools/ocr/prepare_text_layer.py'
        run([sys.executable,str(script),str(image_path),'--lang','eng','--psm','6','--confidence','40','--mask-mode','glyph'],timeout=180)
        svg=sample/'example.svg'
        run([str(exe),str(sample/'example.cleaned.png'),str(svg),'--text-file',str(sample/'example.labels.tsv')],timeout=180)
        ns='{http://www.w3.org/2000/svg}'
        root=ET.parse(svg).getroot()
        paths=root.findall('.//'+ns+'path')
        texts=root.findall('.//'+ns+'text')
        if not paths or not texts or root.findall('.//'+ns+'image'):
            raise RuntimeError('Smoke-test SVG needs paths and editable texts, without embedded raster')
        status.update(status='ready',executable=str(exe),source_sha=(dest/'BUILD_SHA').read_text().strip(),
                      executable_sha256=actual,ocr_script=str(script),sample_svg=str(svg),
                      svg_paths=len(paths),svg_editable_texts=len(texts),
                      note='Runtime files may be discarded after this session; reinstall from Library bundle')
        (dest/'installation_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(status,ensure_ascii=False,indent=2))
        return 0
    except (RuntimeError,ValueError,OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired,zipfile.BadZipFile) as exc:
        status['error']=str(exc)
        print(json.dumps(status,ensure_ascii=False,indent=2),file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())